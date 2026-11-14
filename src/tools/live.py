"""Live public-data lookups for general questions: FX (ECB via Frankfurter), weather (Open-Meteo), web search.

Each function returns `{"available": False, "error": ...}` when the source cannot be reached. Nothing here
ever falls back to a canned value: an agent that cannot fetch live data has to say so.
"""

from __future__ import annotations

from typing import Any

import httpx

WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "rime fog",
    51: "light drizzle", 53: "drizzle", 55: "dense drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers", 81: "rain showers", 82: "violent rain showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}  # fmt: skip


class LiveData:
    def __init__(self, enabled: bool = True, timeout: float = 4.0, client: httpx.Client | None = None) -> None:
        self.enabled = enabled
        self.timeout = timeout
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self._client.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def fx_rate(self, base: str, quote: str) -> dict[str, Any]:
        base, quote = base.upper()[:3], quote.upper()[:3]
        if not self.enabled:
            return {"available": False, "error": "live data disabled"}
        try:
            payload = self._get("https://api.frankfurter.app/latest", {"from": base, "to": quote})
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
            geo = self._get("https://geocoding-api.open-meteo.com/v1/search", {"name": city, "count": 1})
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
        try:
            from ddgs import DDGS

            with DDGS(timeout=int(self.timeout)) as client:
                rows = list(client.text(query, max_results=max_results) or [])
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "error": f"web search unreachable: {type(exc).__name__}"}
        results = [
            {"title": str(r.get("title", ""))[:200], "snippet": str(r.get("body", ""))[:500], "url": str(r.get("href", ""))}
            for r in rows
        ]
        return {"available": bool(results), "results": results, "source": "DuckDuckGo web search"}
