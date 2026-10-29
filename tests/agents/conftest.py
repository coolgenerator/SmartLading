"""LLM 层、事件与仓储测试的品牌数据夹具。"""

from __future__ import annotations

from datetime import date

import pytest

from smartlading.llm import BrandContext
from smartlading.models import SKU, Brand, POStatus, PurchaseOrder, Supplier, SupplierOffer


@pytest.fixture
def demo_brand() -> Brand:
    return Brand(id="b1", name="Tideline", cash_balance=200_000, credit_limit=100_000, daily_fixed_cost=1_500)


@pytest.fixture
def demo_skus() -> list[SKU]:
    return [
        SKU(id="sku_tee", brand_id="b1", name="Organic cotton tee", category="apparel", price=24, unit_platform_fee=7, on_hand=1200,
            hts_code="6109.10.0012", tariff_rate=0.10, demand_template_id="m5_hobbies_1"),
        SKU(id="sku_tank", brand_id="b1", name="Cotton tank top", category="apparel", price=19, unit_platform_fee=6, on_hand=900,
            hts_code="6109.10.0040", tariff_rate=0.10, demand_template_id="m5_hobbies_2"),
        SKU(id="sku_mug", brand_id="b1", name="Ceramic mug", category="home", price=18, unit_platform_fee=6, on_hand=800,
            hts_code="6912.00.4810", tariff_rate=0.15, demand_template_id="m5_household_1"),
    ]


@pytest.fixture
def demo_suppliers() -> list[Supplier]:
    return [
        Supplier(id="sup_cn", brand_id="b1", name="Ningbo Huafang Textiles", country="CN", lead_time_mean_days=45, lead_time_std_days=8,
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
