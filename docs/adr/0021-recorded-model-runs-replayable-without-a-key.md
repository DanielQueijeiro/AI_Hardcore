# 0021. Model evaluations are recorded and can be replayed without a key

Status: accepted

## Context

The 9.3 review scored the evidence E3, not E4: the reviewer could read the code, tests and published reports but could not reproduce the model runs without an API key. Re-running the model is also not a reproduction: a new run gives different answers.

## Decision

A model evaluation can be recorded to a cassette (`python -m eval.run ... --record CASSETTE.json.gz`) and replayed by anyone, offline (`python -m eval.run --replay CASSETTE.json.gz --out X`). `python -m eval.compare REPORT.json X.json` checks that every answer (by SHA-256, per item and run) and every metric come out identical. CI runs that comparison on every push once a cassette is committed (`model-eval-replay`), and the manual `model-eval` job records one.

What goes through the cassette (`src/cassette.py`): every model call of the agents, the guardrail classifier, the Critic and the judge; every live-tool result (FX, weather, web search); every hosted embedding. Everything else (retrieval, tools on fixture data, guardrails, checks, metrics, the gate) runs for real during a replay. A replay is therefore a re-execution of the whole system with the model's side of each exchange held fixed, not a re-read of a stored report.

## Details that made it exact

Each was found by recording a real run and replaying it, until the comparison showed zero differences:

- **Keys are content hashes, not call order**: parallel specialist branches (ADR on issue 06) make call order non-deterministic.
- **FIFO per key**: `--repeat 3` sends identical prompts three times and gets different answers; replay hands them back in recorded order.
- **Normalized identifiers**: ticket ids, service-order ids, trace ids, timestamps and the per-process prompt-leak canary are replaced by placeholders before hashing. The canary was the first real-run miss.
- **Frozen clock**: prompts carry today's date (`src/clock.py`); the cassette stores its date and replay freezes to it.
- **First vector wins**: the embeddings API is not bit-for-bit deterministic. The same text embedded by two app instances of one run came back slightly different, which moved cosine scores in the fourth decimal and changed the prompt. During recording, a text's first vector is reused for the rest of the run, so the recorded run is consistent with itself and the replay sees exactly what it saw.
- **The client's name is replayed**: code that branches on `llm.name` (the guardrail classifier is skipped for the offline policy) takes the same branch on replay.
- **Loud misses**: a request with no recording raises `CassetteMiss` naming the role. A changed prompt or code path fails the replay instead of degrading into something that looks like a pass.

## Consequences

- A replay reproduces a run at a fixed commit. A later change to prompts or answer-shaping code makes the old cassette miss, which is the point: the cassette certifies the report it was recorded with.
- The cassette is a few MB compressed for a full three-run evaluation (embeddings dominate). It is committed next to the report it reproduces.
- Recording reuses the first embedding of each text, so a recorded run makes fewer embeddings calls than an unrecorded one; retrieval results are otherwise the same.
- Verified end to end on 2026-11-18 with five golden items covering hosted dense retrieval, a live weather call, a human approval with resume, and a parallel fan-out: `REPRODUCED: 5 answers and every metric compared (0 differences)`, no unused recorded calls.
