# 0023. Sealed-3 after post-run checklist and prompt fixes

Status: accepted (amends [0016](0016-sealed-held-out-and-independent-judge-calibration.md) and [0022](0022-sealed-2-and-critic-heldout-after-v3-freeze.md)). Written and merged before the first model run of `sealed-3`.

## Context

On 2026-11-19, CI workflow run `44457669721` (`feat/v3-gate-reproducibility` at commit `633c1165a85b`, `src/` frozen at `17ec60d`) executed the first `--repeat 3` model evaluation with hosted dense retrieval, `sealed-2` (`s25`-`s48`), the held-out Critic split (`k33`-`k48`), and the dual-reviewer `borderline` calibration set.

Two separate things happened during that run:

1. **Provider credit exhaustion mid-Run 3 (`05:21:46Z`, one hour into the run).** Runs 1 and 2 (`n=88` each) and the first 40 items of Run 3 (`g01`-`s08`) completed with `0` degraded turns. From `s09` onward in Run 3, the OpenAI key stopped responding and tripped `llm_breaker_open` (40 degraded turns in Run 3; `adversarial` and `critic` fell back to the offline policy; `calibration` could not run). That run therefore could not serve as the published report.
2. **Real defects diagnosed in the clean Runs 1 and 2.** Even setting aside the Run 3 outage, clean Runs 1 and 2 validated several v3 wins — hosted dense retrieval on held-out queries reached `Recall@4 1.000` / `MRR 0.944` even with `glossary_off` (vs BM25 `0.708 / 0.632`), `validation` scored `0.957 / 0.978` (judge `1.000`), `sealed-2` scored `0.875 / 0.875` (judge `1.000 / 0.917`), all v2 bugs (`s04`, `s21`, `g01`, `h14`) passed, and latency dropped (`p50 11.9 -> 10.3 s`, `dev p95 35.6 -> 24.6 s`) — yet `dev` still missed its `0.94` floor (`0.833 / 0.833 / 0.889`) and `s07` tripped `forbidden_claim_rate` (`0.0114 > 0.0`). Inspection of the stored traces exposed four concrete causes:
   - **`evidence_checklist` cross-section bleed (`src/agents/checks.py`):** `internal://support-runbook` holds both `OFFLINE_GPRS_TIMEOUT` (a 4-step connectivity procedure) and `ERR_51_ISSUER_DECLINE / POS_KEY_SYNC_WARN` (declines) under one `source_url`. Because `evidence_checklist` activated any procedure whose `source_url` was cited in the draft, declined-transaction answers (`g08`, `g15`, `s46`) that cited `internal://support-runbook` dragged the 4 offline steps into the Critic checklist and forced `revise` rounds that appended unrelated connectivity troubleshooting.
   - **Telemetry scoping (`src/agents/prompts.py`):** `SUPERVISOR_INSTRUCTIONS` instructed the Router to mention unrelated issues present in the same telemetry record, causing `g05` and `s43` judge rejections and `g12` Run 1 over-escalation (`awaiting_human`).
   - **FX default & settlement completeness (`src/agents/prompts.py`, `src/tools/registry.py`):** `g07` Run 1 called `get_fx_rate(base='EUR', quote='USD')` instead of `BRL`; `g03` Run 2 and `h21` omitted settlement amounts from `get_settlements` (passing the judge 5/5/5/5 but missing amount facts); `g17` Run 2 omitted the receivables-advance status explaining D+30; `s01` Run 3 omitted the rental qualifying clause.
   - **Grader regex bugs on `dev` and `validation`:** `g07` (`dev`) required `eur` and missed `€1 = R$6.3818`; `s07` (`validation`) had a naive forbidden regex `maintenance fee (is|of) r\$` that matched the negation *"does not confirm that the monthly maintenance fee is R$0"*.

Because fixing the first three causes modifies `src/` after `sealed-2` was observed against the model, ADR-0016 and ADR-0022 require relabelling `sealed-2` as `validation` and authoring a fresh sealed split after the new code freeze.

## Decision

1. **New `src/` freeze before authoring `sealed-3`.** All answer-shaping code and prompts under `src/` are frozen at commit `26be3c325f4c02a06e387e351f0744ccac6a5b4e`:
   - `src (all .py)` SHA-256: `798963c4ef9201cc8873747a5c652af1b7411b35bdc658bf220d20cf8f690a3d`
   - `src/agents/prompts.py` SHA-256: `a58c24ab990056466eff421359872f096df055c48e8c474f2539c8581265cb2d`
2. **Relabel `sealed-2` (`s25`-`s48`) to `validation`.** `validation` now holds 70 conversations (`h01`-`h22`, `s01`-`s48`). In the same change, previously observed grader-regex bugs in `dev`/`validation` are fixed: `g07` accepts `€`, `s07`'s forbidden regex ignores same-sentence negations, `s34` accepts `não encontrei`, `s38` drops the unrequested `620` amount fact (question asks only for timing), and `s44` accepts `(11) 97694-6815`.
3. **Add `sealed-3` (`s49`-`s72`, 24 conversations) as `heldout`.** Matches the category balance of `s01`-`s24` and `s25`-`s48`: 8 product (EN/PT/ES), 2 abstention, 1 contradictory source, 3 account, 3 compound, 3 two-turn memory, 2 HITL (PT approve creating `SO-...` and EN answer with no service order), 1 anonymous identity, and 1 live FX (ES GBP/BRL). Dataset hash of `eval/datasets/golden.jsonl`: `752ddbfd3559ea822c2065081bfc03f868b41c50a6b327ce1c6c78517714bf3d`.
4. **Held-out Critic split (`k33`-`k48`) stays sealed.** `CRITIC_INSTRUCTIONS` was not modified in `26be3c3`, and `run_critic` never reached the OpenAI model in CI run `44457669721` (it degraded to offline). `k33`-`k48` remains completely unseen by the model.
5. **No `openai` baseline floor is lowered.** Every `openai` floor and ceiling in `eval/baseline.json` stays unchanged (`dev >= 0.94`, `validation >= 0.90`, `heldout >= 0.80`, `critic.by_set.heldout.recall >= 0.85`, `calibration.by_set.borderline.agreement >= 0.75`, `forbidden_claim_rate == 0.0`, `degraded_turns == 0`). Only deterministic `offline` floors are synced to the 112-item offline run if needed; `src/llm/offline.py` is unchanged.

## Authorship and caveats

- **Blind cross-family generation after freeze.** `sealed-3` (`s49`-`s72`) was drafted after commit `26be3c3` by an isolated Gemini subagent given **only** `data/corpus/*.md`, `src/db/support_store.py`, the exposed tool output contracts, and the list of prior questions (`g01`-`s48`) — blind to `src/agents/prompts.py`, `src/agents/checks.py`, `GLOSSARY` in `src/rag/index.py`, and `src/security/guardrails.py`.
- **Mechanical pre-freeze audit.** Before committing, items were audited strictly for schema and contract validity (aligning `s64`'s reference masked account to `_mask`'s `***04-2` format, adding `£` alongside `GBP` in `s72`, keeping `s69`'s operator note aligned with "scheduled", and verifying every item's `facts` match its own `reference` and `forbidden` do not). No item was run against the model before locking this commit.
- **Honest limit.** Same as ADR-0022: synthetic data over nine curated pages and two mock merchants, not an independent production traffic benchmark.
