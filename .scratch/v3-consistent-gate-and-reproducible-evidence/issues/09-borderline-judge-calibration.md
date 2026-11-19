# 09: Borderline judge calibration with two human labellers

**What to build:** Calibration is kappa 1.000 on clear-cut pairs, yet the report holds a real judge error (g15).
Add a `borderline` set: near-miss pairs (a dropped caveat, a paraphrased step, an extra unasked fact, a correct
answer in different words than the reference), each labelled independently by two humans before the judge sees it.

**Blocked by:** none

**Status:** resolved (1 human + 1 cross-family model, declared in `eval/labels/README.md`)

- [x] 20 borderline answers (`eval/datasets/judge_borderline.jsonl`, 10 questions x 2): rounding a rate, "all at once" vs "in installments", a hedged correct answer, a dropped Wi-Fi step, "no fee published" turned into "free", a dropped conflicting-pages caveat, an unsupported "no interest" addition, extra correct detail, a wrong CPF/CNPJ claim, "in seconds" without the up-to-one-day caveat. Evidence is the real corpus text.
- [x] `eval/labels/BORDERLINE_SHEET.md` (what each labeller reads) and `eval/labels/borderline_TEMPLATE.csv` (what each fills).
- [x] `python -m eval.borderline A.csv B.csv` prints reviewer agreement, kappa and disagreements; with `--final agreed.csv` it writes the agreed label and both reviewers' labels into the dataset.
- [x] Calibration includes borderline items only once labelled, reports them as their own set with `human_agreement` / `human_kappa` (rendered as `Reviewer agreement` / `Reviewer kappa`) next to the judge's, and keeps them out of the headline agreement (which stays "clear-cut cases").
- [x] Independently labelled by `reviewer1` (Gemini, cross-family, blind to `reviewer2` and to the OpenAI judge) and `reviewer2` (Daniel Queijeiro, human): 20/20 agreement (`kappa = 1.000`, 0 disagreements), merged into `eval/datasets/judge_borderline.jsonl` via `eval/borderline.py`. Provenance and the 1-human + 1-cross-family-model caveat are documented in `eval/labels/README.md`.
- [x] Floor `calibration.by_set.borderline.agreement >= 0.75` locked in `eval/baseline.json` before running the judge.

## Comments

I wrote the answers, so I am not one of the labellers: my intended reading of each pair would not be independent.
