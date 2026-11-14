"""Conversation service: runs turns on a thread, pauses for human review, resumes, and records traces."""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections import defaultdict
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command

from src.agents.graph import build_graph, prune_checkpoints
from src.agents.state import new_turn
from src.db.ops_store import OPEN_STATUSES
from src.runtime import Runtime
from src.security.auth import Principal

logger = logging.getLogger(__name__)

_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ANONYMOUS_CONVERSATION_ID = re.compile(r"^[0-9a-f]{32}$")
RECURSION_LIMIT = 60
STILL_WAITING = "Your case is still with a human specialist (ticket {ticket_id}). You will get the outcome in this conversation as soon as they respond."


class ConversationError(ValueError):
    pass


class ChatService:
    def __init__(self, runtime: Runtime, checkpointer: BaseCheckpointSaver) -> None:
        self.rt = runtime
        self.checkpointer = checkpointer
        self.graph = build_graph(runtime, checkpointer)
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._locks_guard = threading.Lock()

    # --- addressing -------------------------------------------------------------------------------------

    def thread_key(self, principal: Principal, conversation_id: str | None) -> tuple[str, str]:
        """A thread is always namespaced by the verified identity, so a caller cannot address someone else's."""
        if conversation_id is not None and not _CONVERSATION_ID.match(conversation_id):
            raise ConversationError("conversation_id must be 1-64 characters of letters, digits, '-' or '_'")
        if principal.user_id is None:
            # Anonymous callers share one namespace, so the id is the only thing keeping two visitors apart:
            # it has to be an unguessable id this server issued. Anything else gets a fresh conversation.
            if conversation_id is None or not _ANONYMOUS_CONVERSATION_ID.match(conversation_id):
                conversation_id = uuid.uuid4().hex
            return f"anon:{conversation_id}", conversation_id
        conversation_id = conversation_id or "default"
        return f"{principal.user_id}:{conversation_id}", conversation_id

    def _lock(self, thread_key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks[thread_key]

    @staticmethod
    def _config(thread_key: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_key}, "recursion_limit": RECURSION_LIMIT}

    # --- turns ------------------------------------------------------------------------------------------

    def handle_message(self, principal: Principal, message: str, conversation_id: str | None = None) -> dict[str, Any]:
        thread_key, conversation_id = self.thread_key(principal, conversation_id)
        config = self._config(thread_key)
        with self._lock(thread_key):
            started = time.perf_counter()
            snapshot = self.graph.get_state(config)
            if snapshot.next:  # the previous turn is paused on a human review
                ticket_id = snapshot.values.get("ticket_id")
                ticket = self.rt.ops.get_ticket(ticket_id) if ticket_id else None
                if ticket and ticket["status"] in ("OPEN", "CLAIMED") and not self.rt.ops.expire_ticket_if_due(ticket_id):
                    return self._waiting(snapshot.values, conversation_id, ticket_id)
                # decided or timed out while nobody was looking: finish that turn first, then take the new message
                self._resume_locked(thread_key, conversation_id)
                started = time.perf_counter()
            output = self.graph.invoke(new_turn(message, principal.as_dict(), thread_key), config)
            return self._result(output, conversation_id, time.perf_counter() - started)

    def resume(self, thread_key: str) -> dict[str, Any] | None:
        """Continue a paused turn after its ticket was resolved or timed out. Idempotent."""
        conversation_id = thread_key.split(":", 1)[1]
        with self._lock(thread_key):
            return self._resume_locked(thread_key, conversation_id)

    def _resume_locked(self, thread_key: str, conversation_id: str) -> dict[str, Any] | None:
        config = self._config(thread_key)
        snapshot = self.graph.get_state(config)
        if not snapshot.next:
            return None
        started = time.perf_counter()
        ticket_id = snapshot.values.get("ticket_id") or ""
        ticket = self.rt.ops.get_ticket(ticket_id) or {}
        if ticket.get("status") in OPEN_STATUSES:
            # The turn is paused on this ticket and nobody has decided it. Whoever asked for the resume was looking
            # at another ticket of the same conversation (the sweep revisits every recently resolved one).
            if not self.rt.ops.expire_ticket_if_due(ticket_id):
                return None
            ticket = self.rt.ops.get_ticket(ticket_id) or {}
        already_reported = len(snapshot.values.get("events") or [])  # spans the first response already accounted for
        output = self.graph.invoke(Command(resume={"ticket_status": ticket.get("status")}), config)
        return self._result(output, conversation_id, time.perf_counter() - started, resumed=True, since=already_reported)

    def sweep_timeouts(self) -> int:
        """Expire tickets nobody answered and let their conversations continue. Called periodically."""
        resumed = 0
        # A decision that was recorded but whose resume never ran (crash between the two) is picked up here.
        for ticket in self.rt.ops.recently_resolved_tickets():
            try:
                if self.resume(ticket["thread_key"]) is not None:
                    resumed += 1
                    self.rt.metrics.inc("human_review_recovered_resumes_total")
            except Exception:  # noqa: BLE001 - one broken thread must not stop the sweep
                logger.exception("recovery_resume_failed", extra={"ticket_id": ticket["ticket_id"]})
        self.rt.ops.prune_traces(self.rt.settings.trace_retention_days)
        for ticket in self.rt.ops.due_tickets():
            if self.rt.ops.expire_ticket_if_due(ticket["ticket_id"]):
                self.rt.metrics.inc("human_review_timeouts_total")
                try:
                    self.resume(ticket["thread_key"])
                    resumed += 1
                except Exception:  # noqa: BLE001 - one broken thread must not stop the sweep
                    logger.exception("timeout_resume_failed", extra={"ticket_id": ticket["ticket_id"]})
        return resumed

    def conversation(self, principal: Principal, conversation_id: str | None) -> dict[str, Any]:
        thread_key, conversation_id = self.thread_key(principal, conversation_id)
        snapshot = self.graph.get_state(self._config(thread_key))
        values = snapshot.values or {}
        return {
            "conversation_id": conversation_id,
            "status": "awaiting_human" if snapshot.next else ("idle" if values else "empty"),
            "pending_ticket_id": values.get("ticket_id") if snapshot.next else None,
            "summary": values.get("summary", ""),
            "turn_count": values.get("turn_count", 0),
            "messages": values.get("history", []),
        }

    # --- result shaping -----------------------------------------------------------------------------------

    def _waiting(self, values: dict[str, Any], conversation_id: str, ticket_id: str) -> dict[str, Any]:
        return {
            "answer": STILL_WAITING.format(ticket_id=ticket_id),
            "status": "awaiting_human",
            "conversation_id": conversation_id,
            "trace_id": values.get("trace_id", ""),
            "ticket_id": ticket_id,
            "agents": [],
            "tools": [],
            "sources": [],
            "plan_steps": 0,
            "critic_rounds": 0,
            "guard": {"allowed": True, "category": "safe"},
            "usage": {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
            "latency_ms": 0,
            "degraded": False,
            "resumed": False,
        }

    def _usage(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        settings = self.rt.settings
        llm = [e for e in events if e["kind"] == "llm"]
        input_tokens = sum(e["input_tokens"] for e in llm)
        output_tokens = sum(e["output_tokens"] for e in llm)
        cost = (input_tokens * settings.price_input_per_mtok + output_tokens * settings.price_output_per_mtok) / 1e6
        return {"llm_calls": len(llm), "input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": round(cost, 6)}

    def _result(
        self, output: dict[str, Any], conversation_id: str, seconds: float, resumed: bool = False, since: int = 0
    ) -> dict[str, Any]:
        """`since` is how many spans an earlier response of this same turn already reported (a resume after a
        human review): the response's usage covers only the new work, the stored trace covers the whole turn."""
        events = output.get("events") or []
        interrupted = bool(output.get("__interrupt__"))
        agents: list[str] = []
        for event in events:
            if event["node"] not in ("guard", "finalize") and (not agents or agents[-1] != event["node"]):
                agents.append(event["node"])
        result = {
            "answer": output.get("interim_message", "") if interrupted else output.get("answer", ""),
            "status": "awaiting_human" if interrupted else output.get("status", "completed"),
            "conversation_id": conversation_id,
            "trace_id": output.get("trace_id", ""),
            "ticket_id": output.get("ticket_id"),
            "agents": agents,
            "tools": [e["tool"] for e in events if e["kind"] == "tool"],
            "sources": output.get("sources", []),
            "plan_steps": output.get("steps", 0),
            "critic_rounds": len(output.get("reviews") or []),
            "guard": output.get("guard") or {},
            "usage": self._usage(events[since:]),
            "latency_ms": int(seconds * 1000),
            "degraded": bool(output.get("degraded")),
            "resumed": resumed,
        }
        thread_key = output.get("thread_key", "")
        self.rt.ops.save_trace(
            result["trace_id"],
            thread_key,
            {
                **result,
                "usage": self._usage(events),
                "user_id": (output.get("principal") or {}).get("user_id"),
                "message": output.get("message", ""),
                "observations": output.get("observations", []),
                "reviews": output.get("reviews", []),
                "events": events,
                "llm_provider": self.rt.llm.name,
            },
        )
        if not interrupted:
            # A finished turn only needs its final state: drop the per-step checkpoints so the store does not grow
            # with every message. A paused turn keeps everything it needs to resume.
            prune_checkpoints(self.checkpointer, thread_key)
        self.rt.metrics.inc("chat_turns_total", status=result["status"])
        self.rt.metrics.observe_latency(seconds)
        logger.info(
            "chat_turn",
            extra={
                "trace_id": result["trace_id"],
                "thread_key": thread_key,
                "status": result["status"],
                "agents": agents,
                "tools": result["tools"],
                "plan_steps": result["plan_steps"],
                "critic_rounds": result["critic_rounds"],
                "latency_ms": result["latency_ms"],
                "cost_usd": result["usage"]["cost_usd"],
                "degraded": result["degraded"],
            },
        )
        return result
