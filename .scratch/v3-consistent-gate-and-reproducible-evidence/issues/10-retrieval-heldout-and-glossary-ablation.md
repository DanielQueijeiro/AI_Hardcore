# 10: Retrieval held-out split and glossary ablation

**What to build:** Recall@4 0.988 is optimistic: the glossary was written alongside the 42 queries. Add retrieval
queries written without looking at the glossary (EN/PT/ES, colloquial wording), and report every mode with the
glossary on and off.

**Blocked by:** 02

**Status:** resolved

- [x] 36 held-out queries (`rh01`-`rh36`, `split: heldout`, 12 per language) in `eval/datasets/retrieval.jsonl`; the glossary was not edited for them. Existing queries are `dev` by default, so every existing gated metric keeps its meaning.
- [x] `run_retrieval` reports dev (gated as before), `heldout`, and `glossary_off` for both; `Retriever(use_glossary=False)` switches the glossary off.
- [x] Result and decision in [ADR-0020](../../../docs/adr/0020-retrieval-mode-from-a-held-out-split.md): keyless BM25 held-out Recall@4 0.708 (Spanish 0.375); hosted dense 1.000. `auto` defaults now pick hosted dense when a key is set, BM25 otherwise; dense degrades to BM25 on an embeddings outage.
- [x] Floors added for held-out (keyless BM25 >= 0.70 offline; hosted dense >= 0.97 Recall@4 and >= 0.90 MRR with the model).
- [ ] README states the held-out numbers next to the dev ones (issue 13).

## Comments

Multi-query search (issue 02) is not in this ablation: the retrieval set has one wording per query, and the
merchant-message variant only exists inside a turn. Its effect shows in the golden suite.
