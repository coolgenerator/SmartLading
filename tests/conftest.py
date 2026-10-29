from datetime import date

import pytest

from smartlading.engine import SimConfig, build_input
from smartlading.models import (
    SKU,
    Brand,
    POStatus,
    PurchaseOrder,
    RiskSignal,
    ScenarioOption,
    SignalStatus,
    Supplier,
    SupplierOffer,
)

START = date(2026, 11, 1)
# 简单的合成需求模板（日销量），代替 M5 参考序列
TEMPLATE = [30, 42, 25, 38, 55, 61, 47, 33, 29, 40, 52, 36, 44, 58]


@pytest.fixture
def brand():
    return Brand(id="b1", name="Demo Brand", cash_balance=250_000, credit_limit=100_000, daily_fixed_cost=1_500)


@pytest.fixture
def sku():
    return SKU(
        id="sku_07",
        brand_id="b1",
        name="Standing desk",
        price=89.0,
        unit_platform_fee=22.0,
        on_hand=1_200,
        hts_code="9403.60",
        tariff_rate=0.10,
        demand_template_id="m5_hobbies_1",
    )


@pytest.fixture
def supplier():
    return Supplier(
        id="s2",
        brand_id="b1",
        name="Ningbo Factory",
        country="CN",
        lead_time_mean_days=40,
        lead_time_std_days=8,
        moq=1_000,
        default_prepay_ratio=0.3,
        risk_score=0.3,
    )


@pytest.fixture
def offer():
    return SupplierOffer(sku_id="sku_07", supplier_id="s2", unit_cost=24.0, unit_freight=3.0)


@pytest.fixture
def options():
    return [
        ScenarioOption(id="A", label="A", quantity=2_000),
        ScenarioOption(id="B", label="B", quantity=4_000),
        ScenarioOption(id="C", label="C", quantity=7_000, prepay_ratio=0.5),
    ]


@pytest.fixture
def in_transit_po():
    return PurchaseOrder(
        id="po_12",
        brand_id="b1",
        sku_id="sku_07",
        supplier_id="s2",
        quantity=800,
        prepay_ratio=0.3,
        order_date=date(2026, 10, 1),
        eta=date(2026, 11, 20),
        status=POStatus.IN_TRANSIT,
    )


def tariff_signal(rate=0.25, probability=1.0, status=SignalStatus.ACCEPTED, effective=START):
    text = "USTR said tariffs on HTS 9403.60 will rise to 25% next month."
    quote = "tariffs on HTS 9403.60 will rise to 25%"
    start = text.index(quote)
    return RiskSignal(
        id="sig_1",
        brand_id="b1",
        source_text=text,
        quote=quote,
        quote_span=(start, start + len(quote)),
        target_type="hts_code",
        target_id="9403.60",
        parameter="tariff_rate",
        change_type="set",
        change_value=rate,
        probability=probability,
        effective_date=effective,
        status=status,
    )


@pytest.fixture
def make_input(brand, sku, supplier, offer, options, in_transit_po):
    def _make(seed=42, signals=(), opts=None, brand_=None, supplier_=None, **config):
        return build_input(
            brand=brand_ or brand,
            sku=sku,
            supplier=supplier_ or supplier,
            offer=offer,
            options=opts or options,
            demand_template=TEMPLATE,
            start_date=START,
            purchase_orders=[in_transit_po],
            signals=list(signals),
            config=SimConfig(seed=seed, **config),
        )

    return _make
