"""Test double: each role is answered by a queue of canned responses or a callable. No network."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from src.llm.base import LLMResponse, ToolCall

Step = LLMResponse | Callable[[dict[str, Any]], LLMResponse]


def call(name: str, **arguments: Any) -> LLMResponse:
    return LLMResponse(tool_calls=[ToolCall(id=f"call_{name}", name=name, arguments=arguments)])


def say(text: str) -> LLMResponse:
    return LLMResponse(text=text)


class ScriptedLLM:
    name = "scripted"
    model = "scripted-test-model"

    def __init__(self, script: dict[str, list[Step] | Step], default: Any | None = None) -> None:
        self._script = {role: (list(steps) if isinstance(steps, list) else steps) for role, steps in script.items()}
        self._default = default
        self.calls: list[dict[str, Any]] = []
        self.count: dict[str, int] = defaultdict(int)

    def complete(self, **kwargs: Any) -> LLMResponse:
        role = kwargs["role"]
        self.calls.append(kwargs)
        self.count[role] += 1
        steps = self._script.get(role)
        if steps is None:
            if self._default is not None:
                return self._default.complete(**kwargs)
            raise AssertionError(f"ScriptedLLM has no script for role '{role}'")
        step = (steps.pop(0) if steps else None) if isinstance(steps, list) else steps
        if step is None:
            if self._default is not None:
                return self._default.complete(**kwargs)
            raise AssertionError(f"ScriptedLLM script for role '{role}' is exhausted")
        response = step(kwargs) if callable(step) else step
        response.input_tokens = response.input_tokens or 100
        response.output_tokens = response.output_tokens or 20
        return response
