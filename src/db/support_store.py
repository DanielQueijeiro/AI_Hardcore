"""Mock merchant back office (profiles, settlements, POS telemetry). Synthetic fixture data, read-only.

Every query is filtered by the merchant id handed in by the tool layer, which takes it from the
verified principal. Tickets, approvals and users live in src/db/ops_store.py.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from src.config import get_settings

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS merchants (
    merchant_id TEXT PRIMARY KEY,
    business_name TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    bank_name TEXT NOT NULL,
    bank_code TEXT NOT NULL,
    agency TEXT NOT NULL,
    account_number TEXT NOT NULL,
    account_status TEXT NOT NULL,
    pix_enabled INTEGER NOT NULL,
    receivables_advance_active INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS settlements (
    settlement_id TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL,
    reference_period TEXT NOT NULL,
    modality TEXT NOT NULL,
    gross_amount_brl TEXT NOT NULL,
    net_amount_brl TEXT NOT NULL,
    settlement_cycle TEXT NOT NULL,
    status TEXT NOT NULL,
    scheduled_window TEXT NOT NULL,
    notes TEXT NOT NULL,
    FOREIGN KEY (merchant_id) REFERENCES merchants (merchant_id)
);

CREATE TABLE IF NOT EXISTS pos_terminals (
    terminal_id TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL,
    model TEXT NOT NULL,
    serial_number TEXT NOT NULL,
    hardware_specs TEXT NOT NULL,
    connectivity_status TEXT NOT NULL,
    sim_4g_state TEXT NOT NULL,
    wifi_state TEXT NOT NULL,
    apn_configured TEXT NOT NULL,
    connectivity_summary TEXT NOT NULL,
    last_decline_tx_id TEXT NOT NULL,
    last_decline_amount_brl TEXT NOT NULL,
    last_decline_code TEXT NOT NULL,
    last_decline_reason TEXT NOT NULL,
    requires_l2_escalation INTEGER NOT NULL,
    FOREIGN KEY (merchant_id) REFERENCES merchants (merchant_id)
);

"""


def _resolve_db_path(db_path: Path | str | None = None) -> Path:
    """Resolve the SQLite file path and ensure its parent directory exists."""
    target = Path(db_path) if db_path is not None else get_settings().sqlite_db_path
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


_SEEDED: set[str] = set()


