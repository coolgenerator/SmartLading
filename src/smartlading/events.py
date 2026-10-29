"""事件注入与在途订单预警（F5）。

Demo 中点按钮回放预设事件：事件里的参数变化以 accepted 信号写入（由仓储层 bump
state_version，已有方案随之过期），并对受影响的计划中/在途订单生成预警。
预警金额全部由规则计算，不经过 LLM。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel

from smartlading.models import SKU, POStatus, PurchaseOrder, RiskSignal, SignalParameter, SignalStatus, Supplier, SupplierOffer
from smartlading.models.p1 import Alert, PresetEvent


class InjectResult(BaseModel):
    signals: list[RiskSignal]
    alerts: list[Alert]
    total_extra_cost: float


def inject_event(
    event: PresetEvent,
    *,
    brand_id: str,
    cash_balance: float,
    credit_limit: float,
    cash_safety_line: float,
    skus: list[SKU],
    suppliers: list[Supplier],
    offers: list[SupplierOffer],
    purchase_orders: list[PurchaseOrder],
) -> InjectResult:
    """基于事件前的状态计算影响；返回的信号和预警由调用方持久化。"""
    signals = [
        RiskSignal(
            id=f"sig_{uuid.uuid4().hex[:10]}",
            brand_id=brand_id,
            source_text=event.description,
            source_type="other",
            quote=event.description,
            quote_span=(0, len(event.description)),
            status=SignalStatus.ACCEPTED,
            rationale=f"Preset event: {event.name}",
            **{"probability": 1.0, **tpl},
        )
        for tpl in event.signal_templates
    ]

    sku_by_id = {s.id: s for s in skus}
    sup_by_id = {s.id: s for s in suppliers}
    offer_by_key = {(o.sku_id, o.supplier_id): o for o in offers}
    headroom = cash_balance + credit_limit - cash_safety_line
    now = datetime.now(timezone.utc)

    alerts: list[Alert] = []
    cumulative = 0.0
    for sig in signals:
        for po in purchase_orders:
            if po.status == POStatus.ARRIVED:
                continue
            sku, sup = sku_by_id[po.sku_id], sup_by_id[po.supplier_id]
            offer = offer_by_key[(po.sku_id, po.supplier_id)]
            impact = _impact(sig, po, sku, sup, offer)
            if impact is None:
                continue
            extra, message, next_step = impact
            gap_before = max(0.0, cumulative - headroom)
            cumulative += extra
            alerts.append(
                Alert(
                    id=f"alt_{uuid.uuid4().hex[:10]}",
                    event_id=event.id,
                    purchase_order_id=po.id,
                    extra_cost=round(extra, 2),
                    # 本条预警新增的现金缺口（现金 + 授信 − 安全线 不够覆盖累计新增支出的部分）
                    cash_gap=round(max(0.0, cumulative - headroom) - gap_before, 2),
                    message=message,
                    next_step=next_step,
                    created_at=now,
                )
            )
    return InjectResult(signals=signals, alerts=alerts, total_extra_cost=round(cumulative, 2))


def _targets(sig: RiskSignal, po: PurchaseOrder, sku: SKU) -> bool:
    match sig.target_type:
        case "hts_code":
            return sku.hts_code == sig.target_id
        case "sku":
            return po.sku_id == sig.target_id
        case "supplier":
            return po.supplier_id == sig.target_id


def _impact(sig: RiskSignal, po: PurchaseOrder, sku: SKU, sup: Supplier, offer: SupplierOffer) -> tuple[float, str, str] | None:
    if not _targets(sig, po, sku):
        return None
    goods = po.quantity * offer.unit_cost
    in_transit = po.status == POStatus.IN_TRANSIT

    match sig.parameter:
        case SignalParameter.TARIFF_RATE:
            old = sku.tariff_rate
            new = sig.apply(old)
            extra = (new - old) * goods * sig.probability
            if extra <= 0:
                return None
            return (
                extra,
                f"{sku.name} tariff {old:.0%} → {new:.0%}: order {po.id} will owe about ${extra:,.0f} more duty on arrival",
                "The duty on an in-transit order can no longer be avoided. Set aside cash for it on arrival, and consider shipping planned orders earlier or from another country."
                if in_transit
                else "The order has not shipped yet. Rerun the simulation to compare shipping earlier, ordering less, or sourcing from another country.",
            )
        case SignalParameter.UNIT_COST | SignalParameter.UNIT_FREIGHT:
            if in_transit and sig.parameter is SignalParameter.UNIT_COST:
                return None  # 在途订单货款已锁定
            old = getattr(offer, sig.parameter.value)
            extra = (sig.apply(old) - old) * po.quantity * sig.probability
            if extra <= 0:
                return None
            label = "purchase cost" if sig.parameter is SignalParameter.UNIT_COST else "freight"
            return (
                extra,
                f"Order {po.id} ({sku.name}): {label} expected to rise by ${extra:,.0f}",
                "The order has not been placed yet. Try new terms in the negotiation room, or compare quotes from other suppliers.",
            )
        case SignalParameter.LEAD_TIME_MEAN_DAYS:
            delay = sig.apply(sup.lead_time_mean_days) - sup.lead_time_mean_days
            if delay <= 0:
                return None
            return (
                0.0,
                f"{sup.name} lead time expected to grow by {delay:.0f} days, affecting order {po.id} ({sku.name}, {sku.on_hand:,} units on hand)",
                "Rerun the simulation to see how the stockout probability changes. If needed, air-freight a small top-up batch or slow down ad spend.",
            )
        case SignalParameter.DEFAULT_PROB:
            exposure = goods * po.prepay_ratio
            delta = sig.apply(sup.default_prob) - sup.default_prob
            if delta <= 0:
                return None
            expected_loss = exposure * delta * sig.probability
            return (
                expected_loss,
                f"{sup.name} default risk is up: the ${exposure:,.0f} prepaid on order {po.id} is at risk, and the expected loss rises by ${expected_loss:,.0f}",
                "Confirm the factory's production and shipping schedule now. For future orders, lower the prepayment or split the order.",
            )
    return None
