"""HTTP contracts (Pydantic v2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    role: str


class ChatRequest(BaseModel):
    """The challenge payload, plus an optional conversation id for multi-turn memory."""

    message: str = Field(..., min_length=1, max_length=2000, description="The merchant's message.")
    user_id: str | None = Field(
        None,
        max_length=100,
        description="Kept for the challenge contract. It is a label, not an identity: account access comes only from "
        "the bearer token, and a user_id that disagrees with the token is rejected.",
    )
    conversation_id: str | None = Field(
        None, max_length=64, description="Continue an existing conversation. Omit to use the caller's default thread."
    )


class Usage(BaseModel):
    llm_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class Orchestration(BaseModel):
    trace_id: str
    agents: list[str] = Field(description="Agents in the order they acted, as chosen at run time.")
    tools_called: list[str]
    sources: list[str]
    plan_steps: int = Field(description="Router decisions taken this turn.")
    critic_rounds: int
    guardrail: dict[str, Any]
    escalated_to_human: bool
    ticket_id: str | None = None
    usage: Usage
    latency_ms: int
    llm_provider: str
    degraded: bool = Field(description="True when the model provider failed and the offline policy answered instead.")


class ChatResponse(BaseModel):
    user_id: str | None
    authenticated: bool
    conversation_id: str
    message: str
    answer: str
    status: Literal["completed", "blocked", "awaiting_human"]
    orchestration: Orchestration


class ConversationResponse(BaseModel):
    conversation_id: str
    status: Literal["empty", "idle", "awaiting_human"]
    pending_ticket_id: str | None
    summary: str
    turn_count: int
    messages: list[dict[str, str]]


class TicketResponse(BaseModel):
    ticket_id: str
    status: str
    merchant_id: str | None
    reason: str
    question: str
    context: str
    proposed_action: str | None
    claimed_by: str | None
    lease_expires_at: str | None
    decision: str | None
    operator_message: str | None
    resolved_by: str | None
    created_at: str
    expires_at: str
    resolved_at: str | None
    action_executed_at: str | None


class TicketDecision(BaseModel):
    decision: Literal["approve", "reject", "answer"]
    message: str = Field("", max_length=2000, description="Shown to the agent, which relays it to the merchant.")


class TicketResolution(BaseModel):
    ticket: TicketResponse
    conversation_resumed: bool
    agent_answer: str | None = Field(None, description="What the agent told the merchant after your decision.")
    trace_id: str | None = None


class FeedbackRequest(BaseModel):
    trace_id: str = Field(..., max_length=64)
    rating: Literal[0, 1]
    comment: str | None = Field(None, max_length=1000)


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str
    version: str


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, Any]
