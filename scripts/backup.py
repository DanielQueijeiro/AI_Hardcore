"""Consistent online backup of both SQLite stores (business/ops state and conversation checkpoints).

    python -m scripts.backup                                    # writes backups/<UTC timestamp>/
    python -m scripts.backup --restore backups/20261113T140000Z  # copy a backup back (stop the API first)

Uses SQLite's backup API, so it is safe while the API is serving. Schema changes are forward-only
numbered migrations (src/db/ops_store.py); rolling a release back means restoring the backup taken
before it was deployed.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from src.config import get_settings


def backup(target_root: Path) -> Path:
    settings = get_settings()
    target = target_root / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target.mkdir(parents=True, exist_ok=True)
    for source in (settings.sqlite_db_path, settings.checkpoint_db_path):
        if source.exists():
            with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target / source.name)) as dst:
                src.backup(dst)
    return target


def restore(source_dir: Path) -> None:
    settings = get_settings()
    for destination in (settings.sqlite_db_path, settings.checkpoint_db_path):
        candidate = source_dir / destination.name
        if candidate.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            for suffix in ("-wal", "-shm"):
                destination.with_name(destination.name + suffix).unlink(missing_ok=True)
            shutil.copy2(candidate, destination)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("backups"))
    parser.add_argument("--restore", type=Path)
    args = parser.parse_args(argv)
    if args.restore:
        restore(args.restore)
        print(f"restored from {args.restore}")
    else:
        print(f"backup written to {backup(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
