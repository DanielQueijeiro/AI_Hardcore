"""Hybrid RAG ingestion combining live getnet.net scraping with curated Getnet Brazil corpus (ADR-0003)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from src.config import get_settings

HEADING_ANCHOR_PATTERN = re.compile(r"^(#+)\s+(.*?)(?:\s*\{#([a-z0-9_-]+)\})?\s*$", re.I)


@dataclass(frozen=True)
class DocumentChunk:
    """Semantic document chunk indexed by the Hybrid RAG pipeline."""

    chunk_id: str
    title: str
    content: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def parse_markdown_corpus(
    markdown_text: str,
    source_label: str = "data/getnet_knowledge_base.md",
) -> list[DocumentChunk]:
    """Split a Markdown knowledge base by level-2 sections into self-contained DocumentChunks."""
    lines = markdown_text.splitlines()
    chunks: list[DocumentChunk] = []

    current_title = "Getnet Overview"
    current_anchor = "overview"
    current_lines: list[str] = []

    def _flush() -> None:
        body = "\n".join(current_lines).strip()
        if not body or len(body) < 40:
            return
        source_ref = f"{source_label}#{current_anchor}" if current_anchor else source_label
        chunks.append(
            DocumentChunk(
                chunk_id=f"kb-{len(chunks) + 1}-{current_anchor}",
                title=current_title,
                content=f"## {current_title}\n{body}",
                source=source_ref,
                metadata={"origin": "curated_kb", "section": current_title, "anchor": current_anchor},
            )
        )

    for line in lines:
        match = HEADING_ANCHOR_PATTERN.match(line)
        if match and len(match.group(1)) == 2:
            _flush()
            raw_title = match.group(2).strip()
            explicit_anchor = match.group(3)
            current_title = raw_title
            current_anchor = explicit_anchor or _slugify(raw_title)
            current_lines = []
        else:
            current_lines.append(line)

    _flush()
    return chunks


def scrape_getnet_website(
    url: str = "https://www.getnet.net/en",
    timeout_seconds: float = 2.0,
) -> list[DocumentChunk]:
    """Fetch and parse live Getnet website content with graceful timeout/WAF resilience (ADR-0003)."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        response = httpx.get(url, headers=headers, timeout=timeout_seconds, follow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(["script", "style", "noscript", "svg", "footer", "nav"]):
            tag.decompose()

        extracted_blocks: list[str] = []
        for elem in soup.find_all(["h1", "h2", "h3", "p", "li"]):
            text = " ".join(elem.get_text(" ", strip=True).split())
            if len(text) >= 35 and text not in extracted_blocks:
                extracted_blocks.append(text)

        if not extracted_blocks:
            return []

        chunks: list[DocumentChunk] = []
        window_size = 6
        for idx in range(0, min(len(extracted_blocks), 24), window_size):
            block_text = "\n".join(extracted_blocks[idx : idx + window_size])
            chunks.append(
                DocumentChunk(
                    chunk_id=f"web-{idx // window_size + 1}",
                    title=f"Getnet Official Web Content ({url})",
                    content=block_text,
                    source=url,
                    metadata={"origin": "live_web_scrape", "url": url},
                )
            )
        return chunks
    except Exception:
        # Per ADR-0003: never fail ingestion when getnet.net is slow, offline, or WAF-blocked
        return []


def load_hybrid_corpus(
    knowledge_base_path: Path | None = None,
    scrape_url: str | None = None,
    enable_live_scrape: bool | None = None,
) -> list[DocumentChunk]:
    """Load the hybrid Getnet RAG corpus from curated Markdown and optional live web scraping."""
    settings = get_settings()
    kb_path = knowledge_base_path or settings.knowledge_base_path
    target_url = scrape_url or settings.getnet_scrape_url
    do_scrape = settings.enable_live_web_scrape if enable_live_scrape is None else enable_live_scrape

    chunks: list[DocumentChunk] = []

    # Resolve path relative to current working directory or project root if needed
    resolved_kb_path = kb_path
    if not resolved_kb_path.exists():
        repo_root = Path(__file__).resolve().parents[2]
        candidate = repo_root / kb_path
        if candidate.exists():
            resolved_kb_path = candidate

    if resolved_kb_path.exists():
        markdown_text = resolved_kb_path.read_text(encoding="utf-8")
        chunks.extend(
            parse_markdown_corpus(
                markdown_text=markdown_text,
                source_label="data/getnet_knowledge_base.md",
            )
        )

    if do_scrape and target_url:
        chunks.extend(scrape_getnet_website(url=target_url))

    return chunks
