from __future__ import annotations

from src.config import Settings
from src.llm.base import LLMClient
from src.llm.offline import OfflinePolicyLLM
from src.llm.openai_client import OpenAIResponsesClient
from src.llm.resilient import ResilientLLM


def build_llm(settings: Settings) -> LLMClient:
    offline = OfflinePolicyLLM()
    if settings.effective_provider() != "openai":
        return offline
    primary = OpenAIResponsesClient(
        api_key=settings.openai_api_key or "",
        model=settings.openai_model,
        base_url=settings.openai_base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        default_effort=settings.reasoning_effort,
    )
    return ResilientLLM(
        primary,
        offline,
        failure_threshold=settings.breaker_failure_threshold,
        cooldown_seconds=settings.breaker_cooldown_seconds,
    )
