"""Conversation service: runs turns on a thread, pauses for human review, resumes, and records traces."""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterator
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
# What a streaming client is shown while a turn runs: which agent decided what, which tool ran, the review outcome.
# Model reasoning ("thought"), tool results and token counts stay in the trace, which is access-controlled.
STREAMED_SPANS = frozenset(
    {"guardrail_input", "decision", "tool", "review", "ticket_opened", "human_decision", "guardrail_output", "memory_compacted", "parallel"}
)
STREAMED_FIELDS = frozenset(
    {"node", "kind", "action", "step", "tool", "error", "verdict", "outcome", "ticket_id", "status", "allowed", "category", "round", "branches"}
)
STILL_WAITING ="Your case is still with a human specialist (ticket {ticket_id}). You will get the outcome in this conversation as soon as they respond."


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

    def stream_message(self, principal: Principal, message: str, conversation_id: str | None = None) -> Iterator[dict[str, Any]]:
        """Run a turn and yield progress as it happens: an `accepted` event, one `step` per routing decision, tool
        call, review or human-review event, then `result` (the same result `handle_message` returns) or `error`.

        The turn runs on its own thread and finishes even if the caller stops reading, so a dropped connection never
        leaves a conversation half-written. The conversation id is validated before anything starts.
        """
        _, conversation_id = self.thread_key(principal, conversation_id)
        events: queue.Queue[dict[str, Any] | None] = queue.Queue()

        def work() -> None:
            try:
                events.put({"type": "result", "result": self.handle_message(principal, message, conversation_id, on_event=events.put)})
            except Exception as exc:  # noqa: BLE001 - reported to the stream, not swallowed
                logger.exception("stream_turn_failed", extra={"conversation_id": conversation_id})
                events.put({"type": "error", "detail": type(exc).__name__})
            finally:
                events.put(None)

        events.put({"type": "accepted", "conversation_id": conversation_id})
        threading.Thread(target=work, name="chat-turn-stream", daemon=True).start()

        def drain() -> Iterator[dict[str, Any]]:
            while (item := events.get()) is not None:
                yield item

        return drain()

    def handle_message(
        self,
        principal: Principal,
        message: str,
        conversation_id: str | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
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
            output = self._run(new_turn(message, principal.as_dict(), thread_key), config, on_event)
            return self._result(output, conversation_id, time.perf_counter() - started)

    def _run(self, graph_input: Any, config: dict[str, Any], on_event: Callable[[dict[str, Any]], None] | None) -> dict[str, Any]:
        """Invoke the graph; with `on_event`, stream it node by node and report each new span as it lands."""
        if on_event is None:
            return self.graph.invoke(graph_input, config)
        reported = 0
        for update in self.graph.stream(graph_input, config, stream_mode="updates"):
            for node, values in update.items():
                spans = (values or {}).get("events") if isinstance(values, dict) else None
                if not spans:
                    continue
                for span in spans[reported:]:
                    if span.get("kind") in STREAMED_SPANS:
                        on_event({"type": "step", **{k: v for k, v in span.items() if k in STREAMED_FIELDS}})
                reported = len(spans)
                logger.debug("stream_node", extra={"node": node})
        snapshot = self.graph.get_state(config)
        output = dict(snapshot.values)
        if snapshot.next:
            output["__interrupt__"] = True  # paused on a human review, as `invoke` would report it
        return output

    def resume(self, thread_key: str) -> dict[str, Any] | None:
        """Continue a paused turn after its ticket was resolved or timed out. Idempotent."""
        conversation_id = thread_key.split(":", 1)[1]
        with self._lock(thread_key):
            return self._resume_locked(thread_key, conversation_id)

    def resume_in_background(self, thread_key: str) -> threading.Thread:
        """Resume on a worker thread so the operator's request does not wait for the agents. If it fails, the
        periodic sweep finds the decided ticket and resumes the conversation then."""

        def work() -> None:
            try:
                self.resume(thread_key)
            except Exception:  # noqa: BLE001
                logger.exception("background_resume_failed", extra={"thread_key": thread_key})

        worker = threading.Thread(target=work, name="hitl-resume", daemon=True)
        worker.start()
        return worker

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

    def conversation(
        self, principal: Principal, conversation_id: str | None, wait_seconds: float = 0.0, poll_seconds: float = 0.5
    ) -> dict[str, Any]:
        """The stored conversation. With `wait_seconds`, a conversation that is waiting on a human is watched until
        the decision lands (or the wait runs out), so a client learns the outcome without polling in a tight loop."""
        thread_key, conversation_id = self.thread_key(principal, conversation_id)
        deadline = time.monotonic() + max(0.0, wait_seconds)
        view = self._conversation_view(thread_key, conversation_id)
        while view["status"] in ("awaiting_human", "in_progress") and time.monotonic() < deadline:
            if view["status"] == "awaiting_human":
                time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))
            # a running turn (a resume, say) is waited out on its lock rather than read half-written
            view = self._conversation_view(thread_key, conversation_id, lock_timeout=max(0.0, deadline - time.monotonic()))
        return view

    def _conversation_view(self, thread_key: str, conversation_id: str, lock_timeout: float = 0.0) -> dict[str, Any]:
        """The conversation as stored. While a turn is running on it, its state is between checkpoints: that is
        reported as `in_progress` instead of being read as if it were final."""
        lock = self._lock(thread_key)
        settled = lock.acquire(timeout=lock_timeout) if lock_timeout > 0 else lock.acquire(blocking=False)
        try:
            snapshot = self.graph.get_state(self._config(thread_key))
        finally:
            if settled:
                lock.release()
        values = snapshot.values or {}
        if not settled:
            status = "in_progress"
        else:
            status = "awaiting_human" if snapshot.next else ("idle" if values else "empty")
        return {
            "conversation_id": conversation_id,
            "status": status,
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
