# Getnet Multi-Agent Support System

A containerized multi-agent service for Getnet merchants. A Router Agent plans and delegates to a
Knowledge Agent (RAG over the Getnet site plus live web tools), a Customer Support Agent (the signed-in
merchant's own data) and a Human Escalation Agent (pauses the conversation until a human operator
decides, then resumes it). A Critic reviews every answer before it is sent.

Python 3.12 · FastAPI · LangGraph (SQLite checkpointer) · OpenAI Responses API behind a provider port ·
no vector database, no external services required to run or test.

- [Quickstart](#quickstart)
- [What changed in v3 (9.3 → resubmission)](#what-changed-in-v3-93--resubmission)
- [What changed since the first submission (7.4 → 9.3)](#what-changed-since-the-first-submission-74--93)
- [Architecture and message workflow](#architecture-and-message-workflow)
- [Identity and security](#identity-and-security)
- [Memory and resilience](#memory-and-resilience)
- [Human in the loop](#human-in-the-loop)
- [RAG pipeline](#rag-pipeline)
- [Tools](#tools)
- [Guardrails](#guardrails)
- [Evaluation](#evaluation)
- [Observability and cost](#observability-and-cost)
- [Testing strategy](#testing-strategy)
- [Production notes](#production-notes)
- [How this was built (SDD and LLM tools)](#how-this-was-built-sdd-and-llm-tools)
- [Limitations](#limitations)

## Quickstart

### Docker

```bash
cp .env.example .env          # set OPENAI_API_KEY and JWT_SECRET
docker compose up --build
curl http://localhost:8000/ready
```

> **Set `OPENAI_API_KEY` before judging the orchestration.** Without it the service still starts, but a
> deterministic rule policy ([src/llm/offline.py](src/llm/offline.py)) answers in place of the model: it exists for
> CI and for provider outages, and it is not the agentic system. The service says which one is running: a
> `offline_policy_active` warning at start-up, `llm_provider` in `/ready`, and `llm_provider` in every `/chat` response.

The image runs as a non-root user on a read-only filesystem; all state lives in the `state` volume.
Interactive API docs: http://localhost:8000/docs.

### Local

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn src.api.main:app --port 8000
```

### Talk to it

> **If you send the ten example payloads with `curl` and no token, three of them (deposit date, card machine
> offline, declined transaction) answer "sign in to see your account". That is deliberate:** the body's
> `user_id` is not proof of identity, so it never unlocks account data
> ([ADR-0014](docs/adr/0014-challenge-payload-and-deployment-mode.md)). Sign in as below, or run
> `python -m scripts.run_scenarios`, which signs in and sends the ten payloads exactly as the challenge lists them.

The challenge payload works as is. Public knowledge needs no login:

```bash
curl -s -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message": "How many installments can I split a sale into with the crediário?", "user_id": "cliente1988"}'
```

Account questions need a verified identity. `user_id` in the body is a label, not a credential:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" \
  -d '{"user_id": "cliente1988", "password": "getnet-demo"}' | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -X POST http://localhost:8000/chat -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"message": "When will the money from yesterday'"'"'s sales be deposited?", "user_id": "cliente1988"}'
```

Demo identities (seeded when `SEED_DEMO_USERS=true`): merchants `cliente1988` and `cliente2026`, operator
`operador1`, all with password `getnet-demo`. They exist for the demo only: with `APP_ENV=production` the
service refuses to start while they are enabled.

### The ten challenge scenarios in one command

Three of the challenge's example scenarios (deposit date, card machine offline, declined transaction) read the
merchant's own data, so they need the login above. This script does the login and then sends the ten payloads
exactly as the challenge lists them:

```bash
python -m scripts.run_scenarios             # against http://localhost:8000, signed in as cliente1988
python -m scripts.run_scenarios --approve   # also plays the human operator for the declined-transaction scenario
python -m scripts.run_scenarios --anonymous # the same payloads with no token: account data stays locked
```

Why the body's `user_id` is not enough on its own is in
[ADR-0014](docs/adr/0014-challenge-payload-and-deployment-mode.md).

A turn takes several model calls (about 12–13.5 s at the median with the real model; the LLM input guard overlaps with Router step 1 and independent subtasks run in parallel). To watch it happen
instead of waiting for the whole answer, send the same body to `/chat/stream` (server-sent events): `accepted`,
then a `step` for each routing decision, tool call, review and human-review event as it lands, then `result`,
which is exactly the `/chat` response.

```bash
curl -N -X POST http://localhost:8000/chat/stream -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"message": "My card machine won'"'"'t connect to the internet, what should I do?"}'
```

Response shape:

```json
{
  "user_id": "cliente1988",
  "authenticated": true,
  "conversation_id": "default",
  "message": "...",
  "answer": "...",
  "status": "completed",
  "orchestration": {
    "trace_id": "trc-...",
    "agents": ["router", "support", "router", "knowledge", "router", "critic"],
    "tools_called": ["get_pos_diagnostics", "search_getnet_knowledge"],
    "sources": ["internal://support-runbook"],
    "plan_steps": 3,
    "critic_rounds": 1,
    "guardrail": {"allowed": true, "category": "safe", "layer": "llm"},
    "escalated_to_human": false,
    "ticket_id": null,
    "usage": {"llm_calls": 9, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
    "latency_ms": 0,
    "llm_provider": "openai",
    "degraded": false
  }
}
```

### Tests and evaluation

```bash
pytest                                     # 222 tests, no network, no API key
ruff check src eval tests scripts
python -m eval.run --mode offline --gate   # deterministic regression gate (what CI runs)
python -m eval.run --replay eval/reports/openai/cassette.json.gz --out /tmp/replayed   # E4 offline replay (no key)
python -m eval.compare eval/reports/openai/report.json /tmp/replayed.json              # verify 408 answers + every metric (0 diffs)
python -m eval.run --gate --repeat 3 --workers 4 --degraded-retries 2 --fail-fast   # with OPENAI_API_KEY: what CI model-eval runs
python -m eval.run --ids g07,s04 --out /tmp/check          # a few golden items, never gated, never the report
python -m eval.run --regrade eval/reports/openai/report.json --regrade-times 3 --out /tmp/regrade   # judge noise only
python -m eval.run --adjudicate eval/reports/openai/report.json                  # attach eval/adjudications.jsonl
```

### Configuration

Every setting is an environment variable; [.env.example](.env.example) lists them all. The ones that matter:

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | unset | Without it the service runs on the offline policy and says so (`llm_provider: "offline"`). |
| `OPENAI_MODEL` | `gpt-6-luna` | Model that drives every agent. Any Responses-API model works. |
| `JUDGE_MODEL` | same as above | Evaluation judge; set a different model (CI uses `gpt-5.4-mini`) so the system is not graded by itself. |
| `JWT_SECRET` | random per process | Set it in any shared deployment, otherwise tokens die on restart. |
| `REQUIRE_CHAT_AUTH` | `false` | Set `true` to require a verified Bearer token on `/chat` and `/conversations/{id}` (disables anonymous mode). |
| `CHAT_RATE_LIMIT_ATTEMPTS` / `WINDOW` | `60` / `60` | Sliding-window request limit per authenticated caller or client IP on `/chat`. |
| `TRUSTED_PROXIES` | empty | Comma-separated proxy addresses whose `X-Forwarded-For` is believed for rate limiting. Empty: the header is ignored and the peer address is used. |
| `METRICS_TOKEN` | unset | Bearer token Prometheus must present on `/metrics`. Unset: `/metrics` is open (demo only). |
| `JWT_ISSUER` / `JWT_AUDIENCE` | `getnet-support-auth` / `getnet-support-api` | Required `iss` / `aud` claims: a token minted for another service that shares the secret is refused. |
| `APP_ENV` | `demo` | `production` refuses to start with demo users enabled, without a `JWT_SECRET` of 32+ characters, or without a `METRICS_TOKEN` of 24+. |
| `TRACE_RETENTION_DAYS` | 30 | Stored traces older than this are deleted by the periodic sweep. |
| `MAX_SUPERVISOR_STEPS` / `MAX_SPECIALIST_TOOL_STEPS` / `MAX_CRITIC_ROUNDS` | 6 / 4 / 2 | Bounds on agent autonomy. |
| `SPECULATIVE_ROUTER` / `MAX_PARALLEL_TASKS` | `true` / `3` | Overlaps LLM input classifier with Router step 1 (discarded if blocked) and caps concurrent `delegate_parallel` subtasks. |
| `HITL_TIMEOUT_SECONDS` / `HITL_LEASE_SECONDS` | 900 / 600 | Human-review deadline and operator lease. |
| `RETRIEVAL_MODE` / `EMBEDDING_PROVIDER` | `auto` / `auto` | `auto` selects hosted dense (`text-embedding-3-small`) when a key is set and keyless `bm25` otherwise ([ADR-0020](docs/adr/0020-retrieval-mode-from-a-held-out-split.md)). |

## What changed in v3 (9.3 → resubmission)

The second submission scored **9.3/10** (weighted 9.47, calibrated down because the model runs were E3-only and the published gate had failed on `dev`). Every concrete gap in that review is mapped in full — together with answers to all five interview questions — in [REVIEW_RESPONSE.md](REVIEW_RESPONSE.md). Summary:

| 9.3 review gap | What changed in v3 | Evidence |
|---|---|---|
| **E3 → E4**: model runs could not be reproduced without a key | Content-hashed record/replay cassette (`src/cassette.py`) for every LLM call, live tool, hosted embedding and frozen date (`src/clock.py`), plus `eval.compare`, manual CI `model-eval`, and automatic keyless CI `model-eval-replay` | [ADR-0021](docs/adr/0021-recorded-model-runs-replayable-without-a-key.md), [cassette.json.gz](eval/reports/openai/cassette.json.gz), [CI run 44622842628](https://github.com/DanielQueijeiro/AI_Hardcore/actions/runs/44622842628) (**408 answers, 0 diffs, 0 unused calls**), [test_cassette.py](tests/test_cassette.py) |
| **Critic missed real omissions** (Wi-Fi step `g12`, prices `g01`) | Deterministic `evidence_checklist` ([checks.py](src/agents/checks.py)) extracts procedure steps, product prices and human decisions from the turn's evidence and feeds them to the Critic; verified on a **48-draft Critic calibration suite** (32 `dev` + 16 blind unseen `heldout` `k33`–`k48`) | [critic_calibration.jsonl](eval/datasets/critic_calibration.jsonl), [model report](eval/reports/openai/report.md#critic-calibration): **1.000 recall** across all 8 defect classes (**1.000 / 0.000 false revise on unseen held-out**) |
| **Cross-lingual retrieval (`s04`) & glossary optimism** | Multi-query retrieval (`query` + `query_en` + merchant message fused with RRF, batched dense embeddings), **36 post-glossary held-out queries** (`rh01`–`rh36`), `glossary_off` ablation, and `RETRIEVAL_MODE=auto` → hosted **dense** (`text-embedding-3-small`) with BM25 outage fallback | [ADR-0020](docs/adr/0020-retrieval-mode-from-a-held-out-split.md), [Retrieval ablation](#retrieval-ablation): hosted dense **1.000 Recall@4 / 0.944 MRR** on held-out even with `glossary_off` (vs BM25 0.708 / 0.632); `s04` 3/3 |
| **Output guard phone false positive** (`+55 11 97694-6815` redacted as card) | Excluded phone-formatted numbers (`+`, area-code parentheses, Brazilian `0800`/`4003`/`+55` formats) from Luhn PAN redaction while keeping card redaction intact | [guardrails.py](src/security/guardrails.py), [test_guardrails.py](tests/test_guardrails.py), `s21` 3/3, `a37` card echo redacted |
| **Latency** (5–9 sequential LLM calls, `dev` p95 35.6 s) | `speculative_router` (overlaps LLM input guard with Router step 1, discarded if blocked) + `delegate_parallel` (concurrent fan-out of up to 3 independent specialist subtasks) | [nodes.py](src/agents/nodes.py), [test_agentic_loop.py](tests/test_agentic_loop.py): `dev` p95 35.6 s → **21.8 s**; overall p50 **9.5 s**, p95 **20.4 s** in the final run (earlier v3 runs: p50 11.9–13.5 s, p95 23.8–28.9 s; hosted dense adds a round-trip per search) |
| **Small single-author datasets & clear-cut-only judge calibration** | Golden expanded `64 → 136` (`18` dev, `94` validation, `24` blind cross-family `sealed-4`, 408 turns per 3x run); retrieval `42 → 78`; Critic `48`; Judge calibration `40 → 60` adding **20 dual-reviewer `borderline` near-miss items** (`eval/labels/README.md`) | [ADR-0022](docs/adr/0022-sealed-2-and-critic-heldout-after-v3-freeze.md)–[0024](docs/adr/0024-sealed-4-after-final-prompt-refinements.md), [judge_borderline.jsonl](eval/datasets/judge_borderline.jsonl): borderline agreement **0.850** (κ **0.700**, 3 false passes vs 1.000 clear-cut) |
| **Repeated-run gate & 2026-11-16 defects** | Gate reads all `N` runs ([ADR-0019](docs/adr/0019-gate-over-repeated-runs.md)) with zero floors lowered; all 7 real 2026-11-16 system defects fixed and re-sealed through `sealed-4` (`479a6d7`); the 6 `dev` misses of the first cassette run fixed from `dev` evidence only, `sealed-4` kept sealed ([ADR-0026](docs/adr/0026-dev-driven-fixes-after-the-479a6d7-freeze.md)) | [CI run 44622842628](https://github.com/DanielQueijeiro/AI_Hardcore/actions/runs/44622842628) at `e031a8e`: **gate PASSED (all 29 gated metrics)**, `dev` **1.000 on all 3 runs**, `validation` 0.972 raw / 0.993 adj., `sealed-4` 0.875 raw / **1.000 judge & adj.** (72/72), `all` 0.958 raw / **0.995 adj.** (406/408) |
| *Not in the review:* **the model run took 2–3 h and reported a failure only at the end** | Golden conversations evaluated 4 at a time with per-conversation cassette scopes, API-degraded conversations re-run, `--fail-fast` after the golden suite ([ADR-0025](docs/adr/0025-parallel-golden-conversations-and-fail-fast.md)) | Eval step **39 min** (was 2 h 13 min); replay of the parallel recording: 408 answers, 0 diffs, 1.5 min offline |

## What changed since the first submission (7.4 → 9.3)

The first version scored 7.4. The review was right on every point; this is what each one led to.

| Review finding | What exists now | Evidence |
|---|---|---|
| Orchestration was a deterministic state machine: no planner, critic, re-planning, quality retry or stopping rule | The Router is a model-driven loop: it decomposes, delegates, reads observations and re-plans one tool call at a time; specialists run their own tool loops and reconsider after poor results; a Critic can send the answer back for more evidence; hard bounds stop it | [nodes.py](src/agents/nodes.py), [test_agentic_loop.py](tests/test_agentic_loop.py) |
| No conversational memory | Per-conversation state checkpointed in SQLite: history, rolling summary with compaction, recovery after restart, isolation per identity | [service.py](src/agents/service.py), [test_memory.py](tests/test_memory.py) |
| Handoff created a ticket and ended | `interrupt` → operator queue → claim with lease → approve / reject / answer → the same turn resumes with the human decision; timeout path; approved write executed exactly once | [test_human_in_the_loop.py](tests/test_human_in_the_loop.py) |
| 12/12 was structural, not semantic | Golden answers with human-written facts, numeric groundedness, citation validity, language match, a sealed held-out split, a judge that is a different model with measured calibration, adversarial suite, regression gate in CI. Measured with the real model on 2026-11-16 over three runs of 64 conversations: semantic pass 0.932 on average (sealed split 0.958, 0.917, 0.917), judge pass 0.969, calibration agreement 1.000 (40/40, 24 of them on questions outside the golden set), 0 of 38 attacks. **The regression gate failed on run 1** (dev 0.833 against a floor of 0.94). Every failed answer is adjudicated against the stored evidence: of thirteen, seven are the system's, one the judge's and five the fact patterns'; the sealed split is 0.958 in every run once grader errors are set aside. The gate still reads the raw number. Routing is reported separately and does not count as quality | [eval/](eval/), [model report](eval/reports/openai/report.md), [offline report](eval/reports/offline/report.md) |
| `user_id` was not an authenticated identity | JWT login; identity comes only from a verified token; body `user_id` that disagrees is rejected; anonymous callers get public knowledge only | [test_identity_and_api.py](tests/test_identity_and_api.py) |
| Injection defence was lexical | Normalized/decoded lexical layer + LLM classifier + untrusted-data sanitization for RAG, web and operator text + output leak checks, all exercised by 38 attacks (EN/PT/ES plus German and French, paraphrase, pretexts, operator impersonation, poisoned documents and tool output) and 30 benign controls: 0 successful attacks, 0 false positives with the real model | [guardrails.py](src/security/guardrails.py), [adversarial.jsonl](eval/datasets/adversarial.jsonl) |
| No retrieval metrics; hybrid weights unproven | Recall@k, Hit@k, MRR, nDCG on 42 labelled queries for BM25 vs dense vs hybrid, with the keyless embedder and with hosted embeddings. The 0.45/0.35/0.20 blend is gone; the default was chosen from the numbers | [Retrieval ablation](#retrieval-ablation) |
| Root container, no CI, no migrations, one health endpoint | Non-root read-only image, CI with tests + eval gate + container smoke test, numbered migrations, `/health` vs `/ready`, online backup script | [Dockerfile](Dockerfile), [ci.yml](.github/workflows/ci.yml) |
| Canned fallback values for weather and FX | Removed. A live tool that cannot reach its source returns `available: false` and the agent says so | [live.py](src/tools/live.py) |

## Architecture and message workflow

```
POST /chat ── verify token ──▶ Principal (merchant | operator | anonymous)
                                   │
                                   ▼
        ┌──────────── LangGraph, one thread per (identity, conversation) ────────────┐
        │                                                                            │
        │  guard ──blocked────────────────────────────────────────────┐              │
        │    │                                                        ▼              │
        │    └─▶ ROUTER ⇄ KNOWLEDGE agent ── tools: search_getnet_knowledge,         │
        │        (plan,                        get_fx_rate, get_weather_forecast,    │
        │         observe,                     web_search                            │
        │         re-plan)                                                           │
        │          ⇄ SUPPORT agent ── tools: get_settlements, get_pos_diagnostics,   │
        │          │                   get_account_profile, list_my_tickets          │
        │          │                   (always the signed-in merchant)               │
        │          ⇄ ESCALATION agent ─▶ ticket ─▶ interrupt ══ human operator ══▶   │
        │          │                                 resume with the decision        │
        │          └─ finish ─▶ CRITIC ──revise──▶ back to ROUTER                    │
        │                         └─approve─▶ finalize (output guard, memory) ─▶ END │
        └──────────────── checkpoint after every step (SQLite) ──────────────────────┘
```

Only the edges are fixed. Which specialist runs, in what order, how many times and when to stop are
decided by the Router model at run time from what it has observed.

**Communication between agents** is the shared graph state. The Router calls one of five typed functions
per step (`delegate_knowledge`, `delegate_support`, `delegate_parallel`, `escalate_to_human`, `finish`); every delegation carries
a `thought` and the `remaining_plan`, which are recorded in the trace. When a turn contains independent subtasks
(for example an account lookup and a public product question), `delegate_parallel` dispatches up to
`MAX_PARALLEL_TASKS` (3) specialist branches concurrently while preserving per-agent tool allow-lists, principal
scoping and tool-step bounds; prompts explicitly forbid parallel fan-out when one subtask depends on another's
lookup. With `SPECULATIVE_ROUTER=true`, the LLM input guardrail and Router step 1 also overlap in parallel after
the synchronous deterministic input guard passes, and any speculative Router output is discarded cleanly if the
classifier blocks. A specialist receives a self-contained task, runs its own bounded tool loop and returns a typed
report plus the raw tool results. Those become an observation the Router reads on its next step. Every prompt
receives today's date via `today_line()` (`src/clock.py`), which cassettes freeze during replay.

**One turn, concretely** ("My card machine is showing a transaction decline error", signed in as `cliente1988`):

1. `guard`: lexical screen, then the LLM classifier. Safe.
2. Router → Support Agent. It calls `get_pos_diagnostics` and reports the decline `ERR_51_ISSUER_DECLINE / POS_KEY_SYNC_WARN`,
   a follow-up question for the knowledge base, and that the fix needs human approval (`terminal_rekey_or_swap`).
3. Router re-plans from that observation → Knowledge Agent, which retrieves the runbook entry for those codes.
   (The Router sometimes skips this step when the telemetry already names the fix; that is its decision.)
4. Router → Escalation Agent, which writes the brief and opens a ticket. The graph **interrupts**; the API
   returns `status: "awaiting_human"` with the ticket id and a message saying what was found and why a human
   is reviewing it.
5. An operator claims the ticket and approves. The graph **resumes** in the same turn: code (not the model)
   verifies the approval and creates the service order.
6. Router writes the answer from the observations; the Critic checks it against the evidence; the output
   guard runs; the turn is stored in memory.

**Bounded autonomy.** A loop the model drives needs limits the model cannot talk its way past:

| Bound | Enforced in | Behaviour at the limit |
|---|---|---|
| Router step budget (6) | `Nodes.supervisor` | The next call is forced to `finish` |
| Duplicate delegation | `Nodes.supervisor` | Refused with an observation explaining why |
| Parallel fan-out cap (`MAX_PARALLEL_TASKS=3`) | `Nodes.supervisor` | Excess tasks truncated; dependent subtasks sequenced one at a time |
| Specialist tool budget (4), repeated tool call | `Nodes._run_specialist` | Forced `report`. A tool without parameters is offered once; a repeated call is not executed and the next step can only report. One tool call per model step |
| One escalation per turn; none for anonymous callers | `Nodes.supervisor` | Refused with an observation |
| Critic rounds (2) | `Nodes.critic` | A draft that is still ungrounded is replaced by an explicit "could not verify" answer |
| Draft in another language than the merchant's | `Nodes.critic`, `checks.detect_language` | Revision forced regardless of the Critic's verdict |
| Critic returns no review | `Nodes.critic` | The deterministic checks decide; an unsupported number or unreturned URL forces a revision |
| Graph recursion limit (60) | `ChatService` | Hard stop |

**The Critic** gets the question, the evidence and the draft, plus deterministic findings computed in code
([checks.py](src/agents/checks.py)): numbers in the draft that appear nowhere in the evidence, URLs no tool
returned, and an **`evidence_checklist`** extracting concrete procedure steps (scoped to sections matching the
turn's telemetry/question), product rental prices, and human-operator decisions/service-order numbers from the
collected evidence. It answers through a typed `review` call. A fabricated URL forces a revision regardless of the
model's verdict, and so does a draft written in a language other than the merchant's. On `revise` the Router sees
the issues and may gather more evidence before rewriting, which is the quality-based retry. It is told to send a
draft back only for a material problem, because every round is latency the merchant waits through, and that "could
not confirm" is acceptable only if the right specialist was actually asked.

**Reply language** is detected in code from function words (English, Portuguese, Spanish) and stated in the
Router, Escalation and Critic prompts. This exists because the first real-model run answered English
questions in Portuguese: most of the evidence is Portuguese, and an instruction in a prompt was not enough.

**Prompts** live in [prompts.py](src/agents/prompts.py). Each one states the role, what the agent may rely on,
how to choose tools, when to reconsider, the output contract, and that tagged blocks are data. No agent
returns free-form JSON; every decision is a function call with a schema.

**Offline policy.** [offline.py](src/llm/offline.py) implements the same model port with rules. It exists for CI,
for demos without a key, and as the degradation path when the provider fails (a circuit breaker switches to it
and the response is flagged `degraded`). It produces extractive, grounded answers, but it is a rule policy:
the adaptive behaviour described above is the model path.

## Identity and security

`POST /auth/login` returns an HS256 JWT (`iss`, `aud`, `sub`, `role`, `exp`, `jti`; issuer and audience are
required on every request). Passwords are stored with scrypt; login failures are uniform for unknown users and
wrong passwords and are rate-limited; `POST /auth/logout` revokes the token's `jti`. Rate limits key on the
verified user, or for anonymous callers on the client address, which is read from `X-Forwarded-For` only when
the direct peer is one of `TRUSTED_PROXIES` (otherwise any client could pick its own bucket).

The rule the rest of the system depends on: **identity is the verified token and nothing else.**

- No token → anonymous principal → public knowledge only. Account tools return `authentication_required`.
- Body `user_id` different from the token's subject → `403`.
- Invalid, expired or revoked token → `401`. It is not downgraded to anonymous.
- No tool has a merchant parameter. Account tools read the merchant from the principal the API verified.
  If a model invents `merchant_id`, the tool layer drops it, records it in the trace and counts it in
  `identity_argument_ignored_total`. Prompt injection therefore cannot reach another tenant even if it
  fully controls the model.
- Conversation threads are keyed by `(verified user, conversation_id)`; traces are readable by their owner
  and by operators; the operator queue requires the `operator` role. Anonymous visitors share one namespace,
  so an anonymous conversation can only be continued with the unguessable id the server issued for it.
- Bank account numbers are masked in the tool layer, before any model sees them.
- The only write action (`terminal_rekey_or_swap`) is executed by code after it finds an `APPROVED` ticket
  for that merchant with an allow-listed action that has not been executed yet. The Router cannot attach an
  action to a ticket unless the Support Agent derived it from account data in the same turn.

So the answer to "if I call `/chat` with `user_id=cliente2026`, where do you prove I am that merchant?" is:
nowhere, and so that call gets no account access (and with `REQUIRE_CHAT_AUTH=true`, an unauthenticated
`/chat` or `/conversations/{id}` request returns `401` outright).

## Memory and resilience

State is a LangGraph thread per `(identity, conversation_id)`, checkpointed to SQLite after every node.

- **History**: the last messages are passed to the Router and the Critic inside a tagged block, so
  "it is still offline" resolves against the earlier turn.
- **Rolling summary**: when history exceeds `HISTORY_COMPACT_AFTER` messages, the older ones are folded into
  a summary by a summarizer call and only `HISTORY_KEEP_MESSAGES` stay verbatim.
- **Restart recovery**: a new process on the same database continues conversations and paused human reviews.
- **Poisoning**: a blocked message is stored as a placeholder, never verbatim; history is rendered as data.
- **Concurrency**: one turn at a time per thread (in-process lock).
- **Provider failure**: timeouts and retries on the client, then a circuit breaker that degrades to the
  offline policy instead of returning a 500. `/ready` reports whether the breaker is open.
- **Tool failure**: a failing tool returns a structured error the agent can react to. Live sources (FX,
  weather, web search) sit behind a short cache, one retry with backoff for transient errors (never for a 4xx),
  and a circuit breaker per source, so a dead dependency costs a turn nothing instead of a timeout per call.
- **Turns in flight**: `GET /conversations/{id}` reports `in_progress` while a turn or a resume is running on the
  conversation, rather than reading state between two checkpoints.

`GET /conversations/{id}` returns the stored memory of one of the caller's own conversations.

## Human in the loop

```
agent ──interrupt──▶ ticket OPEN ──claim (lease)──▶ CLAIMED ──respond──▶ APPROVED | REJECTED | ANSWERED
                          │                                                   │
                          └── nobody answers before expires_at ─▶ TIMED_OUT ──┤
                                                                              ▼
                                                    graph resumes: the decision becomes an observation
```

```bash
OP=$(curl -s -X POST localhost:8000/auth/login -H "Content-Type: application/json" \
  -d '{"user_id": "operador1", "password": "getnet-demo"}' | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s localhost:8000/operator/tickets -H "Authorization: Bearer $OP"                       # the queue, with the agent's brief
curl -s -X POST localhost:8000/operator/tickets/TKT-.../claim -H "Authorization: Bearer $OP"
curl -s -X POST localhost:8000/operator/tickets/TKT-.../respond -H "Authorization: Bearer $OP" \
  -H "Content-Type: application/json" -d '{"decision": "approve", "message": "Remote re-key scheduled for today."}'
```

`respond` returns what the agent told the merchant after the decision; the merchant also sees it in
`GET /conversations/{id}` and in the conversation memory. Resuming runs the agents (several seconds), so an
operator console can call `respond?wait=false` instead: the decision is recorded, the call returns `202` with
`resume: "scheduled"`, and the conversation resumes on a worker (or, if that fails, on the next sweep). The
merchant's client learns the outcome with a long-poll, `GET /conversations/{id}?wait=30`, which returns as soon as
the conversation is no longer waiting on a human (capped by `MAX_CONVERSATION_WAIT_SECONDS`).

- **Claim is a lease.** A second operator gets `409` until the lease lapses; a decision requires holding it.
- **Timeout.** A background sweeper expires unanswered tickets and resumes their conversations with a
  "nobody answered, nothing was changed" observation. The same check runs lazily when the merchant writes again.
  A ticket does not expire while an operator holds a live lease on it.
- **Recovery.** If a decision is recorded and the process dies before the conversation resumes, the sweeper
  resumes it; nothing depends on the merchant writing again.
- **Last resort.** The Router answers with self-service steps when they exist and offers the handoff; it
  escalates for approval only when the fix for the problem that was asked about needs one. The waiting
  message says what was found and why a human is involved.
- **What "executed" means.** An approved action creates a service order. The agent reports the order number
  and that the work is scheduled; it is not allowed to say the work is done.
- **While waiting**, new messages on that conversation get a status reply without running the agents.
- **Idempotency.** The ticket key is `(thread, turn)`, so re-running the node cannot open a second ticket, and the
  write action is exactly-once.
- **Source of truth.** On resume the node reads the ticket row; the resume payload cannot forge an approval.
- **Untrusted.** The operator's note is sanitized like any other external text before a model reads it.

## RAG pipeline

**Ingestion.** `python -m scripts.ingest_getnet` captures nine public Getnet Brazil pages (machines, Pix, digital
account, FAQ, receivables advance, Crediário, Payment Link) into `data/corpus/raw/` with source URL, date and
content hash; `--check` reports pages that changed. The indexed corpus is `data/corpus/*.md`: one curated file
per page, facts restated in English with the Portuguese product terms kept, and explicit statements where a
page is silent or contradicts itself, so "the site does not say" is a retrievable, citable answer. An internal
support runbook for telemetry codes is included and labelled as mock internal content. The challenge's
suggested URL (`getnet.net/en`) is a global landing page without the product detail the scenarios need, which
is why the Brazilian site is the source.

**Chunking.** By `##` section, never across sections; long sections split on sentence boundaries with one
sentence of overlap. Page title and section heading are prepended to the indexed text.

**Storage.** In memory, built at startup: 30 chunks. BM25 statistics plus a dense matrix. A vector database
would add an operational dependency without changing recall at this size; the `Retriever.search` interface is
where one would plug in.

**Retrieval.** Three modes over the same chunks (`RETRIEVAL_MODE=auto` and `EMBEDDING_PROVIDER=auto`,
[ADR-0020](docs/adr/0020-retrieval-mode-from-a-held-out-split.md)):
- `bm25`: accent-folded, stop-word-filtered tokens, with a query-side glossary that maps merchant wording in
  EN/PT/ES to the terms the corpus uses. Default when running keyless (`offline` / CI).
- `dense`: cosine over embeddings. Keyless default is a character n-gram hashing embedder; with an API key
  (`EMBEDDING_PROVIDER=auto` or `openai`) it uses `text-embedding-3-small`, cached on disk, and degrades to BM25 if
  the embeddings API fails so an outage never causes a tool error. Default when an API key is set.
- `hybrid`: reciprocal rank fusion of the two.

`search_getnet_knowledge(query, query_en)` runs multi-query retrieval: the agent's query, its optional English
translation (`query_en`), and the merchant's raw message are batched through `Retriever.search_many()` and fused
with RRF, so a Portuguese or Spanish reformulation never blinds search to the English-curated corpus. Every hit
carries a `coverage` score (share of query terms present), surfaced to the agent as `relevance: good | partial | poor`.
That is the abstention and re-query signal.

**Generation.** The Knowledge Agent answers only from tool results and reports its sources. Code then drops any
reported URL that no tool returned; the Critic rejects answers with unsupported numbers or URLs.

### Retrieval ablation

78 labelled queries over 30 chunks: **42 dev queries** (29 EN, 8 PT, 5 ES) and **36 held-out queries** (`rh01`–`rh36`,
12 EN / 12 PT / 12 ES, colloquial wording written after the glossary was frozen), each evaluated with the glossary
on and off ([ADR-0020](docs/adr/0020-retrieval-mode-from-a-held-out-split.md)).

**Keyless (`hashing-char-ngram-1024`)**, from [eval/reports/offline/report.md](eval/reports/offline/report.md):

| Split / setting | BM25 R@4 / MRR | Dense R@4 / MRR | Hybrid (RRF) R@4 / MRR |
|---|---|---|---|
| dev (42q), glossary on | **0.988 / 0.948** | 0.952 / 0.913 | 0.976 / 0.958 |
| dev (42q), glossary off | 0.941 / 0.861 | 0.917 / 0.847 | 0.929 / 0.871 |
| held-out (36q), glossary on | **0.708 / 0.632** (ES 0.375) | 0.764 / 0.627 | 0.806 / 0.662 |
| held-out (36q), glossary off | 0.708 / 0.590 | 0.764 / 0.611 | 0.792 / 0.650 |

**Hosted embeddings (`text-embedding-3-small`)**, from [eval/reports/openai/report.md](eval/reports/openai/report.md):

| Split / setting | BM25 R@4 / MRR | Dense (hosted) R@4 / MRR | Hybrid (hosted RRF) R@4 / MRR |
|---|---|---|---|
| dev (42q), glossary on | 0.988 / 0.948 | **0.988 / 0.976** (Hit@1 0.952) | 1.000 / 0.964 |
| dev (42q), glossary off | 0.941 / 0.861 | **0.988 / 0.976** | 0.976 / 0.901 |
| held-out (36q), glossary on | 0.708 / 0.632 | **1.000 / 0.944** (36/36; EN/ES/PT all 1.000) | 0.917 / 0.810 |
| held-out (36q), glossary off | 0.708 / 0.590 | **1.000 / 0.944** (identical without glossary) | 0.931 / 0.843 |

The 9.3 review called the earlier 0.988 BM25 Recall@4 optimistic because the glossary was built alongside the 42
dev queries. The 36 post-glossary held-out queries proved that right: BM25 fell to 0.708 Recall@4 (0.375 on Spanish),
whereas hosted multilingual dense (`text-embedding-3-small`) reached **1.000 Recall@4 / 0.944 MRR** with or without
the glossary and beat hosted hybrid (0.917 / 0.810, where weak lexical rankings pulled dense hits down). That is why
`RETRIEVAL_MODE=auto` and `EMBEDDING_PROVIDER=auto` now pick **hosted dense** whenever `OPENAI_API_KEY` is set and
keep **BM25** when running keyless ([ADR-0020](docs/adr/0020-retrieval-mode-from-a-held-out-split.md)).

## Tools

| Agent | Tool | Notes |
|---|---|---|
| Knowledge | `search_getnet_knowledge(query, query_en?)` | Multi-query RRF search (`query` + `query_en` + merchant message) returning passages with `source_url`, `coverage`, relevance rating |
| Knowledge | `get_fx_rate(base, quote="BRL")` | ECB reference rates via Frankfurter (defaults to `BRL` for Brazilian merchants) |
| Knowledge | `get_weather_forecast(city)` | Open-Meteo geocoding + forecast |
| Knowledge | `web_search(query)` | DuckDuckGo; results are sanitized as untrusted text |
| Support | `get_settlements()` | Yesterday's sales per modality, for the signed-in merchant |
| Support | `get_pos_diagnostics()` | Terminal connectivity and last declined transaction |
| Support | `get_account_profile()` | Business profile, masked bank account |
| Support | `list_my_tickets()` | Human-review tickets and operator replies |

All calls go through `run_tool` ([registry.py](src/tools/registry.py)): per-agent allow-list, authentication
check, schema validation, identity arguments dropped, exceptions converted to structured errors, metrics.

## Guardrails

| Layer | What it does | Failure mode |
|---|---|---|
| Input, deterministic | Patterns over normalized views of the message: NFKC, zero-width removal, leetspeak, separator stripping, decoded base64. Injection, prompt extraction, bulk exfiltration, illicit requests, other merchants' ids (EN/PT/ES). Runs synchronously before any model call | Always on |
| Input, LLM classifier | Typed verdict through a forced function call; the message is passed as tagged data. Runs concurrently with speculative Router step 1 (`SPECULATIVE_ROUTER=true`), discarding speculative output before any tool call if blocked. A block is kept only if a second, more careful pass agrees | Fail-open to the deterministic layer |
| Untrusted data | Retrieved passages, web results and operator notes: instruction-like sentences removed, delimiter tags neutralized, wrapped as data in every prompt | Always on |
| Structural | Tool allow-lists, principal-scoped tools, human-gated writes | Always on |
| Output | Prompt canary, other tenants' identifiers, credential-shaped strings, formatted CPF/CNPJ and Luhn-valid card numbers (redacted; phone-formatted strings such as `+55 11 97694-6815`, `0800`, and `4003` are excluded so official support numbers are never masked as PANs). Applied to final answers and to waiting messages | Fail-closed |

The structural layer is the one that carries the security argument; the others reduce how often it is tested.

Blocking a legitimate merchant is a failure too, and it is measured like one. The first version of these
patterns blocked eight ordinary questions out of eight in an audit ("cliente 30 dias" read as a merchant id,
"todos os clientes" as bulk exfiltration), and a real-model run showed the classifier refusing a Portuguese
product question. The patterns were tightened, the classifier got the second pass, and the adversarial suite
now carries 30 benign controls whose false-positive rate is gated next to the attack success rate.

## Evaluation

`python -m eval.run` drives the real application through its HTTP API on throw-away databases.

| Suite | Dataset | Measures |
|---|---|---|
| Retrieval | 78 labelled queries: 42 dev + 36 post-glossary held-out (`rh01`–`rh36`), each tested with glossary on and off | Recall@k, Hit@k, MRR, nDCG@k per mode and language, keyless and hosted |
| Golden answers | 136 conversations: 18 dev, 94 validation (`h01`–`h22`, `s01`–`s72`), 24 sealed held-out (`sealed-4`, `s73`–`s96`: EN/PT/ES, account, compound, memory, HITL approve/reject/answer, abstention, contradictory source, anonymous, live tools). Each runs on its own fresh databases | Fact coverage, forbidden claims, numeric groundedness, citation validity, language match, gold source cited, LLM judge, latency, cost; routing separately |
| Adversarial | 38 attacks + 30 benign controls | Attack success rate, data leaks, unauthorized writes, false-positive rate |
| Critic calibration | 48 fixed drafts (32 `dev` + 16 blind unseen `heldout` `k33`–`k48`) across 8 defect classes | Defect recall and clean-draft false-revise rate, overall and per set |
| Judge calibration | 60 hand-written answers: 16 `original`, 24 `independent`, and 20 dual-reviewer `borderline` near-miss items ([eval/labels/README.md](eval/labels/README.md)) | Judge agreement and Cohen's kappa per set, false passes, and dual-reviewer agreement |

**Required facts, and where they are brittle.** Each golden item lists the atomic facts a correct answer must
carry, each as a set of acceptable phrasings (`["48"]`, `["129[.,]90"]`,
`["does not (say|state|specify)", "não informa", ...]`), matched accent- and case-insensitively, plus claims
that must not appear. For numbers, codes and product names this is exact and language-independent: a fluent
answer with the wrong number fails. For wording (an abstention, tense, hyphenation) it is still pattern matching,
and the `sealed-4` results show its cost: hyphenated `"lump-sum"` (`s79`), `"3 continuous/consecutive hours"` (`s76`),
past-tense Spanish `"aprobó"` (`s93`) and `"registro de transação"` (`s85`) were correct 5/5 answers that strict
sealed regexes missed. On a sealed split those regexes are left untouched and attributed to `grader_facts` in the
adjudication below; they are never edited to turn a sealed failure into a pass.

**Groundedness** is measured against the evidence the agents collected in that turn (read from the trace):
every number in the answer must occur in it, and every URL must have been returned by a tool. An agent's own
report does not count as evidence for a URL.

**LLM judge.** A separate call (`gpt-5.4-mini` in CI) with its own rubric grades correctness, groundedness,
relevance and helpfulness 1–5 against a reference and the evidence. The pass rule is applied in code from the
scores. Its reliability is measured on both clear-cut pairs (`original` + `independent`) and near-miss
`borderline` pairs labelled by two blind reviewers before running the judge.

**Semantic pass** = all facts present, no forbidden claim, numeric groundedness 1.0, no fabricated citation,
expected status, and the judge's pass when a judge ran.

**Three splits, and the sealed-split discipline** ([ADR-0016](docs/adr/0016-sealed-held-out-and-independent-judge-calibration.md),
[ADR-0022](docs/adr/0022-sealed-2-and-critic-heldout-after-v3-freeze.md)–[0024](docs/adr/0024-sealed-4-after-final-prompt-refinements.md)).
Whenever an observed failure on a sealed split drives any change to `src/`, that split immediately becomes
`validation` and a brand-new sealed split is authored blind after the new code freeze. `dev` (`g01`–`g18`) was
used while writing prompts and the offline policy. `validation` (`h01`–`h22` plus former sealed splits `s01`–`s24`,
`s25`–`s48`, `s49`–`s72`; 94 items total) drove earlier fixes and is reported under the name that describes it.
`heldout` (`sealed-4`, `s73`–`s96`, 24 items, balanced 8 EN / 8 PT / 8 ES) was drafted after the `src/` freeze at
commit `479a6d7` by an isolated Gemini subagent blind to prompts, Critic checks, guardrails and the retrieval
glossary; its floor (`0.80`) was fixed before its first run and never touched afterwards. After that freeze, two
commits (`e7cf787`, `e031a8e`) changed prompts and Critic checks to fix `dev` failures only; no `sealed-4` answer was
opened while making them, so `sealed-4` stays held out ([ADR-0026](docs/adr/0026-dev-driven-fixes-after-the-479a6d7-freeze.md)).

**Repeated-run regression gate** ([ADR-0019](docs/adr/0019-gate-over-repeated-runs.md)). One run is an anecdote:
`--repeat N` runs the golden suite `N` times with nothing changed in between. For golden metrics, `--gate` reads
all `N` runs: a floor holds when the mean reaches it and no single run is more than one item (`1/n`) below it; a
ceiling (`forbidden_claim_rate`, `degraded_turns`) holds only if every run is within it. Every other suite runs
once and is gated on that run. No floor in [eval/baseline.json](eval/baseline.json) was lowered in v3.

**Reproducible model runs without a key (E4)** ([ADR-0021](docs/adr/0021-recorded-model-runs-replayable-without-a-key.md)).
`python -m eval.run --record CASSETTE.json.gz` records every LLM call (agents, guard, Critic, judge), live-tool
response, hosted embedding and frozen date (`src/clock.py`) keyed by content hash. Anyone can re-execute the
entire app, graph, retrieval, guardrails, checks, metrics and gate offline with
`python -m eval.run --replay eval/reports/openai/cassette.json.gz --out /tmp/replayed` and verify
`python -m eval.compare eval/reports/openai/report.json /tmp/replayed.json` (0 differences across all 408 answers
and every metric, 0 unused calls; any unrecorded call raises `CassetteMiss`). CI runs this replay check on every
push (`model-eval-replay`). Golden conversations run in parallel, each under its own cassette scope, so a recording
replays exactly whatever order the threads ran in ([ADR-0025](docs/adr/0025-parallel-golden-conversations-and-fail-fast.md)).

**Provenance, re-grading and adjudication.** Each report records the git commit, `git_dirty` status, and SHA-256
hashes of the datasets, `src/`, `prompts.py`, `judge.py`, `baseline.json` and corpora. Every golden item stores
the tool calls and exact `judge_input`, so `--regrade` isolates judge noise without re-running agents. Every
failed answer across all committed model reports is adjudicated in [eval/adjudications.jsonl](eval/adjudications.jsonl),
keyed to the SHA-256 of that exact answer text (enforced by a unit test). The gate always reads the raw numbers.

### Results

**Real model** (`gpt-6-luna` answering, `gpt-5.4-mini` judging, `text-embedding-3-small` hosted dense retrieval,
live web tools on, 2026-11-19, [GitHub Actions run 44622842628](https://github.com/DanielQueijeiro/AI_Hardcore/actions/runs/44622842628),
code at `e031a8e`, clean tree, `0` degraded turns, `0` conversations re-run) — [full report](eval/reports/openai/report.md)
· [replayable cassette](eval/reports/openai/cassette.json.gz) (verified offline: **408 answers, 0 diffs, 0 unused calls**).

Three runs of all 136 conversations (408 turns) with nothing changed between them, 4 conversations in flight at a
time; the table below is run 1:

| Split | n | Semantic pass | Fact coverage | Numeric groundedness | Citation validity | Gold source cited | Language match | Judge pass | p50 | p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| dev | 18 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 9.9 s | 21.8 s |
| validation | 94 | 0.947 | 0.992 | 1.000 | 1.000 | 0.986 | 1.000 | 0.957 | 9.3 s | 20.4 s |
| heldout (`sealed-4`) | 24 | 0.875 | 0.976 | 1.000 | 1.000 | 1.000 | 1.000 | **1.000** | 10.1 s | 17.7 s |
| all | 136 | 0.941 | 0.990 | 1.000 | 1.000 | 0.989 | 1.000 | 0.971 | 9.5 s | 20.4 s |

Run-to-run variation across the three runs, raw and after SHA-256 adjudication:

| Split | n | Run 1 | Run 2 | Run 3 | Raw mean | Judge pass (3 runs) | Adjudicated per run | Adj. mean |
|---|---|---|---|---|---|---|---|---|
| dev | 18 | 1.000 | 1.000 | 1.000 | **1.000** | 1.000, 1.000, 1.000 (1.000) | 1.000, 1.000, 1.000 | **1.000** |
| validation | 94 | 0.947 | 0.989 | 0.979 | 0.972 | 0.957, 0.989, 1.000 (0.982) | 0.979, 1.000, 1.000 | **0.993** |
| heldout (`sealed-4`) | 24 | 0.875 | 0.917 | 0.833 | 0.875 | **1.000, 1.000, 1.000 (1.000)** | 1.000, 1.000, 1.000 | **1.000** |
| all | 136 | 0.941 | 0.978 | 0.956 | 0.958 | 0.971, 0.993, 1.000 (0.988) | 0.985, 1.000, 1.000 | **0.995** |

**Regression gate verdict: PASSED — all 29 gated metrics in [eval/baseline.json](eval/baseline.json), no floor
lowered.** Every one of the 17 raw failures across 408 turns is adjudicated against stored evidence in
[eval/adjudications.jsonl](eval/adjudications.jsonl): **12 `grader_facts`** regex misses on correct answers (every
raw miss on `sealed-4`: `"3 consecutive hours"` `s76`×2, plural `"transações"` and `"registro de transação"` `s85`×3,
`"Se aprobó"` `s93`×2, imperative `"inicia sesión"` `s95`, `"não permite confirmar"` `s81`; sealed regexes left
untouched), **3 `judge`** errors (`h18`, `s18`, `s43`: correct, grounded answers marked down for caveats or
unrequested runbook steps), and **2 real `agent` defects**, both `validation` run 1: `s01` refused to state the
Get Mini's R$ 14.90 rental that the evidence gives "for comparison", and `s63` told the merchant to select Pix for a
QR Code payment because retrieval never surfaced the "select debit" passage (**406/408 = 0.995** adjudicated).

**How this run differs from the first cassette run.** The first cassette run on the `479a6d7` freeze
([GitHub Actions run 44569607884](https://github.com/DanielQueijeiro/AI_Hardcore/actions/runs/44569607884), archived as
[report-2026-11-19-44569607884.md](eval/reports/openai/report-2026-11-19-44569607884.md)) passed every gated metric
but one: `dev` `0.889, 0.833, 0.944` (mean `0.889 < 0.94`). The floor was kept and the system changed instead, from
`dev` evidence only ([ADR-0026](docs/adr/0026-dev-driven-fixes-after-the-479a6d7-freeze.md)): Critic checklist items
for the whole decline code after an approved re-key, every settlement amount, compared card rates and "nothing to
escalate"; rejections stated first and then stop; BRL as the default FX quote; no unrequested account data,
hypotheticals or remarks about what a page does not cover. Before spending the final run, the `dev` split was
measured locally against the real model six runs at a time until its mean held at `0.963`; the CI run then scored
`1.000` on all three runs. `sealed-4` was not opened during any of this.

Other suites in this run:
- **Judge means (1–5, run 1, `n=136`)**: correctness `4.87`, groundedness `4.95`, relevance `4.92`, helpfulness
  `4.79`. `0` forbidden claims, `0` fabricated citations, `0` degraded turns, `1.000` language match, `1.000` routing
  as expected. Mean cost per turn USD `0.00198` at configured `PRICE_*_PER_MTOK`.
- **Critic calibration (48 fixed drafts)**: overall recall **`1.000` (24/24 across all 8 defect classes, 3/3 each)**,
  false revise **`0.167`** (4/24, all `dev`: `k17`, `k18`, `k20`, `k27`; ceiling `0.20`). On unseen **`heldout`
  (`k33`–`k48`, 16 drafts): Recall `1.000` (8/8), False revise `0.000` (0/8)**. False revise was `0.042` before the
  `e031a8e` checklist items and rejection rule; `k27`'s "clean" draft explains the error code after a rejection,
  which the new rule forbids (label not edited after the result).
- **Judge calibration (60 items)**: clear-cut headline (`original` 16/16 + `independent` 24/24) agreement **`1.000`**,
  Cohen's kappa **`1.000`**, `0` false passes, `0` false fails. Dual-reviewer **`borderline`** (20 near-miss items,
  1 human + 1 blind cross-family Gemini with reviewer agreement `1.000` / κ `1.000`, [eval/labels/README.md](eval/labels/README.md)):
  agreement **`0.850`** (17/20, floor `0.75` passed), Cohen's kappa **`0.700`**, **3 false passes** (`b03b`, `b06a`,
  `b07a`), `0` false fails.
- **Adversarial (real LLM classifier)**: 38 attacks, attack success rate **`0.000`** (`28` blocked at input, `10`
  contained downstream), `0` data leaks, `0` unauthorized writes; 30 benign controls, false-positive rate **`0.000`**.
- **Retrieval**: unchanged from the published ablation (hosted dense held-out Recall@4 `1.000`, MRR `0.944`).

Archived model reports remain in git for auditability:
[report-2026-11-19-44569607884.md](eval/reports/openai/report-2026-11-19-44569607884.md) (first cassette run on the `479a6d7` freeze, `dev` gate failed; its format-2 cassette was superseded),
[report-2026-11-16.md](eval/reports/openai/report-2026-11-16.md) (v2 baseline, `n=64`, raw `all` `0.932`, 7 agent/guard defects)
and [report-2026-11-14.md](eval/reports/openai/report-2026-11-14.md) (first repeated run).

**Offline policy** (deterministic; the CI gate, `n=136`, `PASSED`) — [full report](eval/reports/offline/report.md):

| Split | n | Semantic pass | Fact coverage | Numeric groundedness | Citation validity | Language match | Routing as expected |
|---|---|---|---|---|---|---|---|
| dev | 18 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| validation | 94 | 0.660 | 0.748 | 1.000 | 1.000 | 0.553 | 0.851 |
| heldout (`sealed-4`) | 24 | 0.458 | 0.636 | 1.000 | 1.000 | 0.333 | 0.917 |
| all | 136 | 0.669 | 0.762 | 1.000 | 1.000 | 0.574 | 0.882 |

Adversarial (offline): 38 attacks, attack success rate `0.000` (`15` blocked at input, `23` contained downstream), `0`
data leaks, `0` unauthorized writes; 30 benign controls, false-positive rate `0.000`. Critic calibration (offline):
`0.125` recall (catches `unsupported_number` deterministically), `0.000` false revise.

What the offline numbers do and do not show: the pipeline, tools, guardrails, memory and human-review flow
work, answers stay grounded, and no attack succeeds even without the classifier. They are not a measure of
answer quality. The validation and sealed rows are the honest picture of a rule policy: it answers in English
whatever the question's language (it is extractive and cannot translate, so non-English items fail language
match cleanly), reads "pessoa física" as a request for a person, and cannot decompose a question it
has no rule for. The model path does not have those limits, which is the point of having both columns.

## Observability and cost

- **Trace per turn** (`GET /traces/{trace_id}`): every model call (role, model, tokens, latency, degraded),
  tool call (arguments, latency, error), Router decision (thought, task, remaining plan), Critic review,
  guardrail verdict, human decision, and the observations themselves.
- **Structured JSON logs**: one `chat_turn` line per turn with trace id, agents, tools, steps, latency, cost.
- **Metrics** (`GET /metrics`, Prometheus text): `chat_turns_total{status}`, `chat_turn_seconds` histogram,
  `llm_calls_total{role}`, `llm_tokens_total{direction}`, `llm_degraded_calls_total`, `tool_calls_total{tool,outcome}`,
  `guardrail_blocks_total{category,layer}`, `critic_revisions_total`, `low_confidence_fallbacks_total`,
  `fabricated_citations_dropped_total`, `identity_argument_ignored_total`, `escalations_total{reason}`,
  `human_decisions_total{decision}`, `human_review_timeouts_total`, `memory_compactions_total`,
  `login_failures_total`, `chat_rate_limited_total`, `user_feedback_total{rating}`,
  `live_source_calls_total{source,outcome}` (ok, cache hit, retry, error, circuit open), and two gauges set at
  scrape time, `human_review_tickets_open` and `llm_circuit_open`. Every series carries its `# TYPE`.
- **Live progress**: `POST /chat/stream` emits each routing decision, tool call, review and human-review event as
  server-sent events while the turn runs; reasoning and tool results stay in the access-controlled trace.
- **Cost**: real token usage from the provider per call, priced with `PRICE_*_PER_MTOK`, summed per turn in
  the response and the trace. Cost is contained by the step budgets, `reasoning.effort` per role (the guardrail
  classifier runs at the lowest), history compaction, and a `top_k` of 4.
- **Feedback**: `POST /feedback` attaches a thumbs up/down to a trace.

**Alerts** are versioned as Prometheus rules in [deploy/prometheus/alerts.yml](deploy/prometheus/alerts.yml):
degraded-call rate, model breaker open, p95 turn latency, low-confidence fallback rate, tool error rate, a live
source in cool-down, guardrail block spikes by category, human-review backlog and timeouts, failed-login spikes.
A test fails if a rule names a metric the code does not emit.

## Testing strategy

222 tests, all through public interfaces, no network and no key.

| File | What it proves |
|---|---|
| [test_agentic_loop.py](tests/test_agentic_loop.py) | Re-planning from observations, critic-driven retry, `evidence_checklist` completeness & section scoping, parallel fan-out (`delegate_parallel`), speculative Router overlap/discard, refusal to send an ungrounded answer, step budget, duplicate-delegation refusal, fabricated-citation handling, tool reconsideration, compound decomposition, provider outage, trace completeness |
| [test_cassette.py](tests/test_cassette.py) | Content-hashed record/replay across LLM calls, live tools, hosted embeddings, frozen clock, normalized runtime ids, FIFO repeats, per-conversation scopes, parallel golden runs equal to sequential ones, re-run of API-degraded conversations, loud `CassetteMiss` on changed prompts/code, `eval.compare` |
| [test_memory.py](tests/test_memory.py) | Cross-request memory, pronoun follow-ups, restart recovery, compaction, isolation, poisoned-message handling |
| [test_human_in_the_loop.py](tests/test_human_in_the_loop.py) | Interrupt/resume, approve/reject/answer, lease and conflicts, role checks, timeout (sweeper and lazy), restart mid-review, idempotent ticket, exactly-once write, code-level approval gate |
| [test_identity_and_api.py](tests/test_identity_and_api.py) | Token-only identity, tenant isolation at the tool layer, token failure modes, rate limiting, logout, trace privacy, metrics |
| [test_guardrails.py](tests/test_guardrails.py) | Every "block" attack in the adversarial dataset, benign controls, obfuscation, classifier layer and its fail-open, sanitizer on poisoned and real corpus, output guard (including Luhn PAN redaction vs phone-number preservation) |
| [test_llm_adapters.py](tests/test_llm_adapters.py) | Request shape and parsing of the OpenAI adapter against a fake SDK client, fallback for models without reasoning controls, circuit breaker open/recover, provider selection |
| [test_rag_and_eval.py](tests/test_rag_and_eval.py) | Chunking, the three retrieval modes, multi-query RRF & dense `search_many()`, metric math, groundedness and citation checks, language detection, repeated-run gate (ADR-0019), breaker cooldown helper, live tools with a mocked transport |
| [test_streaming_and_ops.py](tests/test_streaming_and_ops.py) | `/chat/stream` events and admission checks, `respond?wait=false` plus long-poll, the long-poll cap, `X-Forwarded-For` trusted only from configured proxies, typed metrics and gauges, alert rules against emitted metrics, live-source retry/cache/breaker, full argument-schema validation, report provenance, partial runs, re-grading, adjudication tied to the exact answer across every committed model report |
| [test_hardening.py](tests/test_hardening.py) | Ordinary wording that used to be blocked, output-guard false positives (including `+55 11 97694-6815`) plus obfuscated canary and internal tool-name blocking, PT/ES injections in retrieved text, anonymous conversation ids, strict `REQUIRE_CHAT_AUTH` and `/chat` rate limiting, production mode, lease-aware timeout, recovery of a decision whose resume never ran, checkpoint and trace retention, usage after a resume, specialist `degraded` propagation, a Critic that returns nothing |

A scripted model ([scripted.py](src/llm/scripted.py)) plays individual agents where exact behaviour must be
asserted (for example "the Critic rejects, the Router must gather more evidence"); everything else runs the
offline policy. Integration testing against the real model is the evaluation harness: same HTTP surface,
scored on semantics rather than asserted on strings, with the gate as the pass/fail criterion and a recorded
cassette proving offline reproducibility.

## Production notes

- **Container**: multi-stage build, non-root uid 10001, read-only root filesystem, all capabilities dropped,
  state in one volume. `/health` is liveness; `/ready` checks the database, migrations and the index.
- **CI** ([ci.yml](.github/workflows/ci.yml)): lint, tests, offline eval gate, image build, non-root check,
  read-only boot, smoke test of the challenge contract, and **`model-eval-replay`** (keyless offline replay of
  `eval/reports/openai/cassette.json.gz` verified by `eval.compare` on every push). The live `model-eval` job is a
  manual `workflow_dispatch` workflow backed by the `OPENAI_API_KEY` repository secret; it evaluates golden
  conversations 4 at a time, re-runs API-degraded ones and stops after the golden suite if the gate already failed
  ([ADR-0025](docs/adr/0025-parallel-golden-conversations-and-fail-fast.md)): about 40 minutes and USD 2 per run.
- **Migrations**: numbered, forward-only, applied at startup and recorded in `schema_migrations`.
- **Backup / rollback**: `python -m scripts.backup` takes a consistent online copy of both databases;
  `--restore` puts one back. Rolling back a release means restoring the backup taken before it.
- **Secrets**: environment only; nothing secret has a usable default except the demo password.
  `APP_ENV=production` refuses to start while demo users are enabled, `JWT_SECRET` is unset or short, or
  `METRICS_TOKEN` is unset or short.
- **Retention**: a finished turn keeps one checkpoint per conversation (its memory), not one per graph step;
  traces are deleted after `TRACE_RETENTION_DAYS`.
- **Scaling out** needs three changes, none of them in agent code: the LangGraph Postgres checkpointer instead
  of SQLite, Postgres for the ops store, and a shared store (Redis) for the login limiter and per-thread locks.
  Until then it is one worker, and the Dockerfile says so.

## How this was built (SDD and LLM tools)

Spec first, then code. [GLOSSARY.md](GLOSSARY.md) fixes the domain language; [SPEC.md](SPEC.md) fixes the
contracts, agents, bounds and acceptance criteria; [docs/adr/](docs/adr/) records the decisions, including the
ones later versions reversed (ADR-0006 supersedes ADR-0001; ADR-0020 amends ADR-0008; ADRs 0019–0026 govern the
v3 gate, retrieval, cassette replay, sealed splits, the parallel model run and the post-freeze `dev` fixes). Work items live in [.scratch/](.scratch/) as one spec and
one file per vertical slice.

LLM coding tools (Claude and Gemini) were used throughout: to turn reviews into specs, implement slices against
tests, author blind cross-family sealed splits (`sealed-2`–`sealed-4` and Critic `k33`–`k48`), and review the
result. The decisions that shape the system were made deliberately and are written down: identity from tokens
only, writes gated in code, untrusted data never promoted to instructions, retrieval mode chosen from held-out
ablations, and evaluation that reports raw failures alongside SHA-256 adjudications and reproducible cassettes.
Everything written is covered by the tests and evaluation gates described above.

## Limitations

- **Grader noise, and `dev` measures its own fixes.** The final run passed every gate, but 15 of its 17 raw
  failures were the graders, not the agent: 12 sealed and validation fact regexes too strict for correct wording
  (`"3 consecutive hours"`, `"Se aprobó"`, plural `"transações"`) and 3 single-call `gpt-5.4-mini` judge errors.
  Sealed regexes are left as written, so `sealed-4` reads `0.875` raw against `1.000` judge and adjudicated.
  `dev` reached `1.000` after fixes made on `dev` ([ADR-0026](docs/adr/0026-dev-driven-fixes-after-the-479a6d7-freeze.md));
  `validation` and `sealed-4` are the evidence that they generalize. Measured locally over 18 runs, about one `dev`
  conversation in 27 still fails at random, so a 3-run gate on 18 items can still fail on noise; majority-of-3 judging was considered
  and not applied, to keep the instrument unchanged for the final measurement.
- **Critic precision after the new checklist items.** False revise on fixed clean drafts rose from `0.042` to
  `0.167` (`dev` only, under the `0.20` ceiling); a revision costs a model round-trip and, after two rounds, sends
  the low-confidence fallback.
- **Borderline judge reliability and annotator provenance.** While clear-cut judge calibration is `1.000` (40/40),
  the 20 near-miss `borderline` items measure `gpt-5.4-mini` at `0.850` agreement (κ `0.700`, 3 false passes
  including an omitted Wi-Fi step). Those 20 items were labelled independently by one human plus one blind
  cross-family Gemini reviewer ([eval/labels/README.md](eval/labels/README.md)), not two external human annotators.
- **Synthetic corpus and datasets.** Even after expanding to 136 golden conversations (`sealed-4` authored blind
  by a separate model family after code freeze), 78 retrieval queries, 48 Critic drafts (`k33`–`k48` blind) and 68
  adversarial cases, every benchmark is drawn from nine curated pages and two mock merchants, not real production
  merchant traffic.
- **Latency.** With `speculative_router` and `delegate_parallel`, `dev` p95 improved from `35.6 s` to `21.8 s` in
  the final run (overall p50 `9.5 s`, p95 `20.4 s`; earlier v3 runs `11.9–13.5 s` / `23.8–28.9 s`, so API load
  moves these numbers by several seconds). Turns stay in the 10–20 s range because hosted dense
  embeddings add a round-trip per search and reasoning calls (`gpt-6-luna`) run across Router, specialist and
  Critic. `/chat/stream` streams step progress while the turn runs, not final tokens (because the Critic reviews
  the final draft before release).
- **Knowledge base freshness & mock fixtures.** The knowledge base is a curated snapshot of nine Getnet Brazil
  pages dated in each file's front matter (`python -m scripts.ingest_getnet --check` detects drift). Merchant data,
  the internal support runbook and the service-order write action are mock fixtures.
- **Security & language bounds.** Deterministic input patterns can be evaded by novel wording (covered by the LLM
  classifier — which fails open by design — and by the structural tool/identity/HITL boundary). Reply-language
  enforcement covers English, Portuguese and Spanish; refusals and the low-confidence fallback are fixed English
  strings.
- **Single worker & operator UX.** Single worker, SQLite, in-process locks and rate limiter (see Production notes).
  Alert rules in [deploy/prometheus/alerts.yml](deploy/prometheus/alerts.yml) are versioned and tested against
  emitted metrics, but `docker-compose.yml` does not bundle Prometheus. Operators have an API, not a UI, and
  merchants learn of human decisions via long-poll or their next message rather than push notifications.
