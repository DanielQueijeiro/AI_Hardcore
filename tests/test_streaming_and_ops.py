"""Streaming turns, background resume with long-poll, operational hardening (rate-limit keys, typed metrics, alert
rules, live-source resilience, argument validation) and the evaluation tooling (provenance, partial runs,
re-grading, adjudication)."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx
import pytest

from eval import run as ev
from src.llm.base import LLMResponse, ToolCall
from src.security.auth import client_ip
from src.tools.live import LiveData
from src.tools.registry import Tool, validate_arguments
from tests.conftest import chat, login

SETTLEMENT_QUESTION = "When will the money from yesterday's sales be deposited?"
DECLINE = "My card machine is showing a transaction decline error."


def sse(response: httpx.Response) -> list[tuple[str, dict]]:
    events = []
    for block in response.text.strip().split("\n\n"):
        name = re.search(r"^event: (.+)$", block, re.M).group(1)
        data = re.search(r"^data: (.+)$", block, re.M).group(1)
        events.append((name, json.loads(data)))
    return events


# --- streaming ----------------------------------------------------------------------------------------


def test_stream_reports_each_step_then_the_same_result_as_chat(client):
    headers = login(client)
    response = client.post("/chat/stream", json={"message": SETTLEMENT_QUESTION, "conversation_id": "s1"}, headers=headers)
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    events = sse(response)

    assert events[0] == ("accepted", {"type": "accepted", "conversation_id": "s1"})
    steps = [data for name, data in events if name == "step"]
    assert {"guardrail_input", "decision", "tool", "review"} <= {s["kind"] for s in steps}
    assert "get_settlements" in [s.get("tool") for s in steps]
    assert all("thought" not in s and "arguments" not in s for s in steps), "reasoning and tool inputs stay in the trace"

    name, result = events[-1]
    assert name == "result" and result["status"] == "completed" and "850.00" in result["answer"]
    reference = chat(client, SETTLEMENT_QUESTION, headers, conversation="s2")
    assert result["answer"] == reference["answer"]
    assert result["orchestration"]["tools_called"] == reference["orchestration"]["tools_called"]
    assert client.get("/conversations/s1", headers=headers).json()["turn_count"] == 1


def test_stream_applies_the_same_admission_checks_as_chat(make_client):
    client = make_client()
    headers = login(client)
    assert client.post("/chat/stream", json={"message": "hi", "conversation_id": "bad id!"}, headers=headers).status_code == 422
    assert client.post("/chat/stream", json={"message": "hi", "user_id": "cliente2026"}, headers=headers).status_code == 403
    strict = make_client(require_chat_auth=True)
    assert strict.post("/chat/stream", json={"message": "hi"}).status_code == 401


def test_stream_shows_the_pause_for_human_review(client):
    response = client.post("/chat/stream", json={"message": DECLINE, "conversation_id": "s3"}, headers=login(client))
    events = sse(response)
    assert any(name == "step" and data["kind"] == "ticket_opened" for name, data in events)
    name, result = events[-1]
    assert name == "result" and result["status"] == "awaiting_human" and result["orchestration"]["ticket_id"]


# --- background resume and long-poll ----------------------------------------------------------------


def test_operator_decision_without_waiting_reaches_the_merchant_through_long_poll(client):
    merchant, operator = login(client), login(client, "operador1")
    ticket_id = chat(client, DECLINE, merchant, conversation="lp")["orchestration"]["ticket_id"]
    client.post(f"/operator/tickets/{ticket_id}/claim", headers=operator)

    started = time.perf_counter()
    response = client.post(
        f"/operator/tickets/{ticket_id}/respond?wait=false", json={"decision": "reject", "message": "Try another card first."}, headers=operator
    )
    assert response.status_code == 202
    body = response.json()
    assert body["resume"] == "scheduled" and body["conversation_resumed"] is False and body["agent_answer"] is None
    assert body["ticket"]["status"] == "REJECTED"

    stored = client.get("/conversations/lp?wait=20", headers=merchant).json()
    assert stored["status"] == "idle", "the long-poll returns as soon as the background resume finishes"
    assert "Try another card first." in stored["messages"][-1]["content"]
    assert time.perf_counter() - started < 20


def test_long_poll_is_capped_and_returns_at_once_when_nothing_is_pending(make_client):
    client = make_client(max_conversation_wait_seconds=0.3)
    merchant = login(client)
    chat(client, SETTLEMENT_QUESTION, merchant, conversation="idle")
    started = time.perf_counter()
    assert client.get("/conversations/idle?wait=30", headers=merchant).json()["status"] == "idle"
    assert time.perf_counter() - started < 1.0

    chat(client, DECLINE, merchant, conversation="waiting")
    started = time.perf_counter()
    assert client.get("/conversations/waiting?wait=30", headers=merchant).json()["status"] == "awaiting_human"
    assert time.perf_counter() - started < 2.0, "the wait is capped by MAX_CONVERSATION_WAIT_SECONDS"


# --- rate-limit identity --------------------------------------------------------------------------------


def test_forwarded_for_is_believed_only_from_a_configured_proxy():
    proxies = frozenset({"10.0.0.2", "10.0.0.3"})
    assert client_ip("203.0.113.9", "1.2.3.4", proxies) == "203.0.113.9", "a direct client cannot pick its own address"
    assert client_ip("10.0.0.2", "198.51.100.7", proxies) == "198.51.100.7"
    assert client_ip("10.0.0.2", "6.6.6.6, 198.51.100.7, 10.0.0.3", proxies) == "198.51.100.7", "read from the right"
    assert client_ip("10.0.0.2", None, proxies) == "10.0.0.2"
    assert client_ip(None, None, frozenset()) == "unknown"


def test_anonymous_rate_limit_follows_the_real_client_behind_a_trusted_proxy(make_client):
    behind_proxy = make_client(chat_rate_limit_attempts=1, trusted_proxies="testclient")
    first = {"X-Forwarded-For": "198.51.100.1"}
    assert behind_proxy.post("/chat", json={"message": "What is Pix?"}, headers=first).status_code == 200
    assert behind_proxy.post("/chat", json={"message": "What is Pix?"}, headers={"X-Forwarded-For": "198.51.100.2"}).status_code == 200
    assert behind_proxy.post("/chat", json={"message": "What is Pix?"}, headers=first).status_code == 429

    direct = make_client(chat_rate_limit_attempts=1)
    assert direct.post("/chat", json={"message": "What is Pix?"}, headers=first).status_code == 200
    spoofed = direct.post("/chat", json={"message": "What is Pix?"}, headers={"X-Forwarded-For": "198.51.100.2"})
    assert spoofed.status_code == 429, "without a trusted proxy the header is ignored"


# --- metrics and alert rules ------------------------------------------------------------------------------


def test_metrics_are_typed_and_report_tickets_waiting(client):
    chat(client, DECLINE, login(client), conversation="m")
    text = client.get("/metrics").text
    assert "# TYPE chat_turns_total counter" in text
    assert "# TYPE chat_turn_seconds histogram" in text
    assert "# TYPE human_review_tickets_open gauge" in text and "human_review_tickets_open 1" in text
    assert "llm_circuit_open 0" in text


def test_every_alert_rule_uses_a_metric_the_service_emits():
    rules = Path("deploy/prometheus/alerts.yml").read_text(encoding="utf-8")
    expressions = re.findall(r"^\s+expr: (.+)$", rules, re.M)
    assert len(expressions) >= 8
    source = "\n".join(p.read_text(encoding="utf-8") for p in Path("src").rglob("*.py"))
    names = {n for expr in expressions for n in re.findall(r"\b([a-z][a-z0-9_]*_(?:total|bucket|open))\b", expr)}
    missing = sorted(n for n in names if n.removesuffix("_bucket") not in source)
    assert names and not missing, f"alert rules name metrics the code never emits: {missing}"


# --- live sources -------------------------------------------------------------------------------------------


def test_live_source_retries_transient_errors_caches_and_opens_its_breaker():
    calls: list[str] = []
    plan = {"BRL": [503, 200], "USD": [503] * 20, "XXX": [404] * 5}  # flaky, down, unknown currency

    def serve(request):
        target = request.url.params["to"]
        calls.append(target)
        status = plan[target].pop(0)
        return httpx.Response(status, json={"date": "2026-11-13", "rates": {target: 6.1}})

    live = LiveData(client=httpx.Client(transport=httpx.MockTransport(serve)), sleep=lambda _: None, breaker_threshold=2)

    assert live.fx_rate("EUR", "BRL")["rate"] == 6.1
    assert calls == ["BRL", "BRL"], "one retry after a 503"
    assert live.fx_rate("EUR", "brl")["rate"] == 6.1 and len(calls) == 2, "the second ask is served from cache"

    assert live.fx_rate("EUR", "XXX")["available"] is False and len(calls) == 3, "a 404 is the request's fault: no retry"

    for _ in range(2):
        assert live.fx_rate("EUR", "USD")["available"] is False
    assert len(calls) == 7 and live.breaker_open("api.frankfurter.app")
    assert live.fx_rate("EUR", "USD") == {"available": False, "error": "FX source unreachable: CircuitOpen"}
    assert len(calls) == 7, "while the breaker is open the source is not called"


def test_tool_arguments_are_checked_against_the_whole_schema():
    tool = Tool(
        "t",
        "test",
        lambda ctx, **kw: kw,
        {
            "query": {"type": "string"},
            "days": {"type": "integer", "minimum": 1, "maximum": 7},
            "unit": {"type": "string", "enum": ["c", "f"]},
            "exact": {"type": "boolean"},
        },
        ("query",),
    )
    assert validate_arguments(tool, {"query": "x", "days": 3, "unit": "c", "exact": True}) == []
    problems = validate_arguments(tool, {"days": True, "unit": "k", "exact": "yes"})
    assert "missing required argument(s): query" in problems
    assert "argument 'days' must be an integer" in problems, "true is not an integer in JSON"
    assert "argument 'unit' must be one of ['c', 'f']" in problems
    assert "argument 'exact' must be a boolean" in problems
    assert validate_arguments(tool, {"query": "x", "days": 9}) == ["argument 'days' must be <= 7"]


# --- evaluation tooling ---------------------------------------------------------------------------------------


def test_report_records_the_code_and_inputs_that_produced_it():
    p = ev.provenance()
    assert set(p) >= {"git_commit", "git_dirty", "dirty_paths", "inputs_sha256"}
    assert {"src (all .py)", "src/agents/prompts.py", "eval/judge.py", "data/corpus", "eval/datasets/poisoned_corpus"} <= set(p["inputs_sha256"])
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in p["inputs_sha256"].values())


def test_dirty_check_reads_porcelain_status_exactly():
    status = " M eval/reports/openai/report.json\nM  src/agents/prompts.py\n?? eval/adjudications.jsonl\n M eval/judge.py"
    assert ev.dirty_paths(status) == ["src/agents/prompts.py", "eval/judge.py"]
    assert ev.dirty_paths("") == []


def test_partial_runs_are_explicit_and_never_gated(tmp_path):
    assert [i["id"] for i in ev.select_golden(["g01", "s01"])] == ["g01", "s01"]
    assert {i["split"] for i in ev.select_golden(split="heldout")} == {"heldout"}
    with pytest.raises(SystemExit, match="unknown golden item"):
        ev.select_golden(["g01", "zz99"])
    with pytest.raises(SystemExit):
        ev.main(["--mode", "offline", "--ids", "g01", "--gate"])

    out = tmp_path / "partial"
    assert ev.main(["--mode", "offline", "--ids", "g01", "--out", str(out)]) == 0
    report = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert report["selection"] == {"ids": ["g01"], "split": None} and report["provenance"]["git_commit"]
    item = report["golden"]["items"][0]
    assert item["id"] == "g01" and item["tool_calls"] and item["tool_calls"][0]["arguments"]["query"]
    assert set(item["judge_input"]) == {"question", "conversation", "reference", "evidence"}
    assert item["answer_sha256"] == ev.answer_sha256(item["answer"])


def _row(item_id, split, *, passed, judge_pass=True, answer=None):
    answer = answer or f"answer {item_id}"
    return {
        "id": item_id,
        "split": split,
        "answer": answer,
        "answer_sha256": ev.answer_sha256(answer),
        "semantic_pass": passed,
        "deterministic_pass": True,
        "judge": {"pass": judge_pass, "rationale": ""},
        "judge_input": {"question": "q", "conversation": "", "reference": "r", "evidence": "e"},
    }


class FakeJudge:
    name, model = "fake", "fake-judge"

    def __init__(self, verdicts):
        self.verdicts = iter(verdicts)

    def complete(self, **_):
        ok = next(self.verdicts)
        grade = {"correctness": 5 if ok else 2, "groundedness": 5, "relevance": 5, "helpfulness": 5, "verdict": "pass", "rationale": "why"}
        return LLMResponse(tool_calls=[ToolCall("c", "grade", grade)])


def test_regrade_uses_the_stored_answers_and_reports_judge_disagreement():
    report = {
        "generated_at": "then",
        "golden": {"items": [_row("g01", "dev", passed=False, judge_pass=False), _row("g02", "dev", passed=True)]},
    }
    # g01 graded three times: pass, pass, fail -> majority pass; g02: pass x3
    result = ev.regrade(report, FakeJudge([True, True, False, True, True, True]), times=3)
    g01, g02 = result["items"]
    assert g01["new_judge_passes"] == [True, True, False] and g01["new_semantic_pass"] is True and not g01["unanimous"]
    assert g02["new_semantic_pass"] is True and g02["unanimous"]
    assert result["judge_flips"] == 1 and result["not_unanimous"] == 1
    assert result["runs"][0]["old"]["dev"]["pass_rate"] == 0.5 and result["runs"][0]["new"]["dev"]["pass_rate"] == 1.0
    assert "| g01 | 1 | fail | pass, pass, fail |" in ev.render_regrade(result)

    with pytest.raises(SystemExit, match="no stored judge inputs"):
        ev.regrade({"golden": {"items": [{k: v for k, v in _row("g01", "dev", passed=True).items() if k != "judge_input"}]}}, FakeJudge([True]))


def test_adjudication_is_tied_to_the_exact_answer_and_never_changes_the_gate():
    report = {
        "golden": {"items": [_row("g01", "dev", passed=False), _row("g02", "dev", passed=False), _row("g03", "dev", passed=True)]},
        "golden_repeat_items": [[_row("g01", "dev", passed=False, answer="a different answer"), _row("g02", "dev", passed=True), _row("g03", "dev", passed=True)]],
    }
    entries = [
        {"id": "g01", "answer_sha256": ev.answer_sha256("answer g01"), "cause": "judge", "outcome": "pass", "note": "grader wrong"},
        {"id": "g02", "answer_sha256": ev.answer_sha256("answer g02"), "cause": "agent", "outcome": "fail", "note": "agent wrong"},
    ]
    adj = ev.adjudicate(report, entries)
    run1, run2 = adj["runs"]
    assert run1["raw"]["dev"]["pass_rate"] == pytest.approx(1 / 3, abs=1e-3)
    assert run1["adjudicated"]["dev"]["pass_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert run2["raw"]["dev"]["pass_rate"] == run2["adjudicated"]["dev"]["pass_rate"], "run 2's g01 answer was never reviewed"
    assert adj["failure_causes"] == {"judge": 1, "agent": 1, "not adjudicated": 1}

    report["adjudication"] = adj
    report["golden"]["dev"] = {"semantic_pass_rate": 1 / 3}
    del report["golden_repeat_items"]  # these rows are minimal; the repeated-run rule has its own test
    failures = ev.check_gate(report, {"min": {"golden.dev.semantic_pass_rate": 0.6}})
    assert failures == ["golden.dev.semantic_pass_rate = 0.3333 is below the baseline 0.6"], "the gate reads the raw rate"


@pytest.mark.parametrize("path", sorted(str(p) for p in Path("eval/reports/openai").glob("report*.json")))
def test_every_failure_of_a_committed_model_report_is_adjudicated(path):
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = [e for e in ev.load_adjudications() if e.get("report") == report["generated_at"]]
    adj = ev.adjudicate(report, entries)
    assert adj["failure_causes"].get("not adjudicated", 0) == 0, "every failure of a committed model report is reviewed"
    assert len(entries) == len(adj["failures"]), "no adjudication points at an answer that report does not contain"
    assert report.get("adjudication") == adj, "the committed report carries its current adjudication"
