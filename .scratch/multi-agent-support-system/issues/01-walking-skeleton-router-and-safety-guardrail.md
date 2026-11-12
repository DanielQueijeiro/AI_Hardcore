# 01: Walking Skeleton — POST /chat API, State Graph & Router Safety Policy Guardrail

**What to build:** Stand up the runnable HTTP service (`POST /chat`, `POST /api/v1/chat`, and `GET /health`), the configurable Zero-Cost model provider port, and the compiled `LangGraph` orchestration state machine featuring the **Router Agent** enforcing the three-tier **Safety Policy** (*Getnet Domain & Support*, *General Utility*, and *Restricted / Unsafe*). Submitting an **Inquiry** from a **Merchant** returns a complete `ChatResponse` containing `OrchestrationMetadata` (`trace_id`, `safety_tier`, `primary_intent`, `agent_sequence`, `tools_called`, `rag_sources`, `escalated_to_human`, `handoff_ticket_id`, and `latency_ms`), immediately rejecting prompt injections, illicit requests, and cross-merchant data access attempts before any downstream agent or tool is invoked.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `GET /health` returns HTTP 200 with service readiness and active LLM provider mode.
- [ ] `POST /chat` (and `POST /api/v1/chat`) accepts `{"message": "...", "user_id": "cliente1988"}` and returns a valid `ChatResponse` with populated `OrchestrationMetadata` (`trace_id`, `safety_tier`, `primary_intent`, `agent_sequence`, `latency_ms`).
- [ ] **Safety Policy** Tier 3 (`RESTRICTED_UNSAFE`) blocks prompt injection attempts and cross-merchant data requests (e.g., `user_id: "cliente1988"` asking for `cliente2026`'s **Settlement** data) with `safety_tier: "RESTRICTED_UNSAFE"`, `primary_intent: "BLOCKED"`, `agent_sequence: ["router_agent"]`, `tools_called: []`, and a safe policy refusal in `answer` (Guardrail Scenarios **G1** and **G2**).
- [ ] **Router Agent** accurately classifies Getnet product **Inquiries**, **Merchant** support **Inquiries**, and benign real-time *General Utility* **Inquiries** into their respective `safety_tier` and `primary_intent` values.
- [ ] Integration tests at the `POST /chat` seam pass deterministically in <3 seconds at $0.00 cost without requiring external paid API keys.
