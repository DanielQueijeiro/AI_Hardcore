# 03: Critic completeness checked against the evidence

**What to build:** The Critic is asked whether a draft is complete and answers yes/no. It approved g12 without the
runbook's "connect to the store Wi-Fi" step in both model reports, and g01 without the rental prices. Asking the
same kind of model the same question again does not fix that; the check has to be anchored in the evidence, not
in the draft.

Two layers, both feeding the existing `revise` path to the Router:

1. **Deterministic omission check** (`src/agents/checks.py`): from the evidence passages the draft relies on,
   extract the items a complete answer cannot drop: the steps of a numbered procedure, and the prices of products
   the merchant named. Items missing from the draft are passed to the Critic as "possibly omitted", like
   unsupported numbers are today.
2. **Structured review**: the Critic's `review` call enumerates the parts of the merchant's question and, for each,
   whether the draft answers it and which evidence covers it. `complete` is derived from that list in code, not
   taken from a free boolean.

**Blocked by:** none

**Status:** resolved in code; effect on the model measured only in 13

- [x] `evidence_checklist` (`src/agents/checks.py`) extracts numbered procedures from retrieved passages; for an English draft it marks each step found or not by its distinctive words, for other languages it lists every step as "check the draft". A procedure the draft does not follow at all is not in play.
- [x] A draft that names two products, or asks about price, and states no R$ amount gets an item per product with the amounts the evidence attaches to it (g01).
- [x] Only items not found are shown to the Critic; covered steps are not listed (no noise for complete drafts).
- [x] Review schema has `parts` (question part, answered) and `checklist` (item, in_draft / not_applicable / must_add, reason). Any unanswered part or `must_add` item forces `revise` in code, whatever the overall verdict.
- [x] Scripted-model tests: the g12 situation (Critic must rule on the Wi-Fi step, says must_add, Router rewrites with it) and an unanswered part.

## Comments

The offline policy's Critic ignores the checklist, so the offline gate cannot show a false-revise rate; that is
what the Critic calibration set (08) measures. Human decisions (04) reuse the same checklist.
