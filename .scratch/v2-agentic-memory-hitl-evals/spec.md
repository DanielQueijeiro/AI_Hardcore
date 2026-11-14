# v2: agentic orchestration, identity, memory, human review, semantic evaluation

**Status:** resolved

## Problem

The first submission scored 7.4/10. The review found a well-built but deterministic system whose headline
metric measured the path taken, not the answer:

| Criterion (weight) | Score | Finding |
|---|---|---|
| Agentic Reasoning & Orchestration (15%) | 6.5 | State machine routed by flags; no planner, critic, re-planning, quality retry or stopping rule |
| Evaluation & Quality Engineering (14%) | 6.2 | 12/12 checked tier, agent sequence, tools and non-empty answer; nothing semantic |
| Security & Identity (13%) | 7.5 | `user_id` in the body is not an authenticated identity; injection defence is lexical |
| Memory, State & Resilience (8%) | 3.5 | New state per request; no thread, checkpoint or summary |
| Human Oversight (7%) | 5.0 | Ticket created, flow ended; no human answer, no resume |
| Context, Knowledge & RAG (10%) | 8.5 | Good design, but no retrieval metrics and unproven hybrid weights |
| Production Engineering (5%) | 7.5 | Root container, no CI, no migrations, single health endpoint |

## Goal

Close every finding with working code and evidence, without copying the benchmark's architecture, and keep
claims honest: anything not measured is not claimed.

## Requirements

Normative rules are in [SPEC.md](../../SPEC.md) (I1-I6, B1-B7, M1-M5, H1-H9, G1-G4, A1-A8). Summary:

1. The Router decides each step from observations; bounds are enforced in code; a Critic gates the answer.
2. Identity comes only from a verified token; tools cannot be pointed at another merchant.
3. Conversations persist across requests and restarts, with compaction.
4. Escalation pauses the turn; an operator claims, decides, and the same turn resumes; writes are approved by a human and executed by code.
5. Evaluation measures retrieval, answer semantics and attack resistance separately, with a held-out split, a calibrated judge and a CI gate.
6. Retrieval mode is chosen from a measured ablation.
7. The image is non-root and read-only; CI builds, tests, gates and smoke-tests it.

## Non-goals

Operator UI, streaming, multi-replica deployment, a real back office.

## Slices

One issue per vertical slice in `issues/`, each delivered with its tests.
