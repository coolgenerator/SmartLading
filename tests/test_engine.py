import time

import numpy as np
import pytest
from conftest import tariff_signal

from smartlading.engine import Simulator, recommend, run_scenario, suggest_quantity
from smartlading.engine.simulate import simulate_option
from smartlading.models import Scenario, ScenarioOption, SignalStatus
from smartlading.models.results import OptionMetrics, SimulationResult

# ---- 可复现性 ----


def test_same_input_same_seed_is_bitwise_identical(make_input):
    a = run_scenario(make_input(seed=7))
    b = run_scenario(make_input(seed=7))
    assert a.model_dump_json() == b.model_dump_json()


def test_input_hash_is_stable_and_sensitive(make_input):
    assert make_input(seed=7).input_hash() == make_input(seed=7).input_hash()
    assert make_input(seed=7).input_hash() != make_input(seed=8).input_hash()


def test_different_seed_changes_results(make_input):
    a = run_scenario(make_input(seed=1))
    b = run_scenario(make_input(seed=2))
    assert a.options[0].cash_fan.p50 != b.options[0].cash_fan.p50


def test_raw_paths_are_bitwise_identical(make_input):
    inp = make_input(seed=11)
    o1 = simulate_option(inp, Simulator(inp).base, inp.options[1])
    o2 = simulate_option(inp, Simulator(inp).base, inp.options[1])
    assert np.array_equal(o1.cash, o2.cash) and np.array_equal(o1.profit, o2.profit)


def test_option_result_independent_of_other_options(make_input, options):
    """共同随机数：某个方案的结果不应因为加了别的方案而改变。"""
    full = run_scenario(make_input(opts=options))
    pair = run_scenario(make_input(opts=options[:2]))
    assert full.options[0] == pair.options[0]


def test_result_roundtrips_through_json(make_input):
    result = run_scenario(make_input())
    assert SimulationResult.model_validate_json(result.model_dump_json()) == result


# ---- 引擎不变量 ----


def test_inventory_never_negative_and_cash_identity(make_input):
    inp = make_input()
    out = simulate_option(inp, Simulator(inp).base, inp.options[0])
    assert (out.inventory >= -1e-9).all()
    assert out.cash.shape == (inp.config.n_paths, inp.config.horizon_days + 1)
    # 利润（现金口径）= 期末现金 - 期初现金 + 固定成本
    expected = out.cash[:, -1] - inp.cash0 + inp.daily_fixed_cost * inp.config.horizon_days
    assert np.allclose(out.profit, expected)


def test_metrics_shape(make_input):
    result = run_scenario(make_input())
    h = result.horizon_days
    for m in result.options:
        assert 0 <= m.runway_p10 <= m.runway_p50 <= m.runway_p90 <= h + 1
        assert 0.0 <= m.stockout_prob <= 1.0
        assert m.worst_case_p5 <= m.expected_profit
        assert len(m.cash_fan.p50) == h + 1
        assert all(lo <= mid <= hi for lo, mid, hi in zip(m.cash_fan.p10, m.cash_fan.p50, m.cash_fan.p90))
        total = sum(m.risk_attribution.values())
        assert total == 0.0 or total == pytest.approx(1.0, abs=1e-3)


def test_bigger_order_reduces_stockout(make_input):
    a, b, _ = run_scenario(make_input()).options
    assert b.stockout_prob <= a.stockout_prob


def test_option_prepay_defaults_to_supplier(make_input, supplier):
    result = run_scenario(make_input())
    assert result.options[0].prepay_ratio == supplier.default_prepay_ratio
    assert result.options[2].prepay_ratio == 0.5


def test_default_risk_maps_from_score(make_input, supplier):
    risky = supplier.model_copy(update={"risk_score": 1.0})
    safe = supplier.model_copy(update={"risk_score": 0.0})
    r_risky = run_scenario(make_input(supplier_=risky)).options[1]
    r_safe = run_scenario(make_input(supplier_=safe)).options[1]
    assert r_safe.default_loss_prob == 0.0
    assert r_risky.default_loss_prob == pytest.approx(0.2, abs=0.04)
    assert r_risky.expected_profit < r_safe.expected_profit


