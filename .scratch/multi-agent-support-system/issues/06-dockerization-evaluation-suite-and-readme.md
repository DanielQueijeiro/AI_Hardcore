# 06: Containerization, Automated 12-Scenario Evaluation Benchmark & Production README

**What to build:** Package the multi-agent orchestration service with a production-ready `Dockerfile` and `docker-compose.yml` so evaluators can build and run the entire stack with standard Docker commands. Provide an automated evaluation benchmark runner that executes all 10 official **Merchant** **Inquiries** plus 2 adversarial **Safety Policy** checks against the service and outputs a structured observability report (routing path, tools called, RAG sources, handoff status, latency, and pass/fail). Document setup, architecture, RAG pipeline, testing strategy, observability, and guardrails in `README.md`.

**Blocked by:** 03: Knowledge Agent — Resilient Web Search for General Utility Inquiries, 05: Cooperative Multi-Agent Chaining & Escalation Agent (Support -> Knowledge / Escalation)

**Status:** resolved

- [x] `Dockerfile` and `docker-compose.yml` build cleanly and expose the FastAPI service on port `8000` with a working healthcheck.
- [x] The evaluation benchmark script runs all 10 official test scenarios plus 2 guardrail scenarios and prints a Markdown summary table verifying 100% pass rate on expected `safety_tier`, `agent_sequence`, and `tools_called`.
- [x] `README.md` covers how to build, configure, and run the application and tests, plus detailed sections on orchestration architecture, message workflow, Hybrid RAG pipeline (ingestion → storage → retrieval → generation), LLM tool usage, guardrails, and production observability/evaluation strategy.
