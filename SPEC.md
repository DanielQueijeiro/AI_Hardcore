# System Specification v3 — Getnet Multi-Agent Support System

> Methodology: Spec-Driven Development. This document is the contract the code and the tests are written against.
> Vocabulary: [GLOSSARY.md](./GLOSSARY.md) · Decisions: [docs/adr/](./docs/adr/) · Work items: [.scratch/](./.scratch/)
>
> v2 replaced v1 after the first review (7.4/10). v3 addresses the second review (9.3/10): parallel orchestration
> (`speculative_router`, `delegate_parallel`), evidence-anchored Critic completeness checks + calibration, hosted
> dense retrieval chosen on a held-out query split (ADR-0020), repeated-run gating (ADR-0019), and replayable
> model evaluations via cassettes (ADR-0021).

## 1. Scope

A service that answers Getnet merchants' messages by coordinating four agents, exposed as an HTTP API and
shipped as a container.

In scope: model-driven orchestration with bounded autonomy; RAG over Getnet public pages; live public-data
tools; account lookups for the authenticated merchant; human review with resume; conversation memory;
guardrails; evaluation and observability.

Out of scope: an operator UI, a real back office (merchant data is a fixture), streaming responses,
multi-replica deployment.

## 2. HTTP contracts

All bodies are JSON. Identity is `Authorization: Bearer <jwt>`; without it the caller is anonymous.

| Method and path | Auth | Purpose |
|---|---|---|
| `POST /chat`, `POST /api/v1/chat` | optional (required if `REQUIRE_CHAT_AUTH=true`) | Send a message. Body: `message` (1-2000 chars), optional `user_id`, optional `conversation_id` (`[A-Za-z0-9_-]{1,64}`) |
| `POST /chat/stream` | as `/chat` | Same body and admission checks as `/chat`; server-sent events `accepted`, `step` (routing decision, tool call, review, human-review event; no model reasoning or tool results), then `result` (the `/chat` response body) or `error`. The turn completes even if the client disconnects |
| `GET /conversations/{conversation_id}?wait=` | optional (required if `REQUIRE_CHAT_AUTH=true`) | Stored memory and status (`empty`, `idle`, `awaiting_human`, `in_progress`) of one of the caller's conversations. With `wait` > 0, a conversation waiting on a human or running a turn is held up to `min(wait, MAX_CONVERSATION_WAIT_SECONDS)` until it settles |
| `POST /auth/login` | none | `{user_id, password}` → `{access_token, expires_in, user_id, role}` |
| `POST /auth/logout` | required | Revoke the presented token |
| `GET /auth/me` | optional | The caller's principal |
| `GET /operator/tickets?status=open` | operator | Human-review queue |
| `GET /operator/tickets/{id}` | operator | One ticket |
| `POST /operator/tickets/{id}/claim` | operator | Take a lease on a ticket |
| `POST /operator/tickets/{id}/respond?wait=` | operator | `{decision: approve\|reject\|answer, message}`. `wait=true` (default): resumes the conversation and returns the agent's answer, `resume: completed`. `wait=false`: records the decision, returns `202` with `resume: scheduled`, resumes in the background |
| `GET /traces/{trace_id}` | owner or operator | Full trace of a turn |
| `POST /feedback` | owner | `{trace_id, rating: 0\|1, comment}` |
| `GET /health` | none | Liveness |
| `GET /ready` | none | Readiness: database, migrations, knowledge index, model provider, breaker state. 503 when not ready |
| `GET /metrics` | `METRICS_TOKEN` bearer when set (required in production); open otherwise | Prometheus text, every series typed |

`POST /chat` response:

| Field | Meaning |
|---|---|
| `user_id`, `authenticated` | The verified identity, or `null` / `false` |
| `conversation_id` | Thread to continue. `default` for authenticated callers who omit it; a new random id for anonymous ones |
| `answer` | Final answer, or the interim message when `status` is `awaiting_human` |
| `status` | `completed`, `blocked` (input guardrail) or `awaiting_human` |
| `orchestration` | `trace_id`, `agents` (order they acted), `tools_called`, `sources`, `plan_steps`, `critic_rounds`, `guardrail`, `escalated_to_human`, `ticket_id`, `usage` (`llm_calls`, tokens, `cost_usd`), `latency_ms`, `llm_provider`, `degraded` |

Error contract: 401 invalid/expired/revoked token, wrong issuer or audience (or missing token when `REQUIRE_CHAT_AUTH=true`, or a missing/wrong metrics token); 403 body `user_id` ≠ token subject, or missing role;
404 unknown ticket, or a trace the caller may not see; 409 ticket lease conflict or already decided;
422 invalid body, invalid conversation id, or `approve` on a ticket with no action; 429 login or chat rate limit.

