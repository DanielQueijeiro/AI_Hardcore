# 03: Knowledge Agent — Resilient Web Search for General Utility Inquiries

**What to build:** Extend the **Knowledge Agent** so benign real-time *General Utility* **Inquiries** classified by the **Router Agent** (`safety_tier: "GENERAL_UTILITY"`, `primary_intent: "GENERAL_WEB_SEARCH"`) invoke the `search_web_general` tool and return an accurate, up-to-date answer via `POST /chat`. Include zero-key HTTP fallbacks (`open-meteo.com` for weather forecasts and `frankfurter.app` for foreign exchange rates) alongside DuckDuckGo search so container IP rate limits never break real-time weather or currency **Inquiries**.

**Blocked by:** 02: Knowledge Agent — Hybrid Getnet RAG for Product & Service Inquiries

**Status:** ready-for-agent

- [ ] Official Scenario **#2** (*"What's the weather forecast in Porto Alegre tomorrow?"*) routes through `["router_agent", "knowledge_agent"]` with `safety_tier: "GENERAL_UTILITY"`, invokes `["search_web_general"]`, and returns a weather forecast for Porto Alegre.
- [ ] Official Scenario **#7** (*"What's the euro exchange rate today?"*) routes through `["router_agent", "knowledge_agent"]` with `safety_tier: "GENERAL_UTILITY"`, invokes `["search_web_general"]`, and returns the current Euro exchange rate.
- [ ] Both scenarios pass deterministically in automated `POST /chat` tests and live container runs without requiring any paid search API keys.
