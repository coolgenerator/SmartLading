"""仓储集成测试，需要 `docker compose up -d`；连不上数据库时跳过。"""

import uuid

import psycopg
import pytest
from agents.agent_helpers import make_scenario, metrics

from smartlading.engine import recommend
from smartlading.llm import FactoryAgentConfig
from smartlading.models import Explanation, RiskSignal, SignalStatus, SimulationResult
from smartlading.models.p1 import FactoryPersona, Negotiation, NegotiationTurn, PresetEvent, Terms
from smartlading.store import InvalidState, Repository, connect


@pytest.fixture
def repo(demo_brand, demo_skus, demo_suppliers, demo_offers, demo_pos):
    try:
        conn = connect()
    except psycopg.OperationalError:
        pytest.skip("Postgres 未启动（docker compose up -d）")
    r = Repository(conn)
    # 每个测试用独立 brand，避免互相干扰
    suffix = uuid.uuid4().hex[:6]
    bid = f"b_{suffix}"
    rename = lambda m, **kw: m.model_copy(update=kw)  # noqa: E731
    r.upsert_brand(rename(demo_brand, id=bid))
    for s in demo_skus:
        r.upsert_sku(rename(s, id=f"{s.id}_{suffix}", brand_id=bid))
    for s in demo_suppliers:
        r.upsert_supplier(rename(s, id=f"{s.id}_{suffix}", brand_id=bid))
    for o in demo_offers:
        r.upsert_offer(rename(o, sku_id=f"{o.sku_id}_{suffix}", supplier_id=f"{o.supplier_id}_{suffix}"))
    for p in demo_pos:
        r.upsert_purchase_order(rename(p, id=f"{p.id}_{suffix}", brand_id=bid, sku_id=f"{p.sku_id}_{suffix}", supplier_id=f"{p.supplier_id}_{suffix}"))
    r.suffix, r.bid = suffix, bid
    yield r
    conn.execute("DELETE FROM brands WHERE id = %s", (bid,))
    conn.close()


def signal(repo, **kw):
    text = "USTR: the rate on 6109.10 rises from 10% to 25%."
    quote = "rises from 10% to 25%"
    start = text.index(quote)
    base = dict(
        id=f"sig_{uuid.uuid4().hex[:8]}", brand_id=repo.bid, source_text=text, quote=quote, quote_span=(start, start + len(quote)),
        target_type="hts_code", target_id="6109.10.0012", parameter="tariff_rate", change_type="set", change_value=0.25,
        probability=0.7, llm_probability=0.7, affected_skus=[f"sku_tee_{repo.suffix}"],
    )
    return RiskSignal(**(base | kw))


def test_brand_roundtrip(repo, demo_brand):
    b = repo.get_brand(repo.bid)
    assert b.cash_safety_line == demo_brand.cash_safety_line
    assert len(repo.list_skus(repo.bid)) == 3 and len(repo.list_offers(repo.bid)) == 3
    ctx = repo.brand_context(repo.bid)
    assert {s.id for s in ctx.suppliers} == {f"sup_cn_{repo.suffix}", f"sup_vn_{repo.suffix}"}


def test_signal_lifecycle_bumps_version(repo):
    sig = signal(repo)
    repo.save_signal(sig)
    assert repo.get_signal(sig.id) == sig
    edited = repo.update_signal(sig.id, probability=0.5)
    assert edited.edited_by_user and edited.probability == 0.5
    _, v1 = repo.accept_signal(sig.id)
    assert v1 == 1 and [s.id for s in repo.list_signals(repo.bid, SignalStatus.ACCEPTED)] == [sig.id]
    with pytest.raises(InvalidState):
        repo.update_signal(sig.id, probability=0.9)
    _, v2 = repo.reject_signal(sig.id)  # 撤销已接受的信号也要让结果过期
    assert v2 == 2


def test_unmatched_signal_cannot_be_accepted(repo):
    sig = signal(repo, matched=False, target_id="9403.60")
    repo.save_signal(sig)
    with pytest.raises(InvalidState):
        repo.accept_signal(sig.id)


def test_db_rejects_quote_outside_source(repo):
    row = signal(repo)
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.conn.execute(
            "INSERT INTO risk_signals (id, brand_id, source_text, quote, quote_start, quote_end, target_type, target_id, parameter, change_type, change_value, probability) "
            "VALUES (%s, %s, %s, %s, 0, 5, 'hts_code', 'x', 'tariff_rate', 'set', 0.25, 0.5)",
            (row.id, repo.bid, row.source_text, "not in source"),
        )


def test_scenario_explanation_and_staleness(repo):
    a, b = metrics("opt_A"), metrics("opt_B", runway_p10=80, profit=90_000)
    result = SimulationResult(seed=42, input_hash="h", engine_version="t", horizon_days=120, n_paths=1000, options=[a, b])
    scn = make_scenario(a, b, rec=recommend(result)).model_copy(
        update={"id": f"scn_{repo.suffix}", "brand_id": repo.bid, "sku_id": f"sku_tee_{repo.suffix}", "supplier_id": f"sup_cn_{repo.suffix}"}
    )
    repo.save_scenario(scn)
    assert repo.get_scenario(scn.id) == scn
    repo.save_explanation(scn.id, Explanation(status="llm_error", problems=["offline"]))
    assert repo.get_explanation(scn.id).status == "llm_error"
    assert repo.stale_scenario_ids(repo.bid) == []
    repo.bump_state_version(repo.bid)
    assert repo.stale_scenario_ids(repo.bid) == [scn.id]


def test_inject_event_persists_alerts(repo):
    event = PresetEvent(
        id=f"evt_{repo.suffix}", name="Tariff increase", description="The rate on 6109.10.0012 rises to 25%.",
        signal_templates=[{"target_type": "hts_code", "target_id": "6109.10.0012", "parameter": "tariff_rate", "change_type": "set", "change_value": 0.25}],
    )
    repo.save_preset_event(repo.bid, event)
    assert repo.list_preset_events(repo.bid) == [event]
    result, version, _ = repo.inject_event(repo.bid, event.id)
    assert version == 1 and len(result.alerts) == 1
    (alert,) = repo.list_alerts(repo.bid, acknowledged=False)
    assert alert.extra_cost == 3000
    repo.ack_alert(alert.id)
    assert repo.list_alerts(repo.bid, acknowledged=False) == []


def test_negotiation_and_persona_roundtrip(repo):
    sup = f"sup_cn_{repo.suffix}"
    persona = FactoryPersona(min_prepay_ratio=0.3, min_quantity=3000, min_unit_cost=3.8, preferences={"prepay": 1.0})
    config = FactoryAgentConfig(opening_terms=Terms(prepay_ratio=0.5, quantity=5000, unit_cost=4.2))
    repo.save_factory_persona(sup, persona, config)
    assert repo.get_factory_persona(sup) == (persona, config)
    neg = Negotiation(id=f"neg_{repo.suffix}", brand_id=repo.bid, supplier_id=sup, sku_id=f"sku_tee_{repo.suffix}",
                      turns=[NegotiationTurn(role="user", message="Can you go lower?", proposed_terms=Terms(prepay_ratio=0.3, quantity=4000, unit_cost=3.9), impact=metrics("proposed"))])
    repo.save_negotiation(neg)
    assert repo.get_negotiation(neg.id) == neg
