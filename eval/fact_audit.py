"""Audit the deterministic fact patterns of the golden set against wordings known to be correct.

    python -m eval.fact_audit                 # print the audit
    python -m eval.fact_audit --out PATH.md   # also write it

Two sources of known-correct wording, neither of which is a model run of its own:
1. Each item's reference answer: a pattern group the reference itself does not satisfy cannot be satisfied by an
   answer that says the same thing.
2. Every answer in a committed model report that a human adjudicated as correct with the miss attributed to the fact
   patterns (`cause: grader_facts`, `outcome: pass`, keyed by the answer's SHA-256).

The audit only reports; it never edits a pattern. Patterns of a sealed split stay as written (ADR-0027): what this
tool measures is how much of a raw score is the grader rather than the agent, and it is the check a new split's
patterns must pass before that split is sealed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from eval import metrics as m
from eval.judge import load_jsonl

ROOT = Path(__file__).resolve().parent
DATASETS = ROOT / "datasets"
REPORTS = ROOT / "reports" / "openai"
# Identifiers the system mints at run time (service orders) cannot appear in a reference written beforehand.
RUNTIME_ID_PATTERNS = ("so-[a-z0-9]{8}",)


def _answers_by_sha(reports: list[Path]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        for rows in [report.get("golden", {}).get("items", []), *report.get("golden_repeat_items", [])]:
            for row in rows:
                out[row.get("answer_sha256", "")] = {**row, "_report": path.name}
    return out


def audit(items: list[dict[str, Any]], adjudications: list[dict[str, Any]], reports: list[Path]) -> dict[str, Any]:
    """Pattern groups that miss a known-correct wording, per item."""
    by_id = {i["id"]: i for i in items}
    reference_misses = {}
    for item in items:
        _, missing = m.fact_coverage(item["reference"], item["facts"])
        missing = [i for i in missing if not any(alt in RUNTIME_ID_PATTERNS for alt in item["facts"][i])]
        if missing:
            reference_misses[item["id"]] = [item["facts"][i][0] for i in missing]

    answers = _answers_by_sha(reports)
    correct_misses: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in adjudications:
        if entry.get("cause") != "grader_facts" or entry.get("outcome") != "pass":
            continue
        row, item = answers.get(entry.get("answer_sha256", "")), by_id.get(entry.get("id", ""))
        if row is None or item is None:
            continue
        _, missing = m.fact_coverage(row["answer"], item["facts"])
        for i in missing:
            correct_misses[item["id"]].append({"pattern": item["facts"][i][0], "report": row["_report"], "run": entry.get("run")})

    splits: dict[str, dict[str, int]] = defaultdict(lambda: {"items": 0, "patterns": 0})
    for item in items:
        splits[item["split"]]["items"] += 1
        splits[item["split"]]["patterns"] += len(item["facts"])
    fragile = {(i, x["pattern"]) for i, xs in correct_misses.items() for x in xs} | {
        (i, p) for i, ps in reference_misses.items() for p in ps
    }
    return {
        "splits": dict(splits),
        "reference_misses": reference_misses,
        "correct_answer_misses": dict(correct_misses),
        "fragile_patterns": len(fragile),
        "fragile_by_split": {
            s: len({(i, p) for i, p in fragile if by_id[i]["split"] == s}) for s in sorted({by_id[i]["split"] for i, _ in fragile})
        },
    }


def render(result: dict[str, Any]) -> str:
    lines = ["# Fact-pattern audit", ""]
    total = sum(s["patterns"] for s in result["splits"].values())
    lines.append(
        f"{result['fragile_patterns']} of {total} fact pattern groups miss a wording known to be correct "
        f"({', '.join(f'{s}: {n}' for s, n in result['fragile_by_split'].items()) or 'none'})."
    )
    lines += ["", "## Patterns the item's own reference does not satisfy", ""]
    lines.append("(Run-time identifiers such as service-order numbers are excluded: no reference can contain them.)")
    lines.append("")
    if result["reference_misses"]:
        lines += [f"- `{i}`: {', '.join(f'`{p[:70]}`' for p in ps)}" for i, ps in sorted(result["reference_misses"].items())]
    else:
        lines.append("None.")
    lines += ["", "## Patterns that missed an answer adjudicated correct (`grader_facts`)", ""]
    if result["correct_answer_misses"]:
        for i, misses in sorted(result["correct_answer_misses"].items()):
            seen = sorted({x["pattern"] for x in misses})
            where = ", ".join(sorted({f"{x['report']} run {x['run']}" for x in misses}))
            lines.append(f"- `{i}` ({len(misses)} answers; {where}): {', '.join(f'`{p[:70]}`' for p in seen)}")
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    result = audit(
        load_jsonl(DATASETS / "golden.jsonl"), load_jsonl(ROOT / "adjudications.jsonl"), sorted(REPORTS.glob("report*.json"))
    )
    text = render(result)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