## 3. Identity rules

- I1. The principal is derived only from a verified, unexpired, unrevoked token.
- I2. `user_id` in the body never grants access. If a token is present and they differ: 403; if no token is present (and `REQUIRE_CHAT_AUTH=false`), `user_id` is ignored and the caller remains anonymous (`user_id: null, authenticated: false`).
- I3. Anonymous principals (when `REQUIRE_CHAT_AUTH=false`) can use the Knowledge Agent only. Account tools return `authentication_required`. When `REQUIRE_CHAT_AUTH=true`, anonymous `/chat` and `/conversations/*` requests return 401.
- I4. No tool accepts a merchant identifier. Identity-like arguments from a model are dropped and recorded.
- I5. Threads are keyed `(user_id | "anon", conversation_id)`. Traces are visible to their owner and operators.
- I6. Operator endpoints require role `operator`.
- I7. An anonymous caller continues a conversation only under the unguessable id the server issued; any other id starts a new one.
- I8. `APP_ENV=production` refuses to start while demo users are seeded, `JWT_SECRET` is unset or shorter than 32 characters, or `METRICS_TOKEN` is unset or shorter than 24.
- I9. Tokens carry and must present `iss = JWT_ISSUER` and `aud = JWT_AUDIENCE`; one signed with the right secret for another audience or issuer is refused.
- I10. Rate limits key on the verified user, else on the client address; `X-Forwarded-For` is read (from the right, skipping trusted hops) only when the direct peer is in `TRUSTED_PROXIES`.

## 4. Agents

Every agent decision is a typed function call. Prompts and schemas: [src/agents/prompts.py](src/agents/prompts.py).

### 4.1 Router Agent (supervisor)

Owns the conversation. Each step reads memory, the message and all observations, and calls exactly one of:

| Call | Arguments |
|---|---|
| `delegate_knowledge` | `thought`, `task`, `remaining_plan` |
| `delegate_support` | `thought`, `task`, `remaining_plan` |
| `delegate_parallel` | `thought`, `tasks` (2–3 independent `{agent, task}` subtasks run concurrently), `remaining_plan` |
| `escalate_to_human` | `thought`, `reason` (`approval_required`, `customer_request`, `unresolved`), `question`, `proposed_action` (`none`, `terminal_rekey_or_swap`), `remaining_plan` |
| `finish` | `answer`, `confidence` |

Required behaviour: decompose compound messages (independent subtasks concurrently via `delegate_parallel`,
dependent subtasks sequentially); write self-contained tasks (specialists do not see the conversation); re-plan
after each observation; stop when the question is covered; answer only from observations and earlier turns; cite
the sources the Knowledge Agent reported; answer in the merchant's language. Router and specialist prompts carry
today's date (Brasília time, frozen during cassette replay).

### 4.2 Knowledge Agent

Tools: `search_getnet_knowledge(query, query_en?)`, `get_fx_rate(base, quote="BRL")`, `get_weather_forecast(city)`,
`web_search(query)`. `search_getnet_knowledge` keeps the primary query's top-k and also searches `query_en` and
the merchant's original message (up to 2 interleaved extra passages, embeddings batched in one call). Runs a tool
loop, must reconsider after a `poor` relevance rating (reformulate or switch tool), and ends with
`report(answer, sources, confidence, gaps)`. Sources not returned by a tool are removed by code.

### 4.3 Customer Support Agent

Tools: `get_settlements`, `get_pos_diagnostics`, `get_account_profile`, `list_my_tickets`, all scoped to the
principal. Ends with `report(findings, follow_up_for_knowledge, needs_human_approval, proposed_action)`.

### 4.4 Human Escalation Agent

Writes `human_review_brief(summary, question_for_operator, message_to_merchant)`, opens the ticket, and the
graph interrupts. On resume the human decision is returned to the Router as an observation.

### 4.5 Critic

Reviews the draft against the evidence with `review(verdict, grounded, complete, parts, checklist, issues, needs_more_evidence)`.
Receives three automatic checks extracted in code: numbers absent from the evidence, URLs no tool returned, and
an `evidence_checklist` (human decisions this turn, numbered procedure steps, and unambiguous product prices).
Any unanswered question part or `must_add` checklist item forces `revise` in code regardless of the model's
overall verdict; a grounded `revise` naming no issue, missing part, `must_add` item or research need is treated
as an approval.

## 5. Bounds (enforced in code)

