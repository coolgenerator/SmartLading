import pytest
from agents.agent_helpers import FakeLLM

from smartlading.llm import NO_IMPACT_MESSAGE, SignalExtractor
from smartlading.llm.extract_signals import ExtractedChange, ExtractionOutput, locate_quote
from smartlading.models import SignalParameter, SignalStatus

NEWS = (
    "WASHINGTON - The Office of the U.S. Trade Representative said on Wednesday that, effective 2026-12-01, "
    "duties on cotton knit apparel under HTS 6109.10 will rise from 10% to 25%. "
    "Separately, several textile mills in Ningbo report that power rationing has pushed lead times back by two weeks."
)
# 原文为中文时同样要能定位引用、识别中文数字
NEWS_ZH = "另据报道，宁波多家纺织厂因限电，交期普遍延误两周。"


def change(**kw) -> ExtractedChange:
    base = dict(
        target_type="hts_code",
        target_id="6109.10",
        parameter="tariff_rate",
        change_type="set",
        change_value=0.25,
        llm_probability=0.7,
        effective_date="2026-12-01",
        quote="will rise from 10% to 25%",
        rationale="The new rate is 25%.",
    )
    return ExtractedChange(**(base | kw))


def extract(ctx, *changes, reason=None, text=NEWS):
    llm = FakeLLM(ExtractionOutput(changes=list(changes), no_impact_reason=reason))
    return SignalExtractor(llm).extract(text, ctx, source_type="tariff"), llm


def test_hts_prefix_expands_to_full_codes(ctx):
    res, llm = extract(ctx, change())
    assert res.status == "found"
    assert {s.target_id for s in res.signals} == {"6109.10.0012", "6109.10.0040"}
    for s in res.signals:
        assert s.status == SignalStatus.PENDING and s.matched and s.value_grounded
        assert NEWS[s.quote_span[0] : s.quote_span[1]] == s.quote
        assert s.probability == s.llm_probability == 0.7
        assert str(s.effective_date) == "2026-12-01"
    assert {sku for s in res.signals for sku in s.affected_skus} == {"sku_tee", "sku_tank"}
    assert "<document>" in llm.calls[0]["user"]


def test_supplier_delay_in_weeks_is_grounded(ctx):
    res, _ = extract(
        ctx,
        change(target_type="supplier", target_id="sup_cn", parameter="lead_time_mean_days", change_type="delta",
               change_value=14, quote="power rationing has pushed lead times back by two weeks", effective_date=None),
    )
    (s,) = res.signals
    assert s.parameter is SignalParameter.LEAD_TIME_MEAN_DAYS and s.value_grounded
    assert s.affected_skus == ["sku_tank", "sku_tee"]


@pytest.mark.parametrize(
    "bad, reason",
    [
        (change(quote="duties will rise to twenty-five percent"), "quote"),
        (change(parameter="moq"), "cannot target"),
        (change(change_value=7.5), "out of range"),
        (change(change_type="multiply", change_value=40), "multiplier"),
    ],
)
def test_invalid_changes_are_dropped(ctx, bad, reason):
    res, _ = extract(ctx, bad)
    assert not res.signals and reason in res.dropped[0].reason
    assert res.status == "no_quantifiable_impact" and res.message.startswith(NO_IMPACT_MESSAGE)


def test_unknown_target_is_kept_but_unmatched(ctx):
    res, _ = extract(ctx, change(target_id="9403.60"))
    (s,) = res.signals
    assert not s.matched and s.affected_skus == []
    assert res.status == "no_quantifiable_impact"


def test_ungrounded_value_is_flagged(ctx):
    res, _ = extract(ctx, change(change_value=0.3))
    assert all(not s.value_grounded for s in res.signals)


def test_no_impact_reason_is_shown(ctx):
    res, _ = extract(ctx, reason="The news only concerns auto parts.", text="The EU will adjust tariffs on auto parts.")
    assert res.message == f"{NO_IMPACT_MESSAGE}: The news only concerns auto parts."


def test_quote_matching_tolerates_whitespace():
    assert locate_quote("will rise from 10%  to\n25%", NEWS) is not None
    assert locate_quote("will rise from 10% to 30%", NEWS) is None


def test_chinese_source_text_is_still_supported(ctx):
    res, _ = extract(
        ctx,
        change(target_type="supplier", target_id="sup_cn", parameter="lead_time_mean_days", change_type="delta",
               change_value=14, quote="交期普遍延误两周", effective_date=None),
        text=NEWS_ZH,
    )
    (s,) = res.signals
    assert s.value_grounded and NEWS_ZH[s.quote_span[0] : s.quote_span[1]] == "交期普遍延误两周"
