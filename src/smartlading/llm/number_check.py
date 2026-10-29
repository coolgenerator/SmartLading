"""数字可追溯（design.md §1.2）。

给 LLM 的输入是一张「允许引用的数字表」（metric_path → 格式化后的值）。LLM 用
{{options[opt_A].runway_p10}} 这样的占位符引用，由代码替换成数字，因此：
  1. 占位符必须都在表里；
  2. 去掉占位符后，文字里不能再出现阿拉伯数字或中文数量表达（防止 LLM 自行计算）。
渲染后再按 design.md 的做法从文本中抽出所有数字，逐一和表中值比对，作为最后一道保险。
verify_numbers 也用于不走占位符的自由文本（谈判回复）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from smartlading.models import CitedNumber, OptionMetrics, Scenario, SimulationResult

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.\[\]]+)\s*\}\}")
# 允许保留的带数字记号：分位数名称。不能用 \b——中文字符也算单词字符，「P10为」会匹配失败
_ALLOWED_TOKENS = re.compile(r"(?<![A-Za-z0-9])P(?:5|10|50|90)(?![0-9])")
_ARABIC = re.compile(r"\d")
_CJK_QUANTITY = re.compile(r"[零一二两三四五六七八九十百千万半]+\s*(?:倍|成|个百分点|个点|%|％|天|美元|块|件|万)")
# 英文的数量词同样算「自行推算」：twice、half、three times、10 points 之类
_EN_QUANTITY = re.compile(
    r"\b(?:twice|double[ds]?|triple[ds]?|thrice|quadruple[ds]?|half|halved|a third|one[- ]third|a quarter|one[- ]quarter"
    r"|(?:one|two|three|four|five|six|seven|eight|nine|ten|a few|several)[- ](?:times|fold|percent|percentage points?|points?"
    r"|days?|weeks?|months?|units?|dollars?|thousand|hundred|million))\b",
    re.IGNORECASE,
)

RISK_SOURCE_NAMES = {"demand": "demand swings", "lead_time": "lead-time delays", "tariff": "tariff increases", "default": "supplier default"}


@dataclass(frozen=True)
class Fact:
    metric_path: str
    value: float
    display: str
    description: str


class FactSheet:
    def __init__(self) -> None:
        self._facts: dict[str, Fact] = {}

    def add(self, path: str, value: float, display: str, description: str) -> None:
        self._facts[path] = Fact(path, value, display, description)

    def __contains__(self, path: str) -> bool:
        return path in self._facts

    def __getitem__(self, path: str) -> Fact:
        return self._facts[path]

    def values(self) -> list[float]:
        return [f.value for f in self._facts.values()]

    def for_prompt(self) -> str:
        return "\n".join(f"{{{{{f.metric_path}}}}} = {f.display}  # {f.description}" for f in self._facts.values())

    def check_template(self, template: str) -> list[str]:
        """返回模板的问题列表，空列表表示可以安全渲染。"""
        problems = [f"unknown placeholder {{{{{k}}}}}" for k in placeholders(template) if k not in self._facts]
        bare = _ALLOWED_TOKENS.sub("", PLACEHOLDER.sub("", template))
        if m := _ARABIC.search(bare):
            problems.append(f"number not supplied by the engine: ...{bare[max(0, m.start() - 12) : m.start() + 12]}...")
        if m := _CJK_QUANTITY.search(bare) or _EN_QUANTITY.search(bare):
            problems.append(f"self-computed quantity: {m.group(0)!r}")
        return problems

    def render(self, template: str) -> str:
        return PLACEHOLDER.sub(lambda m: self._facts[m.group(1)].display, template)

    def cited(self, *templates: str) -> list[CitedNumber]:
        seen: dict[str, CitedNumber] = {}
        for t in templates:
            for p in placeholders(t):
                seen.setdefault(p, CitedNumber(value=self._facts[p].value, metric_path=p))
        return list(seen.values())


def placeholders(template: str) -> list[str]:
    return PLACEHOLDER.findall(template)


# ---------------------------------------------------------------------------
# 格式化
# ---------------------------------------------------------------------------


def fmt_money(v: float) -> str:
    return f"{'-' if v < 0 else ''}${abs(v):,.0f}"


def fmt_pct(v: float) -> str:
    return f"{v * 100:.0f}%" if v >= 0.1 or v == 0 else f"{v * 100:.1f}%"


def fmt_runway(days: int, horizon: int) -> str:
    return f"more than {horizon} days" if days > horizon else f"{days} days"


# ---------------------------------------------------------------------------
# 从方案和模拟结果构建事实表
# ---------------------------------------------------------------------------


def scenario_facts(scenario: Scenario, result: SimulationResult) -> FactSheet:
    facts = FactSheet()
    horizon = result.horizon_days
    facts.add("horizon_days", horizon, f"{horizon} days", "simulation horizon")
    if result.options:
        line = result.options[0].cash_fan.safety_line
        facts.add("safety_line", line, fmt_money(line), "cash safety line")
    if result.suggested is not None:
        q = result.suggested.quantity
        facts.add("suggested.quantity", q, f"{q:,} units", "order quantity suggested by the engine's grid search")
    labels = {o.id: o.label for o in scenario.options}
    for m in result.options:
        _option_facts(facts, m, labels.get(m.option_id, m.option_id), horizon)
    return facts


def _option_facts(facts: FactSheet, m: OptionMetrics, label: str, horizon: int) -> None:
    p = f"options[{m.option_id}]"
    name = f"option {label}"
    facts.add(f"{p}.quantity", m.quantity, f"{m.quantity:,} units", f"{name} order quantity")
    facts.add(f"{p}.prepay_ratio", m.prepay_ratio, fmt_pct(m.prepay_ratio), f"{name} prepayment ratio")
    prepay = m.quantity * m.unit_cost * m.prepay_ratio
    facts.add(f"{p}.prepay_amount", prepay, fmt_money(prepay), f"{name} prepayment paid at order time (the most that can be lost if the supplier defaults)")
    for q in ("p10", "p50", "p90"):
        days = getattr(m, f"runway_{q}")
        facts.add(f"{p}.runway_{q}", days, fmt_runway(days, horizon), f"{name} cash runway {q.upper()} (days until cash first drops below the safety line)")
    facts.add(f"{p}.stockout_prob", m.stockout_prob, fmt_pct(m.stockout_prob), f"{name} stockout probability")
    facts.add(f"{p}.expected_profit", m.expected_profit, fmt_money(m.expected_profit), f"{name} expected profit")
    facts.add(f"{p}.worst_case_p5", m.worst_case_p5, fmt_money(m.worst_case_p5), f"{name} worst-case (P5) profit")
    facts.add(f"{p}.credit_breach_prob", m.credit_breach_prob, fmt_pct(m.credit_breach_prob), f"{name} probability of exhausting the credit line")
    facts.add(f"{p}.default_loss_prob", m.default_loss_prob, fmt_pct(m.default_loss_prob), f"{name} probability that the supplier defaults")
    if m.cash_fan.p10:
        low = min(m.cash_fan.p10)
        facts.add(f"{p}.cash_p10_min", low, fmt_money(low), f"{name} lowest point of the P10 cash curve")
    for source, share in m.risk_attribution.items():
        facts.add(
            f"{p}.risk_attribution.{source}",
            share,
            fmt_pct(share),
            f"{name} share of the worst-case profit shortfall caused by {RISK_SOURCE_NAMES.get(source, source)}",
        )


# ---------------------------------------------------------------------------
# 自由文本的数字校验
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"(?<![A-Za-z])(\d[\d,]*(?:\.\d+)?)\s*(%|％|万|k|K)?")


def extract_numbers(text: str) -> list[float]:
    out: list[float] = []
    for m in _NUMBER.finditer(_ALLOWED_TOKENS.sub("", text)):
        v = float(m.group(1).replace(",", "").rstrip("."))
        match m.group(2):
            case "%" | "％":
                v /= 100
            case "万":
                v *= 10_000
            case "k" | "K":
                v *= 1_000
        out.append(v)
    return out


def verify_numbers(text: str, allowed: list[float], rel_tol: float = 0.01) -> list[float]:
    """返回 text 中找不到出处的数字。负号不参与比较（文本里常写「亏损 $5,000」）。"""

    def matches(x: float) -> bool:
        return any(abs(x - abs(a)) <= max(abs(a) * rel_tol, 0.005) for a in allowed)

    return [x for x in extract_numbers(text) if not matches(x)]
