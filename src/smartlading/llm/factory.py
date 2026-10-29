"""按环境变量选择 LLM 后端。

SMARTLADING_LLM_PROVIDER = openrouter | anthropic
未设置时：有 OPENROUTER_API_KEY 用 OpenRouter，否则用 Claude。
模型分别由 OPENROUTER_MODEL / SMARTLADING_MODEL 覆盖。
"""

from __future__ import annotations

import os

from smartlading.llm.client import ClaudeLLM, LLMError, StructuredLLM
from smartlading.llm.openrouter import OpenRouterLLM


def make_llm(provider: str | None = None) -> StructuredLLM:
    provider = (provider or os.environ.get("SMARTLADING_LLM_PROVIDER") or "").lower()
    if not provider:
        provider = "openrouter" if os.environ.get("OPENROUTER_API_KEY") else "anthropic"
    match provider:
        case "openrouter":
            return OpenRouterLLM()
        case "anthropic":
            return ClaudeLLM()
        case _:
            raise LLMError(f"Unknown LLM provider {provider!r}; use openrouter or anthropic")
