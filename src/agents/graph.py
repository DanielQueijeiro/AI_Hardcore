"""Graph wiring.

    guard ──blocked──────────────────────────────────────────────┐
      │                                                           ▼
      └─▶ router ⇄ knowledge | support            critic ──▶ finalize ─▶ END
            │  ▲      (observe → re-plan)            ▲  │
            │  └── escalation ─▶ human_review        │  └─ revise ─▶ router
            │        (interrupt: human decides)      │
            └──────────── finish ────────────────────┘

Only the edges are static. Which specialist runs, in what order, how many times, and when to stop are
chosen by the Router model each step from what it has observed so far.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from src.agents.nodes import Nodes
from src.agents.state import AgentState
from src.runtime import Runtime


def open_checkpointer(path: Path | str) -> SqliteSaver:
    """Durable checkpoints: conversation memory and paused human reviews survive a process restart."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def prune_checkpoints(checkpointer: BaseCheckpointSaver, thread_id: str) -> int:
    """Keep only the latest checkpoint of a thread (its memory); delete the per-step history before it.

    Only for the SQLite saver, whose schema this relies on; with another saver it is a no-op and retention
    belongs to that store. Returns the number of checkpoints removed.
    """
    if not isinstance(checkpointer, SqliteSaver):
        return 0
    with checkpointer.lock:
        conn = checkpointer.conn
        latest = conn.execute(
            "SELECT checkpoint_id FROM checkpoints WHERE thread_id = ? ORDER BY checkpoint_id DESC LIMIT 1", (thread_id,)
        ).fetchone()
        if latest is None:
            return 0
        removed = conn.execute(
            "DELETE FROM checkpoints WHERE thread_id = ? AND checkpoint_id != ?", (thread_id, latest[0])
        ).rowcount
        conn.execute("DELETE FROM writes WHERE thread_id = ? AND checkpoint_id != ?", (thread_id, latest[0]))
        conn.commit()
        return removed


def build_graph(runtime: Runtime, checkpointer: BaseCheckpointSaver) -> Any:
    nodes = Nodes(runtime)
    graph = StateGraph(AgentState)
    graph.add_node("guard", nodes.guard)
    graph.add_node("router", nodes.supervisor)
    graph.add_node("knowledge", nodes.knowledge)
    graph.add_node("support", nodes.support)
    graph.add_node("escalation", nodes.escalation)
    graph.add_node("human_review", nodes.human_review)
    graph.add_node("critic", nodes.critic)
    graph.add_node("finalize", nodes.finalize)

    graph.add_edge(START, "guard")
    graph.add_conditional_edges(
        "guard", lambda s: "finalize" if s["guard"].get("allowed") is False else "router", ["finalize", "router"]
    )
    graph.add_conditional_edges(
        "router",
        lambda s: {"supervisor": "router"}.get(s["next"], s["next"]),
        ["router", "knowledge", "support", "escalation", "critic"],
    )
    graph.add_edge("knowledge", "router")
    graph.add_edge("support", "router")
    graph.add_edge("escalation", "human_review")
    graph.add_edge("human_review", "router")
    graph.add_conditional_edges(
        "critic", lambda s: "router" if s["next"] == "supervisor" else "finalize", ["router", "finalize"]
    )
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
