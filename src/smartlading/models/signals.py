"""风险信号（F3）。只有 accepted 的信号进入模拟。"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SignalParameter(StrEnum):
    TARIFF_RATE = "tariff_rate"
    LEAD_TIME_MEAN_DAYS = "lead_time_mean_days"
    LEAD_TIME_STD_DAYS = "lead_time_std_days"
    DEFAULT_PROB = "default_prob"
    UNIT_COST = "unit_cost"
    UNIT_FREIGHT = "unit_freight"
    MOQ = "moq"
    PREPAY_RATIO = "prepay_ratio"


class SignalStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class RiskSignal(BaseModel):
    id: str
    brand_id: str
    source_text: str
    source_type: Literal["tariff", "supplier_news", "other"] = "other"
    quote: str
    quote_span: tuple[int, int]
    target_type: Literal["hts_code", "supplier", "sku"]
    target_id: str
    parameter: SignalParameter
    change_type: Literal["set", "delta", "multiply"]
    change_value: float
    probability: float = Field(ge=0.0, le=1.0)
    llm_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    effective_date: date | None = None
    status: SignalStatus = SignalStatus.PENDING
    edited_by_user: bool = False
    # 以下字段由 F3 提取层填写，引擎不读
    matched: bool = True  # target_id 能否在品牌数据中找到；未匹配的信号不能接受
    affected_skus: list[str] = []
    value_grounded: bool = True  # change_value 能否在 quote 里找到对应数字，否则界面提示核对
    rationale: str = ""

    @model_validator(mode="after")
    def _quote_in_source(self) -> RiskSignal:
        start, end = self.quote_span
        if self.source_text[start:end] != self.quote:
            raise ValueError("quote must equal source_text[quote_span[0]:quote_span[1]]")
        return self

    def apply(self, value: float) -> float:
        match self.change_type:
            case "set":
                return self.change_value
            case "delta":
                return value + self.change_value
            case "multiply":
                return value * self.change_value
