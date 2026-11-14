"""Operational state: users, human-review tickets, approved service orders, traces.

Schema changes go through numbered migrations recorded in `schema_migrations`, so an existing
volume is upgraded in place instead of being recreated.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.security.auth import hash_password

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE users (
            user_id TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('merchant', 'operator'))
        );
        CREATE TABLE tickets (
            ticket_id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            thread_key TEXT NOT NULL,
            merchant_id TEXT,
            reason TEXT NOT NULL,
            question TEXT NOT NULL,
            context TEXT NOT NULL,
            proposed_action TEXT,
            status TEXT NOT NULL,
            claimed_by TEXT,
            lease_expires_at TEXT,
            decision TEXT,
            operator_message TEXT,
            resolved_by TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            resolved_at TEXT,
            action_executed_at TEXT
        );
        CREATE INDEX idx_tickets_status ON tickets (status, created_at);
        CREATE INDEX idx_tickets_thread ON tickets (thread_key);
        CREATE TABLE service_orders (
            order_id TEXT PRIMARY KEY,
            ticket_id TEXT NOT NULL UNIQUE REFERENCES tickets (ticket_id),
            merchant_id TEXT NOT NULL,
            action TEXT NOT NULL,
            approved_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """,
    ),
    (
        2,
        """
        CREATE TABLE traces (
            trace_id TEXT PRIMARY KEY,
            thread_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX idx_traces_thread ON traces (thread_key, created_at);
        """,
    ),
    (
        3,
        """
        CREATE TABLE revoked_tokens (
            jti TEXT PRIMARY KEY,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE feedback (
            trace_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            rating INTEGER NOT NULL CHECK (rating IN (0, 1)),
            comment TEXT,
            created_at TEXT NOT NULL
        );
        """,
    ),
]

OPEN_STATUSES = ("OPEN", "CLAIMED")
ALLOWED_ACTIONS = ("terminal_rekey_or_swap",)
# What "executed" means to whoever reads the result, model included: the order exists, the work does not yet.
ORDER_MEANING = "A service order was created and queued for the back office. The work itself has not been performed yet."


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


