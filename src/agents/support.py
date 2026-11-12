"""Agent 3: Customer Support Agent resolving Merchant-specific Settlement and POS Terminal inquiries."""

from __future__ import annotations

from typing import Any

from src.config import generate_completion
from src.schemas import OrchestrationState, PrimaryIntent
from src.tools.support_tools import (
    create_support_ticket_or_escalate,
    get_merchant_profile_and_settlements,
    get_pos_terminal_diagnostics,
)

SUPPORT_SYSTEM_PROMPT = (
    "You are the Getnet Customer Support Agent. Answer the Merchant's inquiry accurately using ONLY "
    "the provided deterministic Merchant profile, Settlement schedule, or POS Terminal diagnostic records. "
    "Preserve all exact BRL amounts, settlement cycles (D+0, D+1, D+2), bank details, and terminal codes."
)


def _is_pos_diagnostic_inquiry(state: OrchestrationState) -> bool:
    """Return True when the inquiry targets POS Terminal connectivity or Transaction Decline diagnostics."""
    if state.get("needs_knowledge_enrichment") or state.get("needs_human_handoff"):
        return True
    if state.get("primary_intent") == PrimaryIntent.COMPOUND_SUPPORT_AND_KB.value:
        return True

    lower = state.get("message", "").lower()
    return any(
        kw in lower
        for kw in (
            "card machine",
            "pos terminal",
            "terminal",
            "get smart",
            "get clássica",
            "get classica",
            "maquininha",
            "won't connect",
            "wont connect",
            "connect to the internet",
            "no internet",
            "offline",
            "transaction decline",
            "decline error",
            "error code",
        )
    )


def _format_settlement_response(profile_data: dict[str, Any]) -> str:
    """Format a deterministic, human-friendly Settlement response from SQLite records."""
    merchant_id = profile_data["merchant_id"]
    if not profile_data.get("found"):
        return (
            f"No active Getnet Merchant profile was found for identifier `{merchant_id}`. "
            "Please verify your registered `user_id` or contact Getnet Merchant Support for onboarding assistance."
        )

    business_name = profile_data["business_name"]
    bank = profile_data["bank_account"]
    pix_label = "Pix Enabled" if bank.get("pix_enabled") else "Pix Disabled"
    advance_label = (
        "Active (Receivables Advance / Antecipação enabled)"
        if profile_data.get("receivables_advance_active")
        else "Standard Settlement (Receivables Advance inactive)"
    )

    lines = [
        f"Here is the **Settlement** schedule for yesterday's sales for **{business_name}** (`{merchant_id}`):",
        "",
        f"- **Registered Bank Account**: {bank['bank_name']} ({bank['bank_code']}) — Agency `{bank['agency']}`, Account `{bank['account_number']}` ({bank['status']}, {pix_label})",
        f"- **Settlement Plan**: {advance_label}",
        "",
        "### Yesterday's Sales & Settlement Schedule",
    ]

    for item in profile_data.get("settlements", []):
        modality = item["modality"]
        gross = item["gross_amount_brl"]
        net = item["net_amount_brl"]
        cycle = item["settlement_cycle"]
        window = item["scheduled_window"]
        notes = item["notes"]
        if gross != net:
            lines.append(
                f"- **{modality}** (`{cycle}`): Gross **{gross}** → Net Settlement **{net}** — {window}. {notes}"
            )
        else:
            lines.append(
                f"- **{modality}** (`{cycle}`): **{gross}** — {window}. {notes}"
            )

    return "\n".join(lines)


def _format_pos_diagnostics_summary(diag_data: dict[str, Any]) -> str:
    """Format POS Terminal diagnostic findings for standalone or cooperative downstream chaining."""
    merchant_id = diag_data["merchant_id"]
    if not diag_data.get("found"):
        return (
            f"No active Getnet Merchant or POS Terminal profile was found for identifier `{merchant_id}`. "
            "Please verify your registered `user_id`."
        )

    decline = diag_data.get("last_transaction_decline", {})
    return (
        f"### POS Terminal Diagnostics for **{diag_data['business_name']}** (`{merchant_id}`)\n"
        f"- **Terminal ID**: `{diag_data['terminal_id']}` | **Model**: **{diag_data['model']}** ({diag_data['hardware_specs']})\n"
        f"- **Serial Number**: `{diag_data['serial_number']}`\n"
        f"- **Connectivity Status**: `{diag_data['connectivity_status']}` — {diag_data['connectivity_summary']}\n"
        f"- **Last Transaction Decline**: Transaction `{decline.get('transaction_id')}` ({decline.get('amount_brl')}) "
        f"with code `{decline.get('decline_code')}` ({decline.get('reason')})"
    )


