"""Pydantic v2 data contracts and LangGraph shared state specification."""

from __future__ import annotations

from enum import Enum
from typing import Any, TypedDict

from pydantic import BaseModel, Field


class SafetyTier(str, Enum):
    """Three-tier Safety Policy classification (ADR-0002)."""

    GETNET_DOMAIN = "GETNET_DOMAIN"
    GENERAL_UTILITY = "GENERAL_UTILITY"
    RESTRICTED_UNSAFE = "RESTRICTED_UNSAFE"


class PrimaryIntent(str, Enum):
    """Primary routing intent assigned by the Router Agent."""

    PRODUCT_KNOWLEDGE = "PRODUCT_KNOWLEDGE"
    GENERAL_WEB_SEARCH = "GENERAL_WEB_SEARCH"
    CUSTOMER_SUPPORT = "CUSTOMER_SUPPORT"
    COMPOUND_SUPPORT_AND_KB = "COMPOUND_SUPPORT_AND_KB"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
    BLOCKED = "BLOCKED"


class ChatRequest(BaseModel):
    """HTTP Request Contract for POST /chat and POST /api/v1/chat."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Merchant Inquiry",
    )
    user_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Merchant identifier, e.g., cliente1988",
    )


class OrchestrationMetadata(BaseModel):
    """Structured observability trace returned with every ChatResponse."""

    trace_id: str
    safety_tier: SafetyTier
    primary_intent: PrimaryIntent
    agent_sequence: list[str]
    tools_called: list[str]
    rag_sources: list[str]
    escalated_to_human: bool
    handoff_ticket_id: str | None = None
    latency_ms: int


class ChatResponse(BaseModel):
    """HTTP Response Contract for POST /chat and POST /api/v1/chat."""

    user_id: str
    message: str
    answer: str
    orchestration: OrchestrationMetadata


class HealthResponse(BaseModel):
    """HTTP Response Contract for GET /health."""

    status: str = "ok"
    service: str
    version: str
    llm_provider: str


class OrchestrationState(TypedDict, total=False):
    """Shared typed state passed across LangGraph agent nodes (ADR-0001)."""

    trace_id: str
    user_id: str
    message: str
    safety_tier: str
    primary_intent: str
    routing_rationale: str
    agent_sequence: list[str]
    tools_called: list[str]
    rag_sources: list[str]
    support_context: dict[str, Any]
    knowledge_context: str
    needs_knowledge_enrichment: bool
    needs_human_handoff: bool
    handoff_ticket_id: str | None
    final_answer: str
