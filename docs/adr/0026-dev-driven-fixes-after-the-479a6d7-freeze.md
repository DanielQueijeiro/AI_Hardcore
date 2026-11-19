# 0026. Dev-driven fixes after the 479a6d7 freeze; sealed-4 stays held out

Status: accepted

## Context

`sealed-4` (`s73`–`s96`) was authored blind after `src/` was frozen at `479a6d7` (ADR-0024). The cassette run on that freeze, CI [44569607884](https://github.com/DanielQueijeiro/AI_Hardcore/actions/runs/44569607884), passed every gated metric except `golden.dev.semantic_pass_rate` (`0.889, 0.833, 0.944`, mean `0.889 < 0.94`). The six `dev` misses were `g01`, `g08`, `g13`×2, `g15` and `g17`. ADR-0016's rule says that a failure observed on a sealed split which drives a change to `src/` turns that split into `validation`. It says nothing against fixing `dev`, which exists to drive prompt work.

## Decision

Fix the system from `dev` evidence only, keep the `0.94` floor and every other floor, and keep `sealed-4` sealed.

- `e7cf787` (from the six `dev` misses of 44569607884): the Critic's `evidence_checklist` requires the whole decline code after an approved re-key (`g08`), each settlement modality's amount (`g17`) and the shared card rates when two machines are compared (`g01`); a rejection is stated in the first sentence (`g15`); account data that changes nothing is left out (`g13`).
- `e031a8e` (from local real-model checks of the `dev` split, 6 runs at a time, after `e7cf787` still showed new one-off `dev` misses): FX quotes in BRL unless the merchant named the target currency (`g07`); today's date line, which every agent prompt carries, counts as evidence for the Critic's number check and the numeric-groundedness metric (`g03`); no remarks about what a source does not cover when the evidence answers, no hypotheticals, remaining steps on "what else can I try", related published facts not set aside (`g05`, `g06`, `g12`, `g13`, `g14`); after a rejection, the decision and the operator's note, then stop (`g15`); no handoff offer when the terminal is online with no recorded decline (`g18`); no connectivity troubleshooting after an approved re-key for a decline (`g08`).
- No `sealed-4` answer or trace was opened while making these changes. The only `sealed-4` observations of 44569607884 were fact-regex misses (`s79`, `s85`, `s93`) already attributed to `grader_facts`, and none of them drove a change. The local checks ran `dev` only; a `validation` pre-check was stopped before it finished, and `heldout` was never run locally.
- The answering model, the judge, the datasets, the fact patterns and `eval/baseline.json` are unchanged.

## Consequences

- The final cassette run, CI [44622842628](https://github.com/DanielQueijeiro/AI_Hardcore/actions/runs/44622842628) at `e031a8e`, passed every gated metric: `dev` `1.000` on all three runs, `validation` `0.972` raw mean, `sealed-4` `0.875` raw mean with judge pass `1.000` on all three runs, `0` degraded turns.
- `dev` now measures fixes made on `dev`; it says the fixes work, not that they generalize. `validation` and `sealed-4` carry that claim, and `sealed-4` is still the only split no change was ever tuned on.
- The new checklist items and stricter rejection rule cost Critic precision on fixed drafts written before them: false revise `0.042` → `0.167` (4 of 24 clean `dev` drafts: `k17`, `k18`, `k20`, `k27`), still under the `0.20` ceiling; held-out drafts stay at recall `1.000`, false revise `0.000`. `k27`'s "clean" draft explains the error code after a rejection, which the new rule now forbids; its label was not edited after seeing the result.
