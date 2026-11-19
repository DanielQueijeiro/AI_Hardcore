# Knowledge corpus

One Markdown file per source page. The front matter records where each file came from.

- `origin: getnet_site` — facts taken from the public Getnet Brazil site on the `retrieved_at` date, restated in
  English with the original Portuguese product terms kept. Where a page does not state something, the file says
  so explicitly instead of filling the gap, so the agent can answer "the site does not specify" truthfully.
  Where two Getnet pages disagree, both files carry a sentence starting "Curation note:" that names the other page
  and its value, so whichever passage is retrieved, the disagreement travels with it (added after h14, where only
  one of the two pages was retrieved and the answer gave one threshold as settled).
- `origin: internal_runbook_mock` — a synthetic support runbook that belongs to the mock back office (same status
  as the fixture merchants in SQLite). It is **not** official Getnet content and answers must not present it as such.

Capture the live pages with `python -m scripts.ingest_getnet` (writes one file per URL to `data/corpus/raw/`,
with a content hash). `python -m scripts.ingest_getnet --check` reports which pages changed since the last
capture, which is the signal to review the matching curated file. Raw captures are indexed only when
`INDEX_RAW_PAGES=true`.
