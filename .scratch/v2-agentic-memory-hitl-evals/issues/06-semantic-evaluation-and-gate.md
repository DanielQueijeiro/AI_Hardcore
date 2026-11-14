# 06: Semantic evaluation, retrieval ablation and the regression gate

**What to build:** Datasets and a runner that score retrieval, answer semantics and attack resistance through the real API, with a held-out split, an LLM judge with calibration, and thresholds enforced in CI.

**Blocked by:** 01-05

**Status:** resolved

- [x] Retrieval metrics are reported for BM25, dense and hybrid, and the default mode follows them.
- [x] Answers are scored on required facts, forbidden claims, numeric groundedness and citation validity; routing is reported separately.
- [x] Held-out results are reported without tuning.
- [x] The adversarial suite reports attack success, leaks, unauthorized writes and false positives.
- [x] `python -m eval.run --gate` fails on regression; CI runs it.
