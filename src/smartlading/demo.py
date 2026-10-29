"""Demo 数据：虚构品牌 Harbor & Pine Home（PRD F1：20 个 SKU、3 家供应商）。

与前端 web/src/lib/seed.ts 保持同一套数字。需求模板是 M5 自助抽样的替身：
按周季节性 + 对数正态噪声生成、均值约为 1 的日序列，再用 SKU.demand_scale 缩放。
"""

from __future__ import annotations

import zlib
from datetime import date, timedelta

import numpy as np

from smartlading.llm.negotiate import FactoryAgentConfig
from smartlading.models import SKU, Brand, POStatus, PurchaseOrder, Supplier, SupplierOffer
from smartlading.models.p1 import FactoryPersona, PresetEvent, Terms

BRAND_ID = "brand_harbor"

# 地图用的坐标不进模型，只在 API 视图里附带
SUPPLIER_GEO = {
    "sup_everbright": ("Shenzhen", 22.543, 114.058),
    "sup_lakeside": ("Ningbo", 29.868, 121.544),
    "sup_saigon": ("Ho Chi Minh City", 10.823, 106.63),
}

# id, name, category, price, fee, on_hand, hts, tariff, daily demand, supplier, unit cost
_SKUS = [
    ("sku_01", "Walnut Floating Shelf", "Shelving", 64, 17, 3200, "9403.60.80", 0.25, 48, "sup_everbright", 18),
    ("sku_02", "Linen Storage Bin (Set of 3)", "Storage", 42, 12, 5100, "6307.90.98", 0.075, 71, "sup_lakeside", 11),
    ("sku_03", "Rattan Accent Chair", "Seating", 219, 46, 640, "9401.59.00", 0.25, 9, "sup_saigon", 74),
    ("sku_04", "Ceramic Table Lamp", "Lighting", 89, 23, 1450, "9405.21.00", 0.039, 22, "sup_lakeside", 24),
    ("sku_05", "Teak Bath Mat", "Bath", 49, 14, 2600, "4421.99.98", 0.033, 36, "sup_saigon", 13),
    ("sku_06", "Stoneware Dinner Set", "Kitchen", 119, 29, 980, "6912.00.48", 0.098, 15, "sup_lakeside", 34),
    ("sku_07", "Oak Bedside Table", "Bedroom", 129, 31, 2600, "9403.50.90", 0.25, 90, "sup_everbright", 38),
    ("sku_08", "Woven Jute Rug 5x8", "Rugs", 159, 38, 760, "5702.39.20", 0.0, 11, "sup_saigon", 46),
    ("sku_09", "Brass Wall Mirror", "Decor", 139, 33, 520, "7009.92.10", 0.065, 8, "sup_everbright", 41),
    ("sku_10", "Acacia Cutting Board", "Kitchen", 39, 11, 4300, "4419.19.90", 0.032, 64, "sup_saigon", 9),
    ("sku_11", "Bamboo Laundry Hamper", "Storage", 59, 16, 1900, "4602.11.00", 0.066, 27, "sup_lakeside", 15),
    ("sku_12", "Velvet Throw Pillow", "Textiles", 34, 10, 6200, "9404.90.20", 0.06, 92, "sup_lakeside", 7),
    ("sku_13", "Oak Dining Bench", "Seating", 249, 52, 310, "9403.60.80", 0.25, 6, "sup_everbright", 82),
    ("sku_14", "Glass Pendant Light", "Lighting", 179, 41, 450, "9405.11.40", 0.039, 7, "sup_everbright", 52),
    ("sku_15", "Cotton Waffle Towels", "Bath", 45, 13, 3800, "6302.60.00", 0.091, 58, "sup_saigon", 10),
    ("sku_16", "Marble Coaster Set", "Decor", 29, 9, 5400, "6802.91.05", 0.049, 77, "sup_lakeside", 6),
    ("sku_17", "Pine Bookcase 5-Tier", "Shelving", 199, 47, 260, "9403.60.80", 0.25, 5, "sup_everbright", 63),
    ("sku_18", "Seagrass Basket", "Storage", 36, 11, 4100, "4602.19.80", 0.035, 54, "sup_saigon", 8),
    ("sku_19", "Linen Duvet Cover", "Textiles", 149, 34, 870, "6302.31.90", 0.067, 13, "sup_lakeside", 39),
    ("sku_20", "Oak Coat Rack", "Entry", 99, 26, 1150, "9403.60.80", 0.25, 16, "sup_everbright", 29),
]

# id, sku, supplier, qty, prepay, ship day, eta day, status（天数相对今天）
_POS = [
    ("po_1041", "sku_07", "sup_everbright", 1200, 0.3, -14, 12, POStatus.IN_TRANSIT),
    ("po_1043", "sku_12", "sup_lakeside", 4000, 0.4, -22, 5, POStatus.IN_TRANSIT),
    ("po_1044", "sku_03", "sup_saigon", 400, 0.3, -6, 24, POStatus.IN_TRANSIT),
    ("po_1046", "sku_10", "sup_saigon", 3000, 0.3, -18, 9, POStatus.IN_TRANSIT),
    ("po_1047", "sku_01", "sup_everbright", 2500, 0.3, -3, 21, POStatus.IN_TRANSIT),
    ("po_1049", "sku_02", "sup_lakeside", 3500, 0.4, 9, 36, POStatus.PLANNED),
    ("po_1038", "sku_15", "sup_saigon", 2800, 0.3, -40, -3, POStatus.ARRIVED),
]