def run_customer_support_agent(state: OrchestrationState) -> OrchestrationState:
    """Execute Agent 3 (Customer Support Agent) node with strict tenant scoping by user_id."""
    user_id = state.get("user_id", "").strip()
    message = state.get("message", "")

    sequence = list(state.get("agent_sequence", []))
    sequence.append("customer_support_agent")
    tools = list(state.get("tools_called", []))

    needs_kb = bool(state.get("needs_knowledge_enrichment", False))
    needs_handoff = bool(state.get("needs_human_handoff", False))

    if _is_pos_diagnostic_inquiry(state):
        diag_data = get_pos_terminal_diagnostics(merchant_id=user_id)
        if "get_pos_terminal_diagnostics" not in tools:
            tools.append("get_pos_terminal_diagnostics")

        handoff_ticket_id = state.get("handoff_ticket_id")
        support_context: dict[str, Any] = dict(diag_data)

        if diag_data.get("found"):
            support_context.setdefault("terminal_model", diag_data.get("model", ""))
            support_context.setdefault("status", diag_data.get("connectivity_status", ""))

            decline_info = diag_data.get("last_transaction_decline", {})
            lower_msg = message.lower()
            is_decline_inquiry = needs_handoff or any(
                kw in lower_msg
                for kw in ("decline", "error", "recusad", "pin-pad", "pinpad")
            )
            if decline_info.get("requires_l2_escalation") and is_decline_inquiry:
                needs_handoff = True
                needs_kb = False
                issue_summary = (
                    f"POS Terminal {diag_data.get('terminal_id')} ({diag_data.get('model')}) "
                    f"Transaction Decline {decline_info.get('decline_code')} on transaction "
                    f"{decline_info.get('transaction_id')} ({decline_info.get('amount_brl')}): "
                    f"{decline_info.get('reason')}"
                )
                ticket_data = create_support_ticket_or_escalate(
                    merchant_id=user_id,
                    issue_summary=issue_summary,
                    severity="HIGH",
                )
                if "create_support_ticket_or_escalate" not in tools:
                    tools.append("create_support_ticket_or_escalate")
                handoff_ticket_id = ticket_data.get("ticket_id")
                support_context["support_ticket"] = ticket_data
            elif diag_data.get("connectivity_status") == "OFFLINE_GPRS_TIMEOUT" and not needs_handoff:
                needs_kb = True

        fallback_answer = _format_pos_diagnostics_summary(diag_data)
        final_answer = (
            generate_completion(
                system_prompt=SUPPORT_SYSTEM_PROMPT,
                user_prompt=f"Merchant ({user_id}) Inquiry: {message}\n\nDiagnostic Data:\n{fallback_answer}",
                fallback_text=fallback_answer,
            )
            if diag_data.get("found")
            else fallback_answer
        )

        return {
            **state,
            "agent_sequence": sequence,
            "tools_called": tools,
            "support_context": support_context,
            "needs_knowledge_enrichment": needs_kb,
            "needs_human_handoff": needs_handoff,
            "handoff_ticket_id": handoff_ticket_id,
            "final_answer": final_answer,
        }

    profile_data = get_merchant_profile_and_settlements(merchant_id=user_id)
    if "get_merchant_profile_and_settlements" not in tools:
        tools.append("get_merchant_profile_and_settlements")

    fallback_answer = _format_settlement_response(profile_data)
    final_answer = (
        generate_completion(
            system_prompt=SUPPORT_SYSTEM_PROMPT,
            user_prompt=f"Merchant ({user_id}) Inquiry: {message}\n\nSettlement Data:\n{fallback_answer}",
            fallback_text=fallback_answer,
        )
        if profile_data.get("found")
        else fallback_answer
    )

    return {
        **state,
        "agent_sequence": sequence,
        "tools_called": tools,
        "support_context": profile_data,
        "needs_knowledge_enrichment": needs_kb,
        "needs_human_handoff": needs_handoff,
        "final_answer": final_answer,
    }