# ---- 风险信号 ----


def test_accepted_tariff_signal_raises_cost(make_input):
    base = run_scenario(make_input()).options[1]
    hit = run_scenario(make_input(signals=[tariff_signal(0.25, 1.0)])).options[1]
    assert hit.expected_profit < base.expected_profit


def test_pending_or_rejected_signal_is_ignored(make_input):
    base = run_scenario(make_input())
    for status in (SignalStatus.PENDING, SignalStatus.REJECTED):
        other = run_scenario(make_input(signals=[tariff_signal(status=status)]))
        assert other.options == base.options


def test_signal_probability_scales_impact(make_input):
    base = run_scenario(make_input()).options[1].expected_profit
    half = run_scenario(make_input(signals=[tariff_signal(probability=0.5)])).options[1].expected_profit
    full = run_scenario(make_input(signals=[tariff_signal(probability=1.0)])).options[1].expected_profit
    assert full < half < base


# ---- 推荐规则 ----


def _metrics(option_id, profit, runway_p10, p5=0.0):
    fan = {"days": [0], "p10": [0.0], "p50": [0.0], "p90": [0.0], "safety_line": 0.0}
    return OptionMetrics(
        option_id=option_id, quantity=1, prepay_ratio=0.3, unit_cost=1.0,
        runway_p10=runway_p10, runway_p50=runway_p10, runway_p90=runway_p10,
        stockout_prob=0.1, expected_profit=profit, worst_case_p5=p5,
        credit_breach_prob=0.0, default_loss_prob=0.0, risk_attribution={}, cash_fan=fan,
    )


def _result(*metrics):
    return SimulationResult(
        seed=1, input_hash="x", engine_version="t", horizon_days=120, n_paths=1, options=list(metrics)
    )


def test_recommend_max_profit_among_feasible():
    rec = recommend(_result(_metrics("A", 100, 121), _metrics("B", 200, 121), _metrics("C", 500, 60)))
    assert rec.recommended_option_id == "B"
    assert rec.rule == "max_profit_under_runway_constraint"
    assert rec.feasible_option_ids == ["A", "B"]
    assert rec.counterfactual_option_id == "C"
    assert rec.warning is None


def test_recommend_falls_back_to_min_risk_with_warning():
    rec = recommend(_result(_metrics("A", 100, 50), _metrics("B", 900, 30)))
    assert rec.recommended_option_id == "A"
    assert rec.rule == "min_risk_fallback"
    assert rec.warning


def test_recommend_on_real_result(make_input):
    result = run_scenario(make_input())
    assert recommend(result).recommended_option_id in {m.option_id for m in result.options}


# ---- 网格搜索 ----


def test_suggest_quantity_is_reproducible_and_respects_moq(make_input, supplier):
    s1 = suggest_quantity(Simulator(make_input(n_paths=300)))
    s2 = suggest_quantity(Simulator(make_input(n_paths=300)))
    assert s1 == s2
    assert s1.quantity >= supplier.moq
    assert s1.quantity in {g.quantity for g in s1.grid}


# ---- 模型校验与性能 ----


def test_scenario_rejects_wrong_option_count():
    one = [ScenarioOption(id="A", label="A", quantity=1)]
    with pytest.raises(ValueError):
        Scenario(id="s", brand_id="b", sku_id="k", supplier_id="p", options=one)


def test_latency_three_options_1000_paths(make_input):
    """NFR：3 方案 × 1000 路径 < 2 秒（含风险归因）。"""
    inp = make_input(n_paths=1000)
    t0 = time.perf_counter()
    result = run_scenario(inp)
    elapsed = time.perf_counter() - t0
    assert len(result.options) == 3
    assert elapsed < 2.0, f"{elapsed:.2f}s"


def test_negotiated_unit_cost_overrides_offer(make_input, options):
    cheaper = options[1].model_copy(update={"id": "B2", "unit_cost": 20.0})
    a, b = run_scenario(make_input(opts=[options[1], cheaper])).options
    assert b.unit_cost == 20.0 and a.unit_cost == 24.0
    assert b.expected_profit > a.expected_profit
