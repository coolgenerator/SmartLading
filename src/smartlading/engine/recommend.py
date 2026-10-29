"""F4 推荐规则：纯规则，LLM 只负责叙述。"""

from __future__ import annotations

from smartlading.models.results import OptionMetrics, Recommendation, SimulationResult


def _risk_key(m: OptionMetrics) -> tuple:
    # 风险越低越好：先看跑道 P10，再看最坏情况利润，最后看断货概率
    return (m.runway_p10, m.worst_case_p5, -m.stockout_prob)


def recommend(result: SimulationResult, min_runway_days: int | None = None) -> Recommendation:
    """在 runway_p10 >= min_runway_days 的约束下选预期利润最高的方案；
    没有方案满足约束时，选风险最低的方案并给出警示。

    min_runway_days 缺省为 horizon_days + 1，即 P10 路径在整个模拟期内都不跌破安全线。
    """
    if min_runway_days is None:
        min_runway_days = result.horizon_days + 1
    options = result.options
    feasible = [m for m in options if m.runway_p10 >= min_runway_days]

    if feasible:
        best = max(feasible, key=lambda m: (m.expected_profit, m.worst_case_p5))
        rule, warning = "max_profit_under_runway_constraint", None
    else:
        best = max(options, key=_risk_key)
        rule = "min_risk_fallback"
        warning = "所有方案在 P10 情景下都会跌破现金安全线，已推荐风险最低的方案"

    # 反事实：其余方案中预期利润最高的那个（通常是更激进、诱惑更大的选择）
    others = [m for m in options if m.option_id != best.option_id]
    counterfactual = max(others, key=lambda m: m.expected_profit) if others else None

    return Recommendation(
        recommended_option_id=best.option_id,
        rule=rule,
        feasible_option_ids=[m.option_id for m in feasible],
        min_runway_days=min_runway_days,
        warning=warning,
        counterfactual_option_id=counterfactual.option_id if counterfactual else None,
    )