class OpsStore:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.path = Path(db_path) if db_path is not None else get_settings().sqlite_db_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            if conn.in_transaction:
                conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    # --- migrations ------------------------------------------------------------------------------

    def migrate(self) -> int:
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
            for version, sql in MIGRATIONS:
                if version not in applied:
                    conn.executescript(sql)
                    conn.execute("INSERT INTO schema_migrations VALUES (?, ?)", (version, _iso(_now())))
            return max((v for v, _ in MIGRATIONS), default=0)

    def schema_version(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
            return int(row["v"] or 0)

    # --- users -------------------------------------------------------------------------------------

    def seed_demo_users(self, password: str) -> None:
        """Demo identities so the challenge scenarios can authenticate. Replace with a real IdP in production."""
        with self._connect() as conn:
            for user_id, role in (("cliente1988", "merchant"), ("cliente2026", "merchant"), ("operador1", "operator")):
                if conn.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone() is None:
                    conn.execute("INSERT INTO users VALUES (?, ?, ?)", (user_id, hash_password(password), role))

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    # --- tickets -----------------------------------------------------------------------------------

    def open_ticket(
        self,
        *,
        idempotency_key: str,
        thread_key: str,
        merchant_id: str | None,
        reason: str,
        question: str,
        context: str,
        proposed_action: str | None,
        ttl_seconds: int,
    ) -> dict[str, Any]:
        """Create the ticket once per (thread, turn, step). Re-running the graph node returns the same row."""
        if proposed_action not in ALLOWED_ACTIONS:
            proposed_action = None
        now = _now()
        ticket_id = f"TKT-{now:%y%m%d}-{uuid.uuid4().hex[:6].upper()}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO tickets (ticket_id, idempotency_key, thread_key, merchant_id, reason, question,
                    context, proposed_action, status, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
                """,
                (ticket_id, idempotency_key, thread_key, merchant_id, reason, question, context, proposed_action,
                 _iso(now), _iso(now + timedelta(seconds=ttl_seconds))),
            )
            row = conn.execute("SELECT * FROM tickets WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            return dict(row)

    def get_ticket(self, ticket_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
            return dict(row) if row else None

    def list_tickets(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if status == "open":
                rows = conn.execute("SELECT * FROM tickets WHERE status IN ('OPEN', 'CLAIMED') ORDER BY created_at").fetchall()
            elif status:
                rows = conn.execute("SELECT * FROM tickets WHERE status = ? ORDER BY created_at", (status.upper(),)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM tickets ORDER BY created_at DESC LIMIT 200").fetchall()
            return [dict(r) for r in rows]

    def tickets_for_merchant(self, merchant_id: str, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tickets WHERE merchant_id = ? ORDER BY created_at DESC LIMIT ?", (merchant_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def pending_ticket_for_thread(self, thread_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tickets WHERE thread_key = ? ORDER BY created_at DESC LIMIT 1", (thread_key,)
            ).fetchone()
            return dict(row) if row else None

    def claim_ticket(self, ticket_id: str, operator_id: str, lease_seconds: int) -> dict[str, Any]:
        """Lease the ticket to one operator. Another operator can take it only after the lease lapses."""
        now = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
            if row is None:
                raise KeyError(ticket_id)
            if row["status"] not in OPEN_STATUSES:
                raise PermissionError(f"ticket is {row['status']}")
            lease_live = row["lease_expires_at"] and datetime.fromisoformat(row["lease_expires_at"]) > now
            if row["status"] == "CLAIMED" and lease_live and row["claimed_by"] != operator_id:
                raise PermissionError(f"ticket is leased to {row['claimed_by']} until {row['lease_expires_at']}")
            conn.execute(
                "UPDATE tickets SET status = 'CLAIMED', claimed_by = ?, lease_expires_at = ? WHERE ticket_id = ?",
                (operator_id, _iso(now + timedelta(seconds=lease_seconds)), ticket_id),
            )
        return self.get_ticket(ticket_id)  # type: ignore[return-value]

    def resolve_ticket(self, ticket_id: str, operator_id: str, decision: str, message: str) -> dict[str, Any]:
        if decision not in ("approve", "reject", "answer"):
            raise ValueError("decision must be approve, reject or answer")
        now = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
            if row is None:
                raise KeyError(ticket_id)
            if row["status"] != "CLAIMED" or row["claimed_by"] != operator_id:
                raise PermissionError("claim the ticket before responding")
            if datetime.fromisoformat(row["lease_expires_at"]) <= now:
                raise PermissionError("lease expired; claim the ticket again")
            if decision == "approve" and not row["proposed_action"]:
                raise ValueError("this ticket has no proposed action to approve; use 'answer'")
            status = {"approve": "APPROVED", "reject": "REJECTED", "answer": "ANSWERED"}[decision]
            conn.execute(
                "UPDATE tickets SET status = ?, decision = ?, operator_message = ?, resolved_by = ?, resolved_at = ? WHERE ticket_id = ?",
                (status, decision, message, operator_id, _iso(now), ticket_id),
            )
        return self.get_ticket(ticket_id)  # type: ignore[return-value]

    def expire_ticket_if_due(self, ticket_id: str) -> dict[str, Any] | None:
        """Mark an unanswered ticket TIMED_OUT once its deadline passes. Returns the ticket if it just expired."""
        now = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
            if row is None or row["status"] not in OPEN_STATUSES:
                return None
            if datetime.fromisoformat(row["expires_at"]) > now:
                return None
            if row["status"] == "CLAIMED" and row["lease_expires_at"] and datetime.fromisoformat(row["lease_expires_at"]) > now:
                return None  # an operator is on it: the review window does not close under their hands
            conn.execute(
                "UPDATE tickets SET status = 'TIMED_OUT', decision = 'timeout', resolved_at = ? WHERE ticket_id = ?",
                (_iso(now), ticket_id),
            )
        return self.get_ticket(ticket_id)

    def due_tickets(self) -> list[dict[str, Any]]:
        now = _iso(_now())
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tickets WHERE expires_at <= ? AND (status = 'OPEN' OR "
                "(status = 'CLAIMED' AND (lease_expires_at IS NULL OR lease_expires_at <= ?)))",
                (now, now),
            ).fetchall()
            return [dict(r) for r in rows]

    def recently_resolved_tickets(self, hours: int = 24) -> list[dict[str, Any]]:
        """Tickets decided or timed out lately; the sweeper makes sure each of their conversations was resumed."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tickets WHERE status NOT IN ('OPEN', 'CLAIMED') AND resolved_at >= ?",
                (_iso(_now() - timedelta(hours=hours)),),
            ).fetchall()
            return [dict(r) for r in rows]

    # --- approved write actions ----------------------------------------------------------------------

    def execute_approved_action(self, ticket_id: str, merchant_id: str) -> dict[str, Any]:
        """The only path to a write. Enforced here, in code: the model cannot talk its way past it.

        Requires an APPROVED ticket that belongs to this merchant, carries an allow-listed action,
        and has not been executed before (exactly-once).
        """
        now = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
            if row is None or row["merchant_id"] != merchant_id:
                return {"executed": False, "error": "approval_not_found", "detail": "No approval ticket with that id for this merchant."}
            if row["status"] != "APPROVED":
                return {"executed": False, "error": "approval_required", "detail": f"Ticket is {row['status']}; a human operator must approve the action first."}
            if row["proposed_action"] not in ALLOWED_ACTIONS:
                return {"executed": False, "error": "action_not_allowed"}
            existing = conn.execute("SELECT * FROM service_orders WHERE ticket_id = ?", (ticket_id,)).fetchone()
            if existing is not None:
                return {"executed": True, "already_executed": True, "meaning": ORDER_MEANING, **dict(existing)}
            order_id = f"SO-{uuid.uuid4().hex[:8].upper()}"
            conn.execute(
                "INSERT INTO service_orders VALUES (?, ?, ?, ?, ?, ?)",
                (order_id, ticket_id, merchant_id, row["proposed_action"], row["resolved_by"], _iso(now)),
            )
            conn.execute("UPDATE tickets SET action_executed_at = ? WHERE ticket_id = ?", (_iso(now), ticket_id))
            return {
                "executed": True,
                "order_id": order_id,
                "ticket_id": ticket_id,
                "action": row["proposed_action"],
                "approved_by": row["resolved_by"],
                "meaning": ORDER_MEANING,
            }

    def count_service_orders(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM service_orders").fetchone()["n"])

    # --- traces ---------------------------------------------------------------------------------------

    def save_trace(self, trace_id: str, thread_key: str, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO traces VALUES (?, ?, ?, ?)",
                (trace_id, thread_key, _iso(_now()), json.dumps(payload, ensure_ascii=False, default=str)),
            )

    def prune_traces(self, retention_days: int) -> int:
        """Traces hold merchant messages and account observations, so they are kept for a bounded time."""
        if retention_days <= 0:
            return 0
        with self._connect() as conn:
            return conn.execute(
                "DELETE FROM traces WHERE created_at < ?", (_iso(_now() - timedelta(days=retention_days)),)
            ).rowcount

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM traces WHERE trace_id = ?", (trace_id,)).fetchone()
            return json.loads(row["payload"]) if row else None

    def traces_for_thread(self, thread_key: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM traces WHERE thread_key = ? ORDER BY created_at DESC LIMIT ?", (thread_key, limit)
            ).fetchall()
            return [json.loads(r["payload"]) for r in rows]

    # --- token revocation and feedback -------------------------------------------------------------------

    def revoke_token(self, jti: str, expires_at: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (int(_now().timestamp()),))
            conn.execute("INSERT OR IGNORE INTO revoked_tokens VALUES (?, ?)", (jti, expires_at))

    def is_revoked(self, jti: str) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM revoked_tokens WHERE jti = ?", (jti,)).fetchone() is not None

    def save_feedback(self, trace_id: str, user_id: str, rating: int, comment: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO feedback VALUES (?, ?, ?, ?, ?)",
                (trace_id, user_id, rating, comment, _iso(_now())),
            )

    def feedback_summary(self) -> dict[str, int]:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(rating), 0) AS up FROM feedback").fetchone()
            return {"count": int(row["n"]), "positive": int(row["up"])}

    def ping(self) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1").fetchone() is not None
