# 02: Cross-lingual multi-query retrieval

**What to build:** In s04 every search was a Portuguese reformulation; BM25 over the English-restated corpus never
returned the "up to 5 devices" passage. The tool description and the Knowledge Agent's instructions push the model
towards the Portuguese term ([src/tools/registry.py](../../../src/tools/registry.py),
[src/agents/prompts.py](../../../src/agents/prompts.py)), and the query-side glossary
([src/rag/index.py](../../../src/rag/index.py)) has no entry for the words used.

Retrieval should not depend on the model picking the corpus language. One `search_knowledge_base` call runs
several query variants (the model's query, the merchant's own message, and an optional English form the model
supplies) and fuses the rankings with reciprocal rank fusion, so a passage any variant finds can surface.

**Blocked by:** none

**Status:** resolved

- [x] The search tool accepts an optional `query_en` and always also searches the merchant's original message. Instead of RRF over all variants, the model's query keeps its own top-k unchanged and the other wordings may each add passages it did not have (at most 2, interleaved by rank), so a focused query can never be pushed out by a noisy one.
- [x] Tool description and Knowledge Agent instructions ask for the English form of the query (the corpus language), instead of "try the Portuguese term".
- [x] A test reproduces s04: the Portuguese query alone misses "up to 5 devices"; the merchant's message or `query_en` brings it in; the query's own ranking is unchanged; an identical wording is not searched twice.
- [x] Retrieval metrics on the 42 queries and every offline golden metric are unchanged (offline gate passed, same numbers as the committed report).
- [x] Each passage carries `matched_by`, and the result lists `also_searched`; both are in the stored evidence and the trace.
