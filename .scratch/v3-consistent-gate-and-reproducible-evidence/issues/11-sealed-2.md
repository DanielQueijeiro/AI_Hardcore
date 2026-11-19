# 11: Sealed-2

**What to build:** A new sealed split (s25+), written after the last change to prompts and answer-shaping code,
never used to change either, with its floor fixed in `eval/baseline.json` before its first model run. The current
s01-s24 is relabelled `validation` (ADR-0016's own rule: a split that drove a fix is no longer sealed).

**Blocked by:** 01-07 (freeze first)

**Status:** resolved ([ADR-0022](../../../docs/adr/0022-sealed-2-and-critic-heldout-after-v3-freeze.md))

- [x] s01-s24 relabelled `validation` (offline floors updated to measured offline policy; openai floors untouched); in the same change corrected s22 ("entre na sua conta"), s23 ("US$") and s24 (Portuguese abstention), from issue 05.
- [x] 24 new items (`s25`-`s48`) covering product, abstention, conflict, account, compound, multi-turn memory, HITL (answer/reject in PT/ES), anonymous identity (ES) and live weather (PT), plus 16 held-out Critic calibration items (`k33`-`k48`, 8 defects + 8 clean, `set: "heldout"`), authored blind after the `17ec60d` freeze by an isolated Gemini subagent given only `data/corpus/*.md` and `support_store.py`.
- [x] Authorship, freeze commit SHA (`17ec60d0cce6`), date and dataset SHA-256 hashes recorded in [ADR-0022](../../../docs/adr/0022-sealed-2-and-critic-heldout-after-v3-freeze.md); model floors locked in `eval/baseline.json` before running the model.
- [x] No prompt or answer-shaping code change after `17ec60d` before running `sealed-2`.
- [x] **Follow-on ([ADR-0023](../../../docs/adr/0023-sealed-3-after-post-run-prompt-and-checklist-fixes.md)):** After CI run `44457669721` exposed cross-section `evidence_checklist` bleed and prompt telemetry/FX/settlement issues (plus OpenAI credit exhaustion mid-Run 3), `src/` was fixed and re-frozen at `26be3c3`, `s25`-`s48` (`sealed-2`) was relabelled `validation`, and a fresh blind `sealed-3` (`s49`-`s72`) was authored by an isolated Gemini subagent with all `openai` baseline floors unchanged.
- [x] **Follow-on ([ADR-0024](../../../docs/adr/0024-sealed-4-after-final-prompt-refinements.md)):** After CI run `44469325383` passed 25/26 gated metrics and verified E4 replay (`0` differences across 336 turns) while missing `dev` raw mean by 1 item (`50/54 = 0.926` vs `0.94`), general prompt refinements for video-only pages (`g06`), empty decline telemetry (`g18`), post-answer handoff (`s21`) and dependent subtask sequencing (`s63`) were frozen at `479a6d7`, `s49`-`s72` (`sealed-3`) was relabelled `validation`, and a fresh blind `sealed-4` (`s73`-`s96`) was authored by an isolated Gemini subagent with all `openai` baseline floors unchanged.
