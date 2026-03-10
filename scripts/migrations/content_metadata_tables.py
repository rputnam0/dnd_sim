from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from dnd_sim.db_schema import (
    CONTENT_CAPABILITIES_TABLE,
    CONTENT_RECORDS_TABLE,
    create_content_metadata_tables,
    get_db_path,
)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _content_records_has_lineage_columns(conn: sqlite3.Connection) -> bool:
    if not _table_exists(conn, CONTENT_RECORDS_TABLE):
        return False
    columns = _table_columns(conn, CONTENT_RECORDS_TABLE)
    return {"source_path", "canonicalization_hash", "imported_at"}.issubset(columns)


def migrate_add_content_metadata_tables(conn: sqlite3.Connection) -> bool:
    """Add canonical content metadata tables if they are not present."""
    has_records = _table_exists(conn, CONTENT_RECORDS_TABLE)
    has_capabilities = _table_exists(conn, CONTENT_CAPABILITIES_TABLE)
    lineage_ready = _content_records_has_lineage_columns(conn)
    if has_records and has_capabilities and lineage_ready:
        return False

    conn.execute("BEGIN IMMEDIATE")
    try:
        create_content_metadata_tables(conn)
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
    return True


def rollback_drop_content_metadata_tables(conn: sqlite3.Connection) -> bool:
    """Drop canonical content metadata tables."""
    has_records = _table_exists(conn, CONTENT_RECORDS_TABLE)
    has_capabilities = _table_exists(conn, CONTENT_CAPABILITIES_TABLE)
    if not has_records and not has_capabilities:
        return False

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(f"DROP TABLE IF EXISTS {CONTENT_CAPABILITIES_TABLE}")
        conn.execute(f"DROP TABLE IF EXISTS {CONTENT_RECORDS_TABLE}")
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
    return True


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Add canonical content metadata tables (content_records/content_capabilities) "
            "or rollback by dropping them."
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
        help="Drop content metadata tables instead of creating them.",
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
        if args.rollback:
            changed = rollback_drop_content_metadata_tables(conn)
            if changed:
                print("[ok] dropped content metadata tables")
            else:
                print("[skip] rollback not needed; content metadata tables are absent")
            return 0

        changed = migrate_add_content_metadata_tables(conn)
        if changed:
            print("[ok] added content metadata tables")
        else:
            print("[skip] migration not needed; content metadata tables already exist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
