"""Deterministic Customer Support Agent tools strictly scoped to the authenticated Merchant ID."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.db.support_store import (
    fetch_merchant_settlements,
    fetch_pos_diagnostics,
    persist_support_ticket,
)


def get_merchant_profile_and_settlements(
    merchant_id: str,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return Merchant profile, registered bank account, Pix status, and recent sales Settlement schedule."""
    return fetch_merchant_settlements(merchant_id=merchant_id, db_path=db_path)


def get_pos_terminal_diagnostics(
    merchant_id: str,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return leased POS Terminal model, serial number, connectivity telemetry, and recent Transaction Decline codes."""
    return fetch_pos_diagnostics(merchant_id=merchant_id, db_path=db_path)


def create_support_ticket_or_escalate(
    merchant_id: str,
    issue_summary: str,
    severity: str = "HIGH",
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Persist a Support Ticket in SQLite and flag needs_human_handoff when severity is HIGH or critical."""
    return persist_support_ticket(
        merchant_id=merchant_id,
        issue_summary=issue_summary,
        severity=severity,
        db_path=db_path,
    )
