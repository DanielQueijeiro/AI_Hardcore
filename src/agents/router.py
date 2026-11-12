"""Agent 1: Router & Guardrail Agent enforcing the 3-Tier Safety Policy (ADR-0002)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.schemas import OrchestrationState, PrimaryIntent, SafetyTier
from src.tools.search_tools import is_fx_query, is_general_utility_query, is_weather_query

PROMPT_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)?\s*(rules|instructions|prompts|guardrails)", re.I),
    re.compile(r"(system\s+prompt|developer\s+message|jailbreak|dan\s+mode|bypass\s+safety)", re.I),
    re.compile(r"(dump|leak|expose|override)\s+(all\s+)?(database|tables|credentials|secrets|rules)", re.I),
)

UNSAFE_CONTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(skimming|skimmer|clone\s+a?\s*(credit\s+|debit\s+)?card|card\s+cloning)\b", re.I),
    re.compile(r"\b(launder\s+money|money\s+laundering|stolen\s+card|fraudulent\s+charge|hack\s+pos)\b", re.I),
    re.compile(r"\b(malware|exploit\s+terminal|bypass\s+pin|steal\s+cvv)\b", re.I),
)

MERCHANT_ID_PATTERN = re.compile(r"\b(cliente\d+|merchant_[a-z0-9_]+)\b", re.I)


@dataclass(frozen=True)
class RoutingDecision:
    """Result of Router Agent's Safety Policy & Intent classification."""

    safety_tier: SafetyTier
    primary_intent: PrimaryIntent
    rationale: str
    needs_knowledge_enrichment: bool = False
    needs_human_handoff: bool = False
    refusal_message: str | None = None


def _detect_cross_merchant_access(message: str, authenticated_user_id: str) -> str | None:
    """Detect if the message references a different Merchant identifier than user_id."""
    auth_normalized = authenticated_user_id.strip().lower()
    mentioned_ids = {match.group(1).lower() for match in MERCHANT_ID_PATTERN.finditer(message)}
    foreign_ids = sorted(mid for mid in mentioned_ids if mid != auth_normalized)
    if foreign_ids:
        return foreign_ids[0]
    return None


