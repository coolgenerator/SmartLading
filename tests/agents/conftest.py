"""LLM 层、事件与仓储测试的公共夹具。用假 LLM，不调用真实 API。"""

from __future__ import annotations

from collections import deque
from datetime import date

import pydantic
import pytest

from smartlading.llm import BrandContext, LLMError
from smartlading.models import (
    SKU,
    Brand,
    CashFan,
    OptionMetrics,
    POStatus,
    PurchaseOrder,
    Recommendation,
    Scenario,
    ScenarioOption,
    SimulationResult,
    Supplier,
    SupplierOffer,
)


class FakeLLM:
    """按顺序返回预设结果；预设为异常时抛出。记录每次调用。"""

    model = "fake-model"

    def __init__(self, *responses: pydantic.BaseModel | Exception) -> None:
        self._responses = deque(responses)
        self.calls: list[dict] = []

    def structured(self, *, system, user, output_type, effort="low", max_tokens=8000):
        self.calls.append({"system": system, "user": user, "output_type": output_type})
        r = self._responses.popleft()
        if isinstance(r, Exception):
            raise r
        assert isinstance(r, output_type)
        return r


class LLMDown:
    model = "fake-model"

    def structured(self, **_):
        raise LLMError("offline")


def metrics(oid: str, *, qty=3000, runway_p10=121, profit=50_000.0, p5=-5_000.0, stockout=0.1, cost=4.0, prepay=0.3, attribution=None) -> OptionMetrics:
    return OptionMetrics(
        option_id=oid,
        quantity=qty,
        prepay_ratio=prepay,
        unit_cost=cost,
        runway_p10=runway_p10,
        runway_p50=121,
        runway_p90=121,
        stockout_prob=stockout,
        expected_profit=profit,
        worst_case_p5=p5,
        credit_breach_prob=0.0,
        default_loss_prob=0.04,
        risk_attribution=attribution or {"demand": 0.5, "lead_time": 0.3, "tariff": 0.1, "default": 0.1},
        cash_fan=CashFan(days=[0, 1, 2], p10=[100_000, 80_000, 90_000], p50=[100_000, 95_000, 110_000], p90=[100_000, 105_000, 130_000], safety_line=45_000),
    )


def make_scenario(*ms: OptionMetrics, rec: Recommendation, selected: str | None = None, version: int = 0) -> Scenario:
    return Scenario(
        id="scn_1",
        brand_id="b1",
        sku_id="sku_tee",
        supplier_id="sup_cn",
        options=[ScenarioOption(id=m.option_id, label=m.option_id.removeprefix("opt_"), quantity=m.quantity) for m in ms],
        state_version=version,
        result=SimulationResult(seed=42, input_hash="h", engine_version="test", horizon_days=120, n_paths=1000, options=list(ms)),
        recommendation=rec,
        selected_option_id=selected,
    )


@pytest.fixture
def demo_brand() -> Brand:
    return Brand(id="b1", name="Tideline", cash_balance=200_000, credit_limit=100_000, daily_fixed_cost=1_500)


@pytest.fixture
def demo_skus() -> list[SKU]:
    return [
        SKU(id="sku_tee", brand_id="b1", name="有机棉 T 恤", category="apparel", price=24, unit_platform_fee=7, on_hand=1200,
            hts_code="6109.10.0012", tariff_rate=0.10, demand_template_id="m5_hobbies_1"),
        SKU(id="sku_tank", brand_id="b1", name="棉质背心", category="apparel", price=19, unit_platform_fee=6, on_hand=900,
            hts_code="6109.10.0040", tariff_rate=0.10, demand_template_id="m5_hobbies_2"),
        SKU(id="sku_mug", brand_id="b1", name="陶瓷马克杯", category="home", price=18, unit_platform_fee=6, on_hand=800,
            hts_code="6912.00.4810", tariff_rate=0.15, demand_template_id="m5_household_1"),
    ]


@pytest.fixture
def demo_suppliers() -> list[Supplier]:
    return [
        Supplier(id="sup_cn", brand_id="b1", name="宁波华纺", country="CN", lead_time_mean_days=45, lead_time_std_days=8,
                 moq=2000, default_prepay_ratio=0.3, risk_score=0.2),
        Supplier(id="sup_vn", brand_id="b1", name="Saigon Ceramics", country="VN", lead_time_mean_days=55, lead_time_std_days=12,
                 moq=1000, default_prepay_ratio=0.5, risk_score=0.35),
    ]


@pytest.fixture
def demo_offers() -> list[SupplierOffer]:
    return [
        SupplierOffer(sku_id="sku_tee", supplier_id="sup_cn", unit_cost=4.0, unit_freight=0.6),
        SupplierOffer(sku_id="sku_tank", supplier_id="sup_cn", unit_cost=3.2, unit_freight=0.5),
        SupplierOffer(sku_id="sku_mug", supplier_id="sup_vn", unit_cost=2.5, unit_freight=0.9),
    ]


@pytest.fixture
def demo_pos() -> list[PurchaseOrder]:
    return [
        PurchaseOrder(id="po_1", brand_id="b1", sku_id="sku_tee", supplier_id="sup_cn", quantity=5000, prepay_ratio=0.3,
                      order_date=date(2026, 10, 1), eta=date(2026, 11, 20), status=POStatus.IN_TRANSIT),
        PurchaseOrder(id="po_2", brand_id="b1", sku_id="sku_mug", supplier_id="sup_vn", quantity=3000, prepay_ratio=0.5,
                      order_date=date(2026, 11, 1), status=POStatus.PLANNED),
    ]


@pytest.fixture
def ctx(demo_skus, demo_suppliers, demo_offers) -> BrandContext:
    return BrandContext(brand_id="b1", skus=demo_skus, suppliers=demo_suppliers, offers=demo_offers)
