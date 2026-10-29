"""推荐解释（F4）。推荐和反事实方案都由 engine.recommend 的规则决定，LLM 只负责叙述。

LLM 输出带占位符的三段模板（reason / main_risks / counterfactual），代码校验后渲染。
design.md 的规则：任何一个数字对不上 → status=rejected_number_mismatch、text=null，
前端只展示数字结果；LLM 调用失败 → status=llm_error。
"""

from __future__ import annotations

import logging
import time

from pydantic import BaseModel, Field

from smartlading.models import Brand, Explanation, ExplanationSections, Scenario
from smartlading.llm.client import LLMError, StructuredLLM
from smartlading.llm.number_check import FactSheet, placeholders, scenario_facts, verify_numbers

log = logging.getLogger(__name__)


class ScenarioStaleError(RuntimeError):
    """方案已过期，不对旧数字生成解释（API 返回 409 scenario_stale）。"""


class ExplanationDraft(BaseModel):
    reason: str = Field(description="推荐理由，2-3 句")
    main_risks: str = Field(description="推荐方案的主要风险来源，1-2 句")
    counterfactual: str = Field(description="如果选指定的另一个方案，最坏情况下会怎样，1-2 句")


SYSTEM_PROMPT = """\
你是 SmartLading 的采购决策解释助手，读者是没有财务背景的中小品牌商老板，希望 30 秒内看懂。
推荐方案已经由规则确定，你只负责用平实的中文解释，不能改变推荐。

数字规则（最重要）：
- 文字中的每一个数字都必须写成事实表中的占位符，例如 {{options[opt_A].runway_p10}}，系统会替换成真实数字。
- 不要写任何阿拉伯数字；不要自己做加减乘除、算差值、倍数或百分比；不要用中文数词表达数量（如「两倍」「三成」）。
- 可以直接写 P5、P10、P50、P90 这几个分位数名称和方案字母。
- 需要比较时用定性的词（更高、更低、明显更短），并分别引用两边的占位符。

内容要求：
- reason：为什么推荐该方案，点出现金跑道和预期利润之间的取舍。
- main_risks：推荐方案最主要的风险来源；优先引用 risk_attribution 中占比最大的一项，并用白话说明它意味着什么。
- counterfactual：如果选指定的另一个方案，最坏情况（P5 利润、现金跑道 P10 或断货概率）会怎样。必须引用该方案的数字。
- 每段 1-3 句，不要客套话。"""


class Explainer:
    def __init__(self, llm: StructuredLLM | None) -> None:
        self._llm = llm

    def explain(self, scenario: Scenario, brand: Brand, *, sku_name: str, supplier_name: str) -> Explanation:
        if scenario.is_stale(brand):
            raise ScenarioStaleError(scenario.id)
        if scenario.result is None or scenario.recommendation is None:
            raise ValueError("方案还没有模拟结果")
        if self._llm is None:
            return Explanation(status="llm_error", problems=["未配置 LLM"])

        rec = scenario.recommendation
        # 用户选了与推荐不同的方案时，反事实对比用用户的选择（US-6）
        counter_id = scenario.selected_option_id
        if counter_id is None or counter_id == rec.recommended_option_id:
            counter_id = rec.counterfactual_option_id
        facts = scenario_facts(scenario, scenario.result)

        started = time.monotonic()
        try:
            draft = self._llm.structured(
                system=SYSTEM_PROMPT,
                user=_user_prompt(scenario, facts, sku_name, supplier_name, counter_id),
                output_type=ExplanationDraft,
                effort="low",
                max_tokens=4000,
            )
        except LLMError as e:
            log.warning("解释生成失败：%s", e)
            return Explanation(status="llm_error", model=self._llm.model, problems=[str(e)])
        latency_ms = int((time.monotonic() - started) * 1000)
        return check_draft(draft, facts, counter_id, model=self._llm.model, latency_ms=latency_ms)


def check_draft(
    draft: ExplanationDraft, facts: FactSheet, counter_id: str | None, *, model: str = "", latency_ms: int = 0
) -> Explanation:
    templates = {"reason": draft.reason, "main_risks": draft.main_risks, "counterfactual": draft.counterfactual}
    problems = [f"{name}：{p}" for name, t in templates.items() for p in facts.check_template(t)]
    if counter_id and not any(k.startswith(f"options[{counter_id}].") for k in placeholders(draft.counterfactual)):
        problems.append(f"counterfactual：没有引用方案 {counter_id} 的结果")

    if not problems:
        rendered = {name: facts.render(t) for name, t in templates.items()}
        text = "\n\n".join(rendered.values())
        # 最后一道保险：渲染后的文本里每个数字都必须能在事实表里找到
        if stray := verify_numbers(text, facts.values()):
            problems.append(f"渲染后出现无法追溯的数字 {stray}")

    if problems:
        log.info("解释被拒：%s", problems)
        return Explanation(status="rejected_number_mismatch", model=model, latency_ms=latency_ms, problems=problems)
    return Explanation(
        status="ok",
        text=text,
        sections=ExplanationSections(**rendered),
        cited_numbers=facts.cited(*templates.values()),
        model=model,
        latency_ms=latency_ms,
    )


def _user_prompt(scenario: Scenario, facts: FactSheet, sku_name: str, supplier_name: str, counter_id: str | None) -> str:
    rec = scenario.recommendation
    assert rec is not None
    label = {o.id: o.label for o in scenario.options}
    rec_label = label.get(rec.recommended_option_id, rec.recommended_option_id)
    if rec.rule == "max_profit_under_runway_constraint":
        feasible = "、".join(f"方案{label.get(i, i)}" for i in rec.feasible_option_ids)
        rule = f"推荐规则：在现金跑道 P10 满足要求的方案（{feasible}）中，选预期利润最高的。"
    else:
        rule = "推荐规则：没有方案的现金跑道 P10 满足要求，因此推荐风险最低的方案。reason 中必须明确提醒老板：所有方案在悲观情形下都会跌破现金安全线。"
    if counter_id:
        who = "老板目前倾向于选它" if counter_id == scenario.selected_option_id else "它是对老板最有诱惑力的替代选择"
        counter = f"反事实对比使用方案{label.get(counter_id, counter_id)}（option_id={counter_id}），{who}。"
    else:
        counter = "只有一个方案，counterfactual 写「无其他方案可比较」。"
    options = "；".join(f"方案{o.label} = option_id {o.id}" for o in scenario.options)
    return f"""\
采购单：SKU「{sku_name}」，供应商「{supplier_name}」。{options}。
推荐方案：方案{rec_label}（option_id={rec.recommended_option_id}）
{rule}
{counter}

事实表（左边是可以使用的占位符，右边是它代表的值，仅供你理解，不要抄写右边的数字）：
{facts.for_prompt()}"""
