from smartlading.events import inject_event
from smartlading.models import SignalStatus
from smartlading.models.p1 import PresetEvent

TARIFF = PresetEvent(
    id="evt_tariff_25",
    name="Tee tariff raised to 25%",
    description="USTR raises the rate on 6109.10.0012 to 25%, effective immediately.",
    signal_templates=[{"target_type": "hts_code", "target_id": "6109.10.0012", "parameter": "tariff_rate", "change_type": "set", "change_value": 0.25}],
)


def run(event, demo_brand, demo_skus, demo_suppliers, demo_offers, demo_pos, **brand_overrides):
    b = demo_brand.model_copy(update=brand_overrides)
    return inject_event(
        event, brand_id="b1", cash_balance=b.cash_balance, credit_limit=b.credit_limit, cash_safety_line=b.cash_safety_line,
        skus=demo_skus, suppliers=demo_suppliers, offers=demo_offers, purchase_orders=demo_pos,
    )


def test_tariff_event_alerts_in_transit_order(demo_brand, demo_skus, demo_suppliers, demo_offers, demo_pos):
    res = run(TARIFF, demo_brand, demo_skus, demo_suppliers, demo_offers, demo_pos)
    (sig,) = res.signals
    assert sig.status == SignalStatus.ACCEPTED and sig.probability == 1.0
    (alert,) = res.alerts
    assert alert.purchase_order_id == "po_1"
    assert alert.extra_cost == (0.25 - 0.10) * 5000 * 4.0
    assert alert.cash_gap == 0


def test_cash_gap_when_headroom_is_small(demo_brand, demo_skus, demo_suppliers, demo_offers, demo_pos):
    # 可用资金 = 现金 + 授信 − 安全线（30 天 × 1,500）= 2,000
    res = run(TARIFF, demo_brand, demo_skus, demo_suppliers, demo_offers, demo_pos, cash_balance=47_000, credit_limit=0)
    assert res.alerts[0].cash_gap == 3_000 - 2_000


def test_supplier_events(demo_brand, demo_skus, demo_suppliers, demo_offers, demo_pos):
    event = PresetEvent(
        id="evt_vn",
        name="Vietnam factory shutdown",
        description="Saigon Ceramics halts production for three weeks after flooding.",
        signal_templates=[
            {"target_type": "supplier", "target_id": "sup_vn", "parameter": "default_prob", "change_type": "set", "change_value": 0.2},
            {"target_type": "supplier", "target_id": "sup_vn", "parameter": "lead_time_mean_days", "change_type": "delta", "change_value": 21},
        ],
    )
    risk, delay = run(event, demo_brand, demo_skus, demo_suppliers, demo_offers, demo_pos).alerts
    exposure = 3000 * 2.5 * 0.5
    assert round(risk.extra_cost, 2) == round(exposure * (0.2 - 0.35 * 0.2), 2)
    assert "21 days" in delay.message and delay.extra_cost == 0
