# 0008. Curated corpus with provenance; retrieval mode chosen by measurement

Status: accepted (supersedes 0003)

Corpus. One Markdown file per source page of the Getnet Brazil site, with `source_url`, `origin` and `retrieved_at` in front matter. Facts are restated in English with the Portuguese terms kept, and where a page is silent or contradicts itself the file says so, which makes "the site does not specify" a retrievable, citable answer instead of a hallucination risk. `scripts/ingest_getnet.py` captures the live pages with a content hash and reports changes; raw captures are indexed only on request because page chrome dilutes ranking. The internal runbook is labelled mock content.

Storage. In memory. Thirty chunks do not justify a vector database; `Retriever.search(query, k, mode)` is the seam for one.

Retrieval. The first version asserted a 0.45/0.35/0.20 dense/title/body blend. It was never measured. There are now three modes (BM25, dense, RRF hybrid) and a labelled set of 42 queries in three languages. With the keyless hashing embedder the hybrid does not beat BM25 (Recall@4 0.976 vs 0.988, MRR 0.946 vs 0.948) and is worse on Portuguese, so BM25 is the default. The sample is small, so the claim is "no evidence the hybrid helps here". Hosted embeddings are supported and may change the result; the same command decides.

Abstention. Each hit carries the share of query terms it covers, surfaced to the agent as a relevance rating. A poor rating is the signal to reformulate, switch tool, or say the knowledge base does not cover the question.

Measured with hosted embeddings (added after the first model run). The same 42 queries with `text-embedding-3-small`: hybrid Recall@4 1.000 and MRR 0.964, dense 0.988 and 0.964, BM25 0.988 and 0.948. So with a real semantic embedder the hybrid is at least as good as BM25 on every metric, by a margin of one or two queries. The model evaluation report prints both tables side by side. The default stays BM25 with the keyless embedder because it needs no key, no network and no cache, and one or two queries out of 42 is not evidence enough to add a dependency to every search; a deployment that already has the key can set `EMBEDDING_PROVIDER=openai` and `RETRIEVAL_MODE=hybrid`, which is what the numbers favour.
