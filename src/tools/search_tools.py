"""Knowledge Agent tools: Hybrid Getnet RAG retrieval (Ticket 02)."""

from __future__ import annotations

from dataclasses import dataclass

from src.rag.retriever import RetrievedChunk, get_retriever


@dataclass(frozen=True)
class KnowledgeRetrievalResult:
    """Structured output from retrieve_getnet_knowledge tool."""

    query: str
    chunks: list[RetrievedChunk]
    sources: list[str]
    context_text: str


def retrieve_getnet_knowledge(
    query: str,
    top_k: int = 2,
    enable_live_scrape: bool = False,
) -> KnowledgeRetrievalResult:
    """Query the local CPU Hybrid RAG index and return top chunks with source citations."""
    retriever = get_retriever(enable_live_scrape=enable_live_scrape)
    matched = retriever.retrieve(query=query, top_k=top_k)

    sources: list[str] = []
    for chunk in matched:
        if chunk.source not in sources:
            sources.append(chunk.source)

    context_blocks = [
        f"[Source: {chunk.source}]\n{chunk.content}"
        for chunk in matched
    ]
    return KnowledgeRetrievalResult(
        query=query,
        chunks=matched,
        sources=sources,
        context_text="\n\n---\n\n".join(context_blocks),
    )
