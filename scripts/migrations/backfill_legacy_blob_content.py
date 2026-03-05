from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from dnd_sim.db import (
    backfill_legacy_blob_content,
    get_db_path,
    rollback_legacy_blob_backfill,
)


def migrate_backfill_legacy_blob_content(conn: sqlite3.Connection) -> dict[str, int]:
    """Run DBS-06 backfill in one transaction."""
    began_transaction = not conn.in_transaction
    if began_transaction:
        conn.execute("BEGIN IMMEDIATE")
    try:
        stats = backfill_legacy_blob_content(conn)
    except Exception:
        if began_transaction:
            conn.rollback()
        raise
    else:
        if began_transaction:
            conn.commit()
    return stats


def rollback_backfill_legacy_blob_content(conn: sqlite3.Connection) -> int:
    """Rollback DBS-06 backfill rows in one transaction."""
    began_transaction = not conn.in_transaction
    if began_transaction:
        conn.execute("BEGIN IMMEDIATE")
    try:
        deleted = rollback_legacy_blob_backfill(conn)
    except Exception:
        if began_transaction:
            conn.rollback()
        raise
    else:
        if began_transaction:
            conn.commit()
    return deleted


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill legacy JSON/blob records into canonical metadata/state tables "
            "or rollback previously backfilled rows."
        )
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=get_db_path(),
        help="Path to the SQLite database file.",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Delete canonical rows created from legacy blob source paths.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"[skip] database not found: {db_path}")
        return 0

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        if args.rollback:
            deleted = rollback_backfill_legacy_blob_content(conn)
            if deleted == 0:
                print("[skip] rollback not needed; no legacy backfilled rows found")
            else:
                print(f"[ok] rolled back legacy backfilled rows: {deleted}")
            return 0

        stats = migrate_backfill_legacy_blob_content(conn)
        print(f"[ok] DBS-06 backfill complete: {json.dumps(stats, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