def classify_inquiry(message: str, user_id: str) -> RoutingDecision:
    """Classify a Merchant Inquiry under the Three-Tier Safety Policy (ADR-0002)."""
    normalized = message.strip()
    lower = normalized.lower()

    # 1. Check Tier 3: Cross-Merchant tenant isolation violation
    foreign_merchant = _detect_cross_merchant_access(normalized, user_id)
    if foreign_merchant is not None:
        return RoutingDecision(
            safety_tier=SafetyTier.RESTRICTED_UNSAFE,
            primary_intent=PrimaryIntent.BLOCKED,
            rationale=(
                f"Blocked cross-merchant access attempt: authenticated Merchant '{user_id}' "
                f"requested data belonging to '{foreign_merchant}'."
            ),
            refusal_message=(
                "Request blocked by Getnet Safety Policy (Unauthorized Cross-Merchant Access): "
                f"As Merchant '{user_id}', you are only authorized to access your own account, "
                f"POS Terminal, and Settlement records. Access to '{foreign_merchant}' is strictly prohibited."
            ),
        )

    # 2. Check Tier 3: Prompt injection or jailbreak patterns
    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern.search(normalized):
            return RoutingDecision(
                safety_tier=SafetyTier.RESTRICTED_UNSAFE,
                primary_intent=PrimaryIntent.BLOCKED,
                rationale="Blocked prompt injection / instruction override attempt.",
                refusal_message=(
                    "Request blocked by Getnet Safety Policy: Instruction override, prompt injection, "
                    "and unauthorized system access requests cannot be processed."
                ),
            )

    # 3. Check Tier 3: Illicit, harmful, or payment-fraud topics
    for pattern in UNSAFE_CONTENT_PATTERNS:
        if pattern.search(normalized):
            return RoutingDecision(
                safety_tier=SafetyTier.RESTRICTED_UNSAFE,
                primary_intent=PrimaryIntent.BLOCKED,
                rationale="Blocked unsafe / illicit payment security or card cloning inquiry.",
                refusal_message=(
                    "Request blocked by Getnet Safety Policy: I cannot assist with card skimming, "
                    "cloning, terminal tampering, or any unauthorized/illicit activities."
                ),
            )

    # 4. Check Tier 2: Benign General Utility (weather forecast, foreign exchange rate, general public utility)
    if is_weather_query(normalized) or is_fx_query(normalized) or is_general_utility_query(normalized):
        return RoutingDecision(
            safety_tier=SafetyTier.GENERAL_UTILITY,
            primary_intent=PrimaryIntent.GENERAL_WEB_SEARCH,
            rationale="Classified as benign General Utility query requiring live web search.",
        )

    # 5. Tier 1: Getnet Domain & Support
    # Distinguish between Merchant-specific operational support vs general product knowledge
    is_connectivity_issue = any(
        kw in lower
        for kw in (
            "won't connect",
            "wont connect",
            "not connecting",
            "cannot connect",
            "can't connect",
            "connect to the internet",
            "no internet",
            "offline",
            "connection error",
            "sem sinal",
            "não conecta",
            "nao conecta",
        )
    ) and any(
        hw in lower
        for hw in ("card machine", "pos", "terminal", "get smart", "get clássica", "get classica", "maquininha", "machine")
    )

    if is_connectivity_issue:
        return RoutingDecision(
            safety_tier=SafetyTier.GETNET_DOMAIN,
            primary_intent=PrimaryIntent.COMPOUND_SUPPORT_AND_KB,
            rationale=(
                "Merchant POS Terminal connectivity issue requires both terminal telemetry diagnostics "
                "and official Getnet network troubleshooting instructions."
            ),
            needs_knowledge_enrichment=True,
        )

    is_decline_or_terminal_error = any(
        kw in lower
        for kw in (
            "transaction decline",
            "decline error",
            "declined",
            "showing a transaction decline",
            "error code",
            "erro na transação",
            "transação recusada",
            "pin-pad",
            "pinpad",
        )
    )
    if is_decline_or_terminal_error:
        return RoutingDecision(
            safety_tier=SafetyTier.GETNET_DOMAIN,
            primary_intent=PrimaryIntent.CUSTOMER_SUPPORT,
            rationale=(
                "Merchant reported a POS Terminal Transaction Decline error requiring terminal diagnostics "
                "and potential Human Handoff escalation."
            ),
            needs_human_handoff=True,
        )

    is_settlement_or_account_support = any(
        kw in lower
        for kw in (
            "yesterday's sales",
            "yesterdays sales",
            "when will the money",
            "be deposited",
            "my settlement",
            "my deposit",
            "my account status",
            "settlement status",
            "settlement schedule",
            "vendas de ontem",
            "meu pagamento",
            "quando vou receber",
        )
    )
    if is_settlement_or_account_support:
        return RoutingDecision(
            safety_tier=SafetyTier.GETNET_DOMAIN,
            primary_intent=PrimaryIntent.CUSTOMER_SUPPORT,
            rationale="Merchant-specific Settlement schedule and sales payout inquiry.",
        )

    # Default Tier 1: Getnet Product & Service Knowledge (POS comparison, Pix rules, Antecipação, Crediário, Payment Link)
    return RoutingDecision(
        safety_tier=SafetyTier.GETNET_DOMAIN,
        primary_intent=PrimaryIntent.PRODUCT_KNOWLEDGE,
        rationale="Getnet product and service knowledge inquiry routed to Hybrid RAG.",
    )


def router_node(state: OrchestrationState) -> OrchestrationState:
    """LangGraph node for Agent 1 (Router & Guardrail Agent)."""
    message = state.get("message", "")
    user_id = state.get("user_id", "")
    decision = classify_inquiry(message=message, user_id=user_id)

    sequence = list(state.get("agent_sequence", []))
    sequence.append("router_agent")

    updated: OrchestrationState = {
        **state,
        "safety_tier": decision.safety_tier.value,
        "primary_intent": decision.primary_intent.value,
        "routing_rationale": decision.rationale,
        "agent_sequence": sequence,
        "needs_knowledge_enrichment": decision.needs_knowledge_enrichment,
        "needs_human_handoff": decision.needs_human_handoff,
    }

    if decision.safety_tier == SafetyTier.RESTRICTED_UNSAFE:
        updated["final_answer"] = (
            decision.refusal_message
            or "Request blocked by Getnet Safety Policy: This inquiry cannot be fulfilled."
        )

    return updated
