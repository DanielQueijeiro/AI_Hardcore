"""LangGraph State-Machine Orchestration for the four specialized Getnet agents (ADR-0001, ADR-0005)."""

from __future__ import annotations

import uuid
from typing import Literal

from langgraph.graph import END, START, StateGraph

from src.agents.router import router_node
from src.schemas import OrchestrationState, PrimaryIntent, SafetyTier


def knowledge_node(state: OrchestrationState) -> OrchestrationState:
    """Agent 2 (Knowledge Agent) node — delegates to src.agents.knowledge when present, else stub."""
    try:
        from src.agents.knowledge import run_knowledge_agent  # type: ignore[import-not-found]

        return run_knowledge_agent(state)
    except ImportError:
        pass

    sequence = list(state.get("agent_sequence", []))
    sequence.append("knowledge_agent")
    tools = list(state.get("tools_called", []))
    rag_sources = list(state.get("rag_sources", []))

    intent = state.get("primary_intent", PrimaryIntent.PRODUCT_KNOWLEDGE.value)
    if intent == PrimaryIntent.GENERAL_WEB_SEARCH.value:
        if "search_web_general" not in tools:
            tools.append("search_web_general")
        answer = (
            f"[Knowledge Agent Web Search] Processed general utility inquiry for '{state.get('message', '')}'."
        )
    else:
        if "retrieve_getnet_knowledge" not in tools:
            tools.append("retrieve_getnet_knowledge")
        if not rag_sources:
            rag_sources.append("data/getnet_knowledge_base.md")
        support_ctx = state.get("support_context") or {}
        if support_ctx:
            answer = (
                f"{state.get('final_answer', '')}\n\n"
                "[Knowledge Agent RAG] Enriched POS Terminal diagnostics with official Getnet troubleshooting steps."
            ).strip()
        else:
            answer = (
                f"[Knowledge Agent RAG] Processed Getnet product inquiry for '{state.get('message', '')}'."
            )

    return {
        **state,
        "agent_sequence": sequence,
        "tools_called": tools,
        "rag_sources": rag_sources,
        "final_answer": answer,
    }


def customer_support_node(state: OrchestrationState) -> OrchestrationState:
    """Agent 3 (Customer Support Agent) node — delegates to src.agents.support when present, else stub."""
    try:
        from src.agents.support import run_customer_support_agent  # type: ignore[import-not-found]

        return run_customer_support_agent(state)
    except ImportError:
        pass

    sequence = list(state.get("agent_sequence", []))
    sequence.append("customer_support_agent")
    tools = list(state.get("tools_called", []))

    needs_kb = bool(state.get("needs_knowledge_enrichment", False))
    needs_handoff = bool(state.get("needs_human_handoff", False))

    if needs_kb or needs_handoff:
        if "get_pos_terminal_diagnostics" not in tools:
            tools.append("get_pos_terminal_diagnostics")
        support_context = {
            "merchant_id": state.get("user_id", ""),
            "terminal_model": "Get Smart",
            "status": "OFFLINE_GPRS_TIMEOUT" if needs_kb else "ERR_51_ISSUER_DECLINE / POS_KEY_SYNC_WARN",
        }
        answer = (
            f"[Customer Support Agent] Executed POS Terminal diagnostics for Merchant '{state.get('user_id', '')}'."
        )
    else:
        if "get_merchant_profile_and_settlements" not in tools:
            tools.append("get_merchant_profile_and_settlements")
        support_context = {
            "merchant_id": state.get("user_id", ""),
            "settlement_summary": "Pix D+0, Debit D+1, Credit D+2",
        }
        answer = (
            f"[Customer Support Agent] Retrieved Settlement schedule for Merchant '{state.get('user_id', '')}'."
        )

    return {
        **state,
        "agent_sequence": sequence,
        "tools_called": tools,
        "support_context": support_context,
        "final_answer": answer,
    }


