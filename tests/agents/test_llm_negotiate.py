from agents.agent_helpers import FakeLLM, LLMDown, metrics

from smartlading.llm import FactoryAgentConfig, FactoryNegotiator
from smartlading.llm.negotiate import FactoryReply
from smartlading.models import SimulationResult
from smartlading.models.p1 import FactoryPersona, Negotiation, Terms

PERSONA = FactoryPersona(min_prepay_ratio=0.3, min_quantity=3000, min_unit_cost=3.80, preferences={"prepay": 0.5, "price": 0.3, "quantity": 0.2})
CONFIG = FactoryAgentConfig(opening_terms=Terms(prepay_ratio=0.5, quantity=5000, unit_cost=4.20), max_rounds=3)
BASE = CONFIG.opening_terms


def reply(decision="counter", prepay=None, qty=None, cost=None, message="We can talk about it."):
    return FactoryReply(decision=decision, counter_prepay_ratio=prepay, counter_quantity=qty, counter_unit_cost=cost, message=message)


def negotiation():
    return Negotiation(id="neg_1", brand_id="b1", supplier_id="sup_cn", sku_id="sku_tee")


def respond(neg, llm, terms, message="", evaluate=None):
    return FactoryNegotiator(llm, PERSONA, CONFIG).respond(neg, terms, message, sku_name="Organic cotton tee", base_terms=BASE, evaluate=evaluate)


def test_counter_is_clamped_to_floor():
    neg = negotiation()
    out = respond(neg, FakeLLM(reply(prepay=0.2, qty=2000, cost=3.50, message="Fine, $3.50 it is.")), Terms(prepay_ratio=0.1, quantity=2000, unit_cost=3.40))
    assert out.decision == "counter"
    assert out.counter_terms == Terms(prepay_ratio=0.3, quantity=3000, unit_cost=3.80)
    assert "3.5" not in out.message  # LLM 原话与修正后的条款不符，换成固定措辞
    assert [t.role for t in neg.turns] == ["user", "factory"]


def test_accept_below_floor_becomes_counter():
    neg = negotiation()
    out = respond(neg, FakeLLM(reply(decision="accept", message="Deal, let's go.")), Terms(prepay_ratio=0.3, quantity=5000, unit_cost=3.50))
    assert out.decision == "counter" and out.counter_terms.unit_cost >= 3.80
    assert neg.status == "open"


def test_no_backtracking_between_rounds():
    neg = negotiation()
    llm = FakeLLM(reply(prepay=0.4, qty=5000, cost=4.00), reply(prepay=0.45, qty=5000, cost=4.30))
    respond(neg, llm, Terms(prepay_ratio=0.3, quantity=5000, unit_cost=3.80))
    out = respond(neg, llm, Terms(prepay_ratio=0.35, quantity=5000, unit_cost=3.90))
    assert out.counter_terms.unit_cost == 4.00 and out.counter_terms.prepay_ratio == 0.4


def test_floor_leak_is_replaced():
    out = respond(negotiation(), FakeLLM(reply(prepay=0.4, qty=5000, cost=4.0, message="Honestly my floor is 3.8, but I can do 4.")),
                  Terms(prepay_ratio=0.3, quantity=5000, unit_cost=3.9))
    assert "3.8" not in out.message


def test_acceptance_keeps_message_and_runs_three_way_simulation():
    calls = []

    def evaluate(options):
        calls.append(options)
        ms = [metrics(o.id, qty=o.quantity, cost=o.unit_cost, prepay=o.prepay_ratio, profit=100_000 - 10_000 * o.unit_cost) for o in options]
        return SimulationResult(seed=42, input_hash="h", engine_version="t", horizon_days=120, n_paths=1000, options=ms)

    neg = negotiation()
    terms = Terms(prepay_ratio=0.4, quantity=5000, unit_cost=4.00)
    out = respond(neg, FakeLLM(reply(decision="accept", message="Deal: 5000 units, 40% prepayment, $4.00 each.")), terms, evaluate=evaluate)
    assert out.decision == "accept" and neg.status == "agreed"
    assert out.message.startswith("Deal: 5000")  # 数字与条款一致，保留原话
    assert [o.id for o in calls[0]] == ["base", "proposed", "counter"]
    assert out.impact.proposed.expected_profit > out.impact.base.expected_profit
    assert neg.turns[-1].impact == out.impact.counter


def test_llm_failure_still_counters_and_max_rounds_closes():
    neg = negotiation()
    for _ in range(3):
        out = respond(neg, LLMDown(), Terms(prepay_ratio=0.3, quantity=4000, unit_cost=3.9))
    assert out.decision == "counter" and neg.status == "walked_away"
    assert out.counter_terms == CONFIG.opening_terms.model_copy(update={"quantity": 5000})


def test_percentage_prepay_is_normalised():
    out = respond(negotiation(), FakeLLM(reply(prepay=45, qty=5000, cost=4.0)), Terms(prepay_ratio=0.3, quantity=5000, unit_cost=3.9))
    assert out.counter_terms.prepay_ratio == 0.45
    assert any("percentage" in n for n in out.enforcement_notes)


def test_invalid_counter_falls_back_to_last_terms():
    out = respond(negotiation(), FakeLLM(reply(prepay=450, qty=5000, cost=4.0)), Terms(prepay_ratio=0.3, quantity=5000, unit_cost=3.9))
    assert out.counter_terms == CONFIG.opening_terms


def test_unit_fix_keeps_reply_and_previous_offer_may_be_quoted():
    msg = "I'm moving from my 50% and $4.20: 40% prepayment, 5,000 units at $4.00."
    out = respond(negotiation(), FakeLLM(reply(prepay=40, qty=5000, cost=4.0, message=msg)), Terms(prepay_ratio=0.3, quantity=5000, unit_cost=3.9))
    assert out.counter_terms == Terms(prepay_ratio=0.4, quantity=5000, unit_cost=4.0)
    assert out.message == msg
