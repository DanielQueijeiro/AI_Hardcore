"""Composition root: everything an agent node or endpoint needs, built once and passed explicitly."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.config import Settings
from src.db.ops_store import OpsStore
from src.db.support_store import ensure_seeded_database
from src.llm import LLMClient, build_llm
from src.observability import Metrics
from src.rag import HashingEmbedder, OpenAIEmbedder, Retriever, build_retriever
from src.rag.index import Embedder
from src.tools.live import LiveData

logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    settings: Settings
    llm: LLMClient
    retriever: Retriever
    ops: OpsStore
    live: LiveData
    metrics: Metrics = field(default_factory=Metrics)


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "openai" and settings.openai_api_key:
        return OpenAIEmbedder(
            api_key=settings.openai_api_key,
            model=settings.embedding_model,
            cache_path=settings.sqlite_db_path.parent / "embeddings_cache.json",
            base_url=settings.openai_base_url,
        )
    return HashingEmbedder()


def build_runtime(
    settings: Settings,
    *,
    llm: LLMClient | None = None,
    retriever: Retriever | None = None,
    live: LiveData | None = None,
) -> Runtime:
    ensure_seeded_database(settings.sqlite_db_path)
    ops = OpsStore(settings.sqlite_db_path)
    if settings.seed_demo_users:
        ops.seed_demo_users(settings.demo_password)
    runtime = Runtime(
        settings=settings,
        llm=llm or build_llm(settings),
        retriever=retriever or build_retriever(settings.corpus_dir, build_embedder(settings), settings.index_raw_pages),
        ops=ops,
        live=live or LiveData(enabled=settings.enable_live_web, timeout=settings.web_timeout_seconds),
    )
    logger.info(
        "runtime_ready",
        extra={
            "llm": runtime.llm.name,
            "model": runtime.llm.model,
            "chunks": len(runtime.retriever.chunks),
            "embedder": runtime.retriever.embedder.name,
            "schema_version": ops.schema_version(),
        },
    )
    return runtime
