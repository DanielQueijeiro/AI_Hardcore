"""Graph state. `history` and `summary` are the conversation memory and persist across turns in the
checkpointer; every other field belongs to the turn in flight and is reset when a new message arrives."""

from __future__ import annotations

import uuid
from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    # --- durable conversation memory ---
    history: list[dict[str, str]]  # [{"role": "user" | "assistant", "content": ...}], most recent last
    summary: str  # rolling summary of turns compacted out of `history`
    turn_count: int

    # --- current turn ---
    turn_id: str
    trace_id: str
    thread_key: str
    principal: dict[str, str | None]
    message: str
    guard: dict[str, Any]
    steps: int  # supervisor decisions taken
    plan: list[str]  # the supervisor's current remaining plan
    next: str
    pending: dict[str, Any]  # arguments of the delegation being executed
    observations: list[dict[str, Any]]  # what specialists and humans reported back
    draft: str
    confidence: str
    critic_rounds: int
    critic_feedback: list[str]
    reviews: list[dict[str, Any]]
    ticket_id: str | None
    interim_message: str
    answer: str
    status: str  # completed | blocked | awaiting_human
    sources: list[str]
    events: list[dict[str, Any]]  # trace spans
    degraded: bool


def new_turn(message: str, principal: dict[str, str | None], thread_key: str) -> dict[str, Any]:
    """Input for one turn: sets the message and clears every per-turn field (memory fields are left alone)."""
    return {
        "turn_id": uuid.uuid4().hex[:12],
        "trace_id": f"trc-{uuid.uuid4().hex[:16]}",
        "thread_key": thread_key,
        "principal": principal,
        "message": message,
        "guard": {},
        "steps": 0,
        "plan": [],
        "next": "",
        "pending": {},
        "observations": [],
        "draft": "",
        "confidence": "",
        "critic_rounds": 0,
        "critic_feedback": [],
        "reviews": [],
        "ticket_id": None,
        "interim_message": "",
        "answer": "",
        "status": "",
        "sources": [],
        "events": [],
        "degraded": False,
    }
