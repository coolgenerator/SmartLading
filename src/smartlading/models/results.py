"""模拟结果、推荐与解释（design.md §1.2）。界面上的所有数字都来自这里。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class CashFan(BaseModel):
    days: list[int]
    p10: list[float]
    p50: list[float]
    p90: list[float]
    safety_line: float


class OptionMetrics(BaseModel):
    option_id: str
    quantity: int
    prepay_ratio: float
    unit_cost: float
    # 跑道单位为天；未触及安全线记为 horizon_days + 1，前端显示 ">120"
    runway_p10: int
    runway_p50: int
    runway_p90: int
    stockout_prob: float
    expected_profit: float
    worst_case_p5: float
    credit_breach_prob: float
    default_loss_prob: float
    # 各风险源对 P5 利润的相对贡献（和为 1，或全部为 0）
    risk_attribution: dict[str, float]
    cash_fan: CashFan


class GridPoint(BaseModel):
    quantity: int
    expected_profit: float
    runway_p10: int


class SuggestedQuantity(BaseModel):
    quantity: int
    prepay_ratio: float
    metrics: OptionMetrics
    grid: list[GridPoint]


class SimulationResult(BaseModel):
    seed: int
    input_hash: str
    engine_version: str
    horizon_days: int
    n_paths: int
    options: list[OptionMetrics]
    suggested: SuggestedQuantity | None = None

    def metrics(self, option_id: str) -> OptionMetrics:
        for m in self.options:
            if m.option_id == option_id:
                return m
        raise KeyError(f"No option {option_id} in result")


class Recommendation(BaseModel):
    recommended_option_id: str
    rule: Literal["max_profit_under_runway_constraint", "min_risk_fallback"]
    feasible_option_ids: list[str]
    min_runway_days: int
    warning: str | None = None
    counterfactual_option_id: str | None = None


class ExplanationSections(BaseModel):
    reason: str
    main_risks: str
    counterfactual: str


class CitedNumber(BaseModel):
    value: float
    metric_path: str


class Explanation(BaseModel):
    status: Literal["ok", "rejected_number_mismatch", "llm_error", "pending"]
    text: str | None = None  # 校验不通过时为 null，不展示
    sections: ExplanationSections | None = None
    cited_numbers: list[CitedNumber] = []
    model: str | None = None
    latency_ms: int | None = None
    problems: list[str] = []  # 被拒原因，仅供调试，不下发给用户
