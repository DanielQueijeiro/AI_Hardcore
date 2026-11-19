# 0022. Sealed-2 and a held-out Critic split, authored blind after the v3 code freeze

Status: accepted (amends [0016](0016-sealed-held-out-and-independent-judge-calibration.md)). Written and merged before the first model run of either split.

## Context

ADR-0016 sets one hard rule for sealed evaluation splits: the moment a failure on a sealed split drives a change to code or prompts, that split stops being sealed and becomes `validation`.

The v3 fixes (commits `a42a9b8` and `17ec60d`) were directly motivated by two failures from the 2026-11-16 `heldout` split (`s01`-`s24`):

- `s04` drove multi-query cross-lingual retrieval and the switch to hosted dense embeddings (ADR-0020).
- `s21` drove the output-guard phone-number fix and the human-decision checklist rule.

In addition, the Critic calibration set (`k01`-`k32`) was used during development to tune the Critic prompt and fix three drafts (`k25`-`k27`), so it is a `dev` set, not an unseen estimate of Critic reliability.

## Decision

1. **Code and prompt freeze first.** All answer-shaping code and prompts under `src/` are frozen at commit `17ec60d0cce69438809295c8bca7d2177848a2df` (`src (all .py)` SHA-256 `fad78b6f591d4870483e6c8d805925029baac469a382d54bca446e5a1d320fef`; `src/agents/prompts.py` SHA-256 `d61159a77c4ccd214ec3c698e90f3ff30632c26ff8810fe8368f59a94e38da85`). Neither split below is run against the model before this freeze, and no change to `src/` follows the model run without relabelling `sealed-2` as `validation`.
2. **Relabel `s01`-`s24` to `validation`.** `validation` now holds 46 conversations (`h01`-`h22` plus `s01`-`s24`). In the same change, the three previously adjudicated fact-pattern mistakes on `s22` ("entre na sua conta"), `s23` ("US$") and `s24` ("não está publicado") are corrected; they had been left untouched while `s01`-`s24` was sealed.
3. **Add `sealed-2` (`s25`-`s48`, 24 conversations) as `heldout`.** Covers the same categories as `s01`-`s24`: 8 product (EN/PT/ES), 2 abstention, 1 contradictory source, 3 account, 3 compound, 3 multi-turn memory, 2 HITL (answer and reject in PT/ES), 1 anonymous identity (ES), and 1 live weather (PT). Dataset hash recorded in `eval/datasets/golden.jsonl`: `fb381516215817128154eca742e7361b5d4ac352487ac740070cb135cbde2e4a`.
4. **Add a held-out Critic split (`k33`-`k48`, 16 drafts, `set: "heldout"`).** Eight defective drafts (one per defect class: `omitted_step`, `omitted_price`, `unsupported_number`, `wrong_language`, `action_claimed_done`, `missing_caveat`, `unanswered_part`, `rejection_not_stated`) and eight clean drafts across EN/PT/ES, sharing no question with `golden.jsonl` or `k01`-`k32`. `run_critic` reports `by_set` (`dev` vs `heldout`) separately. Dataset hash for `eval/datasets/critic_calibration.jsonl`: `193a6724b182c9104a5f54473ad4916244ac11d240406ae6d1a80a97ce7d0a37`.
5. **Lock model floors before measuring.**
   - `golden.heldout.semantic_pass_rate >= 0.80` (unchanged from ADR-0016, gated under ADR-0019's repeated-run rule).
   - `critic.by_set.heldout.recall >= 0.85` and `critic.by_set.heldout.false_revise_rate <= 0.25` (fixed before the first model run of `k33`-`k48`).
   - Offline CI floors for `validation` and `heldout` are updated to the measured performance of the deterministic offline policy on the new splits; no rule of `src/llm/offline.py` is changed.

## Authorship and caveats

- **Separate model family, blind to prompts and heuristics.** The system, prompts and `s01`-`s24` were built with Claude and evaluated with OpenAI (`gpt-6-luna` answering, `gpt-5.4-mini` judging). Both `sealed-2` (`s25`-`s48`) and `k33`-`k48` were drafted on 2026-11-18 by an isolated Gemini subagent given **only** `data/corpus/*.md`, the merchant fixtures in `src/db/support_store.py`, and the list of prior questions to avoid overlap — blind to `src/agents/prompts.py`, `src/agents/checks.py`, and `GLOSSARY` in `src/rag/index.py`.
- **Mechanical schema audit before freeze.** Before committing, the drafted items were audited strictly for tool-contract validity (replacing two raw SQLite columns — `serial_number` and `apn_configured` — that `_get_pos_diagnostics` does not expose, aligning Critic mock tool payloads to `registry.py`'s exact masked schema, and verifying each item's regex matches its own reference). No item was executed against the model during drafting or auditing.
- **Honest limit.** A blind different-family model removes prompt-leakage and single-family correlation, but it is still synthetic data drawn from the same nine curated pages and two mock merchants, not an independent production traffic benchmark.
