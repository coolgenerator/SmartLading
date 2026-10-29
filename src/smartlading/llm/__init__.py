"""LLM 层：风险信号提取（F3）、推荐解释（F4）、工厂谈判 agent（F6）。

所有输出数字都由代码校验或渲染；LLM 失败时各功能降级，不影响模拟器。
"""

from smartlading.llm.client import ClaudeLLM, LLMError, StructuredLLM
from smartlading.llm.explain import Explainer, ScenarioStaleError
from smartlading.llm.extract_signals import NO_IMPACT_MESSAGE, BrandContext, ExtractionResult, SignalExtractor
from smartlading.llm.negotiate import FactoryAgentConfig, FactoryNegotiator, TermsImpact, TurnResult

__all__ = [
    "NO_IMPACT_MESSAGE",
    "BrandContext",
    "ClaudeLLM",
    "Explainer",
    "ExtractionResult",
    "FactoryAgentConfig",
    "FactoryNegotiator",
    "LLMError",
    "ScenarioStaleError",
    "SignalExtractor",
    "StructuredLLM",
    "TermsImpact",
    "TurnResult",
]
