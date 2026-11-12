# 05: Cooperative Multi-Agent Chaining & Escalation Agent (Support -> Knowledge / Escalation)

**What to build:** Enable multi-agent sequences where the **Customer Support Agent** cooperates with downstream agents based on **POS Terminal** diagnostic findings for a **Merchant**, and introduce the fourth specialized agent (**Escalation Agent**). When **POS Terminal** diagnostics reveal a connectivity failure (`OFFLINE_GPRS_TIMEOUT`), chain `router_agent` → `customer_support_agent` → `knowledge_agent` so the response combines `cliente1988`'s terminal telemetry with official network reconnection steps from the Getnet RAG knowledge base. When diagnostics reveal a critical **Transaction Decline** (`ERR_51_ISSUER_DECLINE / POS_KEY_SYNC_WARN`), chain `router_agent` → `customer_support_agent` → `escalation_agent` to record a **Support Ticket** and execute a structured **Human Handoff**.

**Blocked by:** 02: Knowledge Agent — Hybrid Getnet RAG for Product & Service Inquiries, 04: Customer Support Agent — Merchant Profile, Settlements & Deterministic Tools

**Status:** ready-for-agent

- [ ] Official Scenario **#5** (*"My card machine won't connect to the internet, what should I do?"* for `user_id: "cliente1988"`) executes the cooperative sequence `["router_agent", "customer_support_agent", "knowledge_agent"]`, invokes `["get_pos_terminal_diagnostics", "retrieve_getnet_knowledge"]`, populates `rag_sources`, and returns both the `Get Smart` terminal diagnostic status and step-by-step reconnection instructions.
- [ ] Official Scenario **#8** (*"My card machine is showing a transaction decline error."* for `user_id: "cliente1988"`) executes the cooperative sequence `["router_agent", "customer_support_agent", "escalation_agent"]`, invokes `["get_pos_terminal_diagnostics", "create_support_ticket_or_escalate"]`, sets `escalated_to_human: true`, populates `handoff_ticket_id`, and explains the detected **Transaction Decline** code along with the **Human Handoff** details.
- [ ] Full integration test suite at `POST /chat` verifies all 10 official challenge scenarios and 2 guardrail scenarios end-to-end.
