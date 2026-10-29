import pytest
from conftest import FakeLLM, LLMDown, make_scenario, metrics

from smartlading.engine import recommend
from smartlading.llm import Explainer, ScenarioStaleError
from smartlading.llm.explain import ExplanationDraft
from smartlading.llm.number_check import scenario_facts, verify_numbers


@pytest.fixture
def scenario():
    a = metrics("opt_A", runway_p10=121, profit=40_000)
    b = metrics("opt_B", runway_p10=80, profit=70_000, p5=-30_000)
    result_scn = make_scenario(a, b, rec=None.__class__ and _rec(a, b))
    return result_scn


def _rec(*ms):
    from smartlading.models import SimulationResult

    return recommend(SimulationResult(seed=42, input_hash="h", engine_version="t", horizon_days=120, n_paths=1000, options=list(ms)))


def explain(scenario, demo_brand, *drafts):
    llm = FakeLLM(*drafts)
    return Explainer(llm).explain(scenario, demo_brand, sku_name="T 恤", supplier_name="宁波华纺"), llm


GOOD = ExplanationDraft(
    reason="方案A 在 P10 下现金跑道 {{options[opt_A].runway_p10}}，不会跌破安全线 {{safety_line}}。",
    main_risks="主要风险是需求波动，占最坏情况的 {{options[opt_A].risk_attribution.demand}}。",
    counterfactual="如果选方案B，最坏情况下利润为 {{options[opt_B].worst_case_p5}}，现金跑道 P10 只有 {{options[opt_B].runway_p10}}。",
)


def test_rule_picks_a_and_counterfactual_b(scenario):
    assert scenario.recommendation.recommended_option_id == "opt_A"
    assert scenario.recommendation.counterfactual_option_id == "opt_B"


def test_ok_explanation_cites_engine_numbers(scenario, demo_brand):
    exp, llm = explain(scenario, demo_brand, GOOD)
    assert exp.status == "ok", exp.problems
    assert "超过 120 天" in exp.text and "$45,000" in exp.text and "-$30,000" in exp.text and "80 天" in exp.text
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
        ("reason", "方案A 更稳，利润只少了 30,000 美元。"),  # 自行计算
        ("reason", "方案B 的利润几乎是 A 的两倍。"),  # 中文数量
        ("main_risks", "风险见 {{options[opt_A].made_up}}。"),  # 未知占位符
        ("counterfactual", "如果选方案B，风险更高。"),  # 没引用 B 的数字
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
    assert "老板目前倾向于选它" in llm.calls[0]["user"]


def test_stale_scenario_raises(scenario, demo_brand):
    demo_brand.state_version = 3
    with pytest.raises(ScenarioStaleError):
        explain(scenario, demo_brand, GOOD)


def test_llm_failure_is_reported(scenario, demo_brand):
    exp = Explainer(LLMDown()).explain(scenario, demo_brand, sku_name="T 恤", supplier_name="宁波华纺")
    assert exp.status == "llm_error" and exp.text is None
