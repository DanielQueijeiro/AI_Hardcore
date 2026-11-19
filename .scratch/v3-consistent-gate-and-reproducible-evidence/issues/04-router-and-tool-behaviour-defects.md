# 04: Router and tool behaviour defects from the 2026-11-16 run

**What to build:** The agent failures adjudicated in `eval/adjudications.jsonl` that are not retrieval (02), the
output guard (01) or completeness (03).

**Blocked by:** none

**Status:** resolved in code; effect on the model measured only in 13

- [x] FX: `quote` is optional and defaults to BRL; the description says Brazilian merchants get reais.
- [x] After a human decision (g15, s21): the decision is the first item of the Critic's evidence checklist, in every language: a rejection must be stated plainly with the operator's note; after a specialist answered, the draft must not say a person cannot be reached; an executed approval is "ordered or scheduled, not finished". The Router prompt already said this; the Critic now has to rule on it.
- [x] Contradictory sources (h14): the stored evidence showed the cause was retrieval, not wording. In runs 1 and 3 only the Get Clássica page was retrieved, and it did not mention the other page's R$ 20 thousand. Both product pages now carry a "Curation note:" naming the other page and its value (`data/corpus/README.md` explains the convention), so the conflict travels with whichever passage is retrieved. A generic conflicting-value detector was not built: matching "the same fact" across pages is not reliable by regex.
- [x] Tests: checklist items for reject / answer / approve; FX default.
