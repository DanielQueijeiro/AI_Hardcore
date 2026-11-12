"""Integration and packaging tests for Ticket 06: Dockerization, 12-scenario evaluation suite, and README."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_containerization_and_env_configuration_artifacts() -> None:
    """Dockerfile, docker-compose.yml, .dockerignore, and .env.example must exist and configure port 8000, healthcheck, and LLM_PROVIDER modes."""
    dockerfile = REPO_ROOT / "Dockerfile"
    compose = REPO_ROOT / "docker-compose.yml"
    dockerignore = REPO_ROOT / ".dockerignore"
    env_example = REPO_ROOT / ".env.example"

    assert dockerfile.exists(), "Dockerfile must exist at repository root"
    assert compose.exists(), "docker-compose.yml must exist at repository root"
    assert dockerignore.exists(), ".dockerignore must exist at repository root"
    assert env_example.exists(), ".env.example must exist at repository root"

    dockerfile_text = dockerfile.read_text(encoding="utf-8")
    assert "8000" in dockerfile_text
    assert "/health" in dockerfile_text
    assert "uvicorn" in dockerfile_text
    assert "src.api.main:app" in dockerfile_text

    compose_text = compose.read_text(encoding="utf-8")
    assert "8000:8000" in compose_text
    assert "healthcheck" in compose_text
    assert "/health" in compose_text
    assert "LLM_PROVIDER" in compose_text

    env_text = env_example.read_text(encoding="utf-8")
    for provider in ("heuristic", "groq", "gemini", "ollama", "openai"):
        assert provider in env_text, f".env.example should document LLM_PROVIDER option '{provider}'"


def test_evaluation_benchmark_suite_runs_all_12_scenarios_with_100_percent_pass_rate() -> None:
    """The evaluation runner must execute all 10 official inquiries + 2 guardrail checks, validate safety_tier, agent_sequence, and tools_called, and render a Markdown summary table."""
    from scripts.evaluate_scenarios import (
        BENCHMARK_SCENARIOS,
        format_markdown_report,
        main,
        run_evaluation_suite,
    )

    assert len(BENCHMARK_SCENARIOS) == 12
    scenario_ids = [s.scenario_id for s in BENCHMARK_SCENARIOS]
    assert scenario_ids == [
        "S1",
        "S2",
        "S3",
        "S4",
        "S5",
        "S6",
        "S7",
        "S8",
        "S9",
        "S10",
        "G1",
        "G2",
    ]

    summary = run_evaluation_suite(base_url=None)
    assert summary.total == 12
    assert summary.passed == 12
    assert summary.failed == 0
    assert summary.pass_rate == 100.0

    for result in summary.results:
        assert result.passed is True, f"Scenario {result.scenario_id} failed: {result.failure_reasons}"
        assert result.actual_safety_tier == result.expected_safety_tier
        assert result.actual_agent_sequence == result.expected_agent_sequence
        assert result.actual_tools_called == result.expected_tools_called
        assert len(result.answer.strip()) > 20

    markdown = format_markdown_report(summary)
    assert "| ID |" in markdown
    assert "12/12 (100.0%)" in markdown
    for sid in scenario_ids:
        assert f"| **{sid}** |" in markdown

    exit_code = main([])
    assert exit_code == 0


def test_readme_comprehensive_documentation() -> None:
    """README.md must exist and document SDD, Docker/local quickstart, 4-agent orchestration, Hybrid RAG pipeline, LLM tools, guardrails, and observability/evaluation."""
    readme = REPO_ROOT / "README.md"
    assert readme.exists(), "README.md must exist at repository root"

    text = readme.read_text(encoding="utf-8")
    assert len(text) > 3000, "README.md should be comprehensive and detailed"

    required_keywords = [
        "GLOSSARY.md",
        "SPEC.md",
        "docs/adr/",
        "docker compose up",
        "LLM_PROVIDER",
        "pytest",
        "scripts/evaluate_scenarios.py",
        "```mermaid",
        "router_agent",
        "knowledge_agent",
        "customer_support_agent",
        "escalation_agent",
        "https://www.getnet.net/en",
        "data/getnet_knowledge_base.md",
        "LocalCPUEmbedder",
        "get_merchant_profile_and_settlements",
        "get_pos_terminal_diagnostics",
        "create_support_ticket_or_escalate",
        "cliente1988",
        "GETNET_DOMAIN",
        "GENERAL_UTILITY",
        "RESTRICTED_UNSAFE",
        "OrchestrationMetadata",
    ]
    for keyword in required_keywords:
        assert keyword in text, f"README.md is missing required topic/reference: {keyword}"


