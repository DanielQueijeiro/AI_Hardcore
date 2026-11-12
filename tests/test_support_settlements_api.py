"""Integration tests for Customer Support Agent, Merchant settlements, and support tools at POST /chat."""

from fastapi.testclient import TestClient

from src.api.main import app


def test_scenario_3_merchant_yesterday_sales_settlement_schedule_for_cliente1988() -> None:
    """Scenario S3: Yesterday's sales settlement inquiry for cliente1988 returns exact Pix, Debit, and Credit schedules."""
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "message": "When will the money from yesterday's sales be deposited?",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "cliente1988"

    orch = data["orchestration"]
    assert orch["safety_tier"] == "GETNET_DOMAIN"
    assert orch["primary_intent"] == "CUSTOMER_SUPPORT"
    assert orch["agent_sequence"] == ["router_agent", "customer_support_agent"]
    assert orch["tools_called"] == ["get_merchant_profile_and_settlements"]
    assert orch["escalated_to_human"] is False

    answer = data["answer"]
    assert "Padaria & Café Gaúcho LTDA" in answer
    assert "Santander" in answer
    assert "850.00" in answer
    assert "D+0" in answer
    assert "1,240.00" in answer
    assert "D+1" in answer
    assert "14:00" in answer
    assert "2,600.00" in answer
    assert "2,524.60" in answer
    assert "D+2" in answer
    assert "Receivables Advance" in answer


def test_tenant_isolation_returns_only_authenticated_merchant_settlements_for_cliente2026() -> None:
    """Secondary Merchant cliente2026 receives only its own Itaú / D+30 settlement schedule and never cliente1988 data."""
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "message": "When will the money from yesterday's sales be deposited?",
            "user_id": "cliente2026",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "cliente2026"
    assert data["orchestration"]["agent_sequence"] == ["router_agent", "customer_support_agent"]
    assert data["orchestration"]["tools_called"] == ["get_merchant_profile_and_settlements"]

    answer = data["answer"]
    assert "Bistrô Moinhos de Vento S.A." in answer
    assert "Banco Itaú" in answer
    assert "410.00" in answer
    assert "620.00" in answer
    assert "1,100.00" in answer
    assert "D+30" in answer
    # Must never leak cliente1988's private data
    assert "Padaria & Café Gaúcho" not in answer
    assert "Santander" not in answer
    assert "850.00" not in answer
    assert "2,524.60" not in answer


def test_unknown_user_id_receives_graceful_no_active_merchant_message() -> None:
    """Requests from an unknown user_id receive a graceful message rather than raising an unhandled exception."""
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "message": "When will the money from yesterday's sales be deposited?",
            "user_id": "cliente9999",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "cliente9999"
    assert data["orchestration"]["agent_sequence"] == ["router_agent", "customer_support_agent"]
    assert data["orchestration"]["tools_called"] == ["get_merchant_profile_and_settlements"]
    assert "no active" in data["answer"].lower()
    assert "cliente9999" in data["answer"]


def test_all_three_customer_support_tools_enforce_tenant_scoping_and_seed_contracts(tmp_path) -> None:
    """Verify get_merchant_profile_and_settlements, get_pos_terminal_diagnostics, and create_support_ticket_or_escalate."""
    from src.tools.support_tools import (
        create_support_ticket_or_escalate,
        get_merchant_profile_and_settlements,
        get_pos_terminal_diagnostics,
    )

    db_file = tmp_path / "support_test.db"

    # 1. Profile & settlements tool
    s_1988 = get_merchant_profile_and_settlements("cliente1988", db_path=db_file)
    assert s_1988["found"] is True
    assert s_1988["merchant_id"] == "cliente1988"
    assert s_1988["business_name"] == "Padaria & Café Gaúcho LTDA"
    assert len(s_1988["settlements"]) == 3

    # 2. POS terminal diagnostics tool
    diag_1988 = get_pos_terminal_diagnostics("cliente1988", db_path=db_file)
    assert diag_1988["found"] is True
    assert diag_1988["terminal_id"] == "POS-GS-99812"
    assert diag_1988["model"] == "Get Smart"
    assert diag_1988["connectivity_status"] == "OFFLINE_GPRS_TIMEOUT"
    assert diag_1988["last_transaction_decline"]["transaction_id"] == "TX-88410"
    assert (
        diag_1988["last_transaction_decline"]["decline_code"]
        == "ERR_51_ISSUER_DECLINE / POS_KEY_SYNC_WARN"
    )
    assert diag_1988["last_transaction_decline"]["requires_l2_escalation"] is True

    diag_2026 = get_pos_terminal_diagnostics("cliente2026", db_path=db_file)
    assert diag_2026["found"] is True
    assert diag_2026["terminal_id"] == "POS-GC-20260"
    assert diag_2026["model"] == "Get Clássica"
    assert diag_2026["connectivity_status"] == "ONLINE_4G_OK"

    # 3. Support ticket creation & escalation tool
    ticket = create_support_ticket_or_escalate(
        merchant_id="cliente1988",
        issue_summary="Recurring ERR_51_ISSUER_DECLINE / POS_KEY_SYNC_WARN on POS-GS-99812",
        severity="HIGH",
        db_path=db_file,
    )
    assert ticket["created"] is True
    assert ticket["merchant_id"] == "cliente1988"
    assert ticket["terminal_id"] == "POS-GS-99812"
    assert ticket["ticket_id"] == "TKT-1988-001"
    assert ticket["needs_human_handoff"] is True

    unknown_ticket = create_support_ticket_or_escalate(
        merchant_id="unknown_merchant",
        issue_summary="Test issue",
        severity="HIGH",
        db_path=db_file,
    )
    assert unknown_ticket["created"] is False
    assert unknown_ticket["ticket_id"] is None

