# 11: Sealed-2

**What to build:** A new sealed split (s25+), written after the last change to prompts and answer-shaping code,
never used to change either, with its floor fixed in `eval/baseline.json` before its first model run. The current
s01-s24 is relabelled `validation` (ADR-0016's own rule: a split that drove a fix is no longer sealed).

**Blocked by:** 01-07 (freeze first)

**Status:** needs-info (author: an outside person, or a different model family declared as such)

- [ ] s01-s24 relabelled `validation` (baseline floors moved accordingly, the README says when and why); in the same change correct s23 ("US$") and s24 (Portuguese abstention), from issue 05.
- [ ] 24+ items covering the same categories as s01-s24, including compound, HITL and cross-lingual cases.
- [ ] Authorship and date recorded; dataset hash in the first report.
- [ ] No prompt or code change after the first sealed-2 run without relabelling it.
