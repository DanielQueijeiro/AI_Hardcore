"""Hybrid RAG ingestion and local CPU vector retrieval package (ADR-0003, ADR-0004)."""

from src.rag.ingest import DocumentChunk, load_hybrid_corpus, parse_markdown_corpus, scrape_getnet_website
from src.rag.retriever import GetnetHybridRetriever, RetrievedChunk, get_retriever

__all__ = [
    "DocumentChunk",
    "GetnetHybridRetriever",
    "RetrievedChunk",
    "get_retriever",
    "load_hybrid_corpus",
    "parse_markdown_corpus",
    "scrape_getnet_website",
]
