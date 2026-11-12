"""Deterministic local CPU embeddings and hybrid vector + lexical retriever (ADR-0003, ADR-0004)."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from src.rag.ingest import DocumentChunk, load_hybrid_corpus

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "into",
        "is",
        "it",
        "my",
        "of",
        "on",
        "or",
        "should",
        "the",
        "through",
        "to",
        "using",
        "via",
        "what",
        "whats",
        "when",
        "with",
    }
)


@dataclass(frozen=True)
class RetrievedChunk:
    """A ranked DocumentChunk returned by the Hybrid RAG retriever."""

    chunk_id: str
    title: str
    content: str
    source: str
    score: float


def normalize_text(text: str) -> str:
    """Lowercase and strip accents/diacritics so Portuguese/English terms align deterministically."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.lower()


def tokenize(text: str) -> list[str]:
    """Extract normalized alphanumeric tokens excluding common filler stopwords."""
    norm = normalize_text(text)
    return [tok for tok in TOKEN_PATTERN.findall(norm) if tok not in STOPWORDS and len(tok) > 1]


class LocalCPUEmbedder:
    """Deterministic 384-dimensional local CPU embedder using signed feature hashing ($0 cost)."""

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        """Compute L2-normalized dense embedding vector on CPU with unigrams, bigrams, and char n-grams."""
        vec = [0.0] * self.dimension
        tokens = tokenize(text)
        if not tokens:
            return vec

        features: list[tuple[str, float]] = []
        for idx, tok in enumerate(tokens):
            features.append((f"w:{tok}", 2.0))
            if idx + 1 < len(tokens):
                features.append((f"bg:{tok}_{tokens[idx + 1]}", 2.5))
            if len(tok) >= 4:
                for n in (3, 4):
                    for pos in range(len(tok) - n + 1):
                        features.append((f"cg:{tok[pos : pos + n]}", 0.5))

        for feat, weight in features:
            digest = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
            raw = int.from_bytes(digest, "little")
            bucket = raw % self.dimension
            sign = 1.0 if ((raw >> 32) & 1) == 0 else -1.0
            vec[bucket] += sign * weight

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0.0:
            vec = [v / norm for v in vec]
        return vec


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    return sum(a * b for a, b in zip(vec_a, vec_b))


class GetnetHybridRetriever:
    """Local CPU vector + lexical BM25-weighted retriever over Getnet DocumentChunks."""

    def __init__(
        self,
        chunks: list[DocumentChunk],
        embedder: LocalCPUEmbedder | None = None,
    ) -> None:
        self.chunks = list(chunks)
        self.embedder = embedder or LocalCPUEmbedder()
        self._vectors: list[list[float]] = [
            self.embedder.embed(f"{chunk.title}\n{chunk.title}\n{chunk.content}")
            for chunk in self.chunks
        ]
        self._title_tokens: list[set[str]] = [set(tokenize(chunk.title)) for chunk in self.chunks]
        self._body_tokens: list[set[str]] = [set(tokenize(chunk.content)) for chunk in self.chunks]

    def retrieve(self, query: str, top_k: int = 2) -> list[RetrievedChunk]:
        """Return the top-k highest-scoring DocumentChunks for a Merchant query."""
        if not self.chunks:
            return []

        q_vec = self.embedder.embed(query)
        q_tokens = set(tokenize(query))

        scored: list[RetrievedChunk] = []
        for idx, chunk in enumerate(self.chunks):
            dense_score = max(0.0, _cosine_similarity(q_vec, self._vectors[idx]))
            if q_tokens:
                title_overlap = len(q_tokens & self._title_tokens[idx]) / len(q_tokens)
                body_overlap = len(q_tokens & self._body_tokens[idx]) / len(q_tokens)
            else:
                title_overlap = 0.0
                body_overlap = 0.0

            # Prefer curated section chunks when live scrape has lower specificity
            origin_bonus = 0.05 if chunk.metadata.get("origin") == "curated_kb" else 0.0
            combined_score = (0.45 * dense_score) + (0.35 * title_overlap) + (0.20 * body_overlap) + origin_bonus

            scored.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    title=chunk.title,
                    content=chunk.content,
                    source=chunk.source,
                    score=round(combined_score, 4),
                )
            )

        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[: max(1, top_k)]


@lru_cache(maxsize=4)
def get_retriever(
    knowledge_base_path: str | None = None,
    enable_live_scrape: bool = False,
) -> GetnetHybridRetriever:
    """Return a cached GetnetHybridRetriever instance."""
    kb_path = Path(knowledge_base_path) if knowledge_base_path else None
    chunks = load_hybrid_corpus(
        knowledge_base_path=kb_path,
        enable_live_scrape=enable_live_scrape,
    )
    return GetnetHybridRetriever(chunks=chunks)
