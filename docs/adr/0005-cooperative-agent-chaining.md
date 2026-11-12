# 0005. Cooperative Multi-Agent Chaining for Compound Support Inquiries

Status: accepted

Rather than treating the Router Agent as a one-shot switch statement that terminates after invoking a single downstream agent, the orchestration graph permits conditional post-support transitions from the **Customer Support Agent** to either the **Knowledge Agent** (when POS Terminal diagnostics require official troubleshooting steps, as in Scenario #5) or the **Escalation Agent** (when diagnostics reveal severe Transaction Declines or hardware faults requiring Human Handoff, as in Scenario #8). This satisfies the requirement for multi-agent sequences while keeping routing deterministic via explicit state flags in `OrchestrationState`.
