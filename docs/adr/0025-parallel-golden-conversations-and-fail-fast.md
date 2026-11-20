# 0025. Golden conversations run in parallel, and a failing model run stops after the golden suite

Status: accepted

## Context

The `model-eval` CI job took 2–3 hours. Almost all of it is the golden suite: 136 items × `--repeat 3` = 408 conversations, each several sequential model calls (Router, specialists, Critic) plus a judge call, all run one after another. CI run 44569607884 spent 2 h 13 min on the eval step and only learned at the end that `golden.dev.semantic_pass_rate` had failed, after also running the adversarial, Critic and judge-calibration suites that could not change that result.

## Decision

- `eval.run --workers N` evaluates golden conversations N at a time, all runs of `--repeat` in one pool. Each conversation already ran on its own app and databases; it now also gets its own judge client.
- Each conversation records under its own cassette scope (`golden/<run>/<item>`, `Settings.cassette_scope`), which prefixes its keys. Without it, identical requests from two conversations (g08 and g15 open with the same message; the three runs send identical prompts) would share one FIFO list in whatever order the threads reached the model, and a replay could hand one conversation's answer to the other. Scoped, the pairing is fixed whatever the thread order. Cassette format 3.
- `eval.run --degraded-retries N`: a golden conversation in which a model API call failed and a turn was answered by the offline fallback (`degraded`) measures the outage, not the agent. Three earlier CI runs failed on exactly that (degraded turns, a Critic recall collapse, a missing calibration), and more parallel requests make an API error likelier. Such a conversation is run again from scratch on a new app and cassette scope (`golden/<run>/<item>/retry<k>`), at most N times. The row records `discarded_degraded_attempts` and the report lists them; a conversation still degraded after the last attempt is kept and fails the `degraded_turns` gate as before. Answers the model actually gave are never re-run, whatever their grade.
- `eval.run --gate --fail-fast` checks the gate after the golden suite and, if it already fails, skips the remaining suites. The report says it stopped early; a replay restores `workers` and `fail_fast` from the recording and stops at the same point.
- CI: `model-eval` runs `--workers ${{ inputs.eval_workers }}` (default 4) `--degraded-retries 2 --fail-fast`, with a 180-minute timeout.

## Consequences

- Wall-clock time drops roughly by the worker count for the golden suite: offline gate 70 s → 30 s with 4 workers (identical results); the CI model run's eval step took 39 min in [44622842628](https://github.com/DanielQueijeiro/AI_Hardcore/actions/runs/44622842628) against 2 h 13 min sequentially, with the same tokens (about USD 2). Its parallel recording replays offline with 0 differences in about 1.5 min. A failing run reports after the golden suite instead of after every suite.
- Per-turn latency is still measured per conversation; with several conversations in flight it can read slightly higher if the API queues requests. Latency is reported, not gated.
- More concurrent requests mean more exposure to API rate limits. Retries and the per-app breaker still apply, and a degraded turn still fails the gate; if that happens, lower `eval_workers`.
- The sequential CI run 44606495899 was cancelled after 20 minutes, before it produced any result, to switch to this parallel job.
- The adversarial, Critic and calibration suites stay sequential: the adversarial suite shares one app (ticket order matters) and the other two are short.
