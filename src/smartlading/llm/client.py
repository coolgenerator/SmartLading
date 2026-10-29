"""对 Claude API 的薄封装：一次调用，返回经 pydantic 校验的结构化结果。

所有 LLM 功能都通过 StructuredLLM 协议调用模型，测试时换成假实现。任何失败
（网络、拒答、截断、格式不符）都抛 LLMError，由调用方降级——PRD 要求 LLM 失败时
模拟器和图表仍可独立使用。

design.md 写的是「用 tool use 输出结构化 JSON」。当前模型（claude-opus-5-5）不支持强制
tool_choice，这里改用结构化输出（output_format = Pydantic 模型），效果相同且由 API 保证合法 JSON。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Literal, Protocol

import anthropic
import pydantic

log = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("SMARTLADING_MODEL", "claude-opus-5-5")

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class LLMError(RuntimeError):
    pass


class StructuredLLM(Protocol):
    model: str

    def structured[T: pydantic.BaseModel](
        self,
        *,
        system: str,
        user: str,
        output_type: type[T],
        effort: Effort = "low",
        max_tokens: int = 8000,
    ) -> T: ...


class ClaudeLLM:
    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        *,
        model: str = DEFAULT_MODEL,
        timeout: float = 30.0,
    ) -> None:
        self._client = client or anthropic.Anthropic(timeout=timeout, max_retries=1)
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
            response = self._client.beta.messages.parse(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=output_type,
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                # 被安全分类器拒答时由服务端按类别自动换模型重试
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIConnectionError as e:
            raise LLMError(f"Could not reach the Claude API: {e}") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Claude API rate limit hit, please retry shortly") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude API returned {e.status_code}: {e.message}") from e
        except pydantic.ValidationError as e:
            # 拒答或截断时文本不是完整 JSON，解析阶段就会失败
            raise LLMError(f"Model output does not match {output_type.__name__}") from e

        if response.stop_reason == "refusal":
            raise LLMError("The model declined this request")
        if response.stop_reason == "max_tokens":
            raise LLMError("Model output was truncated")
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError("The model returned no structured output")
        log.debug("LLM %s %.0fms usage=%s", output_type.__name__, (time.monotonic() - started) * 1000, response.usage)
        return parsed