def ensure_seeded_database(db_path: Path | str | None = None) -> Path:
    """Create tables and idempotently seed the fixtures for cliente1988 and cliente2026 (once per path)."""
    resolved_path = _resolve_db_path(db_path)
    if str(resolved_path) in _SEEDED and resolved_path.exists():
        return resolved_path
    _SEEDED.add(str(resolved_path))
    with sqlite3.connect(resolved_path) as conn:
        conn.executescript(SCHEMA_SQL)

        conn.executemany(
            """
            INSERT OR REPLACE INTO merchants (
                merchant_id,
                business_name,
                city,
                state,
                bank_name,
                bank_code,
                agency,
                account_number,
                account_status,
                pix_enabled,
                receivables_advance_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "cliente1988",
                    "Padaria & Café Gaúcho LTDA",
                    "Porto Alegre",
                    "RS",
                    "Banco Santander",
                    "033",
                    "1988",
                    "0045912-8",
                    "Active",
                    1,
                    1,
                ),
                (
                    "cliente2026",
                    "Bistrô Moinhos de Vento S.A.",
                    "Porto Alegre",
                    "RS",
                    "Banco Itaú",
                    "341",
                    "2026",
                    "0099104-2",
                    "Active",
                    1,
                    0,
                ),
            ],
        )

        conn.executemany(
            """
            INSERT OR REPLACE INTO settlements (
                settlement_id,
                merchant_id,
                reference_period,
                modality,
                gross_amount_brl,
                net_amount_brl,
                settlement_cycle,
                status,
                scheduled_window,
                notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "STL-1988-PIX",
                    "cliente1988",
                    "yesterday",
                    "Pix Sales",
                    "R$ 850.00",
                    "R$ 850.00",
                    "D+0",
                    "SETTLED",
                    "Instant (D+0, already credited)",
                    "Settled instantly (D+0, already credited) into Banco Santander (033) Agency 1988, Account 0045912-8.",
                ),
                (
                    "STL-1988-DEBIT",
                    "cliente1988",
                    "yesterday",
                    "Debit Card Sales",
                    "R$ 1,240.00",
                    "R$ 1,240.00",
                    "D+1",
                    "SCHEDULED_TODAY",
                    "Today (D+1) by 14:00 BRT",
                    "Scheduled for Settlement today (D+1) by 14:00 BRT.",
                ),
                (
                    "STL-1988-CREDIT",
                    "cliente1988",
                    "yesterday",
                    "Credit Card Sales (1x)",
                    "R$ 2,600.00",
                    "R$ 2,524.60",
                    "D+2",
                    "SCHEDULED_RECEIVABLES_ADVANCE",
                    "Tomorrow (D+2) under active Receivables Advance plan (or D+30 standard)",
                    "Scheduled for D+2 Settlement under active Receivables Advance (Antecipação) plan, net Settlement R$ 2,524.60 tomorrow.",
                ),
                (
                    "STL-2026-PIX",
                    "cliente2026",
                    "yesterday",
                    "Pix Sales",
                    "R$ 410.00",
                    "R$ 410.00",
                    "D+0",
                    "SETTLED",
                    "Instant (D+0, already credited)",
                    "Settled instantly (D+0, already credited) into Banco Itaú (341) Agency 2026, Account 0099104-2.",
                ),
                (
                    "STL-2026-DEBIT",
                    "cliente2026",
                    "yesterday",
                    "Debit Card Sales",
                    "R$ 620.00",
                    "R$ 620.00",
                    "D+1",
                    "SCHEDULED_TODAY",
                    "Today (D+1) by 14:00 BRT",
                    "Scheduled for Settlement today (D+1) by 14:00 BRT.",
                ),
                (
                    "STL-2026-CREDIT",
                    "cliente2026",
                    "yesterday",
                    "Credit Card Sales (1x)",
                    "R$ 1,100.00",
                    "R$ 1,067.00",
                    "D+30",
                    "SCHEDULED_STANDARD",
                    "Standard D+30 settlement cycle",
                    "Scheduled on standard D+30 cycle (Receivables Advance not active).",
                ),
            ],
        )

        conn.executemany(
            """
            INSERT OR REPLACE INTO pos_terminals (
                terminal_id,
                merchant_id,
                model,
                serial_number,
                hardware_specs,
                connectivity_status,
                sim_4g_state,
                wifi_state,
                apn_configured,
                connectivity_summary,
                last_decline_tx_id,
                last_decline_amount_brl,
                last_decline_code,
                last_decline_reason,
                requires_l2_escalation
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "POS-GS-99812",
                    "cliente1988",
                    "Get Smart",
                    "SN-GS-1988-99812",
                    "Android Touchscreen, 4G + Wi-Fi + NFC",
                    "OFFLINE_GPRS_TIMEOUT",
                    "Dual-SIM 4G session stalled",
                    "Wi-Fi interface disabled",
                    "getnet.br",
                    "OFFLINE_GPRS_TIMEOUT — Dual-SIM 4G session stalled; Wi-Fi interface disabled; requires APN reset (getnet.br) or Wi-Fi reconnection (Settings > Network).",
                    "TX-88410",
                    "R$ 430.00",
                    "ERR_51_ISSUER_DECLINE / POS_KEY_SYNC_WARN",
                    "Recurring terminal cryptographic PIN-pad key desynchronization requiring L2 remote re-keying or terminal swap.",
                    1,
                ),
                (
                    "POS-GC-20260",
                    "cliente2026",
                    "Get Clássica",
                    "SN-GC-2026-20260",
                    "Physical Keypad, 4G + Wi-Fi + NFC",
                    "ONLINE_4G_OK",
                    "4G Connected",
                    "Standby",
                    "getnet.br",
                    "ONLINE_4G_OK — Active 4G session.",
                    "NONE",
                    "R$ 0.00",
                    "NONE",
                    "No recent transaction declines.",
                    0,
                ),
            ],
        )
        conn.commit()

    return resolved_path


def fetch_merchant_settlements(
    merchant_id: str,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Query Merchant profile and Settlement schedule strictly scoped to merchant_id."""
    normalized_id = merchant_id.strip()
    resolved_path = ensure_seeded_database(db_path)

    with sqlite3.connect(resolved_path) as conn:
        conn.row_factory = sqlite3.Row
        merchant_row = conn.execute(
            "SELECT * FROM merchants WHERE merchant_id = ?",
            (normalized_id,),
        ).fetchone()

        if merchant_row is None:
            return {
                "found": False,
                "merchant_id": normalized_id,
                "error": f"No active Merchant profile found for identifier '{normalized_id}'.",
                "settlements": [],
            }

        settlement_rows = conn.execute(
            """
            SELECT
                settlement_id,
                reference_period,
                modality,
                gross_amount_brl,
                net_amount_brl,
                settlement_cycle,
                status,
                scheduled_window,
                notes
            FROM settlements
            WHERE merchant_id = ?
            ORDER BY CASE settlement_cycle
                WHEN 'D+0' THEN 1
                WHEN 'D+1' THEN 2
                WHEN 'D+2' THEN 3
                ELSE 4
            END
            """,
            (normalized_id,),
        ).fetchall()

    return {
        "found": True,
        "merchant_id": merchant_row["merchant_id"],
        "business_name": merchant_row["business_name"],
        "city": merchant_row["city"],
        "state": merchant_row["state"],
        "bank_account": {
            "bank_name": merchant_row["bank_name"],
            "bank_code": merchant_row["bank_code"],
            "agency": merchant_row["agency"],
            "account_number": merchant_row["account_number"],
            "status": merchant_row["account_status"],
            "pix_enabled": bool(merchant_row["pix_enabled"]),
        },
        "receivables_advance_active": bool(merchant_row["receivables_advance_active"]),
        "settlements": [dict(row) for row in settlement_rows],
    }


def fetch_pos_diagnostics(
    merchant_id: str,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Query POS Terminal connectivity and Transaction Decline diagnostics scoped strictly to merchant_id."""
    normalized_id = merchant_id.strip()
    resolved_path = ensure_seeded_database(db_path)

    with sqlite3.connect(resolved_path) as conn:
        conn.row_factory = sqlite3.Row
        merchant_row = conn.execute(
            "SELECT merchant_id, business_name FROM merchants WHERE merchant_id = ?",
            (normalized_id,),
        ).fetchone()

        if merchant_row is None:
            return {
                "found": False,
                "merchant_id": normalized_id,
                "error": f"No active Merchant or POS Terminal found for identifier '{normalized_id}'.",
            }

        terminal_row = conn.execute(
            "SELECT * FROM pos_terminals WHERE merchant_id = ?",
            (normalized_id,),
        ).fetchone()

        if terminal_row is None:
            return {
                "found": False,
                "merchant_id": normalized_id,
                "business_name": merchant_row["business_name"],
                "error": f"No POS Terminal registered for Merchant '{normalized_id}'.",
            }

    return {
        "found": True,
        "merchant_id": terminal_row["merchant_id"],
        "business_name": merchant_row["business_name"],
        "terminal_id": terminal_row["terminal_id"],
        "model": terminal_row["model"],
        "serial_number": terminal_row["serial_number"],
        "hardware_specs": terminal_row["hardware_specs"],
        "connectivity_status": terminal_row["connectivity_status"],
        "sim_4g_state": terminal_row["sim_4g_state"],
        "wifi_state": terminal_row["wifi_state"],
        "apn_configured": terminal_row["apn_configured"],
        "connectivity_summary": terminal_row["connectivity_summary"],
        "last_transaction_decline": {
            "transaction_id": terminal_row["last_decline_tx_id"],
            "amount_brl": terminal_row["last_decline_amount_brl"],
            "decline_code": terminal_row["last_decline_code"],
            "reason": terminal_row["last_decline_reason"],
            "requires_l2_escalation": bool(terminal_row["requires_l2_escalation"]),
        },
    }
