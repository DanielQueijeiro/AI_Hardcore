# 0025. Golden conversations run in parallel, and a failing model run stops after the golden suite

Status: accepted

## Context

The `model-eval` CI job took 2–3 hours. Almost all of it is the golden suite: 136 items × `--repeat 3` = 408 conversations, each several sequential model calls (Router, specialists, Critic) plus a judge call, all run one after another. CI run 44569607884 spent 2 h 13 min on the eval step and only learned at the end that `golden.dev.semantic_pass_rate` had failed, after also running the adversarial, Critic and judge-calibration suites that could not change that result.

## Decision

- `eval.run --workers N` evaluates golden conversations N at a time, all runs of `--repeat` in one pool. Each conversation already ran on its own app and databases; it now also gets its own judge client.
- Each conversation records under its own cassette scope (`golden/<run>/<item>`, `Settings.cassette_scope`), which prefixes its keys. Without it, identical requests from two conversations (g08 and g15 open with the same message; the three runs send identical prompts) would share one FIFO list in whatever order the threads reached the model, and a replay could hand one conversation's answer to the other. Scoped, the pairing is fixed whatever the thread order. Cassette format 3.
- `eval.run --gate --fail-fast` checks the gate after the golden suite and, if it already fails, skips the remaining suites. The report says it stopped early; a replay restores `workers` and `fail_fast` from the recording and stops at the same point.
- CI: `model-eval` runs `--workers ${{ inputs.eval_workers }}` (default 4) `--fail-fast`, with a 180-minute timeout.

## Consequences

- Wall-clock time of the golden suite drops roughly by the worker count (offline gate: 70 s → 30 s with 4 workers, identical results). A failing run reports after the golden suite instead of after every suite.
- Per-turn latency is still measured per conversation; with several conversations in flight it can read slightly higher if the API queues requests. Latency is reported, not gated.
- More concurrent requests mean more exposure to API rate limits. Retries and the per-app breaker still apply, and a degraded turn still fails the gate; if that happens, lower `eval_workers`.
- The adversarial, Critic and calibration suites stay sequential: the adversarial suite shares one app (ticket order matters) and the other two are short.
