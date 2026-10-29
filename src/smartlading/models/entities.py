"""核心业务实体（design.md §1.1）。金额统一 USD，比例 0–1，天数为整数。"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

from smartlading.models.results import Recommendation, SimulationResult

Ratio = Field(ge=0.0, le=1.0)

# [假设] 风险评分线性映射为违约概率：评分 1 → 20% 违约
DEFAULT_PROB_PER_RISK_SCORE = 0.2


class Brand(BaseModel):
    id: str
    name: str
    cash_balance: float
    credit_limit: float = Field(ge=0)
    daily_fixed_cost: float = Field(ge=0)
    safety_line_mode: Literal["fixed", "days_of_fixed_cost"] = "days_of_fixed_cost"
    cash_safety_line_fixed: float | None = None
    safety_line_days: int | None = Field(default=30, ge=0)
    state_version: int = 0

    @model_validator(mode="after")
    def _check_safety_line(self) -> Brand:
        if self.safety_line_mode == "fixed" and self.cash_safety_line_fixed is None:
            raise ValueError("safety_line_mode=fixed requires cash_safety_line_fixed")
        if self.safety_line_mode == "days_of_fixed_cost" and self.safety_line_days is None:
            raise ValueError("safety_line_mode=days_of_fixed_cost requires safety_line_days")
        return self

    @computed_field
    @property
    def cash_safety_line(self) -> float:
        if self.safety_line_mode == "fixed":
            assert self.cash_safety_line_fixed is not None
            return self.cash_safety_line_fixed
        assert self.safety_line_days is not None
        return self.safety_line_days * self.daily_fixed_cost


class SKU(BaseModel):
    id: str
    brand_id: str
    name: str
    category: str = ""
    price: float = Field(gt=0)
    unit_platform_fee: float = Field(ge=0)
    on_hand: int = Field(ge=0)
    hts_code: str
    tariff_rate: float = Field(ge=0)
    demand_template_id: str
    demand_scale: float = Field(default=1.0, gt=0)


class Supplier(BaseModel):
    id: str
    brand_id: str
    name: str
    country: str
    lead_time_mean_days: float = Field(gt=0)
    lead_time_std_days: float = Field(ge=0)
    moq: int = Field(ge=0)
    default_prepay_ratio: float = Ratio
    risk_score: float = Ratio

    @computed_field
    @property
    def default_prob(self) -> float:
        return DEFAULT_PROB_PER_RISK_SCORE * self.risk_score


class SupplierOffer(BaseModel):
    sku_id: str
    supplier_id: str
    unit_cost: float = Field(gt=0)
    unit_freight: float = Field(ge=0)


class POStatus(StrEnum):
    PLANNED = "planned"
    IN_TRANSIT = "in_transit"
    ARRIVED = "arrived"


class PurchaseOrder(BaseModel):
    id: str
    brand_id: str
    sku_id: str
    supplier_id: str
    quantity: int = Field(gt=0)
    prepay_ratio: float = Ratio
    order_date: date
    ship_date: date | None = None
    eta: date | None = None
    status: POStatus = POStatus.PLANNED

    @model_validator(mode="after")
    def _in_transit_needs_eta(self) -> PurchaseOrder:
        if self.status == POStatus.IN_TRANSIT and self.eta is None:
            raise ValueError("An in-transit purchase order requires an eta")
        return self


class ScenarioOption(BaseModel):
    id: str
    label: str
    quantity: int = Field(gt=0)
    prepay_ratio: float | None = Field(default=None, ge=0.0, le=1.0)  # None = 用供应商默认
    unit_cost: float | None = Field(default=None, gt=0)  # None = 用报价；谈判试算新单价时填写


class Scenario(BaseModel):
    id: str
    brand_id: str
    sku_id: str
    supplier_id: str
    options: list[ScenarioOption] = Field(min_length=2, max_length=3)
    seed: int = 42
    horizon_days: int = Field(default=120, gt=0)
    n_paths: int = Field(default=1000, gt=0)
    state_version: int = 0
    input_hash: str | None = None
    result: SimulationResult | None = None
    recommendation: Recommendation | None = None
    selected_option_id: str | None = None

    @model_validator(mode="after")
    def _unique_option_ids(self) -> Scenario:
        ids = [o.id for o in self.options]
        if len(set(ids)) != len(ids):
            raise ValueError("Option ids must be unique")
        return self

    def option(self, option_id: str) -> ScenarioOption:
        for o in self.options:
            if o.id == option_id:
                return o
        raise KeyError(f"No option {option_id} in scenario")

    def is_stale(self, brand: Brand) -> bool:
        return self.state_version != brand.state_version
