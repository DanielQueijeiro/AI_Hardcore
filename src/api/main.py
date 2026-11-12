"""FastAPI HTTP entrypoint exposing GET /health, POST /chat, and POST /api/v1/chat."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.agents.graph import run_orchestration
from src.config import get_settings
from src.db.support_store import ensure_seeded_database
from src.rag.retriever import get_retriever
from src.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    OrchestrationMetadata,
    PrimaryIntent,
    SafetyTier,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Pre-seed SQLite fixtures and warm the Hybrid RAG index on application startup."""
    ensure_seeded_database()
    get_retriever()
    yield


app = FastAPI(
    title="Getnet Multi-Agent Support System",
    version="0.1.0",
    description="Multi-agent customer support and knowledge orchestration service for Getnet Merchants.",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Return service readiness and active Zero-Cost LLM provider mode."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        llm_provider=settings.resolved_llm_provider(),
    )


def _handle_chat_request(request: ChatRequest) -> ChatResponse:
    """Execute the multi-agent orchestration graph and package the structured ChatResponse."""
    started = time.perf_counter()
    final_state = run_orchestration(message=request.message, user_id=request.user_id)
    elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))

    agent_sequence = list(final_state.get("agent_sequence", []))
    handoff_ticket_id = final_state.get("handoff_ticket_id")
    escalated = bool(
        "escalation_agent" in agent_sequence
        or (final_state.get("needs_human_handoff") and handoff_ticket_id is not None)
    )

    metadata = OrchestrationMetadata(
        trace_id=final_state.get("trace_id", "trc-unknown"),
        safety_tier=SafetyTier(final_state.get("safety_tier", SafetyTier.GETNET_DOMAIN.value)),
        primary_intent=PrimaryIntent(
            final_state.get("primary_intent", PrimaryIntent.PRODUCT_KNOWLEDGE.value)
        ),
        agent_sequence=agent_sequence,
        tools_called=list(final_state.get("tools_called", [])),
        rag_sources=list(final_state.get("rag_sources", [])),
        escalated_to_human=escalated,
        handoff_ticket_id=handoff_ticket_id,
        latency_ms=elapsed_ms,
    )

    return ChatResponse(
        user_id=request.user_id,
        message=request.message,
        answer=final_state.get("final_answer", ""),
        orchestration=metadata,
    )


@app.post("/chat", response_model=ChatResponse)
def post_chat(request: ChatRequest) -> ChatResponse:
    """Primary HTTP endpoint for Merchant Inquiries."""
    return _handle_chat_request(request)


@app.post("/api/v1/chat", response_model=ChatResponse)
def post_chat_v1(request: ChatRequest) -> ChatResponse:
    """Versioned alias HTTP endpoint for Merchant Inquiries."""
    return _handle_chat_request(request)