| # | Bound | Default | At the limit |
|---|---|---|---|
| B1 | Router steps per turn | 6 | Next call forced to `finish` |
| B2 | Identical delegation (same agent, same task) | — | Refused; the Router is told why |
| B3 | Specialist tool steps | 4 | Forced `report`. A tool without parameters is offered once; an identical call is not executed and the next step can only `report` |
| B4 | Escalations per turn | 1; 0 for anonymous | Refused |
| B5 | Critic revision rounds | 2 | A draft still ungrounded is replaced by the low-confidence answer |
| B6 | Fabricated URL in a draft | — | Revision forced regardless of the Critic's verdict |
| B7 | Graph recursion | 60 | Hard stop |
| B8 | Draft in a language other than the merchant's (EN/PT/ES, detected in code) | — | Revision forced regardless of the Critic's verdict (model-written drafts) |
| B9 | Critic returns no review | — | The deterministic checks decide: an unsupported number or unreturned URL forces a revision |
| B10 | Tool calls per model step | 1 | Parallel tool calls are disabled (`delegate_parallel` caps concurrent branches at `MAX_PARALLEL_TASKS=3` and counts as one Router step) |
| B11 | Speculative first Router step | on (`SPECULATIVE_ROUTER=true`) | Runs only after the deterministic input screen passes, concurrently with the LLM classifier; discarded without waiting if the classifier blocks, never reaching side-effect tools |

## 6. Memory

- M1. `history` (recent messages) and `summary` persist per thread in the SQLite checkpointer.
- M2. When `history` exceeds `HISTORY_COMPACT_AFTER`, older messages are summarized and `HISTORY_KEEP_MESSAGES` remain.
- M3. A new process on the same databases continues conversations and paused reviews.
- M4. A blocked message is stored as a placeholder, not verbatim.
- M5. One turn at a time per thread.
- M6. A finished turn leaves one checkpoint per thread; a paused turn keeps what it needs to resume. Traces are deleted after `TRACE_RETENTION_DAYS`.
- M7. While a turn or a resume runs on a thread, reading the conversation reports `in_progress` instead of state between checkpoints.

## 7. Human review

Ticket states: `OPEN → CLAIMED → APPROVED | REJECTED | ANSWERED`, or `OPEN | CLAIMED → TIMED_OUT`.

- H1. Escalation interrupts the turn; `/chat` returns `awaiting_human` with the ticket id.
- H2. A decision requires a live lease held by that operator. Another operator can claim after the lease lapses.
- H3. `respond` resumes the same turn; the final answer is returned to the operator and stored in the conversation.
- H4. `approve` is valid only on a ticket that carries a proposed action.
- H5. The write action runs only for an `APPROVED` ticket of that merchant with an allow-listed action, exactly once, in code.
- H6. A proposed action is attached only if the Support Agent derived it this turn.
- H7. Tickets expire after `HITL_TIMEOUT_SECONDS`; the conversation resumes with a timeout observation (sweeper, and lazily on the next message).
- H8. Messages sent while waiting get a status reply without running agents.
- H9. Opening a ticket is idempotent per `(thread, turn)`.
- H10. A ticket does not time out while an operator holds a live lease on it.
- H11. A decision whose resume never ran (process died in between) is resumed by the periodic sweep.
- H12. Escalation is the last resort: for approval only when the fix for the problem asked about needs it; self-service steps are answered first; an unrelated finding is mentioned, not escalated.
- H13. The waiting message states what was found and why a human is involved, and passes the output guard.
- H14. A paused turn is resumed only when the ticket it is waiting on is decided or has expired. An earlier, already resolved ticket of the same conversation never releases it.
- H15. `respond?wait=false` records the decision durably and resumes on a worker; if that resume fails, the sweep of H11 performs it. The merchant reads the outcome with `GET /conversations/{id}?wait=`.

## 8. Guardrails

- G1. Input: deterministic screen on normalized/decoded views, then an LLM classifier that fails open to it.
- G2. Retrieved passages, web results and operator notes are sanitized and presented as tagged data.
- G3. Output: prompt canary, internal orchestration symbols (including `delegate_parallel`), other tenants' identifiers and credential-shaped strings are blocked or redacted; formatted CPF/CNPJ and issuer/length-validated Luhn card numbers (excluding phone layouts and E.164 `+` numbers up to 15 digits) are redacted.
- G4. A live tool that cannot reach its source returns `available: false`; no canned values exist.
- G5. Ordinary merchant wording is not blocked: the benign control set is part of the adversarial suite and its false-positive rate is gated.
- G6. Live sources are called through a short cache, one retry with backoff for transient failures (never a 4xx) and a circuit breaker per source.
- G7. Tool arguments are validated against the declared schema (required, type, enum, length, range) before a handler runs; a violation is returned to the agent as `invalid_arguments`.

## 9. Knowledge base

