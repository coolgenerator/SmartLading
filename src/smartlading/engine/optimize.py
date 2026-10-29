"""系统建议订货量：在 Q 的合理范围内网格搜索，规则与 recommend 一致。"""

from __future__ import annotations

import numpy as np

from smartlading.engine.simulate import Simulator
from smartlading.models.entities import ScenarioOption
from smartlading.models.results import GridPoint, SuggestedQuantity


def suggest_quantity(
    sim: Simulator,
    q_min: int | None = None,
    q_max: int | None = None,
    n_grid: int = 15,
) -> SuggestedQuantity:
    """缺省范围：[max(MOQ, 1), 2 × 用户方案中的最大订货量]，预付比例用供应商默认。"""
    inp = sim.inp
    q_min = max(inp.moq, 1) if q_min is None else q_min
    q_max = 2 * max(o.quantity for o in inp.options) if q_max is None else q_max
    q_max = max(q_max, q_min)
    quantities = sorted({int(q) for q in np.linspace(q_min, q_max, n_grid).round()})

    min_runway = inp.config.resolved_min_runway_days
    grid = []
    for q in quantities:
        m = sim.evaluate(ScenarioOption(id=f"grid_{q}", label="", quantity=q), attribution=False)
        grid.append((q, m))

    feasible = [(q, m) for q, m in grid if m.runway_p10 >= min_runway]
    if feasible:
        best_q, _ = max(feasible, key=lambda x: (x[1].expected_profit, x[1].worst_case_p5))
    else:
        best_q, _ = max(grid, key=lambda x: (x[1].runway_p10, x[1].worst_case_p5))

    metrics = sim.evaluate(ScenarioOption(id="suggested", label="Suggested", quantity=best_q))
    return SuggestedQuantity(
        quantity=best_q,
        prepay_ratio=inp.default_prepay_ratio,
        metrics=metrics,
        grid=[GridPoint(quantity=q, expected_profit=m.expected_profit, runway_p10=m.runway_p10) for q, m in grid],
    )
