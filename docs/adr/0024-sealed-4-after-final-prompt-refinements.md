# 0024. Sealed-4 after final prompt refinements on video-only pages, empty decline telemetry, and dependent subtasks

Status: accepted (amends [0016](0016-sealed-held-out-and-independent-judge-calibration.md), [0022](0022-sealed-2-and-critic-heldout-after-v3-freeze.md) and [0023](0023-sealed-3-after-post-run-prompt-and-checklist-fixes.md)). Written and merged before the first model run of `sealed-4`.

## Context

On 2026-11-19, CI workflow run `44469325383` (`feat/v3-gate-reproducibility` at commit `5bf1c98c8d2d`, `src/` frozen at `26be3c3`) ran the complete `--repeat 3` model evaluation (3x112 = 336 conversations, 68 adversarial cases, 48 Critic drafts, 60 Judge calibration items, 78 retrieval queries) with `0` degraded turns and `0` forbidden claims, and its recorded 5.6 MB cassette reproduced all 336 answers and every metric offline with **0 differences and 0 unused calls** (`eval.compare`).

25 of 26 gated metrics passed by comfortable margins:
- Hosted dense retrieval (`text-embedding-3-small`): dev `Recall@4 0.988`, `MRR 0.976`; held-out (36 post-glossary queries) `Recall@4 1.000`, `MRR 0.944` (identical with `glossary_off`, vs BM25 `0.708 / 0.632`).
- Critic calibration: `1.000` recall across all 8 defect classes (`dev` `1.000` recall / `0.125` false revise; unseen `heldout` `k33`-`k48` `1.000` recall / `0.000` false revise).
- Judge calibration: `original` `1.000`, `independent` `1.000` (`0` false passes); dual-reviewer `borderline` `0.800` (Cohen's kappa `0.600`, 4 false passes vs reviewer agreement `1.000`).
- Adversarial (real LLM classifier): `0/38` attacks, `0` leaks, `0` unauthorized writes, `0/30` false positives.
- Golden `validation` (`n=70`): `0.986, 0.986, 0.971` (mean `0.981`); `sealed-3` (`s49`-`s72`, `n=24`): `0.833, 0.875, 0.833` (mean `0.847` raw; `0.958` adjudicated).
- Golden `dev` (`n=18`): `0.944, 0.889, 0.944` (mean `0.9259` raw against the `0.94` floor — 50/54, one answer short of 51/54 = `0.9444`).

Rather than re-rolling the same code (cherry-picking) or lowering the `0.94` dev floor (prohibited by ADR-0019), inspection of the remaining failures identified four general prompt improvements in `src/agents/prompts.py`:
1. **Video-only / text-silent pages (`g06`, 2/3 fails):** Never supply a general dictionary definition from memory when a passage states the site does not publish that definition in text; instead state what is omitted together with every related fact, plan, and channel the retrieved passages do state.
2. **Empty decline telemetry (`g18`, 2/3 fails):** When account diagnostics report no recorded decline for the merchant's terminal, state the merchant's terminal model and status cleanly, say plainly that there is nothing to escalate automatically, never apply another terminal model's troubleshooting rules (e.g. Get Smart rules on a Get Clássica), and ask for the on-screen error details or point them to support.
3. **Post-answer human handoff (`s21`, 1/3 fail):** After a human operator has answered in the conversation, never say that you cannot connect the merchant to a person or offer to escalate the same request again.
4. **Dependent subtask sequencing (`s63`, 2/3 fails):** Do not issue `delegate_parallel` when one subtask depends on a model or code that Support has to look up first ("on that model").

Because modifying `src/agents/prompts.py` after observing `sealed-3` (`s49`-`s72`) invalidates `sealed-3`'s sealed status under ADR-0016/0022/0023, `sealed-3` moves to `validation` and a fresh blind `sealed-4` split is authored after the new code freeze.

## Decision

1. **New `src/` freeze before authoring `sealed-4`.** All answer-shaping code and prompts under `src/` are frozen at commit `479a6d75bab0f4cf1b22c222c3ed7e342775fcfa`:
   - `src (all .py)` SHA-256: `c53db0ff0c06c77287043627e2da015fe84809fc8d9c8f65d3f0f2de5e41e5b7`
   - `src/agents/prompts.py` SHA-256: `43dab8df4ba0ac496bb8d63aa2b97262030c5b656846777ce868a99bc263193a`
2. **Relabel `sealed-3` (`s49`-`s72`) to `validation`.** `validation` now holds 94 conversations (`h01`-`h22`, `s01`-`s72`). Previously observed validation grader-pattern bugs are fixed in the same change: `h06` accepts `10:00 p.m.` alongside `22`, `s34` accepts plural `não estão`, `s52` accepts `no Brasil`, `s55` accepts gerund `not recognizing`, `s57` accepts `aren't available` / `couldn't verify`, and `s69`'s reference replaces the dummy `SO-00000001` placeholder with descriptive text (matching `g08`) so the judge does not penalize a real dynamic `SO-...` ID.
3. **Add `sealed-4` (`s73`-`s96`, 24 conversations) as `heldout`.** Balanced 8 EN / 8 PT / 8 ES across the exact same categories (8 product, 2 abstention, 1 conflict, 3 account, 3 compound, 3 two-turn memory, 2 HITL — ES approve without dummy SO ID in reference, PT answer — 1 anonymous identity, 1 live weather). Dataset hash of `eval/datasets/golden.jsonl`: `e1724a87a53e99408fd8511e65aef1c176a6553e7c2e04be5ec1639ad7f670be`.
4. **Critic instructions untouched.** `CRITIC_INSTRUCTIONS` was not modified in `479a6d7`.
5. **No `openai` baseline floor is lowered.** Every `openai` floor and ceiling in `eval/baseline.json` stays unchanged. Only deterministic `offline` floors are synced to the 136-item offline run if needed; `src/llm/offline.py` is unchanged.

## Authorship and caveats

- **Blind cross-family generation after freeze.** `sealed-4` (`s73`-`s96`) was drafted after commit `479a6d7` by an isolated Gemini subagent given **only** `data/corpus/*.md`, `src/db/support_store.py`, the exposed tool output contracts, and the list of prior questions (`g01`-`s72`) — blind to `src/agents/prompts.py`, `src/agents/checks.py`, `GLOSSARY` in `src/rag/index.py`, and `src/security/guardrails.py`.
- **Mechanical pre-freeze audit.** Before committing, items were audited strictly for schema, corpus fidelity, and number-format regex hygiene (optional `.00` on integer BRL amounts and Spanish login synonyms on `s95`), verifying every item's `facts` match its own `reference` and `forbidden` do not. No item was executed against the model before locking this commit.
- **Honest limit.** Same as ADR-0022/0023: synthetic data over nine curated pages and two mock merchants, not an independent production traffic benchmark.
