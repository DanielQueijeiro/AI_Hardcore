"""Deterministic Customer Support Agent tools strictly scoped to the authenticated Merchant ID."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.db.support_store import (
    fetch_merchant_settlements,
    fetch_pos_diagnostics,
    persist_support_ticket,
)


VALID_TICKET_SEVERITIES: frozenset[str] = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL", "URGENT"})


def _normalize_merchant_id(merchant_id: str) -> str:
    """Normalize and validate the authenticated Merchant identifier before querying SQLite."""
    normalized = (merchant_id or "").strip()
    if not normalized:
        raise ValueError("merchant_id must be a non-empty Merchant identifier.")
    return normalized


def _normalize_severity(severity: str) -> str:
    """Normalize Support Ticket severity to a canonical uppercase level."""
    candidate = (severity or "HIGH").strip().upper()
    return candidate if candidate in VALID_TICKET_SEVERITIES else "HIGH"


def get_merchant_profile_and_settlements(
    merchant_id: str,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return Merchant profile, registered bank account, Pix status, and recent sales Settlement schedule."""
    normalized_id = _normalize_merchant_id(merchant_id)
    return fetch_merchant_settlements(merchant_id=normalized_id, db_path=db_path)


def get_pos_terminal_diagnostics(
    merchant_id: str,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return leased POS Terminal model, serial number, connectivity telemetry, and recent Transaction Decline codes."""
    normalized_id = _normalize_merchant_id(merchant_id)
    return fetch_pos_diagnostics(merchant_id=normalized_id, db_path=db_path)


def create_support_ticket_or_escalate(
    merchant_id: str,
    issue_summary: str,
    severity: str = "HIGH",
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Persist a Support Ticket in SQLite and flag needs_human_handoff when severity is HIGH or critical."""
    normalized_id = _normalize_merchant_id(merchant_id)
    cleaned_summary = (issue_summary or "").strip() or "POS Terminal diagnostic escalation"
    normalized_severity = _normalize_severity(severity)
    return persist_support_ticket(
        merchant_id=normalized_id,
        issue_summary=cleaned_summary,
        severity=normalized_severity,
        db_path=db_path,
    )
