# 0001. LangGraph State-Machine Orchestration with Four Specialized Agents

Status: superseded by [0006](0006-model-driven-router-loop-with-bounded-autonomy.md). LangGraph and the four agents stay; deterministic routing by state flags does not.

We orchestrate the system as an explicit, strictly-typed state graph (`LangGraph` + `Pydantic v2`) comprising four specialized agents (**Router Agent**, **Knowledge Agent**, **Customer Support Agent**, and **Escalation Agent**) rather than free-form autonomous agent loops (`ReAct` peer-to-peer) or linear chains. Free-form multi-agent loops introduce unpredictable latency, infinite handoff risks, and non-deterministic tool invocations that are hard to verify within a 60-minute core build and automated test suite. A typed state graph guarantees deterministic routing, supports multi-step sequences (e.g., `Router` → `Customer Support` → `Escalation` when a POS Terminal diagnostic fails), and records the exact execution path for observability.
