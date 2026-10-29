"""P1 功能的数据结构：事件预警（F5）、谈判（F6）、Demo 投票。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from smartlading.models.results import OptionMetrics


class PresetEvent(BaseModel):
    id: str
    name: str
    description: str
    # 注入时转成 accepted 的 RiskSignal；这里存模板字段，避免强制填写原文
    signal_templates: list[dict]


class Alert(BaseModel):
    id: str
    event_id: str
    purchase_order_id: str
    extra_cost: float
    cash_gap: float
    message: str
    next_step: str
    created_at: datetime
    acknowledged: bool = False


class Terms(BaseModel):
    prepay_ratio: float = Field(ge=0.0, le=1.0)
    quantity: int = Field(gt=0)
    unit_cost: float = Field(gt=0)


class FactoryPersona(BaseModel):
    """工厂底线，仅服务端持有，不下发前端。"""

    min_prepay_ratio: float = Field(ge=0.0, le=1.0)
    min_quantity: int = Field(gt=0)
    min_unit_cost: float = Field(gt=0)
    preferences: dict[str, float] = {}

    def clamp(self, terms: Terms) -> Terms:
        return Terms(
            prepay_ratio=max(terms.prepay_ratio, self.min_prepay_ratio),
            quantity=max(terms.quantity, self.min_quantity),
            unit_cost=max(terms.unit_cost, self.min_unit_cost),
        )


class NegotiationTurn(BaseModel):
    role: Literal["user", "factory"]
    message: str
    proposed_terms: Terms
    impact: OptionMetrics | None = None


class Negotiation(BaseModel):
    id: str
    brand_id: str
    supplier_id: str
    sku_id: str
    base_scenario_id: str | None = None
    status: Literal["open", "agreed", "walked_away"] = "open"
    turns: list[NegotiationTurn] = []


class Vote(BaseModel):
    id: str
    demo_point: int = Field(ge=1, le=3)
    choice: str
    created_at: datetime
