# 08: Critic calibration set

**What to build:** "Critic present ≠ Critic reliable." Measure the Critic as a classifier: a labelled set of
(question, evidence, draft) with known defects (omitted step, omitted price, unsupported number, wrong language,
action claimed as done, missing caveat) and clean drafts. Report recall on defects and false-revise rate on clean
drafts, per defect type, with floors in the gate.

**Blocked by:** 03

**Status:** resolved (development set); a held-out portion is still to write (see Comments)

- [x] `eval/datasets/critic_calibration.jsonl`: 32 items, 16 clean and 16 with a defect, 2 per type (omitted step, omitted price, unsupported number, wrong language, action claimed done, missing caveat on conflicting pages, unanswered part, human rejection not stated). No golden question is reused. Observations are built from real corpus chunks (by chunk id) and fixture-shaped tool data.
- [x] `eval.run --suite critic` (also part of `--suite all`): one Critic call per item on a fixed draft, so it measures the Critic alone. Reports `recall`, `false_revise_rate`, per-defect catches, and per row the final verdict and the model's own verdict (`model_verdict`, also now in every trace review).
- [x] Floors in `eval/baseline.json`: offline recall >= 0.12 and false revise 0; model recall >= 0.9 and false revise <= 0.2.

## Comments

**Measurements with the real model (2026-11-18), in order:**

| Run | Change before it | Recall | False revise |
|---|---|---|---|
| 1 | none | 16/16 | 4/16 |
| 2 | Critic told that offering a human handoff and pointing to support in general are not claims; a step the merchant already did is not_applicable | 16/16 | 4/16 |
| 3 | Critic told that giving runbook steps labelled as internal guidance is the intended use; drafts k25 and k26 corrected | 16/16 | 1/16 |
| 4 | none | 16/16 | 2/16 |
| 5 | draft k27 corrected | 16/16 | 3/16 |

| 6 | the s11 fixes below | 16/16 | 0/16 |
| 7 | none | 16/16 | 3/16 |

Offline (number check only): recall 2/16, false revise 0/16.

**s11 (golden, 2026-11-18, hosted dense retrieval):** three Critic rounds, 33.6 s. The trace showed the Critic
answering "revise" with no issue at all, every checklist item `not_applicable`, and the Router rewriting blind.
Two causes, both fixed: (1) for a Portuguese draft the whole runbook procedure was listed because the draft's words
cannot be compared with the English corpus, although the draft never used it. A procedure now enters the
checklist only if the draft follows part of it or cites its source; the same chunk returned by two searches counts
once. (2) A "revise" that is grounded and names no issue, no missing part, no must-add item and no research is
treated as an approval (`critic_empty_revisions_total`); an ungrounded one still goes back. After the fixes s11
took one Critic round (11.1 s), and runs 6-7 above kept recall at 16/16.

What this shows:
- With the evidence checklist and itemised review, the Critic caught every planted defect in every run, including the two omission types the 9.3 review named (Wi-Fi step, prices).
- The cost is strictness: 1 to 3 of 16 clean drafts are sent back per run (mean about 0.125, run-to-run noise). The ceiling of 0.2 is set from that range, not from the best run. A false revise costs one more Router round (latency), not a wrong answer.
- Three "clean" drafts I wrote were not clean: k25 suggested checking the plan in the app (not in the evidence), k26 and k27 did not say why the machine declines cards, which the merchant asked. The Critic flagged them; the drafts were corrected and each item carries a `note` saying so. Labels were not flipped to match the Critic.
- k18 stays a disagreement: the merchant says they restarted the machine; the Critic keeps asking for the "wait for the network indicator" half of that step. Defensible either way, left labelled clean.
- Because the prompt was changed after looking at these results, this is a development set (`set: dev`). A held-out batch, written by someone who has not seen the Critic's prompt, belongs with sealed-2 (issue 11).
