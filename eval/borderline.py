"""Merge two humans' labels for the borderline judge-calibration answers.

    python -m eval.borderline eval/labels/borderline_ana.csv eval/labels/borderline_bruno.csv
    python -m eval.borderline A.csv B.csv --final eval/labels/borderline_final.csv   # after discussing disagreements

Each labeller fills `eval/labels/BORDERLINE_SHEET.md` independently into `borderline_<name>.csv` (id,label,comment).
The first form prints their agreement (Cohen's kappa) and the disagreements. The second writes the agreed label of
every item into `eval/datasets/judge_borderline.jsonl` together with each labeller's own label, so the report can
show the judge's agreement next to the humans' agreement with each other. The judge's floor on this set must not be
above the human-human agreement: two careful people disagreeing on an item means the item is genuinely borderline.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from eval.judge import cohen_kappa

DATASET = Path(__file__).parent / "datasets" / "judge_borderline.jsonl"


def read_labels(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as f:
        labels = {row["id"].strip(): row["label"].strip().lower() for row in csv.DictReader(f) if row.get("label", "").strip()}
    bad = {k: v for k, v in labels.items() if v not in ("pass", "fail")}
    if bad:
        raise SystemExit(f"{path}: labels must be pass or fail: {bad}")
    return labels


def agreement(a: dict[str, str], b: dict[str, str]) -> dict[str, object]:
    ids = sorted(set(a) & set(b))
    if not ids:
        raise SystemExit("the two files have no labelled item in common")
    return {
        "n": len(ids),
        "agreement": round(sum(a[i] == b[i] for i in ids) / len(ids), 4),
        "kappa": round(cohen_kappa([a[i] for i in ids], [b[i] for i in ids]), 4),
        "disagreements": [i for i in ids if a[i] != b[i]],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("--final", type=Path, help="agreed labels after discussing disagreements (id,label,comment)")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    a, b = read_labels(args.first), read_labels(args.second)
    stats = agreement(a, b)
    print(json.dumps(stats, indent=2))
    if not args.final:
        return 0
    final = read_labels(args.final)
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]
    missing = [r["id"] for r in rows if r["id"] not in final]
    if missing:
        raise SystemExit(f"--final has no label for {missing}")
    names = (args.first.stem.removeprefix("borderline_"), args.second.stem.removeprefix("borderline_"))
    for r in rows:
        r["label"] = final[r["id"]]
        r["human_labels"] = {names[0]: a.get(r["id"]), names[1]: b.get(r["id"])}
    DATASET.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"wrote agreed labels for {len(rows)} items to {DATASET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
