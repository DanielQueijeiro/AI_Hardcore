"""Retrieval: BM25, dense, and reciprocal-rank-fusion hybrid over the same chunks.

The three modes exist so the choice can be measured (`python -m eval.run --suite retrieval`) rather than asserted.
Everything is in-process and dependency-free: the corpus is a few dozen chunks, so a vector database
would add operations without adding recall. Swap `Embedder` for a hosted model and the store for
pgvector/Qdrant when the corpus grows; the `Retriever.search` contract stays the same.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from src.cassette import CassetteMiss
from src.rag.corpus import Chunk, load_corpus

logger = logging.getLogger(__name__)

STOPWORDS = frozenset(
    """
    a an the and or of to in on for with is are was be do does can could i my me you your it its this that
    what when how why which who will would should there from at by as about if have has not no so than
    o a os as um uma de do da dos das e ou em no na nos nas para por com que como qual quais quando onde
    meu minha meus minhas se eu voce sua seu ao aos sao ser esta estao tem ter nao mais
    el la los las un una y en del al con que como cual cuando donde mi mis su sus es son se lo le puedo
    puede hay
    """.split()
)

# Query-side domain glossary: the corpus is written in English with the Portuguese product terms kept,
# so merchant wording in EN/PT/ES is mapped onto the terms the corpus actually uses.
GLOSSARY: dict[str, tuple[str, ...]] = {
    "advance": ("antecipacao", "receivables"),
    "anticipation": ("antecipacao", "receivables"),
    "anticipo": ("antecipacao", "receivables", "advance"),
    "adelanto": ("antecipacao", "receivables", "advance"),
    "recebiveis": ("receivables", "antecipacao"),
    "installments": ("installment", "parcelado", "parcelamento"),
    "parcelas": ("installment", "parcelamento"),
    "parcelar": ("installment", "parcelamento"),
    "cuotas": ("installment", "parcelamento"),
    "split": ("installment",),
    "deposited": ("settlement", "received", "recebimento"),
    "deposit": ("settlement", "received", "recebimento"),
    "payout": ("settlement", "received", "recebimento"),
    "liquidacao": ("settlement", "received"),
    "maquina": ("machine", "maquininha"),
    "maquinas": ("machine", "maquininha"),
    "maquininhas": ("machine", "maquininha"),
    "terminal": ("machine", "maquininha"),
    "datafono": ("machine", "maquininha"),
    "pos": ("machine", "maquininha"),
    "internet": ("connection", "connect", "communication"),
    "offline": ("connection", "connect", "communication"),
    "conecta": ("connection", "connect"),
    "conectar": ("connection", "connect"),
    "recusada": ("declined", "decline"),
    "rechazada": ("declined", "decline"),
    "negada": ("declined", "decline"),
    "taxa": ("fees", "rate"),
    "taxas": ("fees", "rate"),
    "tarifa": ("fees", "rate"),
    "tarifas": ("fees", "rate"),
    "comision": ("fees", "rate"),
    "fee": ("fees", "rate", "taxas"),
    "rent": ("rental", "aluguel"),
    "alquiler": ("rental", "aluguel"),
    "bank": ("account", "conta"),
    "banco": ("account", "conta", "bank"),
    "cuenta": ("account", "conta"),
    "whatsapp": ("link", "social"),
    "difference": ("differences", "vs"),
    "diferenca": ("differences", "vs"),
    "diferencia": ("differences", "vs"),
    "telefone": ("phone", "support"),
    "contato": ("phone", "support", "channels"),
    "contact": ("phone", "support", "channels"),
}


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str, *, expand: bool = False) -> list[str]:
    raw = [t for t in re.findall(r"[a-z0-9]+", fold(text)) if t not in STOPWORDS and len(t) > 1]
    tokens = [_stem(t) for t in raw]
    if expand:
        for token in raw:
            for extra in GLOSSARY.get(token, ()) + GLOSSARY.get(_stem(token), ()):
                tokens.append(_stem(extra))
    return tokens


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float
    coverage: float  # share of distinct query terms present in the chunk; the abstention signal
    rank: int

    def as_evidence(self) -> dict[str, object]:
        return {**self.chunk.as_evidence(), "score": round(self.score, 4), "coverage": round(self.coverage, 2)}


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Character n-gram feature hashing (3-5 grams, signed, sub-linear TF, L2-normalised).

    A keyless, deterministic dense representation. It captures sub-word overlap (cognates, inflection,
    typos) that exact-token BM25 misses, but it is not a semantic model; with OPENAI_API_KEY set the
    index uses `text-embedding-3-small` instead.
    """

    name = "hashing-char-ngram-1024"

    def __init__(self, dims: int = 1024) -> None:
        self.dims = dims

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        counts: Counter[int] = Counter()
        for token in tokenize(text, expand=False):
            padded = f"<{token}>"
            for n in (3, 4, 5):
                for i in range(max(1, len(padded) - n + 1)):
                    digest = hashlib.blake2b(padded[i : i + n].encode(), digest_size=8).digest()
                    value = int.from_bytes(digest, "big")
                    counts[value % self.dims] += 1 if value >> 63 else -1
        vector = [0.0] * self.dims
        for idx, count in counts.items():
            vector[idx] = math.copysign(1 + math.log(abs(count)), count) if count else 0.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


