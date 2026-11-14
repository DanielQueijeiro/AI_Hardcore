"""The orchestration is a model-driven loop inside hard bounds. A scripted model plays the Router and the
Critic so each behaviour (re-planning, quality-based retry, stopping) is asserted exactly."""

from __future__ import annotations

from src.agents.prompts import LOW_CONFIDENCE_FALLBACK
from src.llm.offline import OfflinePolicyLLM
from src.llm.resilient import ResilientLLM
from src.llm.scripted import call
from tests.conftest import approve, chat, delegate, finish, login, revise, scripted


def test_router_replans_from_what_the_specialist_observed(make_client):
    def second_step(kwargs):
        # the telemetry code only exists in the Support Agent's observation, so the plan reacts to it
        assert "OFFLINE_GPRS_TIMEOUT" in kwargs["prompt"]
        return delegate("knowledge", "What does telemetry status OFFLINE_GPRS_TIMEOUT mean and how is it fixed?")

    llm = scripted(
        {
            "supervisor": [
                delegate("support", "Check the card machine connectivity for the merchant."),
                second_step,
                finish("Your terminal is offline (OFFLINE_GPRS_TIMEOUT). Restart it, then connect it to the store Wi-Fi."),
            ],
            "critic": approve(),
        }
    )
    client = make_client(llm)
    out = chat(client, "My card machine won't connect", login(client))
    assert out["orchestration"]["agents"] == ["router", "support", "router", "knowledge", "router", "critic"]
    assert out["orchestration"]["tools_called"] == ["get_pos_diagnostics", "search_getnet_knowledge"]
    assert out["orchestration"]["plan_steps"] == 3
    assert "OFFLINE_GPRS_TIMEOUT" in out["answer"]


def test_critic_rejection_sends_the_router_back_for_more_evidence(make_client):
    prompts: list[str] = []

    def after_rejection(kwargs):
        prompts.append(kwargs["prompt"])
        return delegate("knowledge", "What is the monthly rental of the Get Smart?")

    llm = scripted(
        {
            "supervisor": [
                finish("The Get Smart rental is R$ 999.00 per month."),
                after_rejection,
                finish("The Get Smart rental is R$ 129.90 per month when the minimum sales volume is not reached."),
            ],
            "critic": [revise("R$ 999.00 is not supported by any observation.", research="Get Smart monthly rental"), approve()],
        }
    )
    client = make_client(llm)
    out = chat(client, "How much is the Get Smart rental?", login(client))
    assert "129.90" in out["answer"] and "999" not in out["answer"]
    assert out["orchestration"]["critic_rounds"] == 2
    assert "R$ 999.00 is not supported" in prompts[0] and "Research needed" in prompts[0]
    assert out["orchestration"]["tools_called"] == ["search_getnet_knowledge"]


def test_answer_that_stays_ungrounded_is_never_sent(make_client, settings):
    llm = scripted({"supervisor": finish("The Pix fee is 7.77% per sale."), "critic": revise("7.77% is not in the evidence.")})
    client = make_client(llm)
    out = chat(client, "What is the Pix fee?", login(client))
    assert out["answer"] == LOW_CONFIDENCE_FALLBACK
    assert llm.count["supervisor"] == 1 + settings.max_critic_rounds
    assert llm.count["critic"] == 1 + settings.max_critic_rounds


def test_step_budget_stops_a_router_that_never_finishes(make_client, settings):
    counter = {"n": 0}

    def never_satisfied(kwargs):
        if kwargs["tool_choice"] == "finish":
            return finish("This is the best answer I can give.")
        counter["n"] += 1
        return delegate("knowledge", f"another angle on Pix number {counter['n']}")

    llm = scripted({"supervisor": never_satisfied, "critic": approve()})
    client = make_client(llm)
    out = chat(client, "Tell me about Pix", login(client))
    assert out["status"] == "completed"
    assert counter["n"] == settings.max_supervisor_steps
    assert llm.count["supervisor"] == settings.max_supervisor_steps + 1


def test_identical_delegation_is_refused_instead_of_repeated(make_client):
    def third_step(kwargs):
        assert "Refused: you already delegated this exact task" in kwargs["prompt"]
        return finish("Getnet accepts Pix by QR Code on the card machine.")

    llm = scripted(
        {"supervisor": [delegate("knowledge", "ways to accept Pix"), delegate("knowledge", "ways to accept Pix"), third_step], "critic": approve()}
    )
    client = make_client(llm)
    out = chat(client, "How can I accept Pix?", login(client))
    assert out["orchestration"]["agents"].count("knowledge") == 1


def test_citation_a_tool_never_returned_is_dropped_and_blocked(make_client):
    real, fake = "https://site.getnet.com.br/crediario/", "https://made-up.example/crediario"
    llm = scripted(
        {
            "supervisor": [
                delegate("knowledge", "crediário installment limit"),
                finish(f"Up to 48 installments. Sources: {fake}"),
                finish(f"Up to 48 installments. Sources: {real}"),
            ],
            "knowledge": [
                call("search_getnet_knowledge", query="crediário installment limit"),
                call("report", answer="Up to 48 installments.", sources=[real, fake], confidence="high", gaps=""),
            ],
            "critic": approve(),  # even a lenient critic cannot wave a fabricated URL through
        }
    )
    client = make_client(llm)
    out = chat(client, "How many installments with crediário?", login(client))
    assert out["orchestration"]["sources"] == [real]
    assert fake not in out["answer"] and real in out["answer"]
    assert out["orchestration"]["critic_rounds"] == 2


