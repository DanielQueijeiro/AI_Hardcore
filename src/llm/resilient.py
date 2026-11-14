"""Circuit breaker around the primary model: on failure, degrade to the offline policy instead of a 500."""

from __future__ import annotations

import logging
import time
from typing import Any

from src.llm.base import LLMClient, LLMResponse

logger = logging.getLogger(__name__)


class ResilientLLM:
    def __init__(
        self,
        primary: LLMClient,
        fallback: LLMClient,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.name = primary.name
        self.model = primary.model
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._consecutive_failures = 0
        self._open_until = 0.0

    @property
    def breaker_open(self) -> bool:
        return time.monotonic() < self._open_until

    def complete(self, **kwargs: Any) -> LLMResponse:
        if not self.breaker_open:
            try:
                response = self.primary.complete(**kwargs)
                self._consecutive_failures = 0
                return response
            except Exception as exc:  # noqa: BLE001 - any provider failure must degrade, not crash the turn
                self._consecutive_failures += 1
                logger.warning(
                    "llm_primary_failed",
                    extra={"role": kwargs.get("role"), "error": repr(exc), "failures": self._consecutive_failures},
                )
                if self._consecutive_failures >= self.failure_threshold:
                    self._open_until = time.monotonic() + self.cooldown_seconds
                    logger.error("llm_breaker_open", extra={"cooldown_seconds": self.cooldown_seconds})
        response = self.fallback.complete(**kwargs)
        response.degraded = True
        return response