SAMPLE_NEWS = [
    {
        "title": "USTR Section 301 update",
        "source_type": "tariff",
        "text": "WASHINGTON — The Office of the U.S. Trade Representative said Tuesday it will raise the additional "
        "Section 301 duty on wooden bedroom furniture under HTS 9403.50 to 35% effective December 1. Officials said a "
        "final decision depends on the outcome of the comment period, which several trade groups expect to pass "
        "largely unchanged. Seating and lighting products are not affected.",
    },
    {
        "title": "Shenzhen factory slowdown",
        "source_type": "supplier_news",
        "text": "Several furniture makers in Shenzhen, including Everbright Woodcraft, warned buyers that rolling power "
        "cuts will add about 14 days to production schedules through the end of the quarter. Everbright also told "
        "customers it will raise the deposit it requires on new orders to 40%.",
    },
    {
        "title": "Port congestion easing",
        "source_type": "other",
        "text": "Container dwell times at the ports of Los Angeles and Long Beach fell for a third straight month, "
        "according to the Pacific Merchant Shipping Association. Analysts described conditions as broadly normal "
        "heading into the holiday season.",
    },
]


def demand_template(template_id: str, days: int = 364) -> list[float]:
    rng = np.random.default_rng(zlib.crc32(template_id.encode()))
    weekly = np.array([0.82, 0.9, 0.95, 1.0, 1.08, 1.2, 1.05])
    noise = np.exp(0.32 * rng.standard_normal(days) - 0.05)
    return [round(float(v), 4) for v in weekly[np.arange(days) % 7] * noise]


def brand() -> Brand:
    return Brand(id=BRAND_ID, name="Harbor & Pine Home", cash_balance=380_000, credit_limit=120_000, daily_fixed_cost=1_500, safety_line_days=30, state_version=1)


def suppliers() -> list[Supplier]:
    rows = [
        ("sup_everbright", "Everbright Woodcraft", "China", 38, 6, 1000, 0.3, 0.22),
        ("sup_lakeside", "Lakeside Homeware", "China", 42, 9, 2000, 0.4, 0.41),
        ("sup_saigon", "Saigon Timber Co.", "Vietnam", 47, 12, 1500, 0.3, 0.58),
    ]
    return [
        Supplier(id=i, brand_id=BRAND_ID, name=n, country=c, lead_time_mean_days=m, lead_time_std_days=s, moq=q, default_prepay_ratio=p, risk_score=r)
        for i, n, c, m, s, q, p, r in rows
    ]


def skus() -> list[SKU]:
    return [
        SKU(id=r[0], brand_id=BRAND_ID, name=r[1], category=r[2], price=r[3], unit_platform_fee=r[4], on_hand=r[5],
            hts_code=r[6], tariff_rate=r[7], demand_template_id=f"tmpl_{r[0]}", demand_scale=r[8])
        for r in _SKUS
    ]


def offers() -> list[SupplierOffer]:
    out = [SupplierOffer(sku_id=r[0], supplier_id=r[9], unit_cost=r[10], unit_freight=round(r[10] * 0.12, 2)) for r in _SKUS]
    out += [
        SupplierOffer(sku_id="sku_07", supplier_id="sup_lakeside", unit_cost=36, unit_freight=4.9),
        SupplierOffer(sku_id="sku_07", supplier_id="sup_saigon", unit_cost=33.5, unit_freight=5.6),
    ]
    return out


def purchase_orders(today: date) -> list[PurchaseOrder]:
    d = lambda n: today + timedelta(days=n)  # noqa: E731
    return [
        PurchaseOrder(id=i, brand_id=BRAND_ID, sku_id=s, supplier_id=sup, quantity=q, prepay_ratio=a,
                      order_date=d(ship - 20), ship_date=d(ship), eta=d(eta), status=st)
        for i, s, sup, q, a, ship, eta, st in _POS
    ]


def preset_events(today: date) -> list[PresetEvent]:
    return [
        PresetEvent(
            id="evt_tariff_35",
            name="Furniture tariff rises to 35%",
            description="USTR raises Section 301 duty on HTS 9403 wooden furniture to 35%, effective in 20 days.",
            signal_templates=[{"target_type": "hts_code", "target_id": "9403", "parameter": "tariff_rate", "change_type": "set",
                               "change_value": 0.35, "effective_date": (today + timedelta(days=20)).isoformat()}],
        ),
        PresetEvent(
            id="evt_everbright_delay",
            name="Everbright delays 21 days",
            description="Shenzhen power rationing pushes Everbright Woodcraft lead times out by three weeks.",
            signal_templates=[{"target_type": "supplier", "target_id": "sup_everbright", "parameter": "lead_time_mean_days",
                               "change_type": "delta", "change_value": 21}],
        ),
    ]


def factory_persona(s: Supplier, offer: SupplierOffer) -> tuple[FactoryPersona, FactoryAgentConfig]:
    """底线随谈判的 SKU 报价而定：预付不低于默认减 10 个点，单价不低于报价的 95%。"""
    city = SUPPLIER_GEO.get(s.id, (s.country, 0, 0))[0]
    return (
        FactoryPersona(min_prepay_ratio=max(0.2, s.default_prepay_ratio - 0.1), min_quantity=max(1, s.moq),
                       min_unit_cost=round(offer.unit_cost * 0.95, 2), preferences={"prepay_ratio": 0.5, "unit_cost": 0.3, "quantity": 0.2}),
        FactoryAgentConfig(
            persona=f"Owner of {s.name} in {city}; has exported furniture for over ten years, speaks plainly and watches cash flow closely",
            opening_terms=Terms(prepay_ratio=s.default_prepay_ratio, quantity=max(s.moq, 8000), unit_cost=offer.unit_cost),
        ),
    )
