"""OpenAI Responses API adapter (function tools, reasoning effort, real token usage)."""

from __future__ import annotations

import json
from typing import Any

from openai import BadRequestError, OpenAI

from src.llm.base import LLMResponse, ToolCall


class OpenAIResponsesClient:
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str | None = None,
        timeout: float = 45.0,
        max_retries: int = 2,
        default_effort: str = "low",
    ) -> None:
        self.model = model
        self.default_effort = default_effort
        self._supports_reasoning = True
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=max_retries)

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
        request: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": prompt,
            "reasoning": {"effort": effort or self.default_effort},
            "store": False,
            "metadata": {"agent_role": role},
        }
        if tools:
            request["tools"] = [
                {
                    "type": "function",
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                    "strict": False,
                }
                for tool in tools
            ]
            # One decision per step: the orchestration reads a result before the next call is chosen.
            request["parallel_tool_calls"] = False
            if tool_choice in ("auto", "required"):
                request["tool_choice"] = tool_choice
            else:
                request["tool_choice"] = {"type": "function", "name": tool_choice}

        if not self._supports_reasoning:
            request.pop("reasoning")
        try:
            response = self._client.responses.create(**request)
        except BadRequestError as exc:
            # A model without reasoning controls rejects the parameter: drop it once, for good, and retry.
            if "reasoning" not in request or "reasoning" not in str(exc).lower():
                raise
            self._supports_reasoning = False
            request.pop("reasoning")
            response = self._client.responses.create(**request)

        calls: list[ToolCall] = []
        for item in response.output or []:
            if getattr(item, "type", "") == "function_call":
                try:
                    arguments = json.loads(item.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                calls.append(ToolCall(id=item.call_id, name=item.name, arguments=arguments))

        usage = response.usage
        return LLMResponse(
            text=(response.output_text or "").strip(),
            tool_calls=calls,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            model=response.model or self.model,
        )
