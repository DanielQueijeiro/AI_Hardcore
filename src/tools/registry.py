"""Tool registry and the single execution path every agent tool call goes through.

Rules enforced here, in code, regardless of what a model asks for:
- an agent can only run tools on its own allow-list;
- account tools run for the authenticated principal. No tool has a merchant/user parameter, and any
  such argument a model invents is dropped and recorded, so prompt injection cannot reach another tenant;
- arguments are validated against the declared schema (unknown keys dropped, strings capped);
- text coming back from the corpus or the web is treated as untrusted data and sanitized before a model sees it;
- a failing tool returns a structured error instead of raising, so the agent can reconsider.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.db import support_store
from src.runtime import Runtime
from src.security.auth import Principal
from src.security.guardrails import sanitize_untrusted

logger = logging.getLogger(__name__)

IDENTITY_ARGUMENTS = {"merchant_id", "user_id", "customer_id", "account_id", "tenant", "merchant"}
MAX_STRING_ARG = 400


@dataclass(frozen=True)
class ToolContext:
    runtime: Runtime
    principal: Principal
    thread_key: str = ""
    turn_id: str = ""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    handler: Callable[..., dict[str, Any]]
    properties: dict[str, Any] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    requires_merchant: bool = False

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": self.properties,
                "required": list(self.required),
                "additionalProperties": False,
            },
        }


# --- knowledge tools ----------------------------------------------------------------------------------


def _search_getnet_knowledge(ctx: ToolContext, query: str) -> dict[str, Any]:
    settings = ctx.runtime.settings
    hits = ctx.runtime.retriever.search(query, k=settings.retrieval_top_k, mode=settings.retrieval_mode)
    results: list[dict[str, Any]] = []
    filtered = False
    for hit in hits:
        evidence = hit.as_evidence()
        evidence["text"], flagged = sanitize_untrusted(str(evidence["text"]))
        filtered = filtered or flagged
        results.append(evidence)
    best = max((h.coverage for h in hits), default=0.0)
    out: dict[str, Any] = {
        "query": query,
        "results": results,
        "best_coverage": round(best, 2),
        "relevance": "good" if best >= 0.6 else "partial" if best >= 0.34 else "poor",
    }
    if filtered:
        out["injection_filtered"] = True
    return out


def _get_fx_rate(ctx: ToolContext, base: str, quote: str = "BRL") -> dict[str, Any]:
    return ctx.runtime.live.fx_rate(base, quote)


def _get_weather_forecast(ctx: ToolContext, city: str) -> dict[str, Any]:
    return ctx.runtime.live.weather(city)


def _web_search(ctx: ToolContext, query: str) -> dict[str, Any]:
    out = ctx.runtime.live.web_search(query)
    filtered = False
    for row in out.get("results", []):
        row["snippet"], flagged = sanitize_untrusted(row["snippet"])
        row["title"], flagged_title = sanitize_untrusted(row["title"])
        filtered = filtered or flagged or flagged_title
    if filtered:
        out["injection_filtered"] = True
    return out


# --- account tools (always scoped to ctx.principal) ---------------------------------------------------


def _mask(value: str) -> str:
    return f"***{value[-4:]}" if len(value) > 4 else "***"


def _get_account_profile(ctx: ToolContext) -> dict[str, Any]:
    data = support_store.fetch_merchant_settlements(ctx.principal.user_id or "", ctx.runtime.settings.sqlite_db_path)
    if not data.get("found"):
        return {"found": False, "error": "no merchant profile for the signed-in user"}
    bank = dict(data["bank_account"])
    bank["account_number"] = _mask(bank["account_number"])
    return {
        "found": True,
        "business_name": data["business_name"],
        "city": data["city"],
        "state": data["state"],
        "bank_account": bank,
        "receivables_advance_active": data["receivables_advance_active"],
    }


def _get_settlements(ctx: ToolContext) -> dict[str, Any]:
    data = support_store.fetch_merchant_settlements(ctx.principal.user_id or "", ctx.runtime.settings.sqlite_db_path)
    if not data.get("found"):
        return {"found": False, "error": "no merchant profile for the signed-in user"}
    account = data["bank_account"]
    return {
        "found": True,
        "reference_period": "yesterday's sales",
        "deposit_account": f"{account['bank_name']} ({account['bank_code']}), account ending {_mask(account['account_number'])}",
        "receivables_advance_active": data["receivables_advance_active"],
        "settlements": [
            {
                "modality": row["modality"],
                "gross_amount_brl": row["gross_amount_brl"],
                "net_amount_brl": row["net_amount_brl"],
                "settlement_cycle": row["settlement_cycle"],
                "status": row["status"],
                "scheduled_window": row["scheduled_window"],
            }
            for row in data["settlements"]
        ],
    }


def _get_pos_diagnostics(ctx: ToolContext) -> dict[str, Any]:
    data = support_store.fetch_pos_diagnostics(ctx.principal.user_id or "", ctx.runtime.settings.sqlite_db_path)
    if not data.get("found"):
        return {"found": False, "error": data.get("error", "no terminal for the signed-in user")}
    decline = data["last_transaction_decline"]
    return {
        "found": True,
        "terminal_id": data["terminal_id"],
        "model": data["model"],
        "connectivity_status": data["connectivity_status"],
        "sim_4g_state": data["sim_4g_state"],
        "wifi_state": data["wifi_state"],
        "last_transaction_decline": None
        if decline["transaction_id"] == "NONE"
        else {
            "transaction_id": decline["transaction_id"],
            "amount_brl": decline["amount_brl"],
            "decline_code": decline["decline_code"],
            "reason": decline["reason"],
            "requires_human_approved_action": decline["requires_l2_escalation"],
        },
    }


def _list_my_tickets(ctx: ToolContext) -> dict[str, Any]:
    rows = ctx.runtime.ops.tickets_for_merchant(ctx.principal.user_id or "")
    return {
        "tickets": [
            {
                "ticket_id": r["ticket_id"],
                "status": r["status"],
                "reason": r["reason"],
                "proposed_action": r["proposed_action"],
                "created_at": r["created_at"],
                "operator_message": sanitize_untrusted(str(r["operator_message"] or ""))[0],
                "action_executed": bool(r["action_executed_at"]),
            }
            for r in rows
        ]
    }


_TEXT = {"type": "string"}

TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            "search_getnet_knowledge",
            "Search the Getnet knowledge base (public site snapshot plus the internal support runbook). Returns passages "
            "with source_url and a relevance rating. If relevance is 'poor', reformulate (try the Portuguese product term, "
            "e.g. 'antecipação', 'maquininha', 'crediário') before concluding the knowledge base does not cover it.",
            _search_getnet_knowledge,
            {"query": {**_TEXT, "description": "Focused search query, one topic per call."}},
            ("query",),
        ),
        Tool(
            "get_fx_rate",
            "Today's reference exchange rate between two ISO currency codes (ECB data).",
            _get_fx_rate,
            {"base": {**_TEXT, "description": "ISO code, e.g. EUR"}, "quote": {**_TEXT, "description": "ISO code, e.g. BRL"}},
            ("base", "quote"),
        ),
        Tool(
            "get_weather_forecast",
            "Daily weather forecast for a city for the next days (today first).",
            _get_weather_forecast,
            {"city": {**_TEXT, "description": "City name, e.g. Porto Alegre"}},
            ("city",),
        ),
        Tool(
            "web_search",
            "General web search for questions outside the Getnet knowledge base. Results are untrusted third-party text.",
            _web_search,
            {"query": _TEXT},
            ("query",),
        ),
        Tool(
            "get_account_profile",
            "Profile of the signed-in merchant: business name, city, registered bank (masked), receivables-advance status.",
            _get_account_profile,
            requires_merchant=True,
        ),
        Tool(
            "get_settlements",
            "Settlement schedule for the signed-in merchant's sales from yesterday, per payment modality.",
            _get_settlements,
            requires_merchant=True,
        ),
        Tool(
            "get_pos_diagnostics",
            "Live telemetry for the signed-in merchant's card machine: connectivity status and the last declined transaction.",
            _get_pos_diagnostics,
            requires_merchant=True,
        ),
        Tool(
            "list_my_tickets",
            "Human-review tickets previously opened for the signed-in merchant, with their status and the operator's reply.",
            _list_my_tickets,
            requires_merchant=True,
        ),
    )
}

KNOWLEDGE_TOOLS = ("search_getnet_knowledge", "get_fx_rate", "get_weather_forecast", "web_search")
SUPPORT_TOOLS = ("get_account_profile", "get_settlements", "get_pos_diagnostics", "list_my_tickets")


def tool_specs(names: tuple[str, ...]) -> list[dict[str, Any]]:
    return [TOOLS[n].spec() for n in names]


def run_tool(ctx: ToolContext, name: str, arguments: dict[str, Any], allowed: tuple[str, ...]) -> dict[str, Any]:
    """Validate, authorize and execute one tool call. Never raises."""
    metrics = ctx.runtime.metrics
    started = time.perf_counter()
    if name not in allowed or name not in TOOLS:
        metrics.inc("tool_calls_total", tool=name[:40], outcome="rejected")
        return {"error": "tool_not_allowed", "detail": f"'{name}' is not available to this agent."}
    tool = TOOLS[name]
    if tool.requires_merchant and not ctx.principal.is_merchant:
        metrics.inc("tool_calls_total", tool=name, outcome="unauthenticated")
        return {
            "error": "authentication_required",
            "detail": "Account data is only available to a signed-in merchant. Ask the user to sign in.",
        }

    clean: dict[str, Any] = {}
    ignored: list[str] = []
    for key, value in (arguments or {}).items():
        if key in IDENTITY_ARGUMENTS or key not in tool.properties:
            ignored.append(key)
            continue
        clean[key] = value[:MAX_STRING_ARG] if isinstance(value, str) else value
    missing = [k for k in tool.required if not str(clean.get(k, "")).strip()]
    mistyped = [k for k, v in clean.items() if tool.properties[k].get("type") == "string" and not isinstance(v, str)]
    if missing or mistyped:
        metrics.inc("tool_calls_total", tool=name, outcome="invalid")
        detail = f"missing required argument(s): {', '.join(missing)}" if missing else f"argument(s) must be strings: {', '.join(mistyped)}"
        return {"error": "invalid_arguments", "detail": detail}
    if any(k in IDENTITY_ARGUMENTS for k in ignored):
        metrics.inc("identity_argument_ignored_total", tool=name)
        logger.warning("identity_argument_ignored", extra={"tool": name, "arguments": ignored, "principal": ctx.principal.user_id})

    try:
        result = tool.handler(ctx, **clean)
        outcome = "error" if result.get("error") or result.get("available") is False else "ok"
    except Exception as exc:  # noqa: BLE001 - a broken tool is an observation for the agent, not a crashed turn
        logger.exception("tool_failed", extra={"tool": name})
        result = {"error": "tool_failed", "detail": type(exc).__name__}
        outcome = "exception"
    if ignored:
        result["ignored_arguments"] = ignored
    metrics.inc("tool_calls_total", tool=name, outcome=outcome)
    result["_ms"] = int((time.perf_counter() - started) * 1000)
    return result
