"""Live public-data lookups for general questions: FX (ECB via Frankfurter), weather (Open-Meteo), web search.

Each function returns `{"available": False, "error": ...}` when the source cannot be reached. Nothing here
ever falls back to a canned value: an agent that cannot fetch live data has to say so.

Every call to a source goes through one guard:
- a short-lived cache (the same rate or forecast asked twice in a few minutes is not fetched twice);
- one retry with backoff for transient failures (connection errors, timeouts, 429 and 5xx), never for a 4xx,
  which is the request's fault and would fail again;
- a circuit breaker per source: after repeated failures the source is not called for a cool-down period, so a
  dead dependency costs the turn nothing instead of a timeout on every call.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, TypeVar
from urllib.parse import urlparse

import httpx

T = TypeVar("T")

FX_TTL_SECONDS = 600.0
WEATHER_TTL_SECONDS = 1800.0
WEB_TTL_SECONDS = 600.0
CACHE_ENTRIES = 256


class CircuitOpen(Exception):
    """The source failed repeatedly and is in its cool-down period."""


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return not isinstance(exc, CircuitOpen | ValueError | KeyError)

WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "rime fog",
    51: "light drizzle", 53: "drizzle", 55: "dense drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers", 81: "rain showers", 82: "violent rain showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}  # fmt: skip


class LiveData:
    def __init__(
        self,
        enabled: bool = True,
        timeout: float = 4.0,
        client: httpx.Client | None = None,
        *,
        retries: int = 1,
        backoff_seconds: float = 0.25,
        breaker_threshold: int = 3,
        breaker_cooldown_seconds: float = 60.0,
        metrics: Any = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.enabled = enabled
        self.timeout = timeout
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self.retries = max(0, retries)
        self.backoff_seconds = backoff_seconds
        self.breaker_threshold = breaker_threshold
        self.breaker_cooldown_seconds = breaker_cooldown_seconds
        self.metrics = metrics
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def _count(self, source: str, outcome: str) -> None:
        if self.metrics is not None:
            self.metrics.inc("live_source_calls_total", source=source, outcome=outcome)

    def breaker_open(self, source: str) -> bool:
        with self._lock:
            return self._clock() < self._open_until.get(source, 0.0)

    def _guarded(self, source: str, key: str, ttl: float, fetch: Callable[[], T]) -> T:
        """Cache, retry and circuit breaker around one call to an external source."""
        now = self._clock()
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] > now:
                self._cache.move_to_end(key)
                self._count(source, "cache_hit")
                return json.loads(json.dumps(hit[1]))  # a copy: callers may annotate what they get
            if now < self._open_until.get(source, 0.0):
                self._count(source, "circuit_open")
                raise CircuitOpen(source)
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                value = fetch()
            except Exception as exc:  # noqa: BLE001 - classified below; the caller turns it into available=false
                last = exc
                if not _retryable(exc):
                    self._count(source, "rejected")
                    raise
                if attempt < self.retries:
                    self._count(source, "retry")
                    self._sleep(self.backoff_seconds * (2**attempt))
                continue
            with self._lock:
                self._failures[source] = 0
                self._cache[key] = (self._clock() + ttl, value)
                while len(self._cache) > CACHE_ENTRIES:
                    self._cache.popitem(last=False)
            self._count(source, "ok")
            return json.loads(json.dumps(value))
        with self._lock:
            self._failures[source] = self._failures.get(source, 0) + 1
            if self._failures[source] >= self.breaker_threshold:
                self._open_until[source] = self._clock() + self.breaker_cooldown_seconds
                self._failures[source] = 0
        self._count(source, "error")
        assert last is not None
        raise last

    def _get(self, url: str, params: dict[str, Any], ttl: float) -> dict[str, Any]:
        def fetch() -> dict[str, Any]:
            response = self._client.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json()

        return self._guarded(urlparse(url).netloc, f"{url}?{json.dumps(params, sort_keys=True)}", ttl, fetch)

    def fx_rate(self, base: str, quote: str) -> dict[str, Any]:
        base, quote = base.upper()[:3], quote.upper()[:3]
        if not self.enabled:
            return {"available": False, "error": "live data disabled"}
        try:
            payload = self._get("https://api.frankfurter.app/latest", {"from": base, "to": quote}, FX_TTL_SECONDS)
            rate = payload["rates"][quote]
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "error": f"FX source unreachable: {type(exc).__name__}"}
        return {
            "available": True,
            "base": base,
            "quote": quote,
            "rate": rate,
            "reference_date": payload.get("date"),
            "source": "European Central Bank reference rates via api.frankfurter.app",
            "source_url": "https://www.frankfurter.app/",
        }

    def weather(self, city: str, days: int = 3) -> dict[str, Any]:
        if not self.enabled:
            return {"available": False, "error": "live data disabled"}
        try:
            geo = self._get("https://geocoding-api.open-meteo.com/v1/search", {"name": city, "count": 1}, WEATHER_TTL_SECONDS)
            place = (geo.get("results") or [None])[0]
            if place is None:
                return {"available": False, "error": f"unknown city '{city}'"}
            forecast = self._get(
                "https://api.open-meteo.com/v1/forecast",
                {
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "timezone": place.get("timezone", "auto"),
                    "forecast_days": max(1, min(days, 7)),
                },
                WEATHER_TTL_SECONDS,
            )
            daily = forecast["daily"]
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "error": f"weather source unreachable: {type(exc).__name__}"}
        return {
            "available": True,
            "location": ", ".join(str(p) for p in (place.get("name"), place.get("admin1"), place.get("country")) if p),
            "note": "daily[0] is today in the location's timezone, daily[1] is tomorrow",
            "daily": [
                {
                    "date": daily["time"][i],
                    "condition": WMO.get(int(daily["weather_code"][i]), "unknown"),
                    "temp_max_c": daily["temperature_2m_max"][i],
                    "temp_min_c": daily["temperature_2m_min"][i],
                    "precipitation_probability_pct": daily["precipitation_probability_max"][i],
                }
                for i in range(len(daily["time"]))
            ],
            "source": "Open-Meteo forecast",
            "source_url": "https://open-meteo.com/",
        }

    def web_search(self, query: str, max_results: int = 4) -> dict[str, Any]:
        if not self.enabled:
            return {"available": False, "error": "live data disabled"}
        def fetch() -> list[dict[str, Any]]:
            from ddgs import DDGS

            with DDGS(timeout=int(self.timeout)) as client:
                return list(client.text(query, max_results=max_results) or [])

        try:
            rows = self._guarded("duckduckgo", f"ddgs?{max_results}:{query.strip().lower()}", WEB_TTL_SECONDS, fetch)
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "error": f"web search unreachable: {type(exc).__name__}"}
        results = [
            {"title": str(r.get("title", ""))[:200], "snippet": str(r.get("body", ""))[:500], "url": str(r.get("href", ""))}
            for r in rows
        ]
        return {"available": bool(results), "results": results, "source": "DuckDuckGo web search"}
