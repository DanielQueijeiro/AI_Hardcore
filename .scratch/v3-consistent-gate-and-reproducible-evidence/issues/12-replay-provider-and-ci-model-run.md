# 12: Replay provider and a CI model-evaluation run

**What to build:** The reviewer scored E3 because the model runs could not be reproduced without a key.

1. A `replay` LLM provider: during a model run every request/response pair is recorded to a cassette (keyed by a
   hash of role, instructions, prompt and tools). `LLM_PROVIDER=replay` serves from it, and a request with no
   recording fails loudly. One command re-runs the published evaluation offline and must produce the same report.
2. A `workflow_dispatch` job that runs the model evaluation with the key as a repository secret and uploads the
   report and cassette as artifacts, so the published numbers come from a run anyone can open.

**Blocked by:** none (the cassette for the final report is recorded in 13)

**Status:** resolved in code; the cassette of the final report is recorded in 13

- [x] `src/cassette.py`: recording and replaying wrappers for the model client (agents and judge), live tools and hosted embeddings, one shared cassette per run. `eval.run --record PATH` / `--replay PATH`; replay reapplies the recorded suite, repeats, selection and gate. [ADR-0021](../../../docs/adr/0021-recorded-model-runs-replayable-without-a-key.md).
- [x] Prompts carry today's date: the cassette stores it, replay freezes `src/clock.py` to it.
- [x] Parallel branches: keys are request content, never call order; identical requests are FIFO.
- [x] A request with no recording raises `CassetteMiss` naming the role.
- [x] `eval.compare PUBLISHED.json REPLAYED.json`: every metric and every answer hash identical, latency/cost/timestamps/provenance excluded.
- [x] Verified with the real model on 5 golden items (hosted dense retrieval, live weather, human approval and resume, parallel fan-out): 0 differences, 0 unused recorded calls. Three causes of mismatch were found this way and fixed (per-process canary in prompts, nondeterministic embeddings, a test sharing databases).
- [x] CI: `model-eval` (manual) runs `--gate --repeat 3 --record eval/reports/openai/cassette.json.gz` with hosted retrieval and uploads report and cassette; `model-eval-replay` (every push) replays the committed cassette and runs `eval.compare` against the committed report, skipping with a message while no cassette is committed.
- [ ] The final report (13) is recorded, its cassette committed, and the CI run linked from the README.

## Comments

The CI `model-eval` job needs the repository secret `OPENAI_API_KEY`; setting it is the user's call.
