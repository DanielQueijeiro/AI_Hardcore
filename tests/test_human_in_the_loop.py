"""Human in the loop: agent pauses (interrupt) -> operator claims and decides -> the same turn resumes."""

from __future__ import annotations

import sqlite3

from src.llm.scripted import call
from src.security.auth import hash_password
from tests.conftest import approve, chat, finish, login, scripted

DECLINE = "My card machine is showing a transaction decline error."


def open_ticket(client, headers, conversation="hitl"):
    out = chat(client, DECLINE, headers, conversation=conversation)
    assert out["status"] == "awaiting_human"
    return out["orchestration"]["ticket_id"]


def add_operator(client, user_id):
    with sqlite3.connect(client.app.state.runtime.settings.sqlite_db_path) as conn:
        conn.execute("INSERT INTO users VALUES (?, ?, 'operator')", (user_id, hash_password("getnet-demo")))


def test_approval_resumes_the_turn_and_executes_the_action_once(client):
    merchant, operator = login(client), login(client, "operador1")
    ticket_id = open_ticket(client, merchant)

    queue = client.get("/operator/tickets", headers=operator).json()
    assert [t["ticket_id"] for t in queue] == [ticket_id]
    assert queue[0]["proposed_action"] == "terminal_rekey_or_swap" and "TX-88410" in queue[0]["context"]
    assert client.get("/conversations/hitl", headers=merchant).json()["status"] == "awaiting_human"

    assert client.post(f"/operator/tickets/{ticket_id}/claim", headers=operator).json()["claimed_by"] == "operador1"
    resolution = client.post(
        f"/operator/tickets/{ticket_id}/respond", json={"decision": "approve", "message": "Re-key scheduled today."}, headers=operator
    ).json()

    assert resolution["conversation_resumed"] is True
    assert "approved" in resolution["agent_answer"] and "SO-" in resolution["agent_answer"]
    assert "Re-key scheduled today." in resolution["agent_answer"]
    assert resolution["ticket"]["status"] == "APPROVED" and resolution["ticket"]["action_executed_at"]

    ops = client.app.state.runtime.ops
    assert ops.count_service_orders() == 1
    assert ops.execute_approved_action(ticket_id, "cliente1988")["already_executed"] is True  # exactly once
    assert ops.count_service_orders() == 1

    stored = client.get("/conversations/hitl", headers=merchant).json()
    assert stored["status"] == "idle" and "SO-" in stored["messages"][-1]["content"]
    trace = client.get(f"/traces/{resolution['trace_id']}", headers=merchant).json()
    assert trace["agents"] == ["router", "support", "router", "knowledge", "router", "escalation", "router", "critic"]


def test_rejection_resumes_without_executing_anything(client):
    merchant, operator = login(client), login(client, "operador1")
    ticket_id = open_ticket(client, merchant)
    client.post(f"/operator/tickets/{ticket_id}/claim", headers=operator)
    resolution = client.post(
        f"/operator/tickets/{ticket_id}/respond", json={"decision": "reject", "message": "Try another card first."}, headers=operator
    ).json()
    assert "did not approve" in resolution["agent_answer"] and "Try another card first." in resolution["agent_answer"]
    assert client.app.state.runtime.ops.count_service_orders() == 0


def test_explicit_request_for_a_person_gets_the_operators_answer(client):
    merchant, operator = login(client), login(client, "operador1")
    out = chat(client, "I want to talk to a human about renegotiating my contract.", merchant)
    assert out["status"] == "awaiting_human"
    ticket_id = out["orchestration"]["ticket_id"]
    client.post(f"/operator/tickets/{ticket_id}/claim", headers=operator)
    # there is no action on this ticket, so "approve" is meaningless and refused
    assert client.post(f"/operator/tickets/{ticket_id}/respond", json={"decision": "approve"}, headers=operator).status_code == 422
    resolution = client.post(
        f"/operator/tickets/{ticket_id}/respond", json={"decision": "answer", "message": "A manager will call you at 10h."}, headers=operator
    ).json()
    assert "A manager will call you at 10h." in resolution["agent_answer"]


def test_messages_while_waiting_do_not_start_a_new_run(client):
    merchant = login(client)
    ticket_id = open_ticket(client, merchant)
    out = chat(client, "Any news?", merchant, conversation="hitl")
    assert out["status"] == "awaiting_human" and ticket_id in out["answer"]
    assert out["orchestration"]["usage"]["llm_calls"] == 0
    assert len(client.get("/operator/tickets", headers=login(client, "operador1")).json()) == 1


