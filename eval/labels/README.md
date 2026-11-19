# Borderline judge-calibration labels

The 20 near-miss answers in [`../datasets/judge_borderline.jsonl`](../datasets/judge_borderline.jsonl) were
labelled independently against [`BORDERLINE_SHEET.md`](BORDERLINE_SHEET.md) before running the OpenAI judge
(`gpt-5.4-mini`) on them:

- **`reviewer1`** (`borderline_reviewer1.csv`): independent Gemini pass, blind to `reviewer2`, blind to the
  OpenAI judge (`gpt-5.4-mini`), and from a different model family than Claude (which drafted the sheet).
- **`reviewer2`** (`borderline_reviewer2.csv`): Daniel Queijeiro (human), labelled independently without seeing
  `reviewer1`'s labels.
- **Consensus** (`borderline_final.csv`): merged into `judge_borderline.jsonl` via `python -m eval.borderline`.

Pre-reconciliation agreement between `reviewer1` and `reviewer2`: **20/20** (agreement `1.000`, Cohen's kappa
`1.000`, 0 disagreements).

## Caveat

This is **one human + one cross-family model**, not two independent external humans. The `1.000` inter-reviewer
agreement reflects clear adherence to the written rubric rather than noisy real-world annotator variance.
