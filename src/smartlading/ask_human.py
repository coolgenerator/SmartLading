"""Ask-human 协议（ask-human/1）：agent 需要人拍板时，下发一张由内容块组成的"问题卡"。

- 内容块（Block）按 type 区分：text / card / facts / table / bill / image / media / map。
  text 是协议基线，所有客户端必须支持。
- 能力协商：前端上报 ClientCapabilities（支持哪些块及版本、哪些展示面、表格行数上限），
  服务端用 resolve_for_client 把不支持的块逐级降级（map → table → text 等），
  所以 agent 可以只按"最好的样子"出题，不用关心具体前端。
- 渲染策略（RenderPolicy）决定展示面（inline / sheet / modal）和紧急程度；
  客户端不支持的展示面退回 inline。
- 回答（HumanAnswer）在服务端按 ResponseSpec 校验，不信任前端。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from smartlading.llm.negotiate import TermsImpact
from smartlading.models.p1 import Terms

PROTOCOL = "ask-human/1"


# --- 内容块 ---


class _Block(BaseModel):
    id: str = Field(default_factory=lambda: f"blk_{uuid.uuid4().hex[:8]}")
    version: int = 1

    def fallback(self) -> Block | None:
        """更朴素的等价块；None 表示已经是基线。"""
        return None


class TextBlock(_Block):
    type: Literal["text"] = "text"
    text: str
    tone: Literal["plain", "info", "warn", "danger", "success"] = "plain"


class Fact(BaseModel):
    label: str
    value: str
    hint: str | None = None  # 例如 "+12d vs base"
    tone: Literal["plain", "good", "bad"] = "plain"


class FactsBlock(_Block):
    type: Literal["facts"] = "facts"
    title: str | None = None
    facts: list[Fact]

    def fallback(self) -> Block:
        lines = [f"{f.label}: {f.value}" + (f" ({f.hint})" if f.hint else "") for f in self.facts]
        return TextBlock(id=self.id, text="\n".join(([self.title] if self.title else []) + lines))


class CardBlock(_Block):
    type: Literal["card"] = "card"
    title: str
    subtitle: str | None = None
    body: str | None = None
    image_url: str | None = None
    badges: list[str] = []
    facts: list[Fact] = []
    link: str | None = None

    def fallback(self) -> Block:
        head = self.title + (f" — {self.subtitle}" if self.subtitle else "")
        parts = [head, *(f"[{b}]" for b in self.badges[:1]), self.body or ""]
        parts += [f"{f.label}: {f.value}" for f in self.facts]
        return TextBlock(id=self.id, text="\n".join(p for p in parts if p))


class Column(BaseModel):
    key: str
    label: str
    align: Literal["left", "right"] = "left"


class TableBlock(_Block):
    type: Literal["table"] = "table"
    title: str | None = None
    columns: list[Column]
    rows: list[dict[str, str | float | int | None]]
    highlight_row: int | None = None

    def fallback(self) -> Block:
        lines = [self.title] if self.title else []
        for r in self.rows:
            lines.append(" · ".join(f"{c.label} {_cell(r.get(c.key))}" for c in self.columns))
        return TextBlock(id=self.id, text="\n".join(lines))

    def truncated(self, max_rows: int) -> TableBlock:
        if len(self.rows) <= max_rows:
            return self
        hl = self.highlight_row if self.highlight_row is not None and self.highlight_row < max_rows else None
        return self.model_copy(update={"rows": self.rows[:max_rows], "highlight_row": hl, "title": f"{self.title or 'Table'} (first {max_rows} of {len(self.rows)})"})


class BillLine(BaseModel):
    label: str
    amount: float
    detail: str | None = None  # 例如 "8,000 × $38.00"
    due: str | None = None  # 例如 "On signing" / "Day 38"


class BillBlock(_Block):
    """账单/形式发票：金额由代码计算，块里只做展示。"""

    type: Literal["bill"] = "bill"
    title: str
    issuer: str | None = None
    currency: str = "USD"
    lines: list[BillLine]
    total_label: str = "Total"

    @property
    def total(self) -> float:
        return round(sum(line.amount for line in self.lines), 2)

    def fallback(self) -> Block:
        rows: list[dict[str, str | float | int | None]] = [
            {"item": line.label, "detail": line.detail or "", "due": line.due or "", "amount": _money(line.amount, self.currency)} for line in self.lines
        ]
        rows.append({"item": self.total_label, "detail": "", "due": "", "amount": _money(self.total, self.currency)})
        cols = [Column(key="item", label="Item"), Column(key="detail", label="Detail"), Column(key="due", label="Due"), Column(key="amount", label="Amount", align="right")]
        title = self.title + (f" · {self.issuer}" if self.issuer else "")
        return TableBlock(id=self.id, title=title, columns=cols, rows=rows, highlight_row=len(rows) - 1)


class ImageBlock(_Block):
    type: Literal["image"] = "image"
    url: str
    alt: str
    caption: str | None = None

    def fallback(self) -> Block:
        return TextBlock(id=self.id, text=f"{self.alt}: {self.url}")


class MediaBlock(_Block):
    type: Literal["media"] = "media"
    kind: Literal["video", "audio"]
    url: str
    title: str
    poster_url: str | None = None
    duration_s: float | None = None

    def fallback(self) -> Block:
        if self.poster_url:
            return ImageBlock(id=self.id, url=self.poster_url, alt=self.title, caption=f"{self.kind.title()}: {self.url}")
        return TextBlock(id=self.id, text=f"{self.title} ({self.kind}): {self.url}")


class MapMarker(BaseModel):
    id: str
    lat: float
    lng: float
    label: str
    kind: Literal["supplier", "port", "warehouse", "shipment", "other"] = "other"
    detail: str | None = None


class MapRoute(BaseModel):
    from_id: str
    to_id: str
    label: str | None = None
    style: Literal["sea", "air", "road"] = "sea"


class MapBlock(_Block):
    type: Literal["map"] = "map"
    title: str | None = None
    markers: list[MapMarker]
    routes: list[MapRoute] = []

    def fallback(self) -> Block:
        cols = [Column(key="label", label="Place"), Column(key="kind", label="Type"), Column(key="detail", label="Detail")]
        rows: list[dict[str, str | float | int | None]] = [{"label": m.label, "kind": m.kind, "detail": m.detail or f"{m.lat:.2f}, {m.lng:.2f}"} for m in self.markers]
        by_id = {m.id: m.label for m in self.markers}
        for r in self.routes:
            rows.append({"label": f"{by_id.get(r.from_id, r.from_id)} → {by_id.get(r.to_id, r.to_id)}", "kind": f"route ({r.style})", "detail": r.label or ""})
        return TableBlock(id=self.id, title=self.title, columns=cols, rows=rows)


Block = Annotated[
    TextBlock | FactsBlock | CardBlock | TableBlock | BillBlock | ImageBlock | MediaBlock | MapBlock,
    Field(discriminator="type"),
]


# --- 回答规格与策略 ---


class Action(BaseModel):
    id: str
    label: str
    style: Literal["primary", "secondary", "danger"] = "secondary"
    requires_fields: bool = True  # False 时（例如"拒绝"）不校验必填字段


class FieldOption(BaseModel):
    value: str
    label: str


class InputField(BaseModel):
    id: str
    label: str
    kind: Literal["text", "number", "select", "boolean"]
    required: bool = False
    default: str | float | bool | None = None
    min: float | None = None
    max: float | None = None
    options: list[FieldOption] = []
    help: str | None = None


class ResponseSpec(BaseModel):
    actions: list[Action] = Field(min_length=1)
    fields: list[InputField] = []
    allow_comment: bool = False


Surface = Literal["inline", "sheet", "modal"]


class RenderPolicy(BaseModel):
    surface: Surface = "inline"
    urgency: Literal["low", "normal", "blocking"] = "normal"  # blocking：回答前暂停该会话的其他输入
    expires_at: datetime | None = None
    default_action_id: str | None = None  # 过期后由服务端按此动作处理


class AskHuman(BaseModel):
    kind: Literal["ask_human"] = "ask_human"
    protocol: str = PROTOCOL
    id: str = Field(default_factory=lambda: f"ask_{uuid.uuid4().hex[:10]}")
    source: str  # 发起的 agent，例如 "factory_negotiator"
    title: str
    prompt: str
    blocks: list[Block] = []
    response: ResponseSpec
    policy: RenderPolicy = RenderPolicy()
    context: dict[str, str] = {}  # 关联对象，例如 {"negotiation_id": "neg_1"}
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ClientCapabilities(BaseModel):
    protocol: str = PROTOCOL
    blocks: dict[str, int] = {"text": 1}  # type → 支持的最高版本
    surfaces: list[Surface] = ["inline"]
    max_table_rows: int = 50


class HumanAnswer(BaseModel):
    ask_id: str
    action_id: str
    values: dict[str, str | float | bool | None] = {}
    comment: str | None = None
    answered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AnswerError(ValueError):
    pass


# --- 协商与校验 ---


def resolve_for_client(ask: AskHuman, caps: ClientCapabilities) -> AskHuman:
    """按客户端能力降级内容块和展示面；返回副本，原问题不变。"""
    if _major(caps.protocol) != _major(PROTOCOL):
        raise ValueError(f"unsupported protocol {caps.protocol}")
    blocks: list[Block] = []
    for b in ask.blocks:
        cur: Block | None = b
        while cur is not None and cur.type != "text" and caps.blocks.get(cur.type, 0) < cur.version:
            cur = cur.fallback()
        if cur is None:
            continue
        if isinstance(cur, TableBlock):
            cur = cur.truncated(caps.max_table_rows)
        blocks.append(cur)
    policy = ask.policy
    if policy.surface not in caps.surfaces:
        policy = policy.model_copy(update={"surface": "inline"})
    return ask.model_copy(update={"blocks": blocks, "policy": policy})


def validate_answer(ask: AskHuman, answer: HumanAnswer, *, now: datetime | None = None) -> HumanAnswer:
    """校验并规范化回答：动作合法、必填齐全、数值范围、选项合法；未知字段丢弃。"""
    if answer.ask_id != ask.id:
        raise AnswerError("answer is for a different ask")
    if ask.policy.expires_at and (now or datetime.now(timezone.utc)) > ask.policy.expires_at:
        raise AnswerError("ask has expired")
    action = next((a for a in ask.response.actions if a.id == answer.action_id), None)
    if action is None:
        raise AnswerError(f"unknown action {answer.action_id!r}")

    clean: dict[str, str | float | bool | None] = {}
    for f in ask.response.fields:
        v = answer.values.get(f.id, f.default)
        if v is None or v == "":
            if f.required and action.requires_fields:
                raise AnswerError(f"{f.label} is required")
            continue
        match f.kind:
            case "number":
                if isinstance(v, bool):
                    raise AnswerError(f"{f.label} must be a number")
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    raise AnswerError(f"{f.label} must be a number") from None
                if (f.min is not None and v < f.min) or (f.max is not None and v > f.max):
                    raise AnswerError(f"{f.label} must be between {f.min:g} and {f.max:g}" if f.min is not None and f.max is not None else f"{f.label} is out of range")
            case "boolean":
                if not isinstance(v, bool):
                    raise AnswerError(f"{f.label} must be true or false")
            case "select":
                if str(v) not in {o.value for o in f.options}:
                    raise AnswerError(f"{f.label}: {v!r} is not an option")
                v = str(v)
            case "text":
                v = str(v)
        clean[f.id] = v
    comment = answer.comment if ask.response.allow_comment else None
    return answer.model_copy(update={"values": clean, "comment": comment})


# --- 示例：谈判到最终报价时请用户拍板（F6） ---


class Place(BaseModel):
    id: str
    label: str
    lat: float
    lng: float


def final_offer_ask(
    *,
    supplier_name: str,
    sku_name: str,
    counter_terms: Terms,
    base_terms: Terms,
    impact: TermsImpact | None,
    factory: Place,
    port: Place,
    lead_time_days: float,
    negotiation_id: str,
) -> AskHuman:
    """工厂给出最终报价后生成的问题卡；账单金额全部由条款计算。"""
    t = counter_terms
    goods = t.quantity * t.unit_cost
    deposit = round(goods * t.prepay_ratio, 2)
    blocks: list[Block] = [
        BillBlock(
            title="Proforma invoice",
            issuer=supplier_name,
            lines=[
                BillLine(label=f"Deposit ({t.prepay_ratio:.0%})", amount=deposit, detail=f"{t.quantity:,} × ${t.unit_cost:.2f}", due="On signing"),
                BillLine(label="Balance", amount=round(goods - deposit, 2), due=f"Before shipping (~day {lead_time_days:.0f})"),
            ],
        ),
        MapBlock(
            title="Route",
            markers=[
                MapMarker(id=factory.id, lat=factory.lat, lng=factory.lng, label=factory.label, kind="supplier", detail=f"Lead time ~{lead_time_days:.0f} days"),
                MapMarker(id=port.id, lat=port.lat, lng=port.lng, label=port.label, kind="port"),
            ],
            routes=[MapRoute(from_id=factory.id, to_id=port.id, style="sea")],
        ),
    ]
    if impact is not None:
        cols = [Column(key="terms", label="Terms"), Column(key="profit", label="Exp. profit", align="right"), Column(key="runway", label="Runway P10", align="right"), Column(key="p5", label="Worst P5", align="right")]
        rows: list[dict[str, str | float | int | None]] = [
            {"terms": name, "profit": f"${m.expected_profit:,.0f}", "runway": f"{m.runway_p10}d", "p5": f"${m.worst_case_p5:,.0f}"}
            for name, m in (("Base", impact.base), ("Your ask", impact.proposed), ("Final offer", impact.counter))
        ]
        blocks.append(TableBlock(title="Simulated impact", columns=cols, rows=rows, highlight_row=2))
    return AskHuman(
        source="factory_negotiator",
        title=f"{supplier_name} made a final offer",
        prompt=f"Accept {t.prepay_ratio:.0%} deposit, {t.quantity:,} units of {sku_name} at ${t.unit_cost:.2f}? (Base was {base_terms.prepay_ratio:.0%} at ${base_terms.unit_cost:.2f}.)",
        blocks=blocks,
        response=ResponseSpec(
            actions=[
                Action(id="accept", label="Accept offer", style="primary"),
                Action(id="continue", label="Keep negotiating", requires_fields=False),
                Action(id="walk_away", label="Walk away", style="danger", requires_fields=False),
            ],
            fields=[
                InputField(id="payment_method", label="Pay deposit by", kind="select", required=True, default="tt",
                           options=[FieldOption(value="tt", label="Wire (T/T)"), FieldOption(value="lc", label="Letter of credit")]),
            ],
            allow_comment=True,
        ),
        policy=RenderPolicy(surface="modal", urgency="blocking", default_action_id="continue"),
        context={"negotiation_id": negotiation_id},
    )


def _major(protocol: str) -> tuple[str, str]:
    """"ask-human/1.2" → ("ask-human", "1")；小版本只加可选字段，互相兼容。"""
    name, _, ver = protocol.partition("/")
    return name, ver.split(".")[0]


def _money(v: float, currency: str) -> str:
    sign = "−" if v < 0 else ""
    return f"{sign}{'$' if currency == 'USD' else currency + ' '}{abs(v):,.2f}"


def _cell(v: str | float | int | None) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)
