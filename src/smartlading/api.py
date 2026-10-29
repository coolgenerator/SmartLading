"""FastAPI 层（design.md §3，前缀 /api/v1）。

只做编排：读写走 store.Repository，数字全部来自 engine，文字来自 llm。
响应在模型字段之外附带前端要用的派生字段（相对今天的天数、地图坐标、日均需求），
这些字段不回写数据库。

    uv run uvicorn smartlading.api:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from smartlading import demo
from smartlading.engine import SimConfig, Simulator, build_input, recommend, suggest_quantity
from smartlading.engine.simulate import ENGINE_VERSION
from smartlading.llm import make_llm
from smartlading.llm.client import LLMError, StructuredLLM
from smartlading.llm.explain import Explainer
from smartlading.llm.extract_signals import SignalExtractor
from smartlading.llm.negotiate import FactoryNegotiator
from smartlading.models import SKU, Brand, PurchaseOrder, RiskSignal, Scenario, ScenarioOption, SignalStatus, Supplier
from smartlading.models.p1 import Negotiation, Terms
from smartlading.models.results import OptionMetrics, SimulationResult
from smartlading.store.postgres import InvalidState, NotFound, Repository, connect

log = logging.getLogger(__name__)


def _load_dotenv() -> None:
    env = Path(__file__).resolve().parents[2] / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

app = FastAPI(title="SmartLading API", version=ENGINE_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(NotFound)
def _not_found(_: Request, e: NotFound) -> JSONResponse:
    return JSONResponse({"error": {"code": "not_found", "message": str(e)}}, status_code=404)


@app.exception_handler(InvalidState)
def _invalid(_: Request, e: InvalidState) -> JSONResponse:
    return JSONResponse({"error": {"code": "invalid_state", "message": str(e)}}, status_code=409)


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"error": {"code": code, "message": message}})


def repo() -> Iterator[Repository]:
    conn = connect()
    try:
        yield Repository(conn)
        conn.commit()
    finally:
        conn.close()


Repo = Depends(repo)

_llm: StructuredLLM | None = None
_llm_error: str | None = None


def llm() -> StructuredLLM | None:
    global _llm, _llm_error
    if _llm is None and _llm_error is None:
        try:
            _llm = make_llm()
        except Exception as e:  # 缺 key 等：模拟器仍可独立使用
            _llm_error = str(e)
            log.warning("LLM unavailable: %s", e)
    return _llm


# ---------------------------------------------------------------------------
# 视图：模型 + 前端派生字段
# ---------------------------------------------------------------------------


def _days(d: date | None) -> int:
    return 0 if d is None else (d - date.today()).days


def v_brand(b: Brand) -> dict[str, Any]:
    days = b.safety_line_days if b.safety_line_mode == "days_of_fixed_cost" else round(b.cash_safety_line / max(b.daily_fixed_cost, 1))
    return b.model_dump() | {"safety_line_days": days}


def v_sku(s: SKU) -> dict[str, Any]:
    mean = float(np.mean(demo.demand_template(s.demand_template_id)))
    return s.model_dump() | {"daily_demand": round(mean * s.demand_scale, 1)}


def v_supplier(s: Supplier) -> dict[str, Any]:
    city, lat, lng = demo.SUPPLIER_GEO.get(s.id, (s.country, 0.0, 0.0))
    return s.model_dump() | {"city": city, "lat": lat, "lng": lng}


def v_po(p: PurchaseOrder) -> dict[str, Any]:
    return p.model_dump(mode="json") | {"ship_day": _days(p.ship_date or p.order_date), "eta_day": _days(p.eta)}


def v_signal(s: RiskSignal) -> dict[str, Any]:
    return s.model_dump(mode="json") | {"effective_day": max(0, _days(s.effective_date)) if s.effective_date else 0}


def v_scenario(scn: Scenario, brand: Brand, elapsed_ms: int | None = None) -> dict[str, Any]:
    out = scn.model_dump(mode="json") | {"is_stale": scn.is_stale(brand)}
    if scn.result is not None:
        out["result"]["elapsed_ms"] = elapsed_ms or 0
        out["grid"] = [g.model_dump() for g in scn.result.suggested.grid] if scn.result.suggested else []
    return out


def brand_view(r: Repository, brand_id: str) -> dict[str, Any]:
    brand = r.get_brand(brand_id)
    signals = r.list_signals(brand_id)
    injected = sorted({s.rationale.removeprefix("Preset event: ") for s in signals if s.rationale.startswith("Preset event: ")})
    events = r.list_preset_events(brand_id)
    return {
        "brand": v_brand(brand),
        "skus": [v_sku(s) for s in r.list_skus(brand_id)],
        "suppliers": [v_supplier(s) for s in r.list_suppliers(brand_id)],
        "offers": [o.model_dump() for o in r.list_offers(brand_id)],
        "purchase_orders": [v_po(p) for p in r.list_purchase_orders(brand_id)],
        "signals": [v_signal(s) for s in reversed(signals)],
        "alerts": [a.model_dump(mode="json") for a in r.list_alerts(brand_id)],
        "events": [{"id": e.id, "name": e.name, "description": e.description} for e in events],
        "injected": [e.id for e in events if e.name in injected],
    }


# ---------------------------------------------------------------------------
# Demo / 系统（§3.7）
# ---------------------------------------------------------------------------


def seed_demo(r: Repository) -> None:
    today = date.today()
    with r.transaction():
        r.conn.execute("DELETE FROM negotiations WHERE brand_id = %s", (demo.BRAND_ID,))
        r.conn.execute("DELETE FROM alerts WHERE brand_id = %s", (demo.BRAND_ID,))
        r.conn.execute("DELETE FROM scenarios WHERE brand_id = %s", (demo.BRAND_ID,))
        r.conn.execute("DELETE FROM purchase_orders WHERE brand_id = %s", (demo.BRAND_ID,))
        r.conn.execute("DELETE FROM brands WHERE id = %s", (demo.BRAND_ID,))
        r.upsert_brand(demo.brand())
        for s in demo.suppliers():
            r.upsert_supplier(s)
        for s in demo.skus():
            r.upsert_sku(s)
        for o in demo.offers():
            r.upsert_offer(o)
        for p in demo.purchase_orders(today):
            r.upsert_purchase_order(p)
        for e in demo.preset_events(today):
            r.save_preset_event(demo.BRAND_ID, e)


@app.get("/api/v1/health")
def health() -> dict[str, Any]:
    model = llm()
    return {"ok": True, "engine_version": ENGINE_VERSION, "llm": model is not None, "llm_error": _llm_error}


@app.post("/api/v1/demo/seed")
def demo_seed(r: Repository = Repo) -> dict[str, Any]:
    """首次加载时调用：品牌不存在才写入种子数据。"""
    try:
        r.get_brand(demo.BRAND_ID)
    except NotFound:
        seed_demo(r)
    return brand_view(r, demo.BRAND_ID)


@app.post("/api/v1/demo/reset")
def demo_reset(r: Repository = Repo) -> dict[str, Any]:
    seed_demo(r)
    return brand_view(r, demo.BRAND_ID)


@app.get("/api/v1/brands/{brand_id}/risk-signals/samples")
def samples(brand_id: str) -> list[dict[str, str]]:
    return demo.SAMPLE_NEWS


# ---------------------------------------------------------------------------
# F1 业务状态（§3.1）
# ---------------------------------------------------------------------------


@app.get("/api/v1/brands/{brand_id}")
def get_brand(brand_id: str, r: Repository = Repo) -> dict[str, Any]:
    return brand_view(r, brand_id)


class BrandPatch(BaseModel):
    cash_balance: float | None = None
    credit_limit: float | None = Field(default=None, ge=0)
    daily_fixed_cost: float | None = Field(default=None, ge=0)
    safety_line_days: int | None = Field(default=None, ge=0)


class SupplierPatch(BaseModel):
    lead_time_mean_days: float | None = Field(default=None, gt=0)
    lead_time_std_days: float | None = Field(default=None, ge=0)
    moq: int | None = Field(default=None, ge=0)
    default_prepay_ratio: float | None = Field(default=None, ge=0, le=1)
    risk_score: float | None = Field(default=None, ge=0, le=1)


class SkuPatch(BaseModel):
    price: float | None = Field(default=None, gt=0)
    on_hand: int | None = Field(default=None, ge=0)
    tariff_rate: float | None = Field(default=None, ge=0)


def _changes(p: BaseModel) -> dict[str, Any]:
    return p.model_dump(exclude_none=True)


@app.patch("/api/v1/brands/{brand_id}")
def patch_brand(brand_id: str, patch: BrandPatch, r: Repository = Repo) -> dict[str, Any]:
    with r.transaction():
        b = r.get_brand(brand_id)
        r.upsert_brand(Brand(**(b.model_dump(exclude={"cash_safety_line"}) | _changes(patch))))
        version = r.bump_state_version(brand_id)
    return {"brand": v_brand(r.get_brand(brand_id)), "state_version": version}


@app.patch("/api/v1/brands/{brand_id}/suppliers/{supplier_id}")
def patch_supplier(brand_id: str, supplier_id: str, patch: SupplierPatch, r: Repository = Repo) -> dict[str, Any]:
    with r.transaction():
        s = next((x for x in r.list_suppliers(brand_id) if x.id == supplier_id), None)
        if s is None:
            raise NotFound(f"supplier {supplier_id}")
        updated = Supplier(**(s.model_dump(exclude={"default_prob"}) | _changes(patch)))
        r.upsert_supplier(updated)
        version = r.bump_state_version(brand_id)
    return {"supplier": v_supplier(updated), "state_version": version}


@app.patch("/api/v1/brands/{brand_id}/skus/{sku_id}")
def patch_sku(brand_id: str, sku_id: str, patch: SkuPatch, r: Repository = Repo) -> dict[str, Any]:
    with r.transaction():
        s = next((x for x in r.list_skus(brand_id) if x.id == sku_id), None)
        if s is None:
            raise NotFound(f"sku {sku_id}")
        updated = SKU(**(s.model_dump() | _changes(patch)))
        r.upsert_sku(updated)
        version = r.bump_state_version(brand_id)
    return {"sku": v_sku(updated), "state_version": version}


# ---------------------------------------------------------------------------
# F2 / F4 模拟、推荐与解释（§3.2、§3.4）
# ---------------------------------------------------------------------------


class OptionIn(BaseModel):
    label: str
    quantity: int = Field(gt=0)
    prepay_ratio: float | None = Field(default=None, ge=0, le=1)
    id: str | None = None


class ScenarioIn(BaseModel):
    sku_id: str
    supplier_id: str
    options: list[OptionIn] = Field(min_length=2, max_length=3)
    seed: int = 42
    horizon_days: int = 120
    n_paths: int = 1000
    id: str | None = None  # 带上已有 id = 用当前状态重跑同一个方案


def _simulator(r: Repository, brand_id: str, sku_id: str, supplier_id: str, options: list[ScenarioOption], cfg: SimConfig) -> Simulator:
    brand = r.get_brand(brand_id)
    sku = next((s for s in r.list_skus(brand_id) if s.id == sku_id), None)
    supplier = next((s for s in r.list_suppliers(brand_id) if s.id == supplier_id), None)
    offers = r.list_offers(brand_id)
    offer = next((o for o in offers if o.sku_id == sku_id and o.supplier_id == supplier_id), None)
    if sku is None or supplier is None or offer is None:
        raise _error(422, "no_offer", f"{supplier_id} has no quote for {sku_id}")
    inp = build_input(
        brand=brand, sku=sku, supplier=supplier, offer=offer, options=options,
        demand_template=demo.demand_template(sku.demand_template_id), start_date=date.today(),
        purchase_orders=r.list_purchase_orders(brand_id),
        offers_by_supplier={o.supplier_id: o for o in offers if o.sku_id == sku_id},
        signals=r.list_signals(brand_id, SignalStatus.ACCEPTED), config=cfg,
    )
    return Simulator(inp)


@app.post("/api/v1/brands/{brand_id}/scenarios", status_code=201)
def create_scenario(brand_id: str, body: ScenarioIn, r: Repository = Repo) -> dict[str, Any]:
    options = [ScenarioOption(id=o.id or f"opt_{o.label}", label=o.label, quantity=o.quantity, prepay_ratio=o.prepay_ratio) for o in body.options]
    cfg = SimConfig(seed=body.seed, horizon_days=body.horizon_days, n_paths=body.n_paths)
    started = time.monotonic()
    sim = _simulator(r, brand_id, body.sku_id, body.supplier_id, options, cfg)
    if bad := [o.label for o in options if o.quantity < sim.inp.moq]:
        raise _error(422, "below_moq", f"Option {', '.join(bad)} is below the supplier MOQ of {sim.inp.moq:,} units")
    result = SimulationResult(
        seed=cfg.seed, input_hash=sim.inp.input_hash(), engine_version=ENGINE_VERSION,
        horizon_days=cfg.horizon_days, n_paths=cfg.n_paths, options=[sim.evaluate(o) for o in options],
    )
    result.suggested = suggest_quantity(sim)
    rec = recommend(result)
    brand = r.get_brand(brand_id)
    scn = Scenario(
        id=body.id or f"scn_{uuid.uuid4().hex[:10]}", brand_id=brand_id, sku_id=body.sku_id, supplier_id=body.supplier_id,
        options=options, seed=cfg.seed, horizon_days=cfg.horizon_days, n_paths=cfg.n_paths, state_version=brand.state_version,
        input_hash=result.input_hash, result=result, recommendation=rec, selected_option_id=rec.recommended_option_id,
    )
    r.save_scenario(scn)
    r.conn.execute("UPDATE scenarios SET explanation = NULL WHERE id = %s", (scn.id,))
    return v_scenario(scn, brand, round((time.monotonic() - started) * 1000))


@app.get("/api/v1/brands/{brand_id}/scenarios/{scenario_id}")
def get_scenario(brand_id: str, scenario_id: str, r: Repository = Repo) -> dict[str, Any]:
    return v_scenario(r.get_scenario(scenario_id), r.get_brand(brand_id))


class SelectionIn(BaseModel):
    option_id: str


@app.put("/api/v1/brands/{brand_id}/scenarios/{scenario_id}/selection")
def put_selection(brand_id: str, scenario_id: str, body: SelectionIn, r: Repository = Repo) -> dict[str, Any]:
    scn = r.get_scenario(scenario_id)
    scn.option(body.option_id)
    scn.selected_option_id = body.option_id
    r.save_scenario(scn)
    return {"selected_option_id": body.option_id}


@app.post("/api/v1/brands/{brand_id}/scenarios/{scenario_id}/explanation")
def post_explanation(brand_id: str, scenario_id: str, r: Repository = Repo) -> dict[str, Any]:
    scn, brand = r.get_scenario(scenario_id), r.get_brand(brand_id)
    if scn.is_stale(brand):
        raise _error(409, "scenario_stale", "The scenario is out of date; re-run it before asking for an explanation")
    sku = next(s for s in r.list_skus(brand_id) if s.id == scn.sku_id)
    sup = next(s for s in r.list_suppliers(brand_id) if s.id == scn.supplier_id)
    exp = Explainer(llm()).explain(scn, brand, sku_name=sku.name, supplier_name=sup.name)
    r.save_explanation(scenario_id, exp)
    # 不通过数字校验的文字不下发（PRD：不匹配时不展示该段解释）
    return exp.model_dump(exclude={"problems"}) if exp.status == "ok" else {"status": exp.status, "text": None, "sections": None}


class TermsIn(BaseModel):
    supplier_id: str
    sku_id: str
    terms: Terms


@app.post("/api/v1/brands/{brand_id}/terms/evaluate")
def evaluate_terms(brand_id: str, body: TermsIn, r: Repository = Repo) -> OptionMetrics:
    """谈判室用：按给定条款跑一次单方案模拟（与谈判轮次同一种子）。"""
    t = body.terms
    opt = ScenarioOption(id="base", label="base", quantity=t.quantity, prepay_ratio=t.prepay_ratio, unit_cost=t.unit_cost)
    return _simulator(r, brand_id, body.sku_id, body.supplier_id, [opt], SimConfig()).evaluate(opt, attribution=False)


# ---------------------------------------------------------------------------
# F3 风险信号（§3.3）
# ---------------------------------------------------------------------------


class ExtractIn(BaseModel):
    text: str = Field(max_length=8000)
    source_type: Literal["tariff", "supplier_news", "other"] = "other"


@app.post("/api/v1/brands/{brand_id}/risk-signals/extract")
def extract(brand_id: str, body: ExtractIn, r: Repository = Repo) -> dict[str, Any]:
    model = llm()
    if model is None:
        raise _error(503, "llm_unavailable", "Signal extraction needs an LLM; set OPENROUTER_API_KEY or ANTHROPIC_API_KEY")
    try:
        res = SignalExtractor(model).extract(body.text, r.brand_context(brand_id), body.source_type)
    except LLMError as e:
        raise _error(502, "llm_error", f"The model call failed, please try again ({e})") from e
    for s in res.signals:
        r.save_signal(s)
    return {"status": res.status, "message": res.message, "signals": [v_signal(s) for s in res.signals]}


class SignalPatch(BaseModel):
    change_value: float | None = None
    probability: float | None = Field(default=None, ge=0, le=1)
    effective_day: int | None = Field(default=None, ge=0)
    target_type: Literal["hts_code", "supplier", "sku"] | None = None
    target_id: str | None = None


@app.patch("/api/v1/brands/{brand_id}/risk-signals/{signal_id}")
def patch_signal(brand_id: str, signal_id: str, patch: SignalPatch, r: Repository = Repo) -> dict[str, Any]:
    changes = patch.model_dump(exclude_none=True)
    if (d := changes.pop("effective_day", None)) is not None:
        changes["effective_date"] = date.today() + timedelta(days=d)
    return v_signal(r.update_signal(signal_id, **changes))


@app.post("/api/v1/brands/{brand_id}/risk-signals/{signal_id}/accept")
def accept_signal(brand_id: str, signal_id: str, r: Repository = Repo) -> dict[str, Any]:
    sig, version = r.accept_signal(signal_id)
    return {"signal": v_signal(sig), "state_version": version}


@app.post("/api/v1/brands/{brand_id}/risk-signals/{signal_id}/reject")
def reject_signal(brand_id: str, signal_id: str, r: Repository = Repo) -> dict[str, Any]:
    sig, version = r.reject_signal(signal_id)
    return {"signal": v_signal(sig), "state_version": version}


# ---------------------------------------------------------------------------
# F5 事件与预警（§3.5）
# ---------------------------------------------------------------------------


@app.post("/api/v1/brands/{brand_id}/events/{event_id}/inject")
def inject(brand_id: str, event_id: str, r: Repository = Repo) -> dict[str, Any]:
    result, version, stale = r.inject_event(brand_id, event_id)
    # 事件里的交期延误同步顺延在途订单的 ETA，与地图和预警保持一致
    for sig in result.signals:
        if sig.parameter == "lead_time_mean_days" and sig.target_type == "supplier" and sig.change_type == "delta":
            r.conn.execute(
                "UPDATE purchase_orders SET eta = eta + %s::int WHERE brand_id = %s AND supplier_id = %s AND status <> 'arrived' AND eta IS NOT NULL",
                (round(sig.change_value), brand_id, sig.target_id),
            )
    return {"state_version": version, "alerts": [a.model_dump(mode="json") for a in result.alerts], "stale_scenario_ids": stale}


@app.post("/api/v1/brands/{brand_id}/alerts/{alert_id}/ack")
def ack(brand_id: str, alert_id: str, r: Repository = Repo) -> dict[str, bool]:
    r.ack_alert(alert_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# F6 谈判（§3.6）
# ---------------------------------------------------------------------------


class NegotiationIn(BaseModel):
    supplier_id: str
    sku_id: str


class TurnIn(BaseModel):
    message: str = ""
    proposed_terms: Terms


def _negotiator(r: Repository, brand_id: str, neg: Negotiation) -> tuple[FactoryNegotiator, Terms]:
    sup = next(s for s in r.list_suppliers(brand_id) if s.id == neg.supplier_id)
    offer = next((o for o in r.list_offers(brand_id) if o.sku_id == neg.sku_id and o.supplier_id == neg.supplier_id), None)
    if offer is None:
        raise _error(422, "no_offer", f"{neg.supplier_id} has no quote for {neg.sku_id}")
    persona, config = demo.factory_persona(sup, offer)
    model = llm()
    if model is None:
        raise _error(503, "llm_unavailable", "Negotiation needs an LLM; set OPENROUTER_API_KEY or ANTHROPIC_API_KEY")
    return FactoryNegotiator(model, persona, config), config.opening_terms


@app.post("/api/v1/brands/{brand_id}/negotiations", status_code=201)
def open_negotiation(brand_id: str, body: NegotiationIn, r: Repository = Repo) -> dict[str, Any]:
    neg = Negotiation(id=f"neg_{uuid.uuid4().hex[:10]}", brand_id=brand_id, supplier_id=body.supplier_id, sku_id=body.sku_id)
    r.save_negotiation(neg)
    sup = next(s for s in r.list_suppliers(brand_id) if s.id == body.supplier_id)
    offer = next(o for o in r.list_offers(brand_id) if o.sku_id == body.sku_id and o.supplier_id == body.supplier_id)
    return neg.model_dump(mode="json") | {"opening_terms": demo.factory_persona(sup, offer)[1].opening_terms.model_dump()}


@app.post("/api/v1/brands/{brand_id}/negotiations/{negotiation_id}/turns")
def negotiation_turn(brand_id: str, negotiation_id: str, body: TurnIn, r: Repository = Repo) -> dict[str, Any]:
    neg = r.get_negotiation(negotiation_id)
    negotiator, base = _negotiator(r, brand_id, neg)
    sku = next(s for s in r.list_skus(brand_id) if s.id == neg.sku_id)

    def evaluate(options: list[ScenarioOption]) -> SimulationResult:
        sim = _simulator(r, brand_id, neg.sku_id, neg.supplier_id, options, SimConfig())
        return SimulationResult(seed=42, input_hash=sim.inp.input_hash(), engine_version=ENGINE_VERSION, horizon_days=120,
                                n_paths=sim.inp.config.n_paths, options=[sim.evaluate(o, attribution=False) for o in options])

    try:
        res = negotiator.respond(neg, body.proposed_terms, body.message, sku_name=sku.name, base_terms=base, evaluate=evaluate)
    except ValueError as e:
        raise _error(409, "negotiation_closed", str(e)) from e
    r.save_negotiation(neg)
    return {
        "status": neg.status,
        "factory_reply": {"decision": res.decision, "message": res.message, "counter_terms": res.counter_terms.model_dump()},
        "impact": res.impact.model_dump() if res.impact else None,
    }
