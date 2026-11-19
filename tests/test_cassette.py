"""Record a run once, replay it without a key: same answers, same order, loud failure on anything unrecorded."""

from __future__ import annotations

from datetime import date

import pytest

from src import clock
from src.agents.nodes import today_line
from src.cassette import (
    Cassette,
    CassetteMiss,
    RecordingEmbedder,
    RecordingLive,
    RecordingLLM,
    ReplayEmbedder,
    ReplayLive,
    ReplayLLM,
    normalize,
)
from tests.conftest import approve, chat, finish, login, scripted


def _record_then_replay(make_client, tmp_path, script, conversation):
    path = tmp_path / "run.json.gz"
    recorder = Cassette(path, "record")
    client = make_client(RecordingLLM(scripted(script), recorder))
    recorded = conversation(client)
    recorder.save()
    replay = Cassette(path, "replay")
    fresh = {"sqlite_db_path": tmp_path / "replay" / "support.db", "checkpoint_db_path": tmp_path / "replay" / "checkpoints.db"}
    replayed = conversation(make_client(ReplayLLM(replay), **fresh))
    return recorded, replayed, replay


def test_replay_returns_the_recorded_answers_in_order_for_identical_requests(make_client, tmp_path):
    # Two conversations send the identical first prompt and got different answers (as runs 1 and 2 of --repeat do).
    script = {"supervisor": [finish("Answer from run one."), finish("Answer from run two.")], "critic": approve()}

    def conversation(client):
        headers = login(client)
        return [chat(client, "Tell me about Pix", headers, conversation=c)["answer"] for c in ("run1", "run2")]

    recorded, replayed, replay = _record_then_replay(make_client, tmp_path, script, conversation)
    assert recorded == replayed == ["Answer from run one.", "Answer from run two."]
    assert replay.unused() == 0


def test_replay_survives_identifiers_minted_at_run_time(make_client, tmp_path):
    # Ticket and service-order ids differ between the recording and the replay; they are normalized out of the keys.
    def conversation(client):
        merchant, operator = login(client), login(client, "operador1")
        out = chat(client, "My card machine is showing a transaction decline error.", merchant)
        ticket = out["orchestration"]["ticket_id"]
        client.post(f"/operator/tickets/{ticket}/claim", headers=operator)
        decided = client.post(f"/operator/tickets/{ticket}/respond", json={"decision": "approve", "message": "ok"}, headers=operator).json()
        return normalize(decided["agent_answer"])

    recorded, replayed, replay = _record_then_replay(make_client, tmp_path, {}, conversation)
    assert recorded == replayed and "SO-ID" in recorded
    assert replay.unused() == 0


def test_a_request_that_was_not_recorded_fails_loudly(tmp_path):
    path = tmp_path / "empty.json.gz"
    Cassette(path, "record").save()
    with pytest.raises(CassetteMiss, match="role supervisor"):
        ReplayLLM(Cassette(path, "replay")).complete(role="supervisor", instructions="i", prompt="p")


def test_live_tools_and_embeddings_replay_without_network(tmp_path):
    class FakeEmbedder:
        name = "fake-embedding"

        def embed(self, texts):
            return [[float(len(t)), 0.5] for t in texts]

    path = tmp_path / "live.json.gz"
    recorder = Cassette(path, "record")
    live = RecordingLive(recorder, enabled=False)
    first = live.weather("Porto Alegre")
    vectors = RecordingEmbedder(FakeEmbedder(), recorder).embed(["pix", "crediário"])
    recorder.save()

    replay = Cassette(path, "replay")
    assert ReplayLive(replay, enabled=True).weather("Porto Alegre") == first, "served from the file even with live data on"
    assert ReplayEmbedder(replay).embed(["crediário", "pix"]) == [vectors[1], vectors[0]]
    assert ReplayEmbedder(replay).name == "fake-embedding"
    with pytest.raises(CassetteMiss):
        ReplayLive(replay).fx_rate("USD", "BRL")


def test_replay_freezes_the_date_the_prompts_carry():
    clock.freeze(date(2026, 11, 16))
    try:
        assert today_line() == "Today is Monday, 2026-11-16 (Brasília time)."
    finally:
        clock.freeze(None)


def test_the_first_recorded_vector_of_a_text_is_used_for_the_whole_run(tmp_path):
    # The embeddings API is not bit-for-bit deterministic; a replay must see the vectors the recorded run used.
    class DriftingEmbedder:
        name = "drifting"
        calls = 0

        def embed(self, texts):
            DriftingEmbedder.calls += 1
            return [[1.0, DriftingEmbedder.calls / 10] for _ in texts]

    path = tmp_path / "drift.json.gz"
    recorder = Cassette(path, "record")
    first = RecordingEmbedder(DriftingEmbedder(), recorder).embed(["pix"])
    again = RecordingEmbedder(DriftingEmbedder(), recorder).embed(["pix", "crediário"])
    assert again[0] == first[0] and DriftingEmbedder.calls == 2, "only the new text reached the API"
    recorder.save()
    assert ReplayEmbedder(Cassette(path, "replay")).embed(["pix"]) == first
