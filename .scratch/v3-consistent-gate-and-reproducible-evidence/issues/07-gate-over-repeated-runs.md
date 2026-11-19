# 07: A gate over repeated runs, decided before measuring

**What to build:** Dev has 18 items: one item is 5.6 points. Six runs measured 0.833-0.944, so a floor of 0.94 on a
single run sits inside the system's own variance. The gate reads run 1 only. Changing that is legitimate only if
the rule is written down before the next measurement and is not a lower bar in disguise.

**Blocked by:** none (must land before 11 and 13)

**Status:** resolved

- [x] [ADR-0019](../../../docs/adr/0019-gate-over-repeated-runs.md): golden floors are met by the mean of the runs with no run more than one item below; golden ceilings (forbidden claims, degraded turns) by every run; other suites run once. One run = the old rule exactly, so the offline CI gate is unchanged.
- [x] No floor lowered. Applied to the published 2026-11-16 report the new rule still fails it (dev 0.833, 0.889, 0.889, mean 0.870 < 0.94); the ADR says so.
- [x] `check_gate` implements it; the report records `gate_rule` and every failure line lists all runs and the mean. Tests: tolerated one-item dip, two-item dip with a passing mean (fails), the published dev runs (fails on the mean), a ceiling broken in one run, single-run equivalence.
