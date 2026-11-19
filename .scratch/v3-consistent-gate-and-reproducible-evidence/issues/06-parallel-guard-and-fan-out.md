# 06: Parallel guard and parallel fan-out of independent subtasks

**What to build:** A turn is five to nine sequential model calls (p50 11.9 s, p95 26.4 s).

1. Run the LLM input classifier concurrently with the Router's first step. The deterministic screen still runs
   first and blocks synchronously. If the classifier blocks, the speculative Router step is discarded and never
   reaches a tool with side effects (the first Router step only decides; specialists run after the guard settles).
2. Let the Router delegate several independent subtasks in one step (e.g. a compound question: a product fact and
   the merchant's own settlement). They run in parallel, each with its own bounded tool loop, and their
   observations return together. Step and tool budgets count every branch.

**Blocked by:** 01-05 (so the latency measurement is of the final behaviour)

**Status:** resolved in code; latency effect measured per item only (see Comments)

- [x] Speculative first Router step (`Nodes.guard`, setting `SPECULATIVE_ROUTER`, default on). The deterministic screen runs alone first; a message it blocks never reaches a model. If the classifier blocks, the Router's result is discarded, the refusal does not wait for it, and `speculative_router_steps_total{outcome="discarded"}` counts it. Offline mode has no classifier, so nothing changes there.
- [x] `delegate_parallel` (2 to `MAX_PARALLEL_TASKS`=3 tasks). Runs in the `parallel` node on a thread pool; each branch is an ordinary specialist run (same allow-list, tool budget, identity scoping). The Router decides again only after every branch has reported. The whole fan-out is one Router step.
- [x] Duplicates: a task already delegated, or repeated within the list, is not run and the Router is told; one remaining task becomes an ordinary delegation.
- [x] Tests with timed scripted models: classifier and first Router step overlap; a blocked message discards the step without waiting; two branches overlap and both observations reach the Router; duplicate handling.
- [ ] Latency before/after on the full suite: target p50 < 8 s, p95 < 15 s. Measured in 13.

## Comments

**2026-11-18, per-item check with the real model** (one run each, against the median of the three runs in the
2026-11-16 report). All six passed semantically and with the judge.

| Item | Kind | Before (median) | After | What happened |
|---|---|---|---|---|
| g14 | compound, independent | 19.6 s | 10.2 s | one `delegate_parallel` step (support + knowledge) |
| h20 | compound, independent | 20.3 s | 13.5 s | one `delegate_parallel` step |
| s18 | compound, independent | 21.0 s | 18.5 s | parallel step, then one more knowledge step |
| g05 | compound, dependent | 21.6 s | 22.9 s | sequential, as it should be (the telemetry code is needed first) |
| s04 | single | 7.8 s | 7.3 s | |
| g02 | single, weather | 9.8 s | 20.4 s, then 8.3-9.1 s x3 | see below |

g02 regression: the trace showed the Router re-delegating "to verify this is tomorrow's forecast"; in another
attempt it assumed the date was June 2025. Models do not know the date. `today_line()` now puts today's date
(Brasília time) in the Router and specialist prompts; three re-runs of g02 delegated once each (8.3-9.1 s).
That affects issue 12: a recorded cassette keyed on the prompt changes every day, so replay must freeze the clock.

Design choice: the fan-out is a thread pool inside one node, not LangGraph `Send` branches. `Send` needs an
append reducer on `observations` and `events`, which changes how every node writes state and how checkpoints of a
paused human review are read back. The thread pool gives the same concurrency with the state model untouched. The
cost is that the graph drawing shows one `parallel` node instead of N branches; the trace shows the branches
(`parallel` span with `branches` and wall time, then each specialist's own spans).
