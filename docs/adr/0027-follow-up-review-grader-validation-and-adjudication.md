# 0027. Follow-up review: validating the fact patterns, a stricter adjudication rule, and what is still blind

Status: accepted

## Context

An independent follow-up review of `main` at `98c8eb5` (scored 9.4) reproduced the keyless replay and the offline gate, and found:

- The output guard let a card number through when a '.' or ',' followed it, or a digit group preceded it.
- The Critic checklist read Portuguese "Sim" (yes) as the SIM card.
- 12 of the final run's 17 raw failures are the deterministic fact patterns, not the agent.
- Three adjudications called "judge error" (`h18`, `s18`, `s43`) excused answers that add unrequested content or a meta-remark — the behaviour ADR-0026 fixed as a system defect on `dev`.
- One passing CI run out of several does not show that the gate passes consistently, and `sealed-4` has now been measured twice.
- Several published numbers were stale or misattributed across the README, `REVIEW_RESPONSE.md` and ADR-0026.

## Decision

1. **Fix the two defects without changing any published answer.** The redactor now ends a digit run at '.' or ',' only when a digit follows (a decimal amount) and tries every window of whole digit groups. It has property-style tests: 10 card schemes × every printed layout × 11 prefixes × 13 endings, plus amounts, phones, identifiers and Luhn-invalid neighbours that must stay. "SIM" alone now matches only in capitals. Replaying the published cassette still reproduces all 408 answers and every metric with 0 differences.
2. **Measure the grader instead of editing it.** `python -m eval.fact_audit` runs every fact pattern against its own reference and against every committed answer adjudicated correct with the miss attributed to the patterns. Today, 11 of 391 pattern groups miss a known-correct wording (7 `heldout`, 4 `validation`; [eval/reports/fact-pattern-audit.md](../../eval/reports/fact-pattern-audit.md)). Patterns stay as written: on a sealed split by the sealed-split rule, and everywhere because changing a pattern would change the published, replayable report.
3. **Before any new split is sealed**, its fact patterns must satisfy the item's reference and at least two paraphrases per item written by someone other than the pattern author, in each language the item expects. `eval.fact_audit` must report none of them before the split's first run.
4. **One adjudication rule for every split from the final run on.** An answer that adds unrequested content, a hypothetical, or a remark about what a source does not cover counts as an agent defect, even when the judge's stated reason is wrong. `s18` (the whole offline runbook added to a status question) and `s43` (runbook plus "the guidance does not confirm…") are re-adjudicated as `agent`. `h18` stays a judge error, against the review's reading: it gives the product page's R$ 60,000 and reports the conflicting all-machines figures from the evidence, which is exactly what the dual-reviewer borderline set requires for the same conflict on the Get Clássica (`b06a`, where dropping the conflict is labelled fail). Adjudicated `all` goes from 0.995 to **0.990 (404/408)**, `validation` from 0.993 to **0.986**; causes are now 12 `grader_facts`, 4 `agent`, 1 `judge`. The archived run's adjudications predate this rule and are kept as written. The gate never read adjudications, so its verdict does not change.
5. **What is still blind.** `sealed-4` has been measured twice, in 44569607884 and 44622842628. No `sealed-4` answer drove a change (ADR-0026), but it is no longer blind for future work: the next change to `src/` that targets answer quality needs a new sealed split, authored under rule 3.
6. **Consistency is measured, not asserted.** The local real-model checks behind `e031a8e` put `dev` at about one random failure in 27 conversations. Under that rate the `dev` gate passes about 85% of the time, and three perfect runs are about a 13% draw. A second CI model run on the same system was recorded to measure it (see the README's Results), and the cancelled run 44606495899 is disclosed: it was stopped after 20 minutes to switch to the parallel job and produced no results.

## Consequences

- The guard and checklist fixes are covered by tests and leave the published evidence reproducible at the new commit.
- The raw `sealed-4` score keeps carrying grader error (0.875 raw against 1.000 judge and adjudicated). The audit puts a number on that error rather than hiding it.
- Adjudicated numbers are lower and stricter. They are reported next to the raw numbers, never instead of them.
