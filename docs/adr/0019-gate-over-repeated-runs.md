# 0019. The regression gate reads every run of a repeated measurement

Status: accepted (amends [0013](0013-semantic-evaluation-with-a-regression-gate.md) and [0016](0016-sealed-held-out-and-independent-judge-calibration.md)). Written and merged before the measurement it will judge.

## Context

Until now the gate read run 1 of `--repeat N` and ignored the others. The 2026-11-16 report failed it: dev semantic pass 0.833 against a floor of 0.94. Across the six model runs of dev on record (2026-11-14 and 2026-11-16) the rate was 0.833, 0.944, 0.944, 0.833, 0.889, 0.889. Dev has 18 items, so one item moves the rate by 0.056, and the floor of 0.94 allows at most one failure. A single run's verdict therefore depends on which run happened to come first: the same code passed or failed the gate depending on the draw.

The 9.3 review asked the right question: lower the threshold, change the system, or change the dataset? Lowering the floor after seeing a result is not acceptable. Changing the dataset to make items easier is not either. What can legitimately change is how the measurement is read, and only if the rule is fixed before the next measurement and is not a lower bar in disguise.

## Decision

For golden metrics, the gate reads all N runs:

- **Floors (`min`)**: the mean over the runs must reach the floor, and no single run may be more than one item below it (one item = 1/n of that split; for a judge rate, 1/n of the judged answers).
- **Ceilings (`max`)**: every run must be within the limit. Forbidden claims and degraded turns are not averaged away.
- Every other suite (retrieval, adversarial, calibration) runs once and is gated on that run, as before.
- With one run the rule is exactly the old one, so the offline CI gate is unchanged.

No floor in `eval/baseline.json` is lowered by this change.

## Why this is not a lower bar

- Applied to the published 2026-11-16 report, the new rule still fails it: dev 0.833, 0.889, 0.889, mean 0.870 against 0.94.
- It is stricter than the old rule wherever run 1 was lucky: run 1 at 1.000 with run 2 at 0.833 used to pass and now fails twice over (mean 0.917, and run 2 is two items below).
- It is looser only in one case: run 1 is exactly one item below the band and the other runs make up for it with a mean above the floor. That is the case where the old verdict was decided by run order.

## Consequences

- The model report must be run with `--repeat 3` (or more) to be gated meaningfully; a single run is still allowed and gated as before.
- The report records the rule (`gate_rule`) next to the verdict, and every failure line lists all runs and the mean.
- The tolerance is one item, not a percentage, so a larger split gets a tighter per-run band automatically.
- This does not make dev pass. Whether dev passes is now a question about the system, which is what the phase-1 fixes of v3 address, measured in the final three-run report.