def test_specialist_reconsiders_after_a_poor_search(client):
    out = chat(client, "What is the Getnet policy on interplanetary teleportation insurance?", login(client))
    assert out["orchestration"]["tools_called"] == ["search_getnet_knowledge", "search_getnet_knowledge"]
    assert "does not cover" in out["answer"]


def test_compound_question_uses_both_specialists(client):
    out = chat(client, "When will yesterday's sales be deposited, and what is the monthly rental of the Get Smart?", login(client))
    assert {"support", "knowledge"} <= set(out["orchestration"]["agents"])
    assert "850" in out["answer"] and "129.90" in out["answer"]


def test_provider_outage_degrades_to_the_offline_policy_and_opens_the_breaker(make_client):
    class Down:
        name, model = "openai", "unreachable"

        def complete(self, **_):
            raise TimeoutError("provider down")

    llm = ResilientLLM(Down(), OfflinePolicyLLM(), failure_threshold=2, cooldown_seconds=60)
    client = make_client(llm)
    out = chat(client, "How many installments can I split a sale into with the crediário?", login(client))
    assert out["status"] == "completed" and "48" in out["answer"]
    assert out["orchestration"]["degraded"] is True
    assert llm.breaker_open
    assert client.get("/ready").json()["checks"]["llm_circuit_open"] is True


def test_every_turn_leaves_a_full_trace(client):
    headers = login(client)
    out = chat(client, "My card machine won't connect to the internet, what should I do?", headers)
    trace = client.get(f"/traces/{out['orchestration']['trace_id']}", headers=headers).json()
    kinds = {event["kind"] for event in trace["events"]}
    assert {"guardrail_input", "llm", "decision", "tool", "review", "guardrail_output"} <= kinds
    decisions = [e for e in trace["events"] if e["kind"] == "decision"]
    assert decisions[0]["remaining_plan"], "the router records its plan with every delegation"
    assert trace["usage"]["llm_calls"] == len([e for e in trace["events"] if e["kind"] == "llm"])


def test_draft_in_the_wrong_language_is_sent_back_even_by_a_lenient_critic(make_client):
    prompts: list[str] = []

    def second_try(kwargs):
        prompts.append(kwargs["prompt"])
        return finish("With the crediário you can split the sale into up to 48 installments.")

    llm = scripted(
        {
            "supervisor": [
                delegate("knowledge", "crediário installment limit"),
                finish("Com o crediário, você pode dividir a venda em até 48 parcelas para o seu cliente."),
                second_try,
            ],
            "critic": approve(),
        }
    )
    client = make_client(llm)
    out = chat(client, "How many installments can I split a sale into with the crediário?", login(client))
    assert out["answer"].startswith("With the crediário")
    assert out["orchestration"]["critic_rounds"] == 2
    assert "Reply language: English" in prompts[0] and "Rewrite the whole answer in English" in prompts[0]


def test_a_tool_without_parameters_is_offered_once_and_a_repeat_forces_the_report(make_client):
    offered: list[list[str]] = []

    def support(kwargs):
        offered.append([t["name"] for t in kwargs["tools"]])
        if kwargs["tool_choice"] == "report":
            return call("report", findings="Terminal offline.", follow_up_for_knowledge="", needs_human_approval=False, proposed_action="none")
        return call("get_pos_diagnostics")

    llm = scripted({"supervisor": [delegate("support", "check the terminal"), finish("Your terminal is offline.")], "support": support, "critic": approve()})
    client = make_client(llm)
    out = chat(client, "Is my card machine online?", login(client))
    assert "get_pos_diagnostics" in offered[0] and "get_pos_diagnostics" not in offered[1]
    assert offered[2] == ["report"], "after a repeated call only the report is left"
    assert out["orchestration"]["tools_called"].count("get_pos_diagnostics") == 2  # one executed, one refused
    trace = client.get(f"/traces/{out['orchestration']['trace_id']}", headers=login(client)).json()
    assert len(trace["observations"][0]["evidence"]) == 1


def test_forced_finish_without_answer_falls_back_to_low_confidence_and_counts_metric(make_client, settings):
    counter = {"n": 0}

    def always_delegate(kwargs):
        counter["n"] += 1
        return delegate("knowledge", f"another angle on Pix number {counter['n']}")

    llm = scripted({"supervisor": always_delegate, "critic": approve()})
    client = make_client(llm)
    out = chat(client, "Tell me about Pix", login(client))
    assert out["answer"] == LOW_CONFIDENCE_FALLBACK
    assert counter["n"] == settings.max_supervisor_steps + 1
    assert "low_confidence_fallbacks_total 1" in client.get("/metrics").text
