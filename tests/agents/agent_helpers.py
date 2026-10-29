"""LLM 层测试用的假 LLM 和结果构造函数。"""

from __future__ import annotations

from collections import deque

import pydantic

from smartlading.llm import LLMError
from smartlading.models import (
    CashFan,
    OptionMetrics,
    Recommendation,
    Scenario,
    ScenarioOption,
    SimulationResult,
)


class FakeLLM:
    """按顺序返回预设结果；预设为异常时抛出。记录每次调用。"""

    model = "fake-model"

    def __init__(self, *responses: pydantic.BaseModel | Exception) -> None:
        self._responses = deque(responses)
        self.calls: list[dict] = []

    def structured(self, *, system, user, output_type, effort="low", max_tokens=8000):
        self.calls.append({"system": system, "user": user, "output_type": output_type})
        r = self._responses.popleft()
        if isinstance(r, Exception):
            raise r
        assert isinstance(r, output_type)
        return r


class LLMDown:
    model = "fake-model"

    def structured(self, **_):
        raise LLMError("offline")


def metrics(oid: str, *, qty=3000, runway_p10=121, profit=50_000.0, p5=-5_000.0, stockout=0.1, cost=4.0, prepay=0.3, attribution=None) -> OptionMetrics:
    return OptionMetrics(
        option_id=oid,
        quantity=qty,
        prepay_ratio=prepay,
        unit_cost=cost,
        runway_p10=runway_p10,
        runway_p50=121,
        runway_p90=121,
        stockout_prob=stockout,
        expected_profit=profit,
        worst_case_p5=p5,
        credit_breach_prob=0.0,
        default_loss_prob=0.04,
        risk_attribution=attribution or {"demand": 0.5, "lead_time": 0.3, "tariff": 0.1, "default": 0.1},
        cash_fan=CashFan(days=[0, 1, 2], p10=[100_000, 80_000, 90_000], p50=[100_000, 95_000, 110_000], p90=[100_000, 105_000, 130_000], safety_line=45_000),
    )


def make_scenario(*ms: OptionMetrics, rec: Recommendation, selected: str | None = None, version: int = 0) -> Scenario:
    return Scenario(
        id="scn_1",
        brand_id="b1",
        sku_id="sku_tee",
        supplier_id="sup_cn",
        options=[ScenarioOption(id=m.option_id, label=m.option_id.removeprefix("opt_"), quantity=m.quantity) for m in ms],
        state_version=version,
        result=SimulationResult(seed=42, input_hash="h", engine_version="test", horizon_days=120, n_paths=1000, options=list(ms)),
        recommendation=rec,
        selected_option_id=selected,
    )
