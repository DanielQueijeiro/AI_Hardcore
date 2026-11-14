"""The provider adapter and the breaker, exercised against a fake SDK client (no network)."""

from __future__ import annotations

import time
from types import SimpleNamespace

import httpx
import pytest
from openai import BadRequestError

from src.config import Settings
from src.llm import build_llm
from src.llm.base import LLMResponse
from src.llm.offline import OfflinePolicyLLM
from src.llm.openai_client import OpenAIResponsesClient
from src.llm.resilient import ResilientLLM

TOOL = {"name": "finish", "description": "d", "parameters": {"type": "object", "properties": {"answer": {"type": "string"}}}}


class FakeResponses:
    def __init__(self, reject_reasoning: bool = False) -> None:
        self.requests: list[dict] = []
        self.reject_reasoning = reject_reasoning

    def create(self, **request):
        self.requests.append(request)
        if self.reject_reasoning and "reasoning" in request:
            response = httpx.Response(400, request=httpx.Request("POST", "https://api.test/v1/responses"))
            raise BadRequestError("Unsupported parameter: 'reasoning.effort'", response=response, body=None)
        return SimpleNamespace(
            output=[
                SimpleNamespace(type="reasoning"),
                SimpleNamespace(type="function_call", call_id="call_1", name="finish", arguments='{"answer": "48"}'),
                SimpleNamespace(type="function_call", call_id="call_2", name="finish", arguments="not json"),
            ],
            output_text="",
            usage=SimpleNamespace(input_tokens=321, output_tokens=12),
            model="gpt-test-2026",
        )


def adapter(fake: FakeResponses) -> OpenAIResponsesClient:
    client = OpenAIResponsesClient(api_key="sk-test", model="gpt-test")
    client._client = SimpleNamespace(responses=fake)
    return client


def test_request_shape_and_response_parsing():
    fake = FakeResponses()
    out = adapter(fake).complete(role="supervisor", instructions="sys", prompt="user", tools=[TOOL], tool_choice="finish", effort="none")
    request = fake.requests[0]
    assert request["instructions"] == "sys" and request["input"] == "user" and request["store"] is False
    assert request["reasoning"] == {"effort": "none"} and request["metadata"] == {"agent_role": "supervisor"}
    assert request["tools"][0] == {"type": "function", "name": "finish", "description": "d", "parameters": TOOL["parameters"], "strict": False}
    assert request["tool_choice"] == {"type": "function", "name": "finish"}
    assert [(c.id, c.name, c.arguments) for c in out.tool_calls] == [("call_1", "finish", {"answer": "48"}), ("call_2", "finish", {})]
    assert (out.input_tokens, out.output_tokens, out.model) == (321, 12, "gpt-test-2026")


@pytest.mark.parametrize("choice", ["auto", "required"])
def test_generic_tool_choice_is_passed_through(choice):
    fake = FakeResponses()
    adapter(fake).complete(role="knowledge", instructions="s", prompt="p", tools=[TOOL], tool_choice=choice)
    assert fake.requests[0]["tool_choice"] == choice
    assert fake.requests[0]["reasoning"] == {"effort": "low"}


def test_model_without_reasoning_controls_is_retried_without_them():
    fake = FakeResponses(reject_reasoning=True)
    client = adapter(fake)
    assert client.complete(role="critic", instructions="s", prompt="p").model == "gpt-test-2026"
    client.complete(role="critic", instructions="s", prompt="p")
    assert ["reasoning" in r for r in fake.requests] == [True, False, False], "learned once, not retried every call"


def test_breaker_opens_after_repeated_failures_and_recovers_after_cooldown():
    calls = {"primary": 0}

    class Flaky:
        name, model = "openai", "m"
        healthy = False

        def complete(self, **_):
            calls["primary"] += 1
            if not self.healthy:
                raise TimeoutError
            return LLMResponse(text="from the model")

    primary = Flaky()
    llm = ResilientLLM(primary, OfflinePolicyLLM(), failure_threshold=2, cooldown_seconds=0.05)
    for _ in range(4):
        assert llm.complete(role="summarizer", context={"messages": []}).degraded is True
    assert calls["primary"] == 2, "once open, the breaker stops calling the provider"
    primary.healthy = True
    time.sleep(0.25)  # well past the cooldown; Windows' monotonic clock ticks every ~16 ms
    recovered = llm.complete(role="summarizer", context={})
    assert recovered.text == "from the model" and recovered.degraded is False and not llm.breaker_open


def test_factory_selects_the_offline_policy_without_a_key():
    assert build_llm(Settings(_env_file=None, openai_api_key=None)).name == "offline"
    assert build_llm(Settings(_env_file=None, openai_api_key="sk-x", llm_provider="offline")).name == "offline"
    wrapped = build_llm(Settings(_env_file=None, openai_api_key="sk-x"))
    assert isinstance(wrapped, ResilientLLM) and wrapped.name == "openai"
