from datetime import datetime, timedelta, timezone

import pytest

from smartlading.ask_human import (
    Action,
    AnswerError,
    AskHuman,
    BillBlock,
    BillLine,
    CardBlock,
    ClientCapabilities,
    Column,
    FieldOption,
    HumanAnswer,
    InputField,
    MapBlock,
    MapMarker,
    MapRoute,
    MediaBlock,
    Place,
    RenderPolicy,
    ResponseSpec,
    TableBlock,
    final_offer_ask,
    resolve_for_client,
    validate_answer,
)
from smartlading.models.p1 import Terms

BILL = BillBlock(title="Proforma", issuer="Everbright", lines=[BillLine(label="Deposit", amount=60_800), BillLine(label="Balance", amount=243_200)])
MAP = MapBlock(
    markers=[MapMarker(id="f", lat=22.5, lng=114.1, label="Shenzhen", kind="supplier"), MapMarker(id="p", lat=33.8, lng=-118.2, label="Long Beach", kind="port")],
    routes=[MapRoute(from_id="f", to_id="p")],
)
SPEC = ResponseSpec(
    actions=[Action(id="ok", label="OK", style="primary"), Action(id="no", label="No", requires_fields=False)],
    fields=[
        InputField(id="qty", label="Quantity", kind="number", required=True, min=1000, max=20000),
        InputField(id="pay", label="Pay by", kind="select", options=[FieldOption(value="tt", label="T/T")]),
        InputField(id="split", label="Split", kind="boolean", default=False),
    ],
)


def ask(**kw) -> AskHuman:
    return AskHuman(source="test", title="t", prompt="p", blocks=kw.pop("blocks", [BILL, MAP]), response=SPEC, **kw)


def test_round_trips_through_json_with_discriminator():
    a = ask()
    back = AskHuman.model_validate_json(a.model_dump_json())
    assert [b.type for b in back.blocks] == ["bill", "map"]
    assert isinstance(back.blocks[0], BillBlock) and back.blocks[0].total == 304_000


def test_full_client_keeps_blocks():
    caps = ClientCapabilities(blocks={"text": 1, "bill": 1, "map": 1}, surfaces=["inline", "modal"])
    out = resolve_for_client(ask(policy=RenderPolicy(surface="modal")), caps)
    assert [b.type for b in out.blocks] == ["bill", "map"] and out.policy.surface == "modal"


def test_degrades_bill_and_map_to_table_then_text():
    out = resolve_for_client(ask(), ClientCapabilities(blocks={"text": 1, "table": 1}))
    bill, mp = out.blocks
    assert isinstance(bill, TableBlock) and bill.rows[-1]["amount"] == "$304,000.00" and bill.highlight_row == 2
    assert isinstance(mp, TableBlock) and mp.rows[-1]["label"] == "Shenzhen → Long Beach"

    out = resolve_for_client(ask(), ClientCapabilities())
    assert [b.type for b in out.blocks] == ["text", "text"]
    assert out.blocks[0].text.splitlines()[-1].endswith("Amount $304,000.00")


def test_block_ids_survive_degrading():
    out = resolve_for_client(ask(), ClientCapabilities())
    assert [b.id for b in out.blocks] == [BILL.id, MAP.id]


def test_version_gate_and_media_poster():
    v2 = CardBlock(title="New card", version=2)
    media = MediaBlock(kind="video", url="https://x/v.mp4", title="Factory tour", poster_url="https://x/p.jpg")
    out = resolve_for_client(ask(blocks=[v2, media]), ClientCapabilities(blocks={"text": 1, "card": 1, "image": 1}))
    assert out.blocks[0].type == "text"  # 客户端只懂 card v1
    assert out.blocks[1].type == "image" and out.blocks[1].url == "https://x/p.jpg"


def test_unsupported_surface_falls_back_to_inline_and_tables_truncate():
    big = TableBlock(columns=[Column(key="a", label="A")], rows=[{"a": i} for i in range(10)], highlight_row=8)
    out = resolve_for_client(ask(blocks=[big], policy=RenderPolicy(surface="sheet")), ClientCapabilities(blocks={"table": 1}, max_table_rows=3))
    assert out.policy.surface == "inline"
    assert len(out.blocks[0].rows) == 3 and out.blocks[0].highlight_row is None


def test_rejects_other_protocol_major():
    with pytest.raises(ValueError):
        resolve_for_client(ask(), ClientCapabilities(protocol="ask-human/2", blocks={"text": 1}))
    assert resolve_for_client(ask(), ClientCapabilities(protocol="ask-human/1.3")).protocol == "ask-human/1"


def test_validate_answer_normalises_values():
    a = ask()
    got = validate_answer(a, HumanAnswer(ask_id=a.id, action_id="ok", values={"qty": "9000", "pay": "tt", "junk": "x"}, comment="hi"))
    assert got.values == {"qty": 9000.0, "pay": "tt", "split": False}
    assert got.comment is None  # allow_comment 为 False


@pytest.mark.parametrize(
    "action, values, msg",
    [
        ("nope", {"qty": 9000}, "unknown action"),
        ("ok", {}, "required"),
        ("ok", {"qty": 50}, "between"),
        ("ok", {"qty": True}, "number"),
        ("ok", {"qty": 9000, "pay": "bitcoin"}, "not an option"),
        ("ok", {"qty": 9000, "split": "yes"}, "true or false"),
    ],
)
def test_validate_answer_errors(action, values, msg):
    a = ask()
    with pytest.raises(AnswerError, match=msg):
        validate_answer(a, HumanAnswer(ask_id=a.id, action_id=action, values=values))


def test_decline_action_skips_required_fields_and_expiry_is_enforced():
    a = ask(policy=RenderPolicy(expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)))
    assert validate_answer(a, HumanAnswer(ask_id=a.id, action_id="no")).values == {"split": False}
    with pytest.raises(AnswerError, match="expired"):
        validate_answer(a, HumanAnswer(ask_id=a.id, action_id="no"), now=datetime.now(timezone.utc) + timedelta(hours=1))
    with pytest.raises(AnswerError, match="different ask"):
        validate_answer(a, HumanAnswer(ask_id="ask_other", action_id="no"))


def test_final_offer_ask_bill_matches_terms():
    t = Terms(prepay_ratio=0.25, quantity=8000, unit_cost=38.0)
    a = final_offer_ask(
        supplier_name="Everbright Woodcraft", sku_name="Oak Bedside Table", counter_terms=t, base_terms=t, impact=None,
        factory=Place(id="sup_everbright", label="Shenzhen", lat=22.5, lng=114.1), port=Place(id="lgb", label="Long Beach", lat=33.8, lng=-118.2),
        lead_time_days=38, negotiation_id="neg_1",
    )
    bill = a.blocks[0]
    assert isinstance(bill, BillBlock) and bill.lines[0].amount == 76_000 and bill.total == 304_000
    assert a.policy.surface == "modal" and a.policy.default_action_id == "continue"
    assert validate_answer(a, HumanAnswer(ask_id=a.id, action_id="accept")).values == {"payment_method": "tt"}
