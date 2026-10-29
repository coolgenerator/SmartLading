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
    reason: str = Field(description="Why the recommended option was chosen, 2-3 sentences")
    main_risks: str = Field(description="Main risk sources of the recommended option, 1-2 sentences")
    counterfactual: str = Field(
        description="What the worst case looks like if the owner picks the specified alternative option, 1-2 sentences"
    )


SYSTEM_PROMPT = """\
You explain purchasing decisions for SmartLading. Your reader is the owner of a small consumer brand \
with no finance background who should understand the recommendation within 30 seconds.
The recommended option has already been chosen by a fixed rule. Your only job is to explain it in plain \
language; you must not change or question the recommendation.

Write all three sections in plain English. Refer to options as Option A, Option B and so on.

Number rules (most important):
- Every number in your text must be written as a placeholder from the fact table, for example \
{{options[opt_A].runway_p10}}. The system replaces each placeholder with the real value.
- Never write digits. Never add, subtract, multiply, divide, or compute differences, ratios or \
percentages yourself. Never express quantities in words either (for example "twice", "half" or "three times").
- You may write the percentile names P5, P10, P50 and P90 and the option letters directly.
- To compare options, use qualitative words (higher, lower, much shorter) and cite the placeholder for each side.

Content:
- reason: why this option is recommended, naming the trade-off between cash runway and expected profit.
- main_risks: the biggest risk source for the recommended option. Prefer the largest entry in \
risk_attribution and say in plain words what it means for the owner.
- counterfactual: what the worst case (P5 profit, P10 cash runway or stockout probability) looks like if \
the owner picks the specified alternative option. You must cite that option's numbers.
- 1-3 sentences per section, no pleasantries."""


class Explainer:
    def __init__(self, llm: StructuredLLM | None) -> None:
        self._llm = llm

    def explain(self, scenario: Scenario, brand: Brand, *, sku_name: str, supplier_name: str) -> Explanation:
        if scenario.is_stale(brand):
            raise ScenarioStaleError(scenario.id)
        if scenario.result is None or scenario.recommendation is None:
            raise ValueError("scenario has no simulation result yet")
        if self._llm is None:
            return Explanation(status="llm_error", problems=["no LLM configured"])

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
            log.warning("explanation failed: %s", e)
            return Explanation(status="llm_error", model=self._llm.model, problems=[str(e)])
        latency_ms = int((time.monotonic() - started) * 1000)
        return check_draft(draft, facts, counter_id, model=self._llm.model, latency_ms=latency_ms)


def check_draft(
    draft: ExplanationDraft, facts: FactSheet, counter_id: str | None, *, model: str = "", latency_ms: int = 0
) -> Explanation:
    templates = {"reason": draft.reason, "main_risks": draft.main_risks, "counterfactual": draft.counterfactual}
    problems = [f"{name}: {p}" for name, t in templates.items() for p in facts.check_template(t)]
    if counter_id and not any(k.startswith(f"options[{counter_id}].") for k in placeholders(draft.counterfactual)):
        problems.append(f"counterfactual: cites no result of option {counter_id}")

    if not problems:
        rendered = {name: facts.render(t) for name, t in templates.items()}
        text = "\n\n".join(rendered.values())
        # 最后一道保险：渲染后的文本里每个数字都必须能在事实表里找到
        if stray := verify_numbers(text, facts.values()):
            problems.append(f"untraceable numbers after rendering: {stray}")

    if problems:
        log.info("explanation rejected: %s", problems)
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
        feasible = ", ".join(f"option {label.get(i, i)}" for i in rec.feasible_option_ids)
        rule = f"Rule applied: among the options whose P10 cash runway meets the requirement ({feasible}), pick the highest expected profit."
    else:
        rule = (
            "Rule applied: no option's P10 cash runway meets the requirement, so the lowest-risk option is recommended. "
            "In the reason section you must clearly warn the owner that every option drops below the cash safety line "
            "in the pessimistic case."
        )
    if counter_id:
        who = (
            "the owner is currently leaning towards it"
            if counter_id == scenario.selected_option_id
            else "it is the most tempting alternative"
        )
        counter = f"Use option {label.get(counter_id, counter_id)} (option_id={counter_id}) for the counterfactual; {who}."
    else:
        counter = "There is only one option; write \"No other option to compare.\" as the counterfactual."
    options = "; ".join(f"option {o.label} = option_id {o.id}" for o in scenario.options)
    return f"""\
Purchase order: SKU "{sku_name}", supplier "{supplier_name}". {options}.
Recommended: option {rec_label} (option_id={rec.recommended_option_id})
{rule}
{counter}

Fact table. The left side is the placeholder you may use; the right side is the value it stands for, shown \
only so you understand it. Do not copy the values on the right into your text.
{facts.for_prompt()}"""
