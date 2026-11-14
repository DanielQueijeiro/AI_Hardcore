"""Shared fixtures. Every test gets its own databases; no network, no API key."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.config import Settings
from src.llm.base import LLMClient, LLMResponse
from src.llm.offline import OfflinePolicyLLM
from src.llm.scripted import ScriptedLLM, call

PASSWORD = "getnet-demo"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        llm_provider="offline",
        openai_api_key=None,
        sqlite_db_path=tmp_path / "support.db",
        checkpoint_db_path=tmp_path / "checkpoints.db",
        jwt_secret="test-secret-" + "x" * 32,
        enable_live_web=False,
        hitl_sweep_interval_seconds=3600.0,
        log_level="WARNING",
    )


@pytest.fixture
def make_client(settings: Settings) -> Iterator[Callable[..., TestClient]]:
    opened: list[TestClient] = []

    def factory(llm: LLMClient | None = None, **overrides: Any) -> TestClient:
        client = TestClient(create_app(settings.model_copy(update=overrides), llm=llm))
        client.__enter__()
        opened.append(client)
        return client

    yield factory
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


def login(client: TestClient, user: str = "cliente1988") -> dict[str, str]:
    response = client.post("/auth/login", json={"user_id": user, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def chat(client: TestClient, message: str, headers: dict[str, str] | None = None, conversation: str = "t1", **body: Any) -> dict[str, Any]:
    response = client.post("/chat", json={"message": message, "conversation_id": conversation, **body}, headers=headers or {})
    assert response.status_code == 200, response.text
    return response.json()


def scripted(script: dict[str, Any]) -> ScriptedLLM:
    """Scripted roles answer from the script; every other role falls back to the offline policy."""
    return ScriptedLLM(script, default=OfflinePolicyLLM())


def approve() -> LLMResponse:
    return call("review", verdict="approve", grounded=True, complete=True, issues=[], needs_more_evidence="")


def revise(*issues: str, research: str = "") -> LLMResponse:
    return call("review", verdict="revise", grounded=False, complete=True, issues=list(issues), needs_more_evidence=research)


def delegate(agent: str, task: str) -> LLMResponse:
    return call(f"delegate_{agent}", thought="test", task=task, remaining_plan=["answer"])


def finish(answer: str) -> LLMResponse:
    return call("finish", answer=answer, confidence="high")
