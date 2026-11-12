"""Agent 4: Escalation Agent executing structured Human Handoff with Support Ticket persistence."""

from __future__ import annotations

from typing import Any

from src.config import generate_completion
from src.schemas import OrchestrationState
from src.tools.support_tools import create_support_ticket_or_escalate

ESCALATION_SYSTEM_PROMPT = (
    "You are the Getnet Escalation Agent responsible for structured Human Handoff. "
    "Synthesize the POS Terminal diagnostic findings, explain the Transaction Decline code "
    "and root cause clearly to the Merchant, provide the recorded Support Ticket reference, "
    "and outline the L2 specialist handoff and immediate payment continuity steps."
)


def _build_issue_summary(message: str, support_context: dict[str, Any]) -> str:
    """Build a concise Support Ticket issue summary from POS Terminal diagnostics or the raw Inquiry."""
    decline = support_context.get("last_transaction_decline") or {}
    terminal_id = support_context.get("terminal_id")
    model = support_context.get("model") or support_context.get("terminal_model")
    decline_code = decline.get("decline_code")
    tx_id = decline.get("transaction_id")
    amount_brl = decline.get("amount_brl")
    reason = decline.get("reason")

    if terminal_id and decline_code and decline_code != "NONE":
        return (
            f"POS Terminal {terminal_id} ({model}) Transaction Decline {decline_code} "
            f"on transaction {tx_id} ({amount_brl}): {reason}"
        )
    if terminal_id:
        return f"POS Terminal {terminal_id} ({model}) escalation inquiry: {message.strip()}"
    return f"Merchant escalation inquiry: {message.strip()}"


def _format_escalation_response(
    user_id: str,
    support_context: dict[str, Any],
    ticket_data: dict[str, Any],
    prior_answer: str,
) -> str:
    """Format a comprehensive deterministic Human Handoff response with diagnostics and Support Ticket details."""
    ticket_id = ticket_data.get("ticket_id")
    business_name = (
        support_context.get("business_name")
        or ticket_data.get("business_name")
        or user_id
    )
    terminal_id = (
        support_context.get("terminal_id")
        or ticket_data.get("terminal_id")
        or "N/A"
    )
    model = (
        support_context.get("model")
        or support_context.get("terminal_model")
        or "POS Terminal"
    )
    serial_number = support_context.get("serial_number", "N/A")
    decline = support_context.get("last_transaction_decline") or {}
    tx_id = decline.get("transaction_id", "N/A")
    amount_brl = decline.get("amount_brl", "N/A")
    decline_code = decline.get("decline_code", "UNSPECIFIED_DECLINE")
    decline_reason = decline.get(
        "reason",
        "Critical POS Terminal fault requiring L2 specialist intervention.",
    )

    sections: list[str] = []
    if prior_answer:
        sections.append(prior_answer)
    elif support_context.get("found"):
        sections.append(
            f"### POS Terminal Diagnostics for **{business_name}** (`{user_id}`)\n"
            f"- **Terminal ID**: `{terminal_id}` | **Model**: **{model}** (Serial `{serial_number}`)\n"
            f"- **Detected Transaction Decline**: Transaction `{tx_id}` ({amount_brl}) failed with code "
            f"`{decline_code}` — {decline_reason}"
        )

    if ticket_id:
        sections.append(
            "### Structured Human Handoff & Support Ticket Recorded\n"
            f"- **Support Ticket ID**: `{ticket_id}` (Status: `{ticket_data.get('status', 'OPEN_ESCALATED')}`, "
            f"Severity: `{ticket_data.get('severity', 'HIGH')}`)\n"
            f"- **Root Cause Assessment**: Your **{model}** **POS Terminal** (`{terminal_id}`) reported "
            f"**Transaction Decline** code `{decline_code}` on transaction `{tx_id}` ({amount_brl}). "
            f"{decline_reason}\n"
            "- **Specialist Handoff (L2 Support)**: A **Human Handoff** has been initiated to Getnet's "
            "**L2 POS Hardware & Acquiring Specialist** team with your full terminal telemetry attached. "
            "An L2 specialist will perform a **remote cryptographic PIN-pad key resynchronization (re-keying)** "
            "or dispatch an express **POS Terminal** swap if hardware replacement is required.\n"
            "- **Immediate Continuity Guidance**: Do not attempt repeated card chip insertions on the affected "
            "terminal until re-keying finishes. In the meantime, you can continue accepting payments immediately "
            "via **Payment Link** (*Get Pay*) or **Pix** QR Code in the **App Getnet**."
        )
    else:
        sections.append(
            "### Human Handoff Requested\n"
            f"- **Merchant Identifier**: `{user_id}`\n"
            "- **Status**: Escalated to a live Getnet human support specialist (`needs_human_handoff = True`). "
            "Because no active Merchant profile was matched for automated ticket creation, a specialist will "
            "verify your registration details directly."
        )

    return "\n\n".join(sections)


def run_escalation_agent(state: OrchestrationState) -> dict[str, Any]:
    """Execute Agent 4 (Escalation Agent) to record a Support Ticket and complete Human Handoff."""
    user_id = state.get("user_id", "").strip()
    message = state.get("message", "")
    sequence = list(state.get("agent_sequence", []))
    sequence.append("escalation_agent")
    tools = list(state.get("tools_called", []))
    support_context = dict(state.get("support_context") or {})

    existing_ticket = support_context.get("support_ticket")
    handoff_ticket_id = state.get("handoff_ticket_id")

    if isinstance(existing_ticket, dict) and existing_ticket.get("ticket_id"):
        ticket_data = existing_ticket
        handoff_ticket_id = str(existing_ticket["ticket_id"])
        if "create_support_ticket_or_escalate" not in tools:
            tools.append("create_support_ticket_or_escalate")
    elif handoff_ticket_id:
        ticket_data = {
            "created": True,
            "ticket_id": handoff_ticket_id,
            "merchant_id": user_id,
            "terminal_id": support_context.get("terminal_id"),
            "severity": "HIGH",
            "status": "OPEN_ESCALATED",
            "needs_human_handoff": True,
        }
        if "create_support_ticket_or_escalate" not in tools:
            tools.append("create_support_ticket_or_escalate")
    else:
        issue_summary = _build_issue_summary(message=message, support_context=support_context)
        ticket_data = create_support_ticket_or_escalate(
            merchant_id=user_id,
            issue_summary=issue_summary,
            severity="HIGH",
        )
        if "create_support_ticket_or_escalate" not in tools:
            tools.append("create_support_ticket_or_escalate")
        handoff_ticket_id = ticket_data.get("ticket_id")
        support_context["support_ticket"] = ticket_data

    prior_answer = (state.get("final_answer") or "").strip()
    fallback_answer = _format_escalation_response(
        user_id=user_id,
        support_context=support_context,
        ticket_data=ticket_data,
        prior_answer=prior_answer,
    )

    user_prompt = (
        f"Merchant ({user_id}) Inquiry: {message}\n\n"
        f"POS Diagnostic Context: {support_context}\n\n"
        f"Support Ticket Record: {ticket_data}\n\n"
        f"Draft Escalation Summary:\n{fallback_answer}"
    )
    final_answer = generate_completion(
        system_prompt=ESCALATION_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        fallback_text=fallback_answer,
    )

    return {
        **state,
        "agent_sequence": sequence,
        "tools_called": tools,
        "support_context": support_context,
        "needs_human_handoff": True,
        "handoff_ticket_id": handoff_ticket_id,
        "final_answer": final_answer,
    }
