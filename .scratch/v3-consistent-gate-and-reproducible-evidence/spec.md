# v3: a gate that passes consistently, and evidence a reviewer can reproduce

**Status:** resolved (pending user walkthrough video)

## Problem

The second submission scored 9.3/10 (weighted 9.47, calibrated down). The review
(`Daniel_Queijeiro_AI_Hardcore_feedback_9.3_EN.md`) gave two reasons for the calibration and a list of
concrete gaps:

| Reason / gap | Where it shows |
|---|---|
| Evidence is E3, not E4: the reviewer could not reproduce the model runs without a key | All criteria |
| The regression gate failed on the published run (dev 0.833 against 0.94) | Evaluation, calibration |
| Critic present is not Critic reliable: it approved g12 without the Wi-Fi step, g01 without prices | Agentic Reasoning (9.3) |
| Cross-lingual retrieval miss (s04): Portuguese reformulation, English corpus, lexical retrieval | RAG (9.0) |
| Recall@4 0.988 is optimistic: the glossary was written alongside the queries | RAG (9.0) |
| Output guard masked a 13-digit WhatsApp number as a card number | Security (9.5) |
| p50 11.9 s, p95 26.4 s: classifier, Router loop, specialist loops and Critic in sequence | Observability/cost (9.5) |
| Datasets small and project-generated; sealed split written with a coding assistant | Evaluation |
| Supervisor works over a closed set of specialists and operations | Agentic Reasoning (9.3) |
| Single worker | Production (9.3) |

## Goal

10/10: every criterion at or near the top of the V4 scale, the gate passing in every run of a repeated
measurement on a sealed split written after the last change, and a path for the reviewer to re-run the
published evaluation without an API key.

## Ordering constraint

[ADR-0016](../../docs/adr/0016-sealed-held-out-and-independent-judge-calibration.md): a fix motivated by a
sealed failure turns that split into validation. So the order is fixed:

1. Fix everything measured (phase 1) and the orchestration/latency work (phase 2).
2. Change the evaluation method (phase 3), with the gate rule written in an ADR **before** it is measured.
3. Freeze prompts and code paths that shape answers.
4. Write sealed-2 (s25+), fix its floor, then run the full suite three times (phase 5).

The current sealed split (s01-s24) becomes `validation` the moment phase 1 lands, and the README says so.

## Non-goals

- Lowering any floor after seeing a result.
- Editing a sealed item's fact pattern to turn a failure into a pass.
- A general planner that invents task types. Bounded autonomy over named specialists is the design.

## Open decisions (user)

- Who writes sealed-2: an outside person (preferred) or a different model family, declared in an ADR.
- Whether Postgres/Redis scale-out (issue 14) is in scope.
- Budget for full model runs (one 3x run of the golden suite is roughly 90 minutes and spends tokens).

## Slices

| # | Issue | Phase |
|---|---|---|
| 01 | [Output guard: phone numbers are not card numbers](issues/01-output-guard-card-false-positive.md) | 1 |
| 02 | [Cross-lingual multi-query retrieval](issues/02-cross-lingual-multi-query-retrieval.md) | 1 |
| 03 | [Critic completeness checked against the evidence](issues/03-critic-completeness-against-evidence.md) | 1 |
| 04 | [Router and tool behaviour defects from the 2026-11-16 run](issues/04-router-and-tool-behaviour-defects.md) | 1 |
| 05 | [Grader fact patterns on dev and validation](issues/05-grader-fact-patterns.md) | 1 |
| 06 | [Parallel guard and parallel fan-out of independent subtasks](issues/06-parallel-guard-and-fan-out.md) | 2 |
| 07 | [A gate over repeated runs, decided before measuring](issues/07-gate-over-repeated-runs.md) | 3 |
| 08 | [Critic calibration set](issues/08-critic-calibration-set.md) | 3 |
| 09 | [Borderline judge calibration with two human labellers](issues/09-borderline-judge-calibration.md) | 3 |
| 10 | [Retrieval held-out split and glossary ablation](issues/10-retrieval-heldout-and-glossary-ablation.md) | 3 |
| 11 | [Sealed-2](issues/11-sealed-2.md) | 3 |
| 12 | [Replay provider and a CI model-evaluation run](issues/12-replay-provider-and-ci-model-run.md) | 4 |
| 13 | [Final measurement and review response](issues/13-final-measurement-and-review-response.md) | 5 |
| 14 | [Postgres checkpointer and shared locks (optional)](issues/14-postgres-and-shared-locks.md) | optional |

## Comments

**2026-11-18, phase 1 per-item check** (`eval.run --ids g01,g12,g15,h14,s04,s21,g08,g18`, real model, one run,
uncommitted tree): 8 of 8 semantic pass, judge pass on all, every fact found. The Knowledge Agent passed
`query_en` on every search; s04 answered "up to 5"; h14 gave both thresholds with the caveat; g15 led with
"not approved"; g12 included the Wi-Fi step. Latency 5-26 s per item, no better than before (phase 2).
One run of the eight items each fix targeted is a smoke test, not evidence: several of them passed in some
earlier runs too. The measurement that counts is 13.
