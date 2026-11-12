# Spec: Getnet Multi-Agent Support System

Status: ready-for-agent

## Problem Statement

A Getnet **Merchant** (such as `cliente1988`) needs a single conversational support channel capable of answering product rules (comparing **POS Terminal** models like *Get Clássica* and *Get Smart*, explaining **Pix** account requirements, **Receivables Advance**, **Crediário** installment limits, and **Payment Link** sales via WhatsApp), resolving account-specific operational questions (when yesterday's sales **Settlement** will be deposited, why a **POS Terminal** cannot connect to the internet, or why a **POS Terminal** displays a **Transaction Decline** error), and answering benign real-time general utility questions (such as tomorrow's weather forecast in Porto Alegre or today's Euro exchange rate).

Currently, handling these diverse **Inquiries** requires either manual triage by human operators or rigid single-purpose bots that fail when an **Inquiry** spans multiple domains (for instance, diagnosing a **Merchant**'s specific **POS Terminal** telemetry and simultaneously retrieving official network troubleshooting instructions, or escalating a severe **Transaction Decline** to a **Human Handoff** with a **Support Ticket**). Furthermore, the system must protect against adversarial or unauthorized cross-merchant **Inquiries** under a clear **Safety Policy**, run reliably inside a Docker container, and operate at zero monetary cost ($0.00) during development, testing, and evaluation.

## Solution

We will build a containerized multi-agent orchestration service exposing an HTTP endpoint that accepts a **Merchant**'s `message` and `user_id` and coordinates four specialized agents through a typed state machine:

1. **Router Agent**: Acts as the primary entry point and enforces the three-tier **Safety Policy** (*Getnet Domain & Support*, *General Utility*, and *Restricted / Unsafe*). It rejects unsafe or cross-merchant **Inquiries** immediately and routes valid **Inquiries** to the appropriate downstream agent or cooperative sequence of agents.
2. **Knowledge Agent**: Answers Getnet product and service **Inquiries** using a hybrid Retrieval-Augmented Generation (RAG) pipeline grounded in Getnet's official web content and curated Brazilian product catalog, and resolves *General Utility* **Inquiries** (weather, currency exchange rates) using a resilient web search capability.
3. **Customer Support Agent**: Resolves **Merchant**-specific **Inquiries** using three deterministic tools that inspect **Merchant** profile and **Settlement** schedules, run **POS Terminal** connectivity and **Transaction Decline** diagnostics, and open **Support Tickets**.
4. **Escalation Agent**: Executes a structured **Human Handoff** whenever automated diagnostics uncover critical hardware/cryptographic faults, persistent **Transaction Declines**, or low-confidence states, returning a **Support Ticket** reference and actionable interim guidance.

Every HTTP response returns both the synthesized natural-language answer for the **Merchant** and a structured orchestration trace detailing the **Safety Policy** tier, primary intent, sequence of agents visited, tools invoked, RAG sources used, **Human Handoff** status, and end-to-end execution latency.

## User Stories

1. As a **Merchant**, I want to ask for the difference between the *Get Clássica* and *Get Smart* **POS Terminal** models, so that I can choose the hardware that best fits my business operations.
2. As a **Merchant**, I want to ask whether I need a traditional bank account to receive my sales via **Pix**, so that I know if I can settle funds into a Getnet digital account or external institution.
3. As a **Merchant**, I want to ask how **Receivables Advance** (*antecipação*) works with Getnet, so that I understand how to receive credit and installment sales funds before the standard **Settlement** date.
4. As a **Merchant**, I want to ask how many installments I can split a sale into using **Crediário**, so that I can offer extended payment plans to my buyers accurately.
5. As a **Merchant**, I want to ask whether I can sell through WhatsApp using a **Payment Link**, so that I can collect remote payments without maintaining an e-commerce website.
6. As a **Merchant**, I want to ask when the money from yesterday's sales will be deposited (`user_id: "cliente1988"`), so that I can see the exact **Settlement** status and schedule for my Pix, debit, and credit batches.
7. As a **Merchant** whose **POS Terminal** will not connect to the internet, I want the system to inspect my specific **POS Terminal** telemetry and provide step-by-step reconnection instructions from the Getnet knowledge base, so that I can restore connectivity and resume taking payments.
8. As a **Merchant** whose **POS Terminal** is showing a **Transaction Decline** error, I want the system to diagnose the recent decline code on my terminal and automatically initiate a **Human Handoff** with a **Support Ticket** when a critical terminal/issuer fault is detected, so that a specialist can resolve the issue without me repeating my diagnostic details.
9. As a **Merchant**, I want to ask for tomorrow's weather forecast in Porto Alegre, so that I can plan my storefront foot-traffic operations using real-time general utility information.
10. As a **Merchant**, I want to ask for today's Euro exchange rate, so that I can reference current foreign exchange rates during business operations.
11. As a platform security owner, I want the **Router Agent** to enforce the three-tier **Safety Policy** and block prompt injections, unsafe requests, or attempts by one **Merchant** to query another **Merchant**'s **Settlement** data, so that tenant isolation and platform safety are guaranteed.
12. As a platform security owner, I want **Customer Support Agent** tools to scope all data lookups strictly to the authenticated `user_id` from the request context, so that cross-merchant data leakage is impossible even if prompted.
13. As an AI engineer / evaluator, I want every HTTP response to include an orchestration trace (`trace_id`, `safety_tier`, `primary_intent`, `agent_sequence`, `tools_called`, `rag_sources`, `escalated_to_human`, `handoff_ticket_id`, and `latency_ms`), so that I can observe, audit, and evaluate routing accuracy and multi-agent cooperation.
14. As an evaluator, I want to build and start the entire multi-agent system with standard Docker commands and zero paid API key requirements, so that I can verify all 10 official test scenarios and guardrail checks immediately and at $0.00 cost.
15. As an AI engineer, I want to run an automated evaluation suite against all 10 official **Merchant** **Inquiries** plus adversarial guardrail scenarios, so that I can measure routing precision, tool invocation accuracy, and response quality continuously.

## Implementation Decisions

- **State-Machine Multi-Agent Orchestration (per ADR-0001)**:
  - The orchestration layer is modeled as a compiled `LangGraph` state machine operating over a single shared typed state (`OrchestrationState`).
  - Four distinct agent nodes are registered in the graph: `router_agent`, `knowledge_agent`, `customer_support_agent`, and `escalation_agent`.
  - Communication between agents occurs exclusively via immutable state transitions and explicit routing flags on `OrchestrationState`:
    ```python
    class OrchestrationState(TypedDict):
        trace_id: str
        user_id: str
        message: str
        safety_tier: Literal["GETNET_DOMAIN", "GENERAL_UTILITY", "RESTRICTED_UNSAFE"]
        primary_intent: Literal[
            "PRODUCT_KNOWLEDGE",
            "GENERAL_WEB_SEARCH",
            "CUSTOMER_SUPPORT",
            "COMPOUND_SUPPORT_AND_KB",
            "HUMAN_ESCALATION",
            "BLOCKED",
        ]
        agent_sequence: list[str]
        tools_called: list[str]
        rag_sources: list[str]
        support_context: dict[str, Any]
        knowledge_context: str
        needs_knowledge_enrichment: bool
        needs_human_handoff: bool
        handoff_ticket_id: str | None
        final_answer: str
    ```

- **Three-Tier Safety Policy & Guardrail Routing (per ADR-0002)**:
  - The `router_agent` evaluates every incoming **Inquiry** before any downstream agent or tool is invoked.
  - Tier 3 (`RESTRICTED_UNSAFE`) immediately short-circuits the graph to the terminal node with a policy refusal message when prompt injection patterns, harmful/illegal topics, or cross-merchant data access attempts (e.g., `user_id: "cliente1988"` asking for `cliente2026`'s data) are detected.
  - Tier 2 (`GENERAL_UTILITY`) routes benign real-time queries (such as weather forecasts or currency exchange rates) to `knowledge_agent` with `primary_intent = "GENERAL_WEB_SEARCH"`.
  - Tier 1 (`GETNET_DOMAIN`) routes product/service questions to `knowledge_agent` (`PRODUCT_KNOWLEDGE`) and account/terminal issues to `customer_support_agent` (`CUSTOMER_SUPPORT` or `COMPOUND_SUPPORT_AND_KB`).

- **Cooperative Multi-Agent Chaining (per ADR-0005)**:
  - After `customer_support_agent` executes its diagnostic tools for a **Merchant**, a conditional edge evaluates post-support transitions:
    1. If `needs_knowledge_enrichment` is `True` (e.g., **POS Terminal** connectivity failure where telemetry shows `OFFLINE_GPRS_TIMEOUT`), control flows from `customer_support_agent` → `knowledge_agent` so official network troubleshooting steps from the RAG knowledge base are merged with the terminal diagnostics (`agent_sequence: ["router_agent", "customer_support_agent", "knowledge_agent"]`).
    2. If `needs_human_handoff` is `True` (e.g., recurring **Transaction Decline** with cryptographic PIN-pad desynchronization `ERR_51_ISSUER_DECLINE / POS_KEY_SYNC_WARN`), control flows from `customer_support_agent` → `escalation_agent` (`agent_sequence: ["router_agent", "customer_support_agent", "escalation_agent"]`).
    3. Otherwise (e.g., yesterday's **Settlement** status inquiry), `customer_support_agent` synthesizes the final response and transitions to `END`.

- **Hybrid RAG Pipeline (per ADR-0003)**:
  - The knowledge ingestion module fetches and parses live content from `https://www.getnet.net/en` (with graceful timeout/WAF fallback) and merges it with a curated Getnet product corpus covering *Get Clássica*, *Get Smart*, *Pix*, *Receivables Advance* (*Antecipação*), *Crediário*, *Payment Link* (*Link de Pagamento* / WhatsApp), and **POS Terminal** troubleshooting.
  - Chunks are indexed in an embedded local vector store using local CPU ONNX embeddings (`all-MiniLM-L6-v2`) with source metadata preserved for citation in `rag_sources`.

- **Zero-Cost Multi-Provider LLM & Resilient Free Web Search (per ADR-0004)**:
  - Model inference is abstracted behind a configurable provider interface supporting free-tier cloud providers (`groq`, `gemini`), local `ollama`, `openai`, and a deterministic `heuristic` fallback mode so the service and test suite run out-of-the-box with zero cost ($0.00) even when no external API key is supplied.
  - The web search tool queries DuckDuckGo (`ddgs`) and includes deterministic zero-key HTTP fallbacks to `open-meteo.com` (for weather forecasts such as Porto Alegre) and `frankfurter.app` (for live EUR exchange rates) so container IP rate limits never break general utility **Inquiries**.

- **Customer Support Tools & Deterministic Merchant Store**:
  - Backed by an auto-seeded SQLite store containing rich fixtures for `cliente1988` (and secondary merchant `cliente2026` for tenant isolation verification).
  - Exposes three tools to `customer_support_agent`:
    1. `get_merchant_profile_and_settlements(merchant_id)`: Retrieves registered bank account, Pix status, and itemized **Settlement** status for yesterday's Pix (`D+0`), debit (`D+1`), and credit (`D+2` via **Receivables Advance**) batches.
    2. `get_pos_terminal_diagnostics(merchant_id)`: Retrieves active **POS Terminal** model (`Get Smart`), connectivity state (`OFFLINE_GPRS_TIMEOUT`), and latest **Transaction Decline** telemetry (`ERR_51_ISSUER_DECLINE / POS_KEY_SYNC_WARN`).
    3. `create_support_ticket_or_escalate(merchant_id, issue_summary, severity)`: Persists a **Support Ticket** and returns its ticket identifier for **Human Handoff**.

- **HTTP API Contract**:
  - Exposes `POST /chat` (plus alias `POST /api/v1/chat`) and `GET /health`.
  - Request and response schema:
    ```python
    class ChatRequest(BaseModel):
        message: str
        user_id: str

    class OrchestrationMetadata(BaseModel):
        trace_id: str
        safety_tier: str
        primary_intent: str
        agent_sequence: list[str]
        tools_called: list[str]
        rag_sources: list[str]
        escalated_to_human: bool
        handoff_ticket_id: str | None = None
        latency_ms: int

    class ChatResponse(BaseModel):
        user_id: str
        message: str
        answer: str
        orchestration: OrchestrationMetadata
    ```

## Testing Decisions

- **Philosophy — Test External Behavior at the Highest Seam**:
  - Good tests verify observable system behavior (`ChatResponse` payload, HTTP status codes, `agent_sequence`, `tools_called`, `rag_sources`, `escalated_to_human`, and domain facts present in `answer`) through the public entrypoint rather than asserting on private agent prompts or internal LangGraph node implementation details.
- **Primary Seam (Single High-Level Seam)**:
  - **The HTTP API Boundary (`POST /chat` via FastAPI `TestClient` / `httpx.AsyncClient`)** is the primary testing seam for the entire orchestration system.
  - At this seam, requests enter with `{"message": "...", "user_id": "cliente1988"}` and traverse the real `Router Agent`, real `LangGraph` state transitions, real local ChromaDB/ONNX RAG retriever, and real SQLite `Customer Support Agent` tools.
  - External network boundaries (external LLM API and live weather/FX HTTP endpoints during offline unit/integration runs) are controlled via the configurable provider port so the full test suite executes deterministically in <3 seconds with zero network flakiness and $0.00 cost.
- **Modules & Scenarios Covered**:
  1. All 10 official challenge **Inquiries** verified end-to-end through `POST /chat`, asserting exact `safety_tier`, `agent_sequence`, `tools_called`, and expected domain information in `answer`.
  2. Guardrail & tenant isolation verification through `POST /chat` (prompt injection rejection, unsafe topic refusal, and blocking `cliente1988` from reading `cliente2026`'s **Settlement** data).
  3. Live end-to-end evaluation script that runs against the running container/server and outputs an observability and quality report across all scenarios.
- **Prior Art**:
  - Green-field repository; these integration tests establish the canonical behavioral test suite for the service.

## Out of Scope

- Multi-turn conversational memory across separate HTTP requests (the challenge specifies a stateless `POST` contract taking `message` and `user_id` per request).
- Real payment processing, live bank wire execution, or mutation of real production Getnet databases.
- Frontend web UI or chat widget (evaluation is conducted via the HTTP REST API, automated evaluation runner, and Swagger/OpenAPI docs).
- Authentication/JWT middleware (the challenge contract passes `user_id` directly in the JSON request body).

## Further Notes

- Developed under a strict 60-minute core-development timebox using Spec-Driven Development (SDD).
- The repository includes `GLOSSARY.md` and `docs/adr/0001..0005` so human evaluators can trace every architectural trade-off from domain terminology to code.
