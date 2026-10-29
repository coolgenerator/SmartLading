"""OpenRouter 后端：用 MockTransport 模拟 HTTP，不发真实请求。"""

import json

import httpx2
import openai
import pytest

from smartlading.llm import LLMError, OpenRouterLLM, make_llm
from smartlading.llm.explain import ExplanationDraft
from smartlading.llm.extract_signals import ExtractionOutput
from smartlading.llm.openrouter import OPENROUTER_BASE_URL, strict_schema


def llm_with(handler) -> tuple[OpenRouterLLM, list[dict]]:
    sent: list[dict] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return handler(request)

    client = openai.OpenAI(
        base_url=OPENROUTER_BASE_URL, api_key="test", max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(record)),
    )
    return OpenRouterLLM(client, model="deepseek/deepseek-v4.1-flash"), sent


def completion(content: str | None, finish_reason: str = "stop") -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "gen-1", "object": "chat.completion", "created": 0, "model": "deepseek/deepseek-v4.1-flash",
            "choices": [{"index": 0, "finish_reason": finish_reason, "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )


DRAFT = {"reason": "Safer.", "main_risks": "Demand.", "counterfactual": "Worse."}


def call(llm, output_type=ExplanationDraft, effort="low"):
    return llm.structured(system="sys", user="usr", output_type=output_type, effort=effort)


def test_request_shape_and_parsing():
    llm, sent = llm_with(lambda r: completion(json.dumps(DRAFT, ensure_ascii=False)))
    out = call(llm, effort="max")
    assert out == ExplanationDraft(**DRAFT)
    body = sent[0]
    assert body["model"] == "deepseek/deepseek-v4.1-flash"
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert body["reasoning"] == {"effort": "high", "exclude": True}  # max 映射为 high
    assert body["provider"] == {"require_parameters": True}


def test_code_fences_are_stripped():
    llm, _ = llm_with(lambda r: completion("```json\n" + json.dumps(DRAFT) + "\n```"))
    assert call(llm).reason == "Safer."


@pytest.mark.parametrize(
    "response, msg",
    [
        (completion('{"reason": "missing fields"}'), "does not match"),
        (completion(json.dumps(DRAFT), finish_reason="length"), "truncated"),
        (completion(None), "no content"),
        (httpx2.Response(429, json={"error": {"message": "rate limited"}}), "rate limit"),
        (httpx2.Response(400, json={"error": {"message": "bad schema"}}), "400"),
    ],
)
def test_failures_become_llm_error(response, msg):
    llm, _ = llm_with(lambda r: response)
    with pytest.raises(LLMError, match=msg):
        call(llm)


def test_strict_schema_requires_every_field():
    schema = strict_schema(ExtractionOutput)
    change = schema["$defs"]["ExtractedChange"]
    assert change["additionalProperties"] is False
    assert set(change["required"]) == set(change["properties"])
    assert schema["required"] == ["changes", "no_impact_reason"]
    assert '"default":' not in json.dumps(schema)


def test_factory_picks_provider(monkeypatch):
    monkeypatch.delenv("SMARTLADING_LLM_PROVIDER", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert isinstance(make_llm(), OpenRouterLLM)
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with pytest.raises(LLMError, match="OPENROUTER_API_KEY"):
        make_llm("openrouter")
    with pytest.raises(LLMError, match="Unknown"):
        make_llm("gemini")
