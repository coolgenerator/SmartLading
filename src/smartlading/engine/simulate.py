"""蒙特卡洛采购模拟（PRD「模拟引擎规格」）。

按天推进，向量化到所有路径上。所有方案共用同一组随机抽样（共同随机数），
所以方案之间的差异只来自决策变量，且同一种子下结果逐位一致。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from smartlading.engine.inputs import SimulationInput
from smartlading.models.entities import ScenarioOption
from smartlading.models.results import CashFan, OptionMetrics, SimulationResult
from smartlading.models.signals import SignalParameter

ENGINE_VERSION = "0.1.0"
RISK_SOURCES = ("demand", "lead_time", "tariff", "default")


@dataclass(frozen=True)
class Draws:
    demand_idx: np.ndarray  # (n, H)，需求模板的自助抽样下标
    lead_z: np.ndarray  # (n,)，交期的标准正态
    default_u: np.ndarray  # (n,)，违约判定
    signal_u: np.ndarray  # (n, k)，每条信号是否发生


@dataclass(frozen=True)
class PathParams:
    demand: np.ndarray  # (n, H)
    lead_days: np.ndarray  # (n,)
    defaulted: np.ndarray  # (n,)
    unit_cost: np.ndarray  # (n,)
    unit_freight: np.ndarray  # (n,)
    tariff: np.ndarray  # (n, H+1)，每天生效的税率


@dataclass(frozen=True)
class PathOutcome:
    cash: np.ndarray  # (n, H+1)
    inventory: np.ndarray  # (n, H+1)
    stockout: np.ndarray  # (n,)
    profit: np.ndarray  # (n,)
    credit_breach: np.ndarray  # (n,)
    runway: np.ndarray  # (n,)


def make_draws(inp: SimulationInput) -> Draws:
    cfg = inp.config
    rng = np.random.default_rng(cfg.seed)
    n, h = cfg.n_paths, cfg.horizon_days
    return Draws(
        demand_idx=rng.integers(0, len(inp.demand_template), size=(n, h)),
        lead_z=rng.standard_normal(n),
        default_u=rng.random(n),
        signal_u=rng.random((n, len(inp.signals))),
    )


def path_params(inp: SimulationInput, draws: Draws, disable: frozenset[str] = frozenset()) -> PathParams:
    """把随机抽样和已接受信号落到每条路径的参数上。

    disable 中的风险源被替换为确定值（用于风险归因）：
    demand → 模板均值；lead_time → 基础交期均值；tariff → 基础税率；default → 不违约。
    """
    n, h = inp.config.n_paths, inp.config.horizon_days
    occurred = draws.signal_u < np.array([s.probability for s in inp.signals])

    def with_signals(base: float, parameter: SignalParameter) -> np.ndarray:
        values = np.full(n, base, dtype=float)
        for j, s in enumerate(inp.signals):
            if s.parameter == parameter:
                values = np.where(occurred[:, j], s.apply(values), values)
        return values

    template = np.asarray(inp.demand_template, dtype=float)
    if "demand" in disable:
        demand = np.full((n, h), template.mean() * inp.demand_scale)
    else:
        demand = template[draws.demand_idx] * inp.demand_scale

    if "lead_time" in disable:
        lead_days = np.full(n, max(1, round(inp.lead_time_mean)), dtype=np.int64)
    else:
        mean = np.maximum(with_signals(inp.lead_time_mean, SignalParameter.LEAD_TIME_MEAN_DAYS), 1e-9)
        std = np.maximum(with_signals(inp.lead_time_std, SignalParameter.LEAD_TIME_STD_DAYS), 0.0)
        # 对数正态：按目标均值和标准差反解 mu、sigma
        sigma2 = np.log1p((std / mean) ** 2)
        mu = np.log(mean) - sigma2 / 2
        lead_days = np.maximum(1, np.rint(np.exp(mu + np.sqrt(sigma2) * draws.lead_z))).astype(np.int64)

    if "default" in disable:
        defaulted = np.zeros(n, dtype=bool)
    else:
        prob = np.clip(with_signals(inp.default_prob, SignalParameter.DEFAULT_PROB), 0.0, 1.0)
        defaulted = draws.default_u < prob

    tariff = np.full((n, h + 1), inp.tariff_rate, dtype=float)
    if "tariff" not in disable:
        days = np.arange(h + 1)
        for j, s in enumerate(inp.signals):
            if s.parameter == SignalParameter.TARIFF_RATE:
                mask = occurred[:, j, None] & (days >= s.effective_day)[None, :]
                tariff = np.where(mask, s.apply(tariff), tariff)
        tariff = np.maximum(tariff, 0.0)

    return PathParams(
        demand=demand,
        lead_days=lead_days,
        defaulted=defaulted,
        unit_cost=np.maximum(with_signals(inp.unit_cost, SignalParameter.UNIT_COST), 0.0),
        unit_freight=np.maximum(with_signals(inp.unit_freight, SignalParameter.UNIT_FREIGHT), 0.0),
        tariff=tariff,
    )


def simulate_option(inp: SimulationInput, pp: PathParams, option: ScenarioOption) -> PathOutcome:
    """单个方案的逐日推进：

    S_t = min(D_t, I_{t-1});  I_t = I_{t-1} - S_t + 到货
    C_t = C_{t-1} + (P - m) S_t - F - Pay_t
    付款：下单付 αQc，出货付 (1-α)Qc，到港付 τQc + Qf；违约时预付款损失且不交货。
    """
    cfg = inp.config
    n, h = cfg.n_paths, cfg.horizon_days
    q = option.quantity
    alpha = inp.prepay_for(option)
    # 谈判试算的新单价直接覆盖报价（及作用于报价的信号）
    c = pp.unit_cost if option.unit_cost is None else np.full(n, option.unit_cost)
    f = pp.unit_freight
    lead = pp.lead_days
    ship = np.clip(np.rint(lead * cfg.production_fraction), 1, lead).astype(np.int64)
    delivered = ~pp.defaulted
    unit_margin = inp.price - inp.unit_fee

    inbound_by_day: dict[int, list] = {}
    for s in inp.inbound:
        inbound_by_day.setdefault(s.arrival_day, []).append(s)

    cash = np.empty((n, h + 1))
    inventory = np.empty((n, h + 1))
    prepay = alpha * q * c
    cash[:, 0] = inp.cash0 - prepay
    inventory[:, 0] = inp.on_hand
    costs = prepay.copy()
    margin = np.zeros(n)
    stockout = np.zeros(n, dtype=bool)

    for t in range(1, h + 1):
        inv_prev = inventory[:, t - 1]
        demand = pp.demand[:, t - 1]
        sales = np.minimum(demand, inv_prev)
        stockout |= demand > inv_prev + 1e-9

        pay = np.where(delivered & (ship == t), (1 - alpha) * q * c, 0.0)
        arrived = delivered & (lead == t)
        arrivals = np.where(arrived, float(q), 0.0)
        pay += np.where(arrived, pp.tariff[:, t] * q * c + q * f, 0.0)
        for s in inbound_by_day.get(t, ()):
            arrivals += s.quantity
            pay += pp.tariff[:, t] * s.quantity * s.unit_cost + s.quantity * s.unit_freight

        inventory[:, t] = inv_prev - sales + arrivals
        margin += unit_margin * sales
        costs += pay
        cash[:, t] = cash[:, t - 1] + unit_margin * sales - inp.daily_fixed_cost - pay

    profit = margin - costs
    if cfg.value_ending_inventory:
        landed = c * (1 + pp.tariff[:, h]) + f
        profit = profit + inventory[:, h] * landed

    below = cash < inp.safety_line
    runway = np.where(below.any(axis=1), below.argmax(axis=1), h + 1)
    return PathOutcome(
        cash=cash,
        inventory=inventory,
        stockout=stockout,
        profit=profit,
        credit_breach=(cash < -inp.credit_limit).any(axis=1),
        runway=runway,
    )


def _money(x: float) -> float:
    return round(float(x), 2)


def summarize(
    inp: SimulationInput,
    option: ScenarioOption,
    outcome: PathOutcome,
    defaulted: np.ndarray,
    risk_attribution: dict[str, float],
) -> OptionMetrics:
    h = inp.config.horizon_days
    r10, r50, r90 = np.percentile(outcome.runway, [10, 50, 90], method="lower")
    fan = np.percentile(outcome.cash, [10, 50, 90], axis=0)
    return OptionMetrics(
        option_id=option.id,
        quantity=option.quantity,
        prepay_ratio=inp.prepay_for(option),
        unit_cost=inp.unit_cost if option.unit_cost is None else option.unit_cost,
        runway_p10=int(r10),
        runway_p50=int(r50),
        runway_p90=int(r90),
        stockout_prob=float(outcome.stockout.mean()),
        expected_profit=_money(outcome.profit.mean()),
        worst_case_p5=_money(np.percentile(outcome.profit, 5)),
        credit_breach_prob=float(outcome.credit_breach.mean()),
        default_loss_prob=float(defaulted.mean()),
        risk_attribution=risk_attribution,
        cash_fan=CashFan(
            days=list(range(h + 1)),
            p10=[_money(v) for v in fan[0]],
            p50=[_money(v) for v in fan[1]],
            p90=[_money(v) for v in fan[2]],
            safety_line=inp.safety_line,
        ),
    )


def attribute_risk(
    inp: SimulationInput,
    option: ScenarioOption,
    base_p5: float,
    disabled_params: dict[str, PathParams],
) -> dict[str, float]:
    """逐个关掉风险源，看 P5 利润改善多少，归一化为相对贡献。"""
    gains = {}
    for source, pp in disabled_params.items():
        p5 = np.percentile(simulate_option(inp, pp, option).profit, 5)
        gains[source] = max(0.0, float(p5 - base_p5))
    total = sum(gains.values())
    return {k: (round(v / total, 4) if total > 0 else 0.0) for k, v in gains.items()}


class Simulator:
    """一次抽样、多次评估：方案比较和网格搜索共用同一组随机数。"""

    def __init__(self, inp: SimulationInput):
        self.inp = inp
        self.draws = make_draws(inp)
        self.base = path_params(inp, self.draws)
        self._disabled: dict[str, PathParams] | None = None

    @property
    def disabled(self) -> dict[str, PathParams]:
        if self._disabled is None:
            self._disabled = {s: path_params(self.inp, self.draws, frozenset({s})) for s in RISK_SOURCES}
        return self._disabled

    def evaluate(self, option: ScenarioOption, attribution: bool | None = None) -> OptionMetrics:
        if attribution is None:
            attribution = self.inp.config.compute_attribution
        outcome = simulate_option(self.inp, self.base, option)
        if attribution:
            base_p5 = float(np.percentile(outcome.profit, 5))
            risk = attribute_risk(self.inp, option, base_p5, self.disabled)
        else:
            risk = {}
        return summarize(self.inp, option, outcome, self.base.defaulted, risk)


def run_scenario(inp: SimulationInput) -> SimulationResult:
    sim = Simulator(inp)
    return SimulationResult(
        seed=inp.config.seed,
        input_hash=inp.input_hash(),
        engine_version=ENGINE_VERSION,
        horizon_days=inp.config.horizon_days,
        n_paths=inp.config.n_paths,
        options=[sim.evaluate(o) for o in inp.options],
    )