class OpenAIEmbedder:
    """Hosted embeddings with an on-disk cache keyed by content hash (re-indexing costs nothing)."""

    def __init__(self, api_key: str, model: str, cache_path: Path, base_url: str | None = None) -> None:
        from openai import OpenAI

        self.name = model
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=30, max_retries=2)
        self._cache_path = cache_path
        self._cache: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        if cache_path.exists():
            try:
                self._cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._cache = {}

    def embed(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            keys = [hashlib.sha256(f"{self.name}:{t}".encode()).hexdigest() for t in texts]
            missing: list[tuple[str, str]] = []
            seen: set[str] = set()
            for key, text in zip(keys, texts, strict=True):
                if key not in self._cache and key not in seen:
                    seen.add(key)
                    missing.append((key, text))
            if missing:
                response = self._client.embeddings.create(model=self.name, input=[t for _, t in missing])
                for (key, _), item in zip(missing, response.data, strict=True):
                    self._cache[key] = list(item.embedding)
                if len(missing) >= 10:  # persist document batches; keep merchant query vectors in memory only
                    self._cache_path.parent.mkdir(parents=True, exist_ok=True)
                    self._cache_path.write_text(json.dumps(self._cache), encoding="utf-8")
            return [self._cache[k] for k in keys]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class Retriever:
    K1 = 1.4
    B = 0.6
    RRF_K = 60

    def __init__(self, chunks: list[Chunk], embedder: Embedder | None = None, *, use_glossary: bool = True) -> None:
        self.chunks = chunks
        self.use_glossary = use_glossary  # off only to measure what the hand-written glossary contributes
        self.embedder: Embedder = embedder or HashingEmbedder()
        self._doc_tokens = [tokenize(c.indexed_text) + tokenize(f"{c.title} {c.section}") for c in chunks]
        self._tf = [Counter(tokens) for tokens in self._doc_tokens]
        self._avg_len = sum(len(t) for t in self._doc_tokens) / max(1, len(chunks))
        df: Counter[str] = Counter()
        for tokens in self._doc_tokens:
            df.update(set(tokens))
        n = len(chunks)
        self._idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}
        self._vectors: list[list[float]] | None = None
        self._vectors_lock = threading.Lock()

    # --- rankers -------------------------------------------------------------------------------

    def _bm25(self, query: str) -> list[tuple[int, float]]:
        terms = tokenize(query, expand=self.use_glossary)
        scores: list[tuple[int, float]] = []
        for idx, tf in enumerate(self._tf):
            length = len(self._doc_tokens[idx])
            score = 0.0
            for term in set(terms):
                freq = tf.get(term, 0)
                if not freq:
                    continue
                denom = freq + self.K1 * (1 - self.B + self.B * length / self._avg_len)
                score += self._idf.get(term, 0.0) * freq * (self.K1 + 1) / denom
            if score > 0:
                scores.append((idx, score))
        return sorted(scores, key=lambda item: -item[1])

    def _ensure_vectors(self) -> list[list[float]]:
        if self._vectors is None:
            with self._vectors_lock:
                if self._vectors is None:
                    self._vectors = self.embedder.embed([c.indexed_text for c in self.chunks])
        return self._vectors

    def _query_text(self, query: str) -> str:
        if isinstance(self.embedder, HashingEmbedder):
            return f"{query} {' '.join(t for t in tokenize(query, expand=self.use_glossary))}"
        return query

    def _dense(self, query: str, *, qv: list[float] | None = None) -> list[tuple[int, float]]:
        vectors = self._ensure_vectors()
        vec = qv if qv is not None else self.embedder.embed([self._query_text(query)])[0]
        scores = [(idx, _cosine(vec, doc)) for idx, doc in enumerate(vectors)]
        return sorted(scores, key=lambda item: -item[1])

    def _coverage(self, query: str, idx: int) -> float:
        terms = set(tokenize(query, expand=False))
        if not terms:
            return 0.0
        glossary = GLOSSARY if self.use_glossary else {}
        expanded = {t: {t, *(_stem(e) for e in glossary.get(t, ()))} for t in terms}
        present = sum(1 for alts in expanded.values() if any(a in self._tf[idx] for a in alts))
        return present / len(terms)

    # --- public --------------------------------------------------------------------------------

    def _search_one(
        self, query: str, k: int = 4, mode: str = "hybrid", *, qv: list[float] | None = None, dense_failed: bool = False
    ) -> list[Hit]:
        if not self.chunks or not query.strip():
            return []
        if mode == "bm25":
            ranked = self._bm25(query)
        elif mode == "dense":
            if dense_failed:
                ranked = self._bm25(query)
            else:
                try:
                    ranked = self._dense(query, qv=qv)
                except CassetteMiss:
                    raise
                except Exception as exc:  # noqa: BLE001 - an embedding outage degrades to lexical, never to a 500
                    logger.warning("dense_retrieval_failed", extra={"error": repr(exc)})
                    ranked = self._bm25(query)
        else:
            if dense_failed:
                dense: list[tuple[int, float]] = []
            else:
                try:
                    dense = self._dense(query, qv=qv)
                except CassetteMiss:
                    raise
                except Exception as exc:  # noqa: BLE001 - embedding outage degrades to lexical, never to a 500
                    logger.warning("dense_retrieval_failed", extra={"error": repr(exc)})
                    dense = []
            fused: dict[int, float] = {}
            for ranking in (self._bm25(query), dense[: max(20, k * 5)]):
                for position, (idx, _) in enumerate(ranking):
                    fused[idx] = fused.get(idx, 0.0) + 1.0 / (self.RRF_K + position + 1)
            ranked = sorted(fused.items(), key=lambda item: -item[1])
        return [
            Hit(chunk=self.chunks[idx], score=score, coverage=self._coverage(query, idx), rank=rank)
            for rank, (idx, score) in enumerate(ranked[:k], start=1)
        ]

    def search(self, query: str, k: int = 4, mode: str = "hybrid") -> list[Hit]:
        return self._search_one(query, k, mode)

    def search_many(self, queries: dict[str, str], k: int = 4, mode: str = "hybrid") -> dict[str, list[Hit]]:
        """Run several query wordings together, batching hosted embeddings into a single API call."""
        if not self.chunks or not queries:
            return {label: [] for label in queries}
        vectors_by_label: dict[str, list[float]] = {}
        dense_failed = False
        if mode in ("dense", "hybrid"):
            non_empty = [(label, q) for label, q in queries.items() if q.strip()]
            if non_empty:
                try:
                    self._ensure_vectors()
                    embedded = self.embedder.embed([self._query_text(q) for _, q in non_empty])
                    vectors_by_label = {label: vec for (label, _), vec in zip(non_empty, embedded, strict=True)}
                except CassetteMiss:
                    raise
                except Exception as exc:  # noqa: BLE001 - an embedding outage degrades every wording to lexical
                    logger.warning("dense_retrieval_failed", extra={"error": repr(exc)})
                    dense_failed = True
        return {
            label: self._search_one(query, k, mode, qv=vectors_by_label.get(label), dense_failed=dense_failed)
            for label, query in queries.items()
        }


def build_retriever(corpus_dir: Path, embedder: Embedder | None = None, include_raw: bool = False) -> Retriever:
    return Retriever(load_corpus(corpus_dir, include_raw), embedder)
