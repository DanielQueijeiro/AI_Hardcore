# 09: Borderline judge calibration with two human labellers

**What to build:** Calibration is kappa 1.000 on clear-cut pairs, yet the report holds a real judge error (g15).
Add a `borderline` set: near-miss pairs (a dropped caveat, a paraphrased step, an extra unasked fact, a correct
answer in different words than the reference), each labelled independently by two humans before the judge sees it.

**Blocked by:** none

**Status:** ready-for-human (the tooling is built; the labels must come from two people)

- [x] 20 borderline answers (`eval/datasets/judge_borderline.jsonl`, 10 questions x 2): rounding a rate, "all at once" vs "in installments", a hedged correct answer, a dropped Wi-Fi step, "no fee published" turned into "free", a dropped conflicting-pages caveat, an unsupported "no interest" addition, extra correct detail, a wrong CPF/CNPJ claim, "in seconds" without the up-to-one-day caveat. Evidence is the real corpus text. No labels are in the file.
- [x] `eval/labels/BORDERLINE_SHEET.md` (what each labeller reads) and `eval/labels/borderline_TEMPLATE.csv` (what each fills).
- [x] `python -m eval.borderline A.csv B.csv` prints human-human agreement, kappa and disagreements; with `--final agreed.csv` it writes the agreed label and both humans' labels into the dataset.
- [x] Calibration includes borderline items only once labelled, reports them as their own set with `human_agreement` / `human_kappa` next to the judge's, and keeps them out of the headline agreement (which stays "clear-cut cases").
- [ ] Two people label the 20 answers independently (the user plus one other person); disagreements discussed and the final file merged.
- [ ] Floor for `calibration.by_set.borderline.agreement` set below the human-human agreement, after the first judge run on labelled items.

## Comments

I wrote the answers, so I am not one of the labellers: my intended reading of each pair would not be independent.