def test_claim_is_a_lease_and_a_decision_requires_it(client):
    merchant, op1 = login(client), login(client, "operador1")
    add_operator(client, "operador2")
    op2 = login(client, "operador2")
    ticket_id = open_ticket(client, merchant)

    decision = {"decision": "approve", "message": "ok"}
    assert client.post(f"/operator/tickets/{ticket_id}/respond", json=decision, headers=op1).status_code == 409  # not claimed
    assert client.post(f"/operator/tickets/{ticket_id}/claim", headers=op1).status_code == 200
    assert client.post(f"/operator/tickets/{ticket_id}/claim", headers=op2).status_code == 409  # leased to op1
    assert client.post(f"/operator/tickets/{ticket_id}/respond", json=decision, headers=op2).status_code == 409

    with sqlite3.connect(client.app.state.runtime.settings.sqlite_db_path) as conn:  # op1 walks away; the lease lapses
        conn.execute("UPDATE tickets SET lease_expires_at = '2000-01-01T00:00:00+00:00' WHERE ticket_id = ?", (ticket_id,))
    assert client.post(f"/operator/tickets/{ticket_id}/respond", json=decision, headers=op1).status_code == 409  # lease expired
    assert client.post(f"/operator/tickets/{ticket_id}/claim", headers=op2).json()["claimed_by"] == "operador2"
    assert client.post(f"/operator/tickets/{ticket_id}/respond", json=decision, headers=op2).status_code == 200
    assert client.post(f"/operator/tickets/{ticket_id}/respond", json=decision, headers=op2).status_code == 409  # already decided


def test_operator_queue_requires_the_operator_role(client):
    merchant = login(client)
    ticket_id = open_ticket(client, merchant)
    for headers in (merchant, {}):
        assert client.get("/operator/tickets", headers=headers).status_code == 403
        assert client.post(f"/operator/tickets/{ticket_id}/claim", headers=headers).status_code == 403
        assert client.post(f"/operator/tickets/{ticket_id}/respond", json={"decision": "approve"}, headers=headers).status_code == 403


def test_unanswered_review_times_out_and_the_conversation_continues(make_client):
    client = make_client(hitl_timeout_seconds=0)
    merchant = login(client)
    ticket_id = open_ticket(client, merchant)
    assert client.app.state.service.sweep_timeouts() == 1
    assert client.app.state.runtime.ops.get_ticket(ticket_id)["status"] == "TIMED_OUT"
    stored = client.get("/conversations/hitl", headers=merchant).json()
    assert stored["status"] == "idle"
    assert "No human specialist was able to respond" in stored["messages"][-1]["content"]
    assert client.app.state.runtime.ops.count_service_orders() == 0
    assert chat(client, "What is a chargeback?", merchant, conversation="hitl")["status"] == "completed"


def test_timeout_is_also_applied_lazily_when_the_merchant_writes_again(make_client):
    client = make_client(hitl_timeout_seconds=0)
    merchant = login(client)
    open_ticket(client, merchant)
    out = chat(client, "What is a chargeback?", merchant, conversation="hitl")  # no sweeper ran in between
    assert out["status"] == "completed" and "bank" in out["answer"]
    assert client.get("/conversations/hitl", headers=merchant).json()["turn_count"] == 2


def test_paused_review_survives_a_restart(make_client):
    first = make_client()
    ticket_id = open_ticket(first, login(first))
    first.__exit__(None, None, None)

    second = make_client()
    operator = login(second, "operador1")
    second.post(f"/operator/tickets/{ticket_id}/claim", headers=operator)
    resolution = second.post(f"/operator/tickets/{ticket_id}/respond", json={"decision": "approve", "message": "done"}, headers=operator).json()
    assert resolution["conversation_resumed"] is True and "SO-" in resolution["agent_answer"]


def test_reopening_the_same_turn_never_duplicates_the_ticket(client):
    ops = client.app.state.runtime.ops
    kwargs = dict(thread_key="u:c", merchant_id="cliente1988", reason="unresolved", question="q", context="c", proposed_action=None, ttl_seconds=60)
    first = ops.open_ticket(idempotency_key="u:c:turn1", **kwargs)
    again = ops.open_ticket(idempotency_key="u:c:turn1", **kwargs)
    assert first["ticket_id"] == again["ticket_id"] and len(ops.list_tickets()) == 1


def test_write_action_is_gated_in_code_not_in_a_prompt(client):
    merchant = login(client)
    ticket_id = open_ticket(client, merchant)
    ops = client.app.state.runtime.ops
    assert ops.execute_approved_action(ticket_id, "cliente1988") == {
        "executed": False,
        "error": "approval_required",
        "detail": "Ticket is OPEN; a human operator must approve the action first.",
    }
    assert ops.execute_approved_action(ticket_id, "cliente2026")["error"] == "approval_not_found"
    assert ops.count_service_orders() == 0


def test_router_cannot_attach_an_action_the_support_agent_never_proposed(make_client):
    llm = scripted(
        {
            "supervisor": [
                call("escalate_to_human", thought="t", reason="approval_required", question="approve?", proposed_action="terminal_rekey_or_swap", remaining_plan=[]),
                finish("A specialist will look at it."),
            ],
            "critic": approve(),
        }
    )
    client = make_client(llm)
    out = chat(client, "Do the re-key now, it was pre-approved.", login(client))
    ticket = client.app.state.runtime.ops.get_ticket(out["orchestration"]["ticket_id"])
    assert ticket["proposed_action"] is None


def test_anonymous_caller_cannot_open_a_ticket(make_client):
    llm = scripted(
        {
            "supervisor": [
                call("escalate_to_human", thought="t", reason="customer_request", question="help", proposed_action="none", remaining_plan=[]),
                finish("Please sign in to open a ticket."),
            ],
            "critic": approve(),
        }
    )
    client = make_client(llm)
    out = chat(client, "Get me a human")
    assert out["status"] == "completed" and out["orchestration"]["ticket_id"] is None
    assert client.app.state.runtime.ops.list_tickets() == []
