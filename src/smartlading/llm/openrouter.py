"""OpenRouter 后端（默认 DeepSeek V4.1 Flash），实现与 ClaudeLLM 相同的 StructuredLLM 协议。

OpenRouter 是 OpenAI 兼容接口，用 openai SDK 指向 https://openrouter.ai/api/v1。
结构化输出用 response_format=json_schema（strict），并要求 OpenRouter 只路由到支持该参数的
服务商（provider.require_parameters）。返回后仍用 Pydantic 校验一次，不信任服务商的保证。
"""

from __future__ import annotations

import copy
import logging
import os
import re
import time
from typing import Any

import openai
import pydantic

from smartlading.llm.client import Effort, LLMError

log = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-v4.1-flash")

# OpenRouter 的 reasoning.effort 只有 low / medium / high
_EFFORT = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class OpenRouterLLM:
    def __init__(
        self,
        client: openai.OpenAI | None = None,
        *,
        model: str = DEFAULT_OPENROUTER_MODEL,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        if client is None:
            key = api_key or os.environ.get("OPENROUTER_API_KEY")
            if not key:
                raise LLMError("OPENROUTER_API_KEY is not set")
            client = openai.OpenAI(
                base_url=OPENROUTER_BASE_URL,
                api_key=key,
                timeout=timeout,
                max_retries=1,
                default_headers={"X-Title": "SmartLading"},
            )
        self._client = client
        self.model = model

    def structured[T: pydantic.BaseModel](
        self,
        *,
        system: str,
        user: str,
        output_type: type[T],
        effort: Effort = "low",
        max_tokens: int = 8000,
    ) -> T:
        started = time.monotonic()
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": output_type.__name__, "strict": True, "schema": strict_schema(output_type)},
                },
                extra_body={
                    "reasoning": {"effort": _EFFORT[effort], "exclude": True},
                    "provider": {"require_parameters": True},
                },
            )
        except openai.APIConnectionError as e:
            raise LLMError(f"Could not reach OpenRouter: {e}") from e
        except openai.RateLimitError as e:
            raise LLMError("OpenRouter rate limit hit, please retry shortly") from e
        except openai.APIStatusError as e:
            raise LLMError(f"OpenRouter returned {e.status_code}: {e.message}") from e

        if not response.choices:
            raise LLMError("OpenRouter returned no choices")
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise LLMError("Model output was truncated")
        if getattr(choice.message, "refusal", None):
            raise LLMError("The model declined this request")
        content = _FENCE.sub("", (choice.message.content or "").strip())
        if not content:
            raise LLMError("The model returned no content")
        try:
            parsed = output_type.model_validate_json(content)
        except pydantic.ValidationError as e:
            raise LLMError(f"Model output does not match {output_type.__name__}") from e
        log.debug("OpenRouter %s %.0fms usage=%s", output_type.__name__, (time.monotonic() - started) * 1000, response.usage)
        return parsed


def strict_schema(model: type[pydantic.BaseModel]) -> dict[str, Any]:
    """把 Pydantic 的 JSON Schema 改成 strict 模式要求的形状：
    每个 object 都 additionalProperties=false 且所有属性必填；去掉 strict 模式不支持的 default。"""
    schema = copy.deepcopy(model.model_json_schema())

    def fix(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for v in node.values():
                fix(v)
        elif isinstance(node, list):
            for v in node:
                fix(v)

    fix(schema)
    return schema
