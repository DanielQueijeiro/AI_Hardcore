"""Provider-neutral LLM port. Every agent talks to this, never to a vendor SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    degraded: bool = False


class LLMClient(Protocol):
    name: str
    model: str

    def complete(
        self,
        *,
        role: str,
        instructions: str,
        prompt: str,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        effort: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """One model step.

        `role` names the caller (supervisor, knowledge, support, critic, guardrail, summarizer, judge).
        `tool_choice` is "auto", "required", or a tool name to force.
        `context` is the structured form of what `prompt` renders as text; only non-model
        implementations (offline policy, test scripts) read it.
        """
        ...
