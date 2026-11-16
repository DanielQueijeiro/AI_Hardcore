# 0017. Reports carry their provenance; failures are re-gradable and adjudicated; the gate stays raw

Status: accepted (amends [0013](0013-semantic-evaluation-with-a-regression-gate.md) and [0016](0016-sealed-held-out-and-independent-judge-calibration.md))

An audit of the published model report found that its numbers could not answer three questions a reviewer asks first.

- Which code produced it? The report recorded dataset hashes only, and every commit of this version was made after the runs, so neither the report nor the history ties the result to the code.
- Was a failure the agent's or the grader's? Of the eight failed answers across the three runs, review found four grader errors: two fact patterns that missed a correct phrasing ("do not confirm", "entre na sua conta") and two judge verdicts that called a sentence unsupported although the runbook passage the answer drew on contains it. The other four are the agent's (EUR/USD instead of EUR/BRL, a left-out Wi-Fi step, a false "not documented", a missed battery time). The gate failure on dev in run 1 is two grader errors and one agent error.
- Why did a sealed item miss a documented fact? For s18 the report did not keep the search queries, so retrieval and reading could not be told apart.

What changed, all in the harness, nothing in the agents, prompts, judge or datasets:

- Every report records `provenance`: the git commit, whether the tree differed from it (and where), and SHA-256 of the source tree, the prompts, the judge, the baseline, the corpus and the poisoned corpus.
- Every golden item stores its tool calls with their arguments, the SHA-256 of its answer, and the exact input the judge saw. `--regrade REPORT --regrade-times N` grades the stored answers again, N times each with a majority verdict, without running the agents: judge noise can now be measured apart from agent noise, which [0016](0016-sealed-held-out-and-independent-judge-calibration.md) could only do by hand on six answers.
- `eval/adjudications.jsonl` holds a human review of each failed answer, keyed to the SHA-256 of that exact answer so a verdict never carries over to another answer to the same question, with its cause (`agent`, `judge`, `grader_facts`, `harness`). Reports show the raw and the adjudicated semantic pass side by side; `--adjudicate` attaches the current reviews to an existing report without touching any measured number. A test fails if a failure of the published report has no review.
- `--ids` / `--split` run part of the golden suite for checking a fix on a few items. Such a run is never gated and never written over the report.

What did not change, on purpose. The gate reads the raw numbers: an adjudication explains a failure, it does not undo it, because the reviewer is the project and a gate that its own author can talk out of failing protects nothing. Sealed items keep their fact patterns as written, s22 included; the adjudication is where the grader error is recorded. And adjudicating the published report did not re-seal anything: the review read the sealed answers, but no prompt, judge, corpus or dataset changed because of it. The next change that does follows the rule of [0016](0016-sealed-held-out-and-independent-judge-calibration.md): the sealed split becomes validation and a new one is written first.

The first measurement with stored evidence (2026-11-16, commit `6202c2b`, clean tree) settled what the earlier one could only infer. A judge verdict calling "Pix or a Payment Link" unsupported was checked against the stored judge input, which contains the runbook sentence. s04 failed because every search was a Portuguese reformulation and the English passage never came back, a retrieval miss rather than the reading miss the earlier review guessed. And it found a defect no test had: the output guard's card-number check fired on the support WhatsApp number, whose 13 digits pass Luhn. Of thirteen failures, seven are the system's, one the judge's, five the fact patterns'. The gate failed on dev in run 1 again (0.833), and stays below its floor in that run even adjudicated (0.889). The 2026-11-14 report is kept beside it as `report-2026-11-14.*`, with its own adjudications.

Known weakness: the adjudications are the project's own judgement. Each one states its evidence (the passage, the regex, the score) so a reader can check it, and the raw numbers stay next to them.
