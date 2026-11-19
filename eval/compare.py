"""Check that a replayed evaluation reproduces a published report.

    python -m eval.run --replay eval/reports/openai/cassette.json.gz --out /tmp/replay
    python -m eval.compare eval/reports/openai/report.json /tmp/replay.json

Every metric must be identical. What a replay cannot reproduce is left out: wall-clock latency, pricing-dependent
cost, timestamps, provenance (the replay runs other code paths' commit), and the cassette block itself (except
unused recorded calls, which must be zero).
Answers are compared by their SHA-256, item by item, so a passing comparison means the replay produced the same
answers, not just the same averages.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from eval.run import flatten

IGNORED = re.compile(r"(latency|_ms\b|ms_p\d+|cost_usd|generated_at|provenance|cassette|gate_rule|^gate$)")


def _answers(report: dict[str, Any]) -> list[tuple[str, str]]:
    runs = [report.get("golden", {}).get("items", []), *report.get("golden_repeat_items", [])]
    return [(f"run{n}:{row['id']}", row.get("answer_sha256", "")) for n, rows in enumerate(runs, start=1) for row in rows]


def differences(published: dict[str, Any], replayed: dict[str, Any]) -> list[str]:
    a = {k: v for k, v in flatten(published).items() if not IGNORED.search(k)}
    b = {k: v for k, v in flatten(replayed).items() if not IGNORED.search(k)}
    out = [f"{k}: published {a.get(k)} vs replayed {b.get(k)}" for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
    answers_a, answers_b = dict(_answers(published)), dict(_answers(replayed))
    out += [f"{k}: answer differs" for k in sorted(set(answers_a) | set(answers_b)) if answers_a.get(k) != answers_b.get(k)]
    if published.get("gate") != replayed.get("gate"):
        out.append(f"gate: published {published.get('gate')} vs replayed {replayed.get('gate')}")
    unused = (replayed.get("cassette") or {}).get("unused_recorded_calls", 0)
    if unused:
        out.append(f"cassette: {unused} recorded call(s) were not used during replay")
    return out


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print(__doc__)
        return 2
    published, replayed = (json.loads(Path(p).read_text(encoding="utf-8")) for p in args)
    diffs = differences(published, replayed)
    for line in diffs:
        print(line)
    n = len(_answers(published))
    print(f"{'REPRODUCED' if not diffs else 'DIFFERENT'}: {n} answers and every metric compared ({len(diffs)} differences)")
    return 1 if diffs else 0


if __name__ == "__main__":
    raise SystemExit(main())