def escalation_node(state: OrchestrationState) -> OrchestrationState:
    """Agent 4 (Escalation Agent) node — delegates to src.agents.escalation when present, else stub."""
    try:
        from src.agents.escalation import run_escalation_agent  # type: ignore[import-not-found]

        return run_escalation_agent(state)
    except ImportError:
        pass

    sequence = list(state.get("agent_sequence", []))
    sequence.append("escalation_agent")
    tools = list(state.get("tools_called", []))
    if "create_support_ticket_or_escalate" not in tools:
        tools.append("create_support_ticket_or_escalate")

    ticket_id = state.get("handoff_ticket_id") or "TKT-1988-001"
    answer = (
        f"{state.get('final_answer', '')}\n\n"
        f"[Escalation Agent] Human Handoff initiated with Support Ticket {ticket_id}."
    ).strip()

    return {
        **state,
        "agent_sequence": sequence,
        "tools_called": tools,
        "needs_human_handoff": True,
        "handoff_ticket_id": ticket_id,
        "final_answer": answer,
    }


def route_from_router(
    state: OrchestrationState,
) -> Literal["knowledge_agent", "customer_support_agent", "escalation_agent", "__end__"]:
    """Conditional router transition enforcing Tier 3 short-circuit and Tier 1/2 dispatch."""
    if state.get("safety_tier") == SafetyTier.RESTRICTED_UNSAFE.value:
        return END

    intent = state.get("primary_intent")
    if intent == PrimaryIntent.BLOCKED.value:
        return END
    if intent in (PrimaryIntent.PRODUCT_KNOWLEDGE.value, PrimaryIntent.GENERAL_WEB_SEARCH.value):
        return "knowledge_agent"
    if intent in (PrimaryIntent.CUSTOMER_SUPPORT.value, PrimaryIntent.COMPOUND_SUPPORT_AND_KB.value):
        return "customer_support_agent"
    if intent == PrimaryIntent.HUMAN_ESCALATION.value:
        return "escalation_agent"
    return "knowledge_agent"


def route_from_support(
    state: OrchestrationState,
) -> Literal["knowledge_agent", "escalation_agent", "__end__"]:
    """Conditional post-support transition enabling cooperative multi-agent chaining (ADR-0005)."""
    if state.get("needs_human_handoff"):
        return "escalation_agent"
    if state.get("needs_knowledge_enrichment"):
        return "knowledge_agent"
    return END


def build_orchestration_graph():
    """Compile and return the LangGraph orchestration state machine."""
    workflow = StateGraph(OrchestrationState)

    workflow.add_node("router_agent", router_node)
    workflow.add_node("knowledge_agent", knowledge_node)
    workflow.add_node("customer_support_agent", customer_support_node)
    workflow.add_node("escalation_agent", escalation_node)

    workflow.add_edge(START, "router_agent")
    workflow.add_conditional_edges(
        "router_agent",
        route_from_router,
        {
            "knowledge_agent": "knowledge_agent",
            "customer_support_agent": "customer_support_agent",
            "escalation_agent": "escalation_agent",
            END: END,
        },
    )
    workflow.add_conditional_edges(
        "customer_support_agent",
        route_from_support,
        {
            "knowledge_agent": "knowledge_agent",
            "escalation_agent": "escalation_agent",
            END: END,
        },
    )
    workflow.add_edge("knowledge_agent", END)
    workflow.add_edge("escalation_agent", END)

    return workflow.compile()


orchestration_graph = build_orchestration_graph()


def run_orchestration(message: str, user_id: str) -> OrchestrationState:
    """Execute the compiled LangGraph state machine for a single Merchant Inquiry."""
    initial_state: OrchestrationState = {
        "trace_id": f"trc-{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "message": message,
        "safety_tier": SafetyTier.GETNET_DOMAIN.value,
        "primary_intent": PrimaryIntent.PRODUCT_KNOWLEDGE.value,
        "routing_rationale": "",
        "agent_sequence": [],
        "tools_called": [],
        "rag_sources": [],
        "support_context": {},
        "knowledge_context": "",
        "needs_knowledge_enrichment": False,
        "needs_human_handoff": False,
        "handoff_ticket_id": None,
        "final_answer": "",
    }
    result: OrchestrationState = orchestration_graph.invoke(initial_state)
    return result