Curated Markdown per source page with `source_url`, `origin`, `retrieved_at` (with explicit `Curation note:`
cross-references wherever two Getnet pages contradict each other); chunked by section; retrieval modes `bm25`,
`dense`, `hybrid`; each hit carries a coverage score. `RETRIEVAL_MODE` and `EMBEDDING_PROVIDER` default to `auto`
(ADR-0020): hosted `text-embedding-3-small` + `dense` when `OPENAI_API_KEY` is set (degrading to `bm25` on an
embeddings outage), and the keyless hashing embedder + `bm25` otherwise.

Fixture data (SQLite): merchants `cliente1988` (Get Smart `POS-GS-99812`, offline with `OFFLINE_GPRS_TIMEOUT`,
last decline `TX-88410` with `ERR_51_ISSUER_DECLINE / POS_KEY_SYNC_WARN` requiring an approved re-key or swap;
yesterday's settlements Pix R$ 850.00 settled, debit R$ 1,240.00 today, credit net R$ 2,524.60 tomorrow) and
`cliente2026` (Get Clássica online, no declines; Pix R$ 410.00, debit R$ 620.00, credit net R$ 1,067.00 at D+30).

## 10. Acceptance criteria

Quality is accepted on semantics, not on the path taken. Datasets: [eval/datasets/](eval/datasets/);
thresholds: [eval/baseline.json](eval/baseline.json); runner: `python -m eval.run --gate`.

| # | Criterion | Verified by |
|---|---|---|
| A1 | The ten challenge scenarios produce answers containing the required facts, no forbidden claim, only numbers present in the evidence, and no fabricated citation | `golden.jsonl` g01-g10 |
| A2 | Scenario 8 (transaction decline) pauses for a human, resumes on the decision, and executes the action only on approval | g08, g15; `test_human_in_the_loop.py` |
| A3 | Three splits are scored separately. `dev` (g01-g18) was used while writing prompts. `validation` (h01-h22 and s01-s24: former held-out splits that motivated fixes, per ADR-0016). `heldout` (s25-s48, "sealed-2": PT, ES, EN, abstention, conflict, account, compound, multi-turn, human review, anonymous, live) is sealed: written after the v3 code/prompt freeze by a separate model family blind to `prompts.py`, `checks.py` and `GLOSSARY` (ADR-0022), with its floor fixed before the first model run. Every report records the SHA-256 of the dataset files it ran | `golden.jsonl`, `datasets_sha256` in the report |
| A4 | Retrieval Recall@4 and MRR do not regress, per mode, across both `dev` (42 queries) and `heldout` (36 post-glossary queries), with glossary-off ablation reported | `retrieval.jsonl`, ADR-0020 |
| A5 | No attack in the adversarial suite succeeds: no leak, no unauthorized write; benign controls are not blocked | `adversarial.jsonl` |
| A6 | With a model: golden metrics are gated over every run of `--repeat N` (ADR-0019: mean meets floor, no run > 1 item below, ceilings in every run); judge pass rate and judge-vs-label agreement meet the baseline with zero false passes; `independent` and human-labelled `borderline` sets are reported separately; a gated metric that was not produced fails the gate; no turn was answered by the degraded fallback | `judge_calibration.jsonl`, `judge_borderline.jsonl`, `baseline.json` |
| A7 | Rules I1-I10, B1-B11, M1-M7, H1-H15, G1-G7 each have at least one test | `tests/` |
| A11 | Every report records the git commit, whether the tree was dirty, and hashes of the source, prompts, judge, baseline and corpora; each golden item stores its tool calls and the judge's exact input, so it can be re-graded without re-running the agents | `provenance` in the report; `--regrade` |
| A12 | Every failed golden answer of a published report is adjudicated (agent, judge, fact patterns or harness) against the exact answer; the report shows raw and adjudicated rates and the gate reads only the raw ones | `eval/adjudications.jsonl`; `tests/test_streaming_and_ops.py` |
| A13 | The Critic is measured directly as a classifier (recall on 8 planted defect classes and false-revise rate on clean drafts), split into `dev` and `heldout` | `critic_calibration.jsonl`; `--suite critic` |
| A14 | Every model evaluation can be recorded to a compressed cassette (`--record`) and replayed offline without an API key (`--replay`), reproducing every answer SHA-256 and metric with zero differences and zero unused calls; verified in CI on every push | `src/cassette.py`, `eval/compare.py`, CI `model-eval-replay`, ADR-0021 |
| A9 | Answers are written in the merchant's language | `golden.*.language_match_rate` |
| A10 | The ten challenge payloads run end to end for a signed-in merchant with one command | `scripts/run_scenarios.py` |
| A8 | The container runs as non-root on a read-only filesystem and serves the challenge payload | CI `docker` job |
