"""引擎输入：从业务实体抽出的不可变快照。

引擎只吃 SimulationInput，不碰仓储或 LLM；同一个快照的 JSON 哈希即 input_hash，
相同 input_hash 必须产出逐位一致的结果。
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from smartlading.models.entities import (
    SKU,
    Brand,
    POStatus,
    PurchaseOrder,
    ScenarioOption,
    Supplier,
    SupplierOffer,
)
from smartlading.models.signals import RiskSignal, SignalParameter, SignalStatus

# 条款类参数是确定性的：一旦接受就直接改写快照，不参与按路径随机跳变
_TERMS_PARAMETERS = {SignalParameter.MOQ, SignalParameter.PREPAY_RATIO}


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class SimConfig(_Frozen):
    seed: int = 42
    horizon_days: int = Field(default=120, gt=0)
    n_paths: int = Field(default=1000, gt=0)
    # [假设] 出货日 = 交期 × 该比例（剩余为海运）；出货时付尾款
    production_fraction: float = Field(default=0.5, gt=0.0, le=1.0)
    # 可行约束：runway_p10 >= min_runway_days；None = horizon_days + 1（P10 路径从未触及安全线）
    min_runway_days: int | None = None
    # PRD 的利润是现金口径（期末剩余库存不计价）；打开后按到岸成本计入期末库存
    value_ending_inventory: bool = False
    compute_attribution: bool = True

    @property
    def resolved_min_runway_days(self) -> int:
        return self.horizon_days + 1 if self.min_runway_days is None else self.min_runway_days


class InboundShipment(_Frozen):
    """已在途的订单：尾款视为已付，到港日付关税和运费。"""

    arrival_day: int = Field(ge=1)
    quantity: int = Field(gt=0)
    unit_cost: float
    unit_freight: float


class EngineSignal(_Frozen):
    """以概率 probability 在每条路径上发生；关税从 effective_day 起生效。"""

    parameter: SignalParameter
    change_type: Literal["set", "delta", "multiply"]
    change_value: float
    probability: float = Field(ge=0.0, le=1.0)
    effective_day: int = Field(default=0, ge=0)

    def apply(self, value):
        match self.change_type:
            case "set":
                return self.change_value + 0 * value
            case "delta":
                return value + self.change_value
            case "multiply":
                return value * self.change_value


class SimulationInput(_Frozen):
    start_date: date
    # 品牌
    cash0: float
    credit_limit: float
    safety_line: float
    daily_fixed_cost: float
    # SKU
    price: float
    unit_fee: float
    on_hand: int
    tariff_rate: float
    demand_template: tuple[float, ...] = Field(min_length=1)
    demand_scale: float = 1.0
    # 供应商与报价
    unit_cost: float
    unit_freight: float
    lead_time_mean: float
    lead_time_std: float
    default_prob: float
    default_prepay_ratio: float
    moq: int
    # 其余
    inbound: tuple[InboundShipment, ...] = ()
    signals: tuple[EngineSignal, ...] = ()
    options: tuple[ScenarioOption, ...] = Field(min_length=1)
    config: SimConfig = SimConfig()

    def input_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()

    def prepay_for(self, option: ScenarioOption) -> float:
        return self.default_prepay_ratio if option.prepay_ratio is None else option.prepay_ratio


def _signal_targets(signal: RiskSignal, sku: SKU, supplier: Supplier) -> bool:
    match signal.target_type:
        case "hts_code":
            return signal.target_id == sku.hts_code
        case "sku":
            return signal.target_id == sku.id
        case "supplier":
            return signal.target_id == supplier.id


def build_input(
    *,
    brand: Brand,
    sku: SKU,
    supplier: Supplier,
    offer: SupplierOffer,
    options: Sequence[ScenarioOption],
    demand_template: Sequence[float],
    start_date: date,
    purchase_orders: Sequence[PurchaseOrder] = (),
    offers_by_supplier: dict[str, SupplierOffer] | None = None,
    signals: Sequence[RiskSignal] = (),
    config: SimConfig = SimConfig(),
) -> SimulationInput:
    """把业务实体组装成引擎快照。

    - 只纳入该 SKU 的在途订单，其成本按对应供应商的报价计（缺省用本次报价）
    - 只纳入 accepted 且目标匹配的信号；条款类信号（moq、prepay_ratio）直接改写快照
    """
    if offer.sku_id != sku.id or offer.supplier_id != supplier.id:
        raise ValueError("offer does not match the given sku/supplier")
    offers_by_supplier = offers_by_supplier or {}
    terms = {"moq": float(supplier.moq), "prepay_ratio": supplier.default_prepay_ratio}
    engine_signals: list[EngineSignal] = []
    for s in signals:
        if s.status != SignalStatus.ACCEPTED or not _signal_targets(s, sku, supplier):
            continue
        if s.parameter in _TERMS_PARAMETERS:
            terms[s.parameter.value] = s.apply(terms[s.parameter.value])
            continue
        effective_day = 0 if s.effective_date is None else max(0, (s.effective_date - start_date).days)
        engine_signals.append(
            EngineSignal(
                parameter=s.parameter,
                change_type=s.change_type,
                change_value=s.change_value,
                probability=s.probability,
                effective_day=effective_day,
            )
        )

    inbound = []
    for po in purchase_orders:
        if po.sku_id != sku.id or po.status != POStatus.IN_TRANSIT:
            continue
        assert po.eta is not None
        po_offer = offers_by_supplier.get(po.supplier_id, offer)
        inbound.append(
            InboundShipment(
                arrival_day=max(1, (po.eta - start_date).days),
                quantity=po.quantity,
                unit_cost=po_offer.unit_cost,
                unit_freight=po_offer.unit_freight,
            )
        )

    return SimulationInput(
        start_date=start_date,
        cash0=brand.cash_balance,
        credit_limit=brand.credit_limit,
        safety_line=brand.cash_safety_line,
        daily_fixed_cost=brand.daily_fixed_cost,
        price=sku.price,
        unit_fee=sku.unit_platform_fee,
        on_hand=sku.on_hand,
        tariff_rate=sku.tariff_rate,
        demand_template=tuple(demand_template),
        demand_scale=sku.demand_scale,
        unit_cost=offer.unit_cost,
        unit_freight=offer.unit_freight,
        lead_time_mean=supplier.lead_time_mean_days,
        lead_time_std=supplier.lead_time_std_days,
        default_prob=supplier.default_prob,
        default_prepay_ratio=min(1.0, max(0.0, terms["prepay_ratio"])),
        moq=int(terms["moq"]),
        inbound=tuple(inbound),
        signals=tuple(engine_signals),
        options=tuple(options),
        config=config,
    )
