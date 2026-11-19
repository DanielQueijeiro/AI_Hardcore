# 05: Grader fact patterns on dev and validation

**What to build:** Five of the thirteen adjudicated failures were fact patterns that missed a correct phrasing.
Fix the ones on dev and validation. The items s01-s24 become validation once phase 1 lands (see spec), so their
patterns may be corrected too, and the README must say that this happened after their sealed measurement was
published.

**Blocked by:** none

**Status:** dev part resolved; s23/s24 moved to 11

- [x] g08 accepts "scheduled" (and PT/ES forms) as the approval fact.
- [x] g18 accepts "no decline code" and "did not return ... decline".
- [ ] s23 accepts "US$"; s24 accepts the Portuguese abstention. **Moved to 11**: while s01-s24 are labelled `heldout`, ADR-0016 says their patterns stay as written. They are corrected in the same change that relabels them `validation`.
- [x] The fact check over every stored answer of the 2026-11-16 report (3 runs x 64) changes exactly three verdicts, all adjudicated as "fact pattern": g08 run 2, g18 runs 2 and 3. No pass became a fail. (Done with `eval.metrics.fact_coverage` directly; `--regrade` would also re-run the judge, which needs the key.)
