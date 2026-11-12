"""Integration tests for Knowledge Agent General Utility Web Search via POST /chat (Ticket 03)."""

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.tools import search_tools
from src.tools.search_tools import search_web_general


def test_scenario_2_weather_forecast_in_porto_alegre_tomorrow() -> None:
    """Scenario #2: Weather forecast inquiry in Porto Alegre tomorrow routes to Knowledge Agent and invokes search_web_general."""
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "message": "What's the weather forecast in Porto Alegre tomorrow?",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    data = response.json()
    orch = data["orchestration"]

    assert orch["safety_tier"] == "GENERAL_UTILITY"
    assert orch["primary_intent"] == "GENERAL_WEB_SEARCH"
    assert orch["agent_sequence"] == ["router_agent", "knowledge_agent"]
    assert orch["tools_called"] == ["search_web_general"]
    assert orch["escalated_to_human"] is False

    answer_lower = data["answer"].lower()
    assert "porto alegre" in answer_lower
    assert "°c" in answer_lower or "celsius" in answer_lower
    assert any(
        term in answer_lower
        for term in ("forecast", "temperature", "high", "low", "max", "min", "precipitation", "clear", "partly cloudy", "rain")
    )


def test_scenario_7_euro_exchange_rate_today() -> None:
    """Scenario #7: Euro exchange rate inquiry routes to Knowledge Agent and invokes search_web_general."""
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "message": "What's the euro exchange rate today?",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    data = response.json()
    orch = data["orchestration"]

    assert orch["safety_tier"] == "GENERAL_UTILITY"
    assert orch["primary_intent"] == "GENERAL_WEB_SEARCH"
    assert orch["agent_sequence"] == ["router_agent", "knowledge_agent"]
    assert orch["tools_called"] == ["search_web_general"]
    assert orch["escalated_to_human"] is False

    answer_lower = data["answer"].lower()
    assert "eur" in answer_lower or "euro" in answer_lower
    assert "brl" in answer_lower or "r$" in answer_lower
    assert "usd" in answer_lower


def test_general_web_search_uses_live_open_meteo_and_frankfurter_and_ddgs_with_resilient_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify live Open-Meteo, Frankfurter, and DuckDuckGo search execution plus resilient offline fallback."""
    client = TestClient(app)

    class _FakeHttpResponse:
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._payload

    def _fake_http_get(url: str, *args: object, **kwargs: object) -> _FakeHttpResponse:
        if "api.open-meteo.com" in url:
            return _FakeHttpResponse(
                {
                    "daily": {
                        "time": ["2026-03-20", "2026-03-21"],
                        "weather_code": [1, 61],
                        "temperature_2m_max": [27.0, 28.4],
                        "temperature_2m_min": [18.0, 17.2],
                        "precipitation_probability_max": [10, 65],
                    }
                }
            )
        if "api.frankfurter.app" in url:
            return _FakeHttpResponse(
                {
                    "amount": 1.0,
                    "base": "EUR",
                    "date": "2026-03-20",
                    "rates": {"BRL": 6.245, "USD": 1.092},
                }
            )
        raise httpx.ConnectError(f"Unexpected URL {url}")

    monkeypatch.setattr(httpx, "get", _fake_http_get)

    weather_resp = client.post(
        "/chat",
        json={"message": "What's the weather forecast in Porto Alegre tomorrow?", "user_id": "cliente1988"},
    )
    assert weather_resp.status_code == 200
    weather_answer = weather_resp.json()["answer"]
    assert "28.4°C" in weather_answer
    assert "17.2°C" in weather_answer
    assert "65%" in weather_answer
    assert "Slight rain" in weather_answer

    fx_resp = client.post(
        "/chat",
        json={"message": "What's the euro exchange rate today?", "user_id": "cliente1988"},
    )
    assert fx_resp.status_code == 200
    fx_answer = fx_resp.json()["answer"]
    assert "6.2450" in fx_answer
    assert "1.0920" in fx_answer

    # Verify DuckDuckGo search integration for general queries when DDGS returns snippets
    class _FakeDDGS:
        def __enter__(self) -> "_FakeDDGS":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def text(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
            return [
                {
                    "title": "Banco Central do Brasil SELIC Rate",
                    "body": "Current Brazilian benchmark interest rate information.",
                    "href": "https://www.bcb.gov.br",
                }
            ]

    monkeypatch.setattr(search_tools, "DDGS", _FakeDDGS)
    ddg_result = search_web_general("Brazil central bank benchmark rate", enable_live_http=True)
    assert "Banco Central do Brasil SELIC Rate" in ddg_result
    assert "https://www.bcb.gov.br" in ddg_result

    # Verify resilient fallback when HTTP endpoints fail or rate-limit
    def _raise_network_error(*args: object, **kwargs: object) -> None:
        raise httpx.ConnectTimeout("Simulated container network timeout")

    monkeypatch.setattr(httpx, "get", _raise_network_error)
    fallback_weather = client.post(
        "/chat",
        json={"message": "What's the weather forecast in Porto Alegre tomorrow?", "user_id": "cliente1988"},
    )
    assert fallback_weather.status_code == 200
    assert "porto alegre" in fallback_weather.json()["answer"].lower()
    assert "°c" in fallback_weather.json()["answer"].lower()


