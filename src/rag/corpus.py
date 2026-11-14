"""Corpus loading and chunking.

One Markdown file per source page, with front matter recording provenance. Chunks are cut on `##`
section boundaries (never across them) and long sections are split on sentence boundaries with a
small overlap. The page title and section heading are prepended to the indexed text so a chunk such
as "Fees" still matches "Get Smart fees".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MAX_CHUNK_CHARS = 1100
OVERLAP_SENTENCES = 1


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    text: str
    source_url: str
    origin: str
    retrieved_at: str = ""

    @property
    def indexed_text(self) -> str:
        return f"{self.title}. {self.section}. {self.text}"

    def as_evidence(self) -> dict[str, str]:
        return {
            "chunk_id": self.chunk_id,
            "title": self.title,
            "section": self.section,
            "source_url": self.source_url,
            "origin": self.origin,
            "text": self.text,
        }


def parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    if not raw.startswith("---"):
        return {}, raw
    try:
        _, header, body = raw.split("---", 2)
    except ValueError:
        return {}, raw
    meta: dict[str, str] = {}
    for line in header.strip().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, body.strip()


def _split_long(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    parts: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        if current and sum(len(s) + 1 for s in current) + len(sentence) > limit:
            parts.append(" ".join(current))
            current = current[-OVERLAP_SENTENCES:]
        current.append(sentence)
    if current:
        parts.append(" ".join(current))
    return parts


def chunk_document(raw: str, fallback_id: str) -> list[Chunk]:
    meta, body = parse_front_matter(raw)
    doc_id = meta.get("id", fallback_id)
    title = meta.get("title", doc_id)
    chunks: list[Chunk] = []
    sections = re.split(r"^##\s+", body, flags=re.M)
    for block in sections:
        block = block.strip()
        if not block:
            continue
        if "\n" in block:
            heading, text = block.split("\n", 1)
        else:
            heading, text = title, block
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        for part in _split_long(text):
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}#{len(chunks)}",
                    doc_id=doc_id,
                    title=title,
                    section=heading.strip(),
                    text=part,
                    source_url=meta.get("source_url", ""),
                    origin=meta.get("origin", "unknown"),
                    retrieved_at=meta.get("retrieved_at", ""),
                )
            )
    return chunks


def load_corpus(corpus_dir: Path, include_raw: bool = False) -> list[Chunk]:
    """Curated snapshot files; with include_raw, also the page captures written by scripts/ingest_getnet.py."""
    chunks: list[Chunk] = []
    paths = sorted(p for p in corpus_dir.glob("*.md") if p.name.lower() != "readme.md")
    raw_dir = corpus_dir / "raw"
    if include_raw and raw_dir.is_dir():
        paths += sorted(raw_dir.glob("*.md"))
    for path in paths:
        fallback = path.stem if path.parent == corpus_dir else f"raw-{path.stem}"
        chunks.extend(chunk_document(path.read_text(encoding="utf-8"), fallback))
    return chunks
