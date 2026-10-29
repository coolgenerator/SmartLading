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
# 允许保留的带数字记号：分位数名称
_ALLOWED_TOKENS = re.compile(r"\bP(?:5|10|50|90)\b")
_ARABIC = re.compile(r"\d")
_CJK_QUANTITY = re.compile(r"[零一二两三四五六七八九十百千万半]+\s*(?:倍|成|个百分点|个点|%|％|天|美元|块|件|万)")

RISK_SOURCE_NAMES = {"demand": "需求波动", "lead_time": "交期延误", "tariff": "关税上调", "default": "供应商违约"}


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
        problems = [f"未知占位符 {{{{{k}}}}}" for k in placeholders(template) if k not in self._facts]
        bare = _ALLOWED_TOKENS.sub("", PLACEHOLDER.sub("", template))
        if m := _ARABIC.search(bare):
            problems.append(f"出现未经引擎给出的数字：…{bare[max(0, m.start() - 12) : m.start() + 12]}…")
        if m := _CJK_QUANTITY.search(bare):
            problems.append(f"出现自行推算的数量：「{m.group(0)}」")
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
    return f"超过 {horizon} 天" if days > horizon else f"{days} 天"


# ---------------------------------------------------------------------------
# 从方案和模拟结果构建事实表
# ---------------------------------------------------------------------------


def scenario_facts(scenario: Scenario, result: SimulationResult) -> FactSheet:
    facts = FactSheet()
    horizon = result.horizon_days
    facts.add("horizon_days", horizon, f"{horizon} 天", "模拟周期")
    if result.options:
        line = result.options[0].cash_fan.safety_line
        facts.add("safety_line", line, fmt_money(line), "现金安全线")
    if result.suggested is not None:
        q = result.suggested.quantity
        facts.add("suggested.quantity", q, f"{q:,} 件", "系统建议订货量")
    labels = {o.id: o.label for o in scenario.options}
    for m in result.options:
        _option_facts(facts, m, labels.get(m.option_id, m.option_id), horizon)
    return facts


def _option_facts(facts: FactSheet, m: OptionMetrics, label: str, horizon: int) -> None:
    p = f"options[{m.option_id}]"
    name = f"方案{label}"
    facts.add(f"{p}.quantity", m.quantity, f"{m.quantity:,} 件", f"{name} 订货量")
    facts.add(f"{p}.prepay_ratio", m.prepay_ratio, fmt_pct(m.prepay_ratio), f"{name} 预付比例")
    prepay = m.quantity * m.unit_cost * m.prepay_ratio
    facts.add(f"{p}.prepay_amount", prepay, fmt_money(prepay), f"{name} 下单时预付金额（供应商违约时的损失上限）")
    for q in ("p10", "p50", "p90"):
        days = getattr(m, f"runway_{q}")
        facts.add(f"{p}.runway_{q}", days, fmt_runway(days, horizon), f"{name} 现金跑道 {q.upper()}")
    facts.add(f"{p}.stockout_prob", m.stockout_prob, fmt_pct(m.stockout_prob), f"{name} 断货概率")
    facts.add(f"{p}.expected_profit", m.expected_profit, fmt_money(m.expected_profit), f"{name} 预期利润")
    facts.add(f"{p}.worst_case_p5", m.worst_case_p5, fmt_money(m.worst_case_p5), f"{name} 最坏情况（P5）利润")
    facts.add(f"{p}.credit_breach_prob", m.credit_breach_prob, fmt_pct(m.credit_breach_prob), f"{name} 授信用尽的概率")
    facts.add(f"{p}.default_loss_prob", m.default_loss_prob, fmt_pct(m.default_loss_prob), f"{name} 供应商违约发生的概率")
    if m.cash_fan.p10:
        low = min(m.cash_fan.p10)
        facts.add(f"{p}.cash_p10_min", low, fmt_money(low), f"{name} 现金 P10 曲线最低点")
    for source, share in m.risk_attribution.items():
        facts.add(
            f"{p}.risk_attribution.{source}",
            share,
            fmt_pct(share),
            f"{name} 最坏情况利润中「{RISK_SOURCE_NAMES.get(source, source)}」的贡献占比",
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
