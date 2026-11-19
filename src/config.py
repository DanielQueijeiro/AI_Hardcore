"""Runtime configuration. Every knob is an environment variable; nothing secret has a usable default."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Getnet Multi-Agent Support System"
    app_version: str = "0.2.0"
    # "demo": the challenge setup (seeded demo users, generated JWT secret allowed).
    # "production": refuses to start with demo users or without a real JWT secret.
    app_env: Literal["demo", "production"] = "demo"

    # --- LLM ---------------------------------------------------------------
    # "openai": agents are driven by the model below (requires OPENAI_API_KEY).
    # "offline": a deterministic rule policy stands in for the model (CI, no-key demos, outage fallback).
    llm_provider: Literal["openai", "offline"] = "openai"
    # Evaluation only: record every model call, live-tool result and embedding of a run, or replay one without a key.
    record_to: Path | None = None
    replay_from: Path | None = None
    # Prefix for this app's cassette keys, so conversations evaluated in parallel never share a recording (src/cassette.py).
    cassette_scope: str = ""
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-6-luna"
    reasoning_effort: str = "low"
    guardrail_reasoning_effort: str = "none"
    llm_timeout_seconds: float = 45.0
    llm_max_retries: int = 2
    breaker_failure_threshold: int = 3
    breaker_cooldown_seconds: float = 60.0
    # Optional separate model for the evaluation judge, so the system is not graded by itself.
    judge_model: str | None = None
    # auto: hosted embeddings when an API key is set, the keyless hashing embedder otherwise (ADR-0020)
    embedding_provider: Literal["openai", "local", "auto"] = "auto"
    embedding_model: str = "text-embedding-3-small"
    # USD per 1M tokens, used only for cost reporting. Override when pricing changes.
    price_input_per_mtok: float = 0.10
    price_output_per_mtok: float = 0.50

    # --- Agent loop bounds (bounded autonomy) --------------------------------
    max_supervisor_steps: int = 6
    max_specialist_tool_steps: int = 4
    max_critic_rounds: int = 2
    max_parallel_tasks: int = 3
    # Run the Router's first step while the input classifier is still deciding; discarded if the message is blocked.
    speculative_router: bool = True
    history_keep_messages: int = 8
    history_compact_after: int = 16

    # --- Auth ----------------------------------------------------------------
    jwt_secret: str | None = None
    jwt_expires_minutes: int = 60
    jwt_issuer: str = "getnet-support-auth"
    jwt_audience: str = "getnet-support-api"
    require_chat_auth: bool = False
    # Demo identities (cliente1988, cliente2026, operador1) so the challenge scenarios can sign in.
    # Set SEED_DEMO_USERS=false in any real deployment and provision users through your IdP.
    seed_demo_users: bool = True
    demo_password: str = "getnet-demo"
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 300
    chat_rate_limit_attempts: int = 60
    chat_rate_limit_window_seconds: int = 60

    # --- Human in the loop ----------------------------------------------------
    hitl_timeout_seconds: int = 900
    hitl_lease_seconds: int = 600
    hitl_sweep_interval_seconds: float = 15.0

    # --- HTTP ------------------------------------------------------------------
    trace_retention_days: int = 30
    cors_origins: str = ""
    # Comma-separated addresses of reverse proxies whose X-Forwarded-For is believed when rate limiting.
    # Empty: the direct peer address is used, and the header is ignored.
    trusted_proxies: str = ""
    # Bearer token Prometheus presents on /metrics. Unset in demo mode: /metrics is open. Required in production.
    metrics_token: str | None = None
    # How long GET /conversations/{id}?wait= may hold a request open waiting for a human decision.
    max_conversation_wait_seconds: float = 30.0
    log_level: str = "INFO"

    # --- Data ------------------------------------------------------------------
    sqlite_db_path: Path = Path("data/support.db")
    checkpoint_db_path: Path = Path("data/checkpoints.db")
    corpus_dir: Path = Path("data/corpus")
    index_raw_pages: bool = False
    # Chosen from the ablation in eval/reports: with the keyless embedder BM25 is at least as good as the
    # hybrid, so the simpler ranker is the default. Re-run `python -m eval.run --suite retrieval` after
    # switching EMBEDDING_PROVIDER to decide again from data.
    # auto: dense with hosted embeddings, bm25 with the keyless embedder (ADR-0020)
    retrieval_mode: Literal["hybrid", "bm25", "dense", "auto"] = "auto"
    retrieval_top_k: int = 4
    enable_live_web: bool = True
    web_timeout_seconds: float = 4.0

    def unsafe_for_production(self) -> list[str]:
        """What must change before APP_ENV=production may start. Empty in a correctly configured deployment."""
        problems = []
        if self.seed_demo_users:
            problems.append("SEED_DEMO_USERS must be false (demo merchants and a demo operator share a published password)")
        if not self.jwt_secret or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must be set to at least 32 characters")
        if not self.metrics_token or len(self.metrics_token) < 24:
            problems.append("METRICS_TOKEN must be set to at least 24 characters (/metrics exposes operational data)")
        return problems

    def trusted_proxy_set(self) -> frozenset[str]:
        return frozenset(p.strip() for p in self.trusted_proxies.split(",") if p.strip())

    def effective_provider(self) -> str:
        if self.replay_from:
            return "replay"
        return "openai" if self.llm_provider == "openai" and self.openai_api_key else "offline"

    def effective_embedding_provider(self) -> str:
        if self.replay_from and self.embedding_provider != "local":
            return "replay"
        if self.embedding_provider == "auto":
            return "openai" if self.openai_api_key and self.llm_provider == "openai" else "local"
        return "openai" if self.embedding_provider == "openai" and self.openai_api_key else "local"

    def effective_retrieval_mode(self) -> str:
        if self.retrieval_mode == "auto":
            return "dense" if self.effective_embedding_provider() in ("openai", "replay") else "bm25"
        return self.retrieval_mode

    def resolved_jwt_secret(self) -> str:
        return self.jwt_secret or _EPHEMERAL_SECRET


# Used only when JWT_SECRET is unset: tokens then die with the process, which is the safe failure mode.
_EPHEMERAL_SECRET = secrets.token_urlsafe(48)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
