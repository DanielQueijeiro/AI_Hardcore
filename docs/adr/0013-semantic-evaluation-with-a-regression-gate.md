# 0013. Semantic evaluation with a regression gate

Status: accepted

The first version reported 12/12 from a check of route, tools and non-empty answer. A wrong answer on the right route passed. The evaluation now separates three questions and never mixes them:

- Did retrieval find the right passage? Recall@k, Hit@k, MRR, nDCG on labelled queries, per mode and language.
- Is the answer right, grounded and safe? End-to-end through the HTTP API: required facts as sets of acceptable phrasings (exact for numbers and codes in any language; for wording still pattern matching, whose cost the model run measured, see [0017](0017-evaluation-provenance-regrading-and-adjudication.md)), forbidden claims, numeric groundedness against the evidence in the turn's trace, citation validity, and an LLM judge with a rubric and a human-written reference.
- Did it take a sensible path? Reported as "routing as expected" and excluded from the quality score.

The judge is a separate call, optionally a different model, and its pass rule is computed in code from its scores. It is calibrated against human pass/fail labels on hand-written good and bad answers; false passes are the figure that matters.

A held-out split is never used for tuning and its failures stay in the report. Thresholds per mode live in `eval/baseline.json`; `--gate` fails on regression and CI runs the offline gate on every push. The offline report is explicit that it measures the pipeline and groundedness, not model quality.

Known weakness: the datasets are small and single-author. They are sized to catch regressions, and the README says so.

What the first runs against the real model changed in the harness and the judge is recorded in [0015](0015-what-the-first-model-run-changed.md): a gated metric that was not produced now fails the gate, each golden item runs on fresh databases, language match is measured and gated, and the judge calibration set includes the failure modes those runs exposed.

The held-out split described above was later found to have been re-run between fixes; it is now called `validation`, and a sealed split and an independent calibration set were added. See [0016](0016-sealed-held-out-and-independent-judge-calibration.md).
