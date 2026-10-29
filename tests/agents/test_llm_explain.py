import pytest
from agents.agent_helpers import FakeLLM, LLMDown, make_scenario, metrics

from smartlading.engine import recommend
from smartlading.llm import Explainer, ScenarioStaleError
from smartlading.llm.explain import ExplanationDraft
from smartlading.llm.number_check import scenario_facts, verify_numbers
from smartlading.models import SimulationResult


@pytest.fixture
def scenario():
    a = metrics("opt_A", runway_p10=121, profit=40_000)
    b = metrics("opt_B", runway_p10=80, profit=70_000, p5=-30_000)
    result = SimulationResult(seed=42, input_hash="h", engine_version="t", horizon_days=120, n_paths=1000, options=[a, b])
    return make_scenario(a, b, rec=recommend(result))


def explain(scenario, demo_brand, *drafts):
    llm = FakeLLM(*drafts)
    return Explainer(llm).explain(scenario, demo_brand, sku_name="Organic cotton tee", supplier_name="Ningbo Huafang Textiles"), llm


GOOD = ExplanationDraft(
    reason="Option A keeps a P10 cash runway of {{options[opt_A].runway_p10}} and never drops below the {{safety_line}} safety line.",
    main_risks="The main risk is demand swings, which drive {{options[opt_A].risk_attribution.demand}} of the worst case.",
    counterfactual="If you pick Option B, worst-case profit is {{options[opt_B].worst_case_p5}} and the P10 runway is only {{options[opt_B].runway_p10}}.",
)


def test_percentile_names_next_to_chinese_are_allowed(scenario, demo_brand):
    draft = GOOD.model_copy(update={"reason": "Option A has a P10 runway of {{options[opt_A].runway_p10}} and a higher P5 profit (P10/P50 view)."})
    exp, _ = explain(scenario, demo_brand, draft)
    assert exp.status == "ok", exp.problems


def test_rule_picks_a_and_counterfactual_b(scenario):
    assert scenario.recommendation.recommended_option_id == "opt_A"
    assert scenario.recommendation.counterfactual_option_id == "opt_B"


def test_ok_explanation_cites_engine_numbers(scenario, demo_brand):
    exp, llm = explain(scenario, demo_brand, GOOD)
    assert exp.status == "ok", exp.problems
    assert "more than 120 days" in exp.text and "$45,000" in exp.text and "-$30,000" in exp.text and "80 days" in exp.text
    assert "{{" not in exp.text
    paths = {c.metric_path for c in exp.cited_numbers}
    assert "options[opt_B].worst_case_p5" in paths
    assert next(c.value for c in exp.cited_numbers if c.metric_path == "options[opt_B].worst_case_p5") == -30_000
    facts = scenario_facts(scenario, scenario.result)
    assert verify_numbers(exp.text, facts.values()) == []
    assert "{{options[opt_A].runway_p10}}" in llm.calls[0]["user"]


@pytest.mark.parametrize(
    "field, bad",
    [
        ("reason", "Option A is safer and only gives up $30,000 of profit."),  # 自行计算
        ("reason", "Option B earns nearly twice as much as A."),  # 英文数量词
        ("main_risks", "See {{options[opt_A].made_up}}."),  # 未知占位符
        ("counterfactual", "If you pick Option B, the risk is higher."),  # 没引用 B 的数字
    ],
)
def test_any_mismatch_rejects_whole_text(scenario, demo_brand, field, bad):
    exp, _ = explain(scenario, demo_brand, GOOD.model_copy(update={field: bad}))
    assert exp.status == "rejected_number_mismatch"
    assert exp.text is None and exp.sections is None
    assert exp.problems


def test_user_choice_becomes_counterfactual(scenario, demo_brand):
    scenario.selected_option_id = "opt_B"
    _, llm = explain(scenario, demo_brand, GOOD)
    assert "the owner is currently leaning towards it" in llm.calls[0]["user"]


def test_stale_scenario_raises(scenario, demo_brand):
    demo_brand.state_version = 3
    with pytest.raises(ScenarioStaleError):
        explain(scenario, demo_brand, GOOD)


def test_llm_failure_is_reported(scenario, demo_brand):
    exp = Explainer(LLMDown()).explain(scenario, demo_brand, sku_name="Organic cotton tee", supplier_name="Ningbo Huafang Textiles")
    assert exp.status == "llm_error" and exp.text is None
