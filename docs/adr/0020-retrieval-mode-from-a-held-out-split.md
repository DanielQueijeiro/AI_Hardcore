# 0020. Retrieval mode re-chosen on a held-out query split: hosted dense when a key is set

Status: accepted (amends [0008](0008-retrieval-mode-chosen-by-measurement.md))

## Context

ADR-0008 chose BM25 from 42 labelled queries: Recall@4 0.988. The 9.3 review called that optimistic, because the query-side glossary (`GLOSSARY` in `src/rag/index.py`, Portuguese and Spanish terms mapped onto the English corpus) was written alongside those same queries. The s04 failure (Portuguese searches never reaching an English passage) pointed the same way.

Two measurements were added to `eval.run --suite retrieval`:

- **A held-out split** of 36 queries (`rh01`-`rh36`, 12 EN, 12 PT, 12 ES), colloquial wording, written after the glossary. The glossary was not edited for them. Their author had read the glossary, so they are unseen by the glossary but not written blind.
- **A glossary ablation**: every mode on both splits with the glossary switched off (`Retriever(use_glossary=False)`).

## Results (2026-11-18)

Recall@4 / MRR:

| | BM25 | dense (keyless) | hybrid (keyless) | dense (hosted) | hybrid (hosted) |
|---|---|---|---|---|---|
| dev, glossary on | 0.988 / 0.948 | 0.952 / 0.913 | 0.976 / 0.958 | 0.988 / 0.976 | 1.000 / 0.964 |
| dev, glossary off | 0.941 / 0.861 | 0.917 / 0.847 | 0.929 / 0.871 | 0.988 / 0.976 | 0.976 / 0.901 |
| held-out, glossary on | **0.708** / 0.632 | 0.764 / 0.627 | 0.806 / 0.662 | **1.000** / 0.944 | 0.917 / 0.810 |
| held-out, glossary off | 0.708 / 0.590 | 0.764 / 0.611 | 0.792 / 0.650 | 1.000 / 0.944 | 0.931 / 0.843 |

Spanish held-out with BM25: Recall@4 0.375. With hosted dense: 1.000.

What it says:
- The reviewer was right. On wording nobody tuned for, BM25 finds the right section in the top 4 for 71% of queries, not 99%. The dev number owed part of itself to the glossary (Spanish dev drops from 1.0 to 0.7 without it).
- Hosted embeddings (`text-embedding-3-small`) are multilingual and do not need the glossary: dense finds 36 of 36 held-out queries, with or without it.
- Hybrid (RRF with BM25) is worse than dense alone on held-out: the lexical ranking pulls weak matches up.

## Decision

- `EMBEDDING_PROVIDER` and `RETRIEVAL_MODE` default to `auto`: with an API key, hosted embeddings and **dense**; without one, the keyless hashing embedder and **BM25** (the ADR-0008 choice, still the best keyless option on dev). CI has no key, so its gate is unchanged.
- Dense retrieval now degrades to BM25 if the embeddings call fails, as hybrid already did. An embedding outage never becomes a tool error.
- The glossary stays: it still helps the keyless path on dev and costs nothing. It no longer carries the model configuration.
- New floors: keyless BM25 held-out Recall@4 >= 0.70 (offline gate), hosted dense held-out Recall@4 >= 0.97 and MRR >= 0.90 (model gate). Each is the measured value, not a target.

## Caveats

- This decision was made after looking at the held-out results, so the held-out split chose between three existing modes. That is a low-dimensional choice (no weights or prompts were tuned on it), but the split is no longer untouched for retrieval. A later retrieval change needs new held-out queries.
- The held-out queries were written by the same project. They differ in wording from dev, not in authorship.
- Every search with hosted dense makes one embeddings call per query wording (the model's query, `query_en`, the merchant's message), which adds latency to each search.
