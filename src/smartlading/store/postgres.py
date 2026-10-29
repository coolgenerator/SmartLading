"""Postgres 仓储（psycopg 3）。表结构见 db/init/001_schema.sql。

约定：
- 每个方法只做一件事，事务由调用方用 `with repo.transaction():` 控制
- 任何影响模拟输入的写操作（接受/撤销信号、注入事件）都在同一事务里 bump brands.state_version
- 嵌套对象（模拟结果、推荐、解释、谈判轮次、预设事件信号）以 JSONB 整体读写
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from smartlading.events import InjectResult, inject_event
from smartlading.llm.extract_signals import BrandContext
from smartlading.llm.negotiate import FactoryAgentConfig
from smartlading.models import (
    SKU,
    Brand,
    Explanation,
    PurchaseOrder,
    Recommendation,
    RiskSignal,
    Scenario,
    ScenarioOption,
    SignalStatus,
    SimulationResult,
    Supplier,
    SupplierOffer,
)
from smartlading.models.p1 import Alert, FactoryPersona, Negotiation, NegotiationTurn, PresetEvent

DEFAULT_DSN = os.environ.get("SMARTLADING_DATABASE_URL", "postgresql://smartlading:smartlading@localhost:55461/smartlading")


class NotFound(LookupError):
    pass


class InvalidState(ValueError):
    pass


def connect(dsn: str = DEFAULT_DSN) -> psycopg.Connection[dict[str, Any]]:
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=True)


class Repository:
    def __init__(self, conn: psycopg.Connection[dict[str, Any]]) -> None:
        self.conn = conn

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self.conn.transaction():
            yield

    # ------------------------------------------------------------------
    # 通用
    # ------------------------------------------------------------------

    def _upsert(self, table: str, row: dict[str, Any], pk: tuple[str, ...] = ("id",)) -> None:
        cols = list(row)
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in pk)
        self.conn.execute(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
            f"ON CONFLICT ({', '.join(pk)}) DO UPDATE SET {updates}",
            [Jsonb(v) if isinstance(v, (dict, list)) and table != "risk_signals" else v for v in row.values()],
        )

    def _one(self, sql: str, params: tuple[Any, ...], what: str) -> dict[str, Any]:
        row = self.conn.execute(sql, params).fetchone()
        if row is None:
            raise NotFound(what)
        return row

    # ------------------------------------------------------------------
    # F1 业务状态
    # ------------------------------------------------------------------

    def upsert_brand(self, brand: Brand) -> None:
        self._upsert("brands", brand.model_dump(exclude={"cash_safety_line"}))

    def upsert_sku(self, sku: SKU) -> None:
        self._upsert("skus", sku.model_dump())

    def upsert_supplier(self, supplier: Supplier) -> None:
        self._upsert("suppliers", supplier.model_dump(exclude={"default_prob"}))

    def upsert_offer(self, offer: SupplierOffer) -> None:
        self._upsert("supplier_offers", offer.model_dump(), pk=("sku_id", "supplier_id"))

    def upsert_purchase_order(self, po: PurchaseOrder) -> None:
        self._upsert("purchase_orders", po.model_dump(mode="json"))

    def get_brand(self, brand_id: str) -> Brand:
        return Brand(**self._one("SELECT * FROM brands WHERE id = %s", (brand_id,), f"品牌 {brand_id}"))

    def list_skus(self, brand_id: str) -> list[SKU]:
        rows = self.conn.execute("SELECT * FROM skus WHERE brand_id = %s ORDER BY id", (brand_id,)).fetchall()
        return [SKU(**r) for r in rows]

    def list_suppliers(self, brand_id: str) -> list[Supplier]:
        rows = self.conn.execute("SELECT * FROM suppliers WHERE brand_id = %s ORDER BY id", (brand_id,)).fetchall()
        return [Supplier(**r) for r in rows]

    def list_offers(self, brand_id: str) -> list[SupplierOffer]:
        rows = self.conn.execute(
            "SELECT o.* FROM supplier_offers o JOIN skus s ON s.id = o.sku_id WHERE s.brand_id = %s ORDER BY o.sku_id, o.supplier_id",
            (brand_id,),
        ).fetchall()
        return [SupplierOffer(**r) for r in rows]

    def list_purchase_orders(self, brand_id: str) -> list[PurchaseOrder]:
        rows = self.conn.execute("SELECT * FROM purchase_orders WHERE brand_id = %s ORDER BY id", (brand_id,)).fetchall()
        return [PurchaseOrder(**r) for r in rows]

    def bump_state_version(self, brand_id: str) -> int:
        row = self._one(
            "UPDATE brands SET state_version = state_version + 1 WHERE id = %s RETURNING state_version", (brand_id,), f"品牌 {brand_id}"
        )
        return row["state_version"]

    def brand_context(self, brand_id: str) -> BrandContext:
        return BrandContext(
            brand_id=brand_id,
            skus=self.list_skus(brand_id),
            suppliers=self.list_suppliers(brand_id),
            offers=self.list_offers(brand_id),
        )

    # ------------------------------------------------------------------
    # F3 风险信号
    # ------------------------------------------------------------------

    def save_signal(self, signal: RiskSignal) -> None:
        row = signal.model_dump(mode="json", exclude={"quote_span"})
        row["quote_start"], row["quote_end"] = signal.quote_span
        self._upsert("risk_signals", row)

    def get_signal(self, signal_id: str) -> RiskSignal:
        return _signal(self._one("SELECT * FROM risk_signals WHERE id = %s", (signal_id,), f"信号 {signal_id}"))

    def list_signals(self, brand_id: str, status: SignalStatus | None = None) -> list[RiskSignal]:
        sql = "SELECT * FROM risk_signals WHERE brand_id = %s"
        params: tuple[Any, ...] = (brand_id,)
        if status is not None:
            sql += " AND status = %s"
            params += (status.value,)
        return [_signal(r) for r in self.conn.execute(sql + " ORDER BY created_at, id", params).fetchall()]

    def update_signal(self, signal_id: str, **changes: Any) -> RiskSignal:
        """用户修改 change_value / probability / target / effective_date（US-5）。只能改 pending 的信号。"""
        allowed = {"change_value", "probability", "target_type", "target_id", "effective_date", "change_type"}
        if bad := set(changes) - allowed:
            raise InvalidState(f"不能修改字段 {sorted(bad)}")
        with self.transaction():
            sig = self.get_signal(signal_id)
            if sig.status != SignalStatus.PENDING:
                raise InvalidState("只能修改待确认的信号")
            updated = RiskSignal(**(sig.model_dump() | changes | {"edited_by_user": True}))
            self.save_signal(updated)
        return updated

    def accept_signal(self, signal_id: str) -> tuple[RiskSignal, int]:
        """写入状态模型并 bump state_version；返回 (信号, 新版本号)。"""
        with self.transaction():
            sig = self.get_signal(signal_id)
            if sig.status != SignalStatus.PENDING:
                raise InvalidState(f"信号当前为 {sig.status}，不能接受")
            if not sig.matched:
                raise InvalidState("信号的影响对象不在品牌数据中，请先修改影响对象")
            self.conn.execute("UPDATE risk_signals SET status = 'accepted' WHERE id = %s", (signal_id,))
            version = self.bump_state_version(sig.brand_id)
        return sig.model_copy(update={"status": SignalStatus.ACCEPTED}), version

    def reject_signal(self, signal_id: str) -> tuple[RiskSignal, int]:
        """拒绝待确认信号，或撤销已接受的信号（后者会 bump state_version）。"""
        with self.transaction():
            sig = self.get_signal(signal_id)
            self.conn.execute("UPDATE risk_signals SET status = 'rejected' WHERE id = %s", (signal_id,))
            if sig.status == SignalStatus.ACCEPTED:
                version = self.bump_state_version(sig.brand_id)
            else:
                version = self.get_brand(sig.brand_id).state_version
        return sig.model_copy(update={"status": SignalStatus.REJECTED}), version

    # ------------------------------------------------------------------
    # F2 / F4 方案
    # ------------------------------------------------------------------

    def save_scenario(self, scenario: Scenario) -> None:
        row = scenario.model_dump(mode="json")
        row["options"] = Jsonb(row["options"])
        row["input_hash"] = row["input_hash"] or ""
        for key in ("result", "recommendation"):
            row[key] = Jsonb(row[key]) if row[key] is not None else None
        self._upsert("scenarios", row)

    def get_scenario(self, scenario_id: str) -> Scenario:
        r = self._one("SELECT * FROM scenarios WHERE id = %s", (scenario_id,), f"方案 {scenario_id}")
        return Scenario(
            id=r["id"],
            brand_id=r["brand_id"],
            sku_id=r["sku_id"],
            supplier_id=r["supplier_id"],
            options=[ScenarioOption(**o) for o in r["options"]],
            seed=r["seed"],
            horizon_days=r["horizon_days"],
            n_paths=r["n_paths"],
            state_version=r["state_version"],
            input_hash=r["input_hash"] or None,
            result=SimulationResult(**r["result"]) if r["result"] else None,
            recommendation=Recommendation(**r["recommendation"]) if r["recommendation"] else None,
            selected_option_id=r["selected_option_id"],
        )

    def stale_scenario_ids(self, brand_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT s.id FROM scenarios s JOIN brands b ON b.id = s.brand_id "
            "WHERE s.brand_id = %s AND s.result IS NOT NULL AND s.state_version <> b.state_version ORDER BY s.created_at",
            (brand_id,),
        ).fetchall()
        return [r["id"] for r in rows]

    def save_explanation(self, scenario_id: str, explanation: Explanation) -> None:
        self.conn.execute(
            "UPDATE scenarios SET explanation = %s WHERE id = %s", (Jsonb(explanation.model_dump(mode="json")), scenario_id)
        )

    def get_explanation(self, scenario_id: str) -> Explanation | None:
        r = self._one("SELECT explanation FROM scenarios WHERE id = %s", (scenario_id,), f"方案 {scenario_id}")
        return Explanation(**r["explanation"]) if r["explanation"] else None

    # ------------------------------------------------------------------
    # F5 事件与预警
    # ------------------------------------------------------------------

    def save_preset_event(self, brand_id: str, event: PresetEvent) -> None:
        self._upsert(
            "preset_events",
            {"id": event.id, "brand_id": brand_id, "name": event.name, "description": event.description, "signals": event.signal_templates},
        )

    def list_preset_events(self, brand_id: str) -> list[PresetEvent]:
        rows = self.conn.execute("SELECT * FROM preset_events WHERE brand_id = %s ORDER BY id", (brand_id,)).fetchall()
        return [_event(r) for r in rows]

    def get_preset_event(self, event_id: str) -> PresetEvent:
        return _event(self._one("SELECT * FROM preset_events WHERE id = %s", (event_id,), f"事件 {event_id}"))

    def inject_event(self, brand_id: str, event_id: str) -> tuple[InjectResult, int, list[str]]:
        """应用事件：写入 accepted 信号和预警，bump 版本。返回 (结果, 新版本号, 过期方案 id)。"""
        with self.transaction():
            # 锁住品牌行，避免并发注入时基于同一旧状态计算
            brand = Brand(**self._one("SELECT * FROM brands WHERE id = %s FOR UPDATE", (brand_id,), f"品牌 {brand_id}"))
            result = inject_event(
                self.get_preset_event(event_id),
                brand_id=brand_id,
                cash_balance=brand.cash_balance,
                credit_limit=brand.credit_limit,
                cash_safety_line=brand.cash_safety_line,
                skus=self.list_skus(brand_id),
                suppliers=self.list_suppliers(brand_id),
                offers=self.list_offers(brand_id),
                purchase_orders=self.list_purchase_orders(brand_id),
            )
            for sig in result.signals:
                self.save_signal(sig)
            for alert in result.alerts:
                self._upsert("alerts", {"brand_id": brand_id, **alert.model_dump()})
            version = self.bump_state_version(brand_id)
            stale = self.stale_scenario_ids(brand_id)
        return result, version, stale

    def list_alerts(self, brand_id: str, acknowledged: bool | None = None) -> list[Alert]:
        sql = "SELECT * FROM alerts WHERE brand_id = %s"
        params: tuple[Any, ...] = (brand_id,)
        if acknowledged is not None:
            sql += " AND acknowledged = %s"
            params += (acknowledged,)
        rows = self.conn.execute(sql + " ORDER BY created_at DESC, id", params).fetchall()
        return [Alert(**{k: v for k, v in r.items() if k != "brand_id"}) for r in rows]

    def ack_alert(self, alert_id: str) -> None:
        self._one("UPDATE alerts SET acknowledged = true WHERE id = %s RETURNING id", (alert_id,), f"预警 {alert_id}")

    # ------------------------------------------------------------------
    # F6 谈判
    # ------------------------------------------------------------------

    def save_factory_persona(self, supplier_id: str, persona: FactoryPersona, config: FactoryAgentConfig) -> None:
        self._upsert(
            "factory_personas",
            {"supplier_id": supplier_id, "persona": {"persona": persona.model_dump(), "config": config.model_dump()}},
            pk=("supplier_id",),
        )

    def get_factory_persona(self, supplier_id: str) -> tuple[FactoryPersona, FactoryAgentConfig]:
        r = self._one("SELECT persona FROM factory_personas WHERE supplier_id = %s", (supplier_id,), f"工厂设定 {supplier_id}")
        return FactoryPersona(**r["persona"]["persona"]), FactoryAgentConfig(**r["persona"]["config"])

    def save_negotiation(self, negotiation: Negotiation) -> None:
        row = negotiation.model_dump(mode="json")
        row["turns"] = Jsonb(row["turns"])
        self._upsert("negotiations", row)

    def get_negotiation(self, negotiation_id: str) -> Negotiation:
        r = self._one("SELECT * FROM negotiations WHERE id = %s", (negotiation_id,), f"谈判 {negotiation_id}")
        return Negotiation(
            id=r["id"],
            brand_id=r["brand_id"],
            supplier_id=r["supplier_id"],
            sku_id=r["sku_id"],
            base_scenario_id=r["base_scenario_id"],
            status=r["status"],
            turns=[NegotiationTurn(**t) for t in r["turns"]],
        )


def _signal(r: dict[str, Any]) -> RiskSignal:
    data = {k: v for k, v in r.items() if k not in ("quote_start", "quote_end", "created_at")}
    return RiskSignal(**data, quote_span=(r["quote_start"], r["quote_end"]))


def _event(r: dict[str, Any]) -> PresetEvent:
    return PresetEvent(id=r["id"], name=r["name"], description=r["description"], signal_templates=r["signals"])
