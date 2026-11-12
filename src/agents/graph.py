"""LangGraph State-Machine Orchestration for the four specialized Getnet agents (ADR-0001, ADR-0005)."""

from __future__ import annotations

import uuid
from typing import Literal

from langgraph.graph import END, START, StateGraph

from src.agents.escalation import run_escalation_agent
from src.agents.knowledge import run_knowledge_agent
from src.agents.router import router_node
from src.agents.support import run_customer_support_agent
from src.schemas import OrchestrationState, PrimaryIntent, SafetyTier


def knowledge_node(state: OrchestrationState) -> OrchestrationState:
    """Agent 2 (Knowledge Agent) node."""
    return run_knowledge_agent(state)  # type: ignore[return-value]


def customer_support_node(state: OrchestrationState) -> OrchestrationState:
    """Agent 3 (Customer Support Agent) node."""
    return run_customer_support_agent(state)


def escalation_node(state: OrchestrationState) -> OrchestrationState:
    """Agent 4 (Escalation Agent) node."""
    return run_escalation_agent(state)  # type: ignore[return-value]


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
