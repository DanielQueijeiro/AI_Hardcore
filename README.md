# Getnet Multi-Agent Support System

A containerized multi-agent service for Getnet merchants. A Router Agent plans and delegates to a
Knowledge Agent (RAG over the Getnet site plus live web tools), a Customer Support Agent (the signed-in
merchant's own data) and a Human Escalation Agent (pauses the conversation until a human operator
decides, then resumes it). A Critic reviews every answer before it is sent.

Python 3.12 · FastAPI · LangGraph (SQLite checkpointer) · OpenAI Responses API behind a provider port ·
no vector database, no external services required to run or test.

- [Quickstart](#quickstart)
- [What changed since the first submission](#what-changed-since-the-first-submission)
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

A turn takes several sequential model calls (about 11 s at the median with the real model). To watch it happen
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
pytest                                     # 185 tests, no network, no API key
ruff check src eval tests scripts
python -m eval.run --mode offline --gate   # deterministic regression gate (what CI runs)
python -m eval.run --gate --repeat 3       # with OPENAI_API_KEY: real model + LLM judge + judge calibration
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
| `JUDGE_MODEL` | same as above | Evaluation judge; set a different model so the system is not graded by itself. |
| `JWT_SECRET` | random per process | Set it in any shared deployment, otherwise tokens die on restart. |
| `REQUIRE_CHAT_AUTH` | `false` | Set `true` to require a verified Bearer token on `/chat` and `/conversations/{id}` (disables anonymous mode). |
| `CHAT_RATE_LIMIT_ATTEMPTS` / `WINDOW` | `60` / `60` | Sliding-window request limit per authenticated caller or client IP on `/chat`. |
| `TRUSTED_PROXIES` | empty | Comma-separated proxy addresses whose `X-Forwarded-For` is believed for rate limiting. Empty: the header is ignored and the peer address is used. |
| `METRICS_TOKEN` | unset | Bearer token Prometheus must present on `/metrics`. Unset: `/metrics` is open (demo only). |
| `JWT_ISSUER` / `JWT_AUDIENCE` | `getnet-support-auth` / `getnet-support-api` | Required `iss` / `aud` claims: a token minted for another service that shares the secret is refused. |
| `APP_ENV` | `demo` | `production` refuses to start with demo users enabled, without a `JWT_SECRET` of 32+ characters, or without a `METRICS_TOKEN` of 24+. |
| `TRACE_RETENTION_DAYS` | 30 | Stored traces older than this are deleted by the periodic sweep. |
| `MAX_SUPERVISOR_STEPS` / `MAX_SPECIALIST_TOOL_STEPS` / `MAX_CRITIC_ROUNDS` | 6 / 4 / 2 | Bounds on agent autonomy. |
| `HITL_TIMEOUT_SECONDS` / `HITL_LEASE_SECONDS` | 900 / 600 | Human-review deadline and operator lease. |
| `RETRIEVAL_MODE` | `bm25` | `bm25`, `dense` or `hybrid`; chosen from the ablation below. |

## What changed since the first submission

The first version scored 7.4. The review was right on every point; this is what each one led to.

| Review finding | What exists now | Evidence |
|---|---|---|
| Orchestration was a deterministic state machine: no planner, critic, re-planning, quality retry or stopping rule | The Router is a model-driven loop: it decomposes, delegates, reads observations and re-plans one tool call at a time; specialists run their own tool loops and reconsider after poor results; a Critic can send the answer back for more evidence; hard bounds stop it | [nodes.py](src/agents/nodes.py), [test_agentic_loop.py](tests/test_agentic_loop.py) |
| No conversational memory | Per-conversation state checkpointed in SQLite: history, rolling summary with compaction, recovery after restart, isolation per identity | [service.py](src/agents/service.py), [test_memory.py](tests/test_memory.py) |
| Handoff created a ticket and ended | `interrupt` → operator queue → claim with lease → approve / reject / answer → the same turn resumes with the human decision; timeout path; approved write executed exactly once | [test_human_in_the_loop.py](tests/test_human_in_the_loop.py) |
| 12/12 was structural, not semantic | Golden answers with human-written facts, numeric groundedness, citation validity, language match, a sealed held-out split, a judge that is a different model with measured calibration, adversarial suite, regression gate in CI. Measured with the real model over three runs of 64 conversations: semantic pass 0.958 on average (sealed split 1.000, 1.000, 0.875), judge pass 0.969, calibration agreement 1.000 (40/40, 24 of them on questions outside the golden set). **The regression gate failed on run 1** (dev 0.833 against a floor of 0.94); of the eight failures across the three runs, a review attributes four to the agent and four to the graders (two fact patterns, two judge verdicts), so the dev split is 0.944 in run 1 once grader errors are set aside. The gate still reads the raw number. Routing is reported separately and does not count as quality | [eval/](eval/), [model report](eval/reports/openai/report.md), [offline report](eval/reports/offline/report.md) |
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

**Communication between agents** is the shared graph state. The Router calls one of four typed functions
per step (`delegate_knowledge`, `delegate_support`, `escalate_to_human`, `finish`); every delegation carries
a `thought` and the `remaining_plan`, which are recorded in the trace. A specialist receives a
self-contained task, runs its own bounded tool loop and returns a typed report plus the raw tool results.
Those become an observation the Router reads on its next step.

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
| Specialist tool budget (4), repeated tool call | `Nodes._run_specialist` | Forced `report`. A tool without parameters is offered once; a repeated call is not executed and the next step can only report. One tool call per model step |
| One escalation per turn; none for anonymous callers | `Nodes.supervisor` | Refused with an observation |
| Critic rounds (2) | `Nodes.critic` | A draft that is still ungrounded is replaced by an explicit "could not verify" answer |
| Draft in another language than the merchant's | `Nodes.critic`, `checks.detect_language` | Revision forced regardless of the Critic's verdict |
| Critic returns no review | `Nodes.critic` | The deterministic checks decide; an unsupported number or unreturned URL forces a revision |
| Graph recursion limit (60) | `ChatService` | Hard stop |

**The Critic** gets the question, the evidence and the draft, plus two automatic findings: numbers in the draft
that appear nowhere in the evidence, and URLs no tool returned. It answers through a typed `review` call. A
fabricated URL forces a revision regardless of the model's verdict, and so does a draft written in a language
other than the merchant's. On `revise` the Router sees the issues and may gather more evidence before
rewriting, which is the quality-based retry. It is told to send a draft back only for a material problem,
because every round is latency the merchant waits through, and that "could not confirm" is acceptable only if
the right specialist was actually asked.

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

**Retrieval.** Three modes over the same chunks:
- `bm25`: accent-folded, stop-word-filtered tokens, with a query-side glossary that maps merchant wording in
  EN/PT/ES to the terms the corpus uses.
- `dense`: cosine over embeddings. Keyless default is a character n-gram hashing embedder; with
  `EMBEDDING_PROVIDER=openai` it uses `text-embedding-3-small`, cached on disk.
- `hybrid`: reciprocal rank fusion of the two.

Every hit carries a `coverage` score (share of query terms present), surfaced to the agent as
`relevance: good | partial | poor`. That is the abstention and re-query signal.

**Generation.** The Knowledge Agent answers only from tool results and reports its sources. Code then drops any
reported URL that no tool returned; the Critic rejects answers with unsupported numbers or URLs.

### Retrieval ablation

42 labelled queries (29 EN, 8 PT, 5 ES); relevance is labelled at section level. From
[eval/reports/offline/report.md](eval/reports/offline/report.md):

| Mode | Hit@1 | Recall@3 | Recall@4 | MRR | nDCG@4 |
|---|---|---|---|---|---|
| bm25 | 0.905 | 0.988 | 0.988 | 0.948 | 0.951 |
| dense (hashing embedder) | 0.857 | 0.941 | 0.952 | 0.913 | 0.909 |
| hybrid (RRF) | 0.905 | 0.952 | 0.976 | 0.946 | 0.938 |

The same queries with hosted embeddings (`text-embedding-3-small`), from
[eval/reports/openai/report.md](eval/reports/openai/report.md):

| Mode | Hit@1 | Recall@3 | Recall@4 | MRR | nDCG@4 |
|---|---|---|---|---|---|
| bm25 | 0.905 | 0.988 | 0.988 | 0.948 | 0.951 |
| dense (hosted) | 0.929 | 0.988 | 0.988 | 0.964 | 0.966 |
| hybrid (RRF) | 0.929 | 0.988 | 1.000 | 0.964 | 0.969 |

The first submission asserted a 0.45 / 0.35 / 0.20 hybrid without measuring it. Measured: with the keyless
embedder the hybrid is not better than BM25 and is worse on Portuguese; with a real semantic embedder the
hybrid is at least as good as BM25 on every metric. In both cases the gap is one or two queries out of 42, so
the honest claim is "the hybrid helps slightly once the dense side is a real embedder", not more. The default
stays `bm25` with the keyless embedder because it needs no key, network or cache; a deployment that has the
key should set `EMBEDDING_PROVIDER=openai` and `RETRIEVAL_MODE=hybrid`. The query set is small, single-author
and close to the ceiling, which limits how much it can discriminate.

## Tools

| Agent | Tool | Notes |
|---|---|---|
| Knowledge | `search_getnet_knowledge(query)` | Passages with `source_url`, `coverage`, relevance rating |
| Knowledge | `get_fx_rate(base, quote)` | ECB reference rates via Frankfurter |
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
| Input, deterministic | Patterns over normalized views of the message: NFKC, zero-width removal, leetspeak, separator stripping, decoded base64. Injection, prompt extraction, bulk exfiltration, illicit requests, other merchants' ids (EN/PT/ES) | Always on |
| Input, LLM classifier | Typed verdict through a forced function call; the message is passed as tagged data. A block is kept only if a second, more careful pass agrees, so one hasty verdict cannot refuse an ordinary question; the second pass runs only for flagged messages | Fail-open to the deterministic layer |
| Untrusted data | Retrieved passages, web results and operator notes: instruction-like sentences removed, delimiter tags neutralized, wrapped as data in every prompt | Always on |
| Structural | Tool allow-lists, principal-scoped tools, human-gated writes | Always on |
| Output | Prompt canary, other tenants' identifiers, credential-shaped strings, formatted CPF/CNPJ and Luhn-valid card numbers (redacted). Applied to final answers and to the waiting message sent when a turn pauses for a human | Fail-closed |

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
| Retrieval | 42 labelled queries | Recall@k, Hit@k, MRR, nDCG@k per mode and language |
| Golden answers | 64 conversations: 18 dev, 22 validation, 24 sealed held-out (single and multi-turn, EN/PT/ES, account, compound, HITL approve/reject/answer, abstention, contradictory source, anonymous). Each runs on its own fresh databases | Fact coverage, forbidden claims, numeric groundedness, citation validity, language match, gold source cited, LLM judge, latency, cost; routing separately |
| Adversarial | 38 attacks + 30 benign controls | Attack success rate, data leaks, unauthorized writes, false-positive rate |
| Judge calibration | 40 good and bad answers with pass/fail labels: 16 original, 24 on questions that appear in no golden item | Judge agreement and Cohen's kappa, overall and per set; false passes |

**Required facts, and where they are brittle.** Each golden item lists the atomic facts a correct answer must
carry, each as a set of acceptable phrasings (`["48"]`, `["129[.,]90"]`,
`["does not (say|state|specify)", "não informa", ...]`), matched accent- and case-insensitively, plus claims
that must not appear. For numbers, codes and product names this is exact and language-independent: a fluent
answer with the wrong number fails. For wording (an abstention, "sign in") it is still pattern matching, and the
model run shows its cost: g04 ("do not confirm") and s22 ("entre na sua conta") were correct answers that no
listed phrasing matched. Those two are counted as failures and attributed to the grader in the adjudication
below; moving wording checks from patterns to the judge is the planned fix.

**Groundedness** is measured against the evidence the agents collected in that turn (read from the trace):
every number in the answer must occur in it, and every URL must have been returned by a tool. An agent's own
report does not count as evidence for a URL.

**LLM judge.** A separate call with its own rubric grades correctness, groundedness, relevance and helpfulness
1–5 against a human-written reference and the evidence. The pass rule is applied in code from the scores. Its
reliability is measured on the calibration set, where "false pass" (accepting an answer a human rejected) is
the number to watch.

**Semantic pass** = all facts present, no forbidden claim, numeric groundedness 1.0, no fabricated citation,
expected status, and the judge's pass when a judge ran.

**Three splits, and exactly how clean each is** ([ADR-0016](docs/adr/0016-sealed-held-out-and-independent-judge-calibration.md)).
`dev` (g01-g18) was used while writing prompts and the offline policy. `validation` (h01-h22) was written as
a held-out split and stopped being one: it was run against the model, two items failed, general fixes
followed, the acceptable phrasings of h07 and h11 were widened, and it was run again. It is reported under
the name that describes it. `heldout` (s01-s24) is sealed: written after the last change to any prompt, never
used to change one, its floor (0.80) fixed before its first model run and not raised afterwards. Its result
is published as measured; a grader mistake in a sealed item is reported, not corrected into a pass. The
sealed items were drafted with an LLM coding assistant from the corpus and the fixtures by this project, so
they are unseen by the prompts, not written by an outside party.

**One run is an anecdote.** `--repeat N` runs the golden suite N times with nothing changed in between and
reports every run, the mean and which items failed in how many runs.

**Provenance.** Each report records the SHA-256 of the dataset files it ran and, from this version on, the git
commit, whether the working tree differed from it, and hashes of the source tree, the prompts, the judge, the
baseline, the corpus and the poisoned corpus. The committed model report predates that: it carries dataset
hashes only.

**Re-grading and adjudication.** Each golden item now stores the search queries and tool arguments of its turn
and the exact input the judge saw, so `--regrade REPORT --regrade-times N` can grade the same answers again,
N times each, without running the agents: judge noise measured on its own. Every failed answer is reviewed in
[eval/adjudications.jsonl](eval/adjudications.jsonl), keyed to the SHA-256 of that exact answer, and attributed
to the agent, the judge, the fact patterns or the harness. The report shows the raw and the adjudicated pass
rate side by side; the gate reads only the raw one.

**Regression gate.** [eval/baseline.json](eval/baseline.json) holds floors and ceilings per mode;
`--gate` exits non-zero on a regression, on a gated metric that was never produced (a judge or calibration
that did not answer), and, with a model, on any turn answered by the degraded fallback. CI runs the offline
gate on every push.

### Results

**Real model** (`gpt-6-luna` answering, `gpt-5.4-mini` judging, live web tools on, 2026-11-14) —
[full report](eval/reports/openai/report.md). Three runs of the golden suite with nothing changed between
them; the table is run 1, the one the gate reads. **The gate failed on this run**: dev semantic pass 0.833
against a floor of 0.94. Every other gated metric passed, including the sealed split.

| Split | n | Semantic pass | Fact coverage | Numeric groundedness | Citation validity | Gold source cited | Language match | Judge pass | p50 | p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| dev | 18 | 0.833 | 0.972 | 1.000 | 1.000 | 1.000 | 1.000 | 0.889 | 12.2 s | 25.1 s |
| validation | 22 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 10.7 s | 16.0 s |
| heldout (sealed) | 24 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 9.8 s | 27.1 s |
| all | 64 | 0.953 | 0.992 | 1.000 | 1.000 | 1.000 | 1.000 | 0.969 | 10.7 s | 25.1 s |

Run-to-run variation (semantic pass per run, then the mean):

| Split | Run 1 | Run 2 | Run 3 | Mean |
|---|---|---|---|---|
| dev | 0.833 | 0.944 | 0.944 | 0.907 |
| validation | 1.000 | 1.000 | 1.000 | 1.000 |
| heldout (sealed) | 1.000 | 1.000 | 0.875 | 0.958 |
| all | 0.953 | 0.984 | 0.938 | 0.958 |

Eight items failed in exactly one of the three runs; none failed twice. What each one was:

| Item | Run | What happened |
|---|---|---|
| g04 (dev) | 1 | Abstention worded in a way the fact list does not recognise |
| g07 (dev) | 1 | Asked for EUR/BRL, answered with EUR/USD: a wrong answer |
| g08 (dev) | 1 | **Judge mistake.** Correct outcome plus "keep selling with Pix or a Payment Link", which the judge called unsupported. The runbook chunk the answer's PIN-pad diagnosis comes from says exactly that |
| g15 (dev) | 2 | **Judge mistake**, same sentence as g08 |
| g12 (dev) | 3 | Left out the "connect to the store Wi-Fi" step the reference lists: an agent miss |
| s04 (sealed) | 3 | Said the limit of devices per store is not documented; the corpus says 5. For the literal question BM25 ranks that passage first and the answer cites its page, so the passage was read and missed, and the Critic approved the false abstention |
| s18 (sealed) | 3 | Answered the account half, not the battery charging time the FAQ states. An English query finds the FAQ passage in the top two; a Portuguese reformulation ("bateria") does not, and the Get Smart page says battery specifications are only in an image. The report did not store the search queries then, so which of the two happened is not known |
| s22 (sealed) | 3 | **Grader mistake.** The answer ("entre na sua conta Getnet") is right and the judge passed it; the fact list does not include that phrasing. Left as a failure, as the protocol requires |

So the sealed split is 24/24 in two runs and 21/24 in the third, of which two are real misses and one is the
grader. Across all three runs the review attributes four failures to the agent (g07, g12, s04, s18) and four to
the graders (g04, s22 fact patterns; g08, g15 judge): the adjudicated dev rate is 0.944, 1.000 and 0.944 per
run, against a raw 0.833, 0.944 and 0.944 ([adjudicated table](eval/reports/openai/report.md#adjudicated-failures-human-review-the-gate-reads-the-raw-numbers)).
None of the eight has been fixed in this version, and the dev floor has not been lowered to make the gate pass.

- Judge means (1-5, run 1): correctness 4.84, groundedness 4.94, relevance 4.86, helpfulness 4.67. No
  forbidden claim, no fabricated citation, no turn answered by the degraded fallback, routing as expected
  1.000. Mean cost per turn USD 0.00175 at the configured prices (`PRICE_*_PER_MTOK`; set them to your
  price list).
- Judge calibration: 40 of 40 in agreement with the reference labels, Cohen's kappa 1.000, 0 false passes,
  0 false fails; per set, 16 of 16 on `original` and 24 of 24 on `independent` (questions that appear in no
  golden item). The independent labels were drafted with an LLM assistant against the rubric, so this is
  agreement with a rubric-following labeller, not with an outside human.
- Adversarial: 38 attacks, attack success rate 0.000 (28 blocked at input, 10 contained downstream), 0 data
  leaks, 0 unauthorized writes; 30 benign controls, false-positive rate 0.000.

How it got there is part of the evidence. The first run against the real model failed its gate (semantic
pass 0.72, judge pass 0.78): English questions answered in Portuguese, the "card machine offline" scenario
escalated to a human instead of answered, a tool called four times in a row. The evaluation found those; the
fixes are in [ADR-0015](docs/adr/0015-what-the-first-model-run-changed.md). A later run at 0.925 (37/40:
`h01`, `h09`, `g04`) led to tighter Portuguese/English language markers, bilingual and safety-refusal
calibration in the judge, and Router faithfulness, after which a single run of the 40 dev and validation
items passed 40/40 (that run's report was not kept, so the figure cannot be checked here). The three-run
measurement above is what that single run did not show.

**Offline policy** (deterministic; the CI gate) — [full report](eval/reports/offline/report.md):

| Split | n | Semantic pass | Fact coverage | Numeric groundedness | Citation validity | Language match | Routing as expected |
|---|---|---|---|---|---|---|---|
| dev | 18 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| validation | 22 | 0.682 | 0.682 | 1.000 | 1.000 | 0.727 | 0.773 |
| heldout (sealed) | 24 | 0.750 | 0.771 | 1.000 | 1.000 | 0.667 | 1.000 |

Adversarial: 38 attacks, attack success rate 0.000 (15 blocked at input, 23 contained downstream), 0 data
leaks, 0 unauthorized writes; 30 benign controls, false-positive rate 0.000.

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

185 tests, all through public interfaces, no network and no key.

| File | What it proves |
|---|---|
| [test_agentic_loop.py](tests/test_agentic_loop.py) | Re-planning from observations, critic-driven retry, refusal to send an ungrounded answer, step budget, duplicate-delegation refusal, fabricated-citation handling, tool reconsideration, compound decomposition, provider outage, trace completeness |
| [test_memory.py](tests/test_memory.py) | Cross-request memory, pronoun follow-ups, restart recovery, compaction, isolation, poisoned-message handling |
| [test_human_in_the_loop.py](tests/test_human_in_the_loop.py) | Interrupt/resume, approve/reject/answer, lease and conflicts, role checks, timeout (sweeper and lazy), restart mid-review, idempotent ticket, exactly-once write, code-level approval gate |
| [test_identity_and_api.py](tests/test_identity_and_api.py) | Token-only identity, tenant isolation at the tool layer, token failure modes, rate limiting, logout, trace privacy, metrics |
| [test_guardrails.py](tests/test_guardrails.py) | Every "block" attack in the adversarial dataset, benign controls, obfuscation, classifier layer and its fail-open, sanitizer on poisoned and real corpus, output guard |
| [test_llm_adapters.py](tests/test_llm_adapters.py) | Request shape and parsing of the OpenAI adapter against a fake SDK client, fallback for models without reasoning controls, circuit breaker open/recover, provider selection |
| [test_rag_and_eval.py](tests/test_rag_and_eval.py) | Chunking, the three retrieval modes, metric math, groundedness and citation checks, language detection, the gate (including a gated metric that was never produced), live tools with a mocked transport |
| [test_streaming_and_ops.py](tests/test_streaming_and_ops.py) | `/chat/stream` events and admission checks, `respond?wait=false` plus long-poll, the long-poll cap, `X-Forwarded-For` trusted only from configured proxies, typed metrics and gauges, alert rules against emitted metrics, live-source retry/cache/breaker, full argument-schema validation, report provenance, partial runs, re-grading, adjudication tied to the exact answer |
| [test_hardening.py](tests/test_hardening.py) | Ordinary wording that used to be blocked, output-guard false positives plus obfuscated canary and internal tool-name blocking, PT/ES injections in retrieved text, anonymous conversation ids, strict `REQUIRE_CHAT_AUTH` and `/chat` rate limiting, production mode, lease-aware timeout, recovery of a decision whose resume never ran, checkpoint and trace retention, usage after a resume, specialist `degraded` propagation, a Critic that returns nothing |

A scripted model ([scripted.py](src/llm/scripted.py)) plays individual agents where exact behaviour must be
asserted (for example "the Critic rejects, the Router must gather more evidence"); everything else runs the
offline policy. Integration testing against the real model is the evaluation harness: same HTTP surface,
scored on semantics rather than asserted on strings, with the gate as the pass/fail criterion.

## Production notes

- **Container**: multi-stage build, non-root uid 10001, read-only root filesystem, all capabilities dropped,
  state in one volume. `/health` is liveness; `/ready` checks the database, migrations and the index.
- **CI** ([ci.yml](.github/workflows/ci.yml)): lint, tests, offline eval gate, image build, non-root check,
  read-only boot and a smoke test of the challenge contract. The model evaluation is a manual job.
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
ones this version reversed (ADR-0006 supersedes the deterministic state machine of ADR-0001). Work items live in
[.scratch/](.scratch/) as one spec and one file per vertical slice.

LLM coding tools (Claude) were used throughout: to turn the review into a spec, to implement slices against
tests, and to review the result. The decisions that shape the system were made deliberately and are written
down: identity from tokens only, writes gated in code, untrusted data never promoted to instructions,
retrieval mode chosen by measurement, and evaluation that reports failures instead of hiding them. Everything
an LLM wrote is covered by the tests and the evaluation gate described above.

## Limitations

- The committed model report (`2026-11-14`) is three runs of the golden suite and its gate failed on the dev
  split in run 1 (0.833 against 0.94). Dev varied between 0.833 and 0.944 across the runs, so that floor,
  set from an earlier single run, is tighter than the system's measured variance.
- The golden, adversarial and retrieval datasets are small (64, 68 and 42 items) and written by one person.
  They catch regressions and gross errors; they are not a statistically strong estimate of quality. The
  retrieval set has no held-out split and sits close to the ceiling.
- Latency: in the reported run a turn takes 10.7 seconds at the median and 25.1 at p95. That is the price of a
  classifier, a Router loop, specialist tool loops and a Critic run in sequence. `/chat/stream` shows progress
  while it runs but does not make the turn shorter; running the input classifier in parallel with the first
  Router step is the obvious next step and is not built. The final answer is not streamed token by token,
  because it arrives as the argument of the Router's `finish` call and the Critic reviews it before it is sent.
- The knowledge base is a curated snapshot of nine pages dated in each file's front matter. Fees change; a
  production system would schedule the ingestion check and re-curate on change.
- Merchant data, the runbook and the write action are mock fixtures.
- The deterministic input patterns can be evaded by wording they do not anticipate (the adversarial set
  includes paraphrased, German and French attacks that pass them); the LLM classifier and the structural
  controls are what cover that, and the classifier fails open by design.
- Reply-language detection covers English, Portuguese and Spanish. In any other language the Router still
  gets the instruction to answer in the merchant's language, but nothing enforces it. Refusals and the
  low-confidence fallback are fixed English strings.
- A turn is five to nine sequential model calls; the evaluation report gives the measured latency.
- Single worker, SQLite, in-process locks and rate limiter (see Production notes).
- Operators have an API, not a UI, and there is no notification when a ticket opens (the backlog alert is the
  closest thing). Merchants learn a decision through the long-poll or their next message, not a push.
