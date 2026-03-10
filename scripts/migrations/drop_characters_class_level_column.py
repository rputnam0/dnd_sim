from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from dnd_sim.characters import (
    canonical_class_level_text,
    normalize_class_levels,
    parse_class_levels_strict,
)
from dnd_sim.db_schema import get_db_path

_CHARACTERS_SCHEMA_WITH_CLASS_LEVEL = """
CREATE TABLE characters (
    character_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    class_level TEXT NOT NULL,
    ac INTEGER NOT NULL,
    max_hp INTEGER NOT NULL,
    initiative_mod INTEGER,
    data_json TEXT NOT NULL
)
"""

_CHARACTERS_SCHEMA_CANONICAL = """
CREATE TABLE characters (
    character_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    ac INTEGER NOT NULL,
    max_hp INTEGER NOT NULL,
    initiative_mod INTEGER,
    data_json TEXT NOT NULL
)
"""

_MIGRATION_SCRATCH_TABLE = "characters__migration_old"
_ROLLBACK_SCRATCH_TABLE = "characters__migration_new"
_DEFAULT_BACKUP_TABLE = "characters_class_level_backup"


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [str(row[1]) for row in rows]


def _canonicalize_character_data_json(raw_data_json: str) -> str:
    payload = json.loads(raw_data_json)
    if not isinstance(payload, dict):
        raise ValueError("characters.data_json must be a JSON object")

    class_levels_raw = payload.get("class_levels")
    class_levels = normalize_class_levels(class_levels_raw)
    if not class_levels:
        class_level_text = str(payload.get("class_level", "") or "")
        class_levels = normalize_class_levels(parse_class_levels_strict(class_level_text))
    if not class_levels:
        raise ValueError("characters.data_json is missing canonical class_levels mapping")

    payload["class_levels"] = class_levels
    payload.pop("class_level", None)
    return json.dumps(payload, sort_keys=True)


def migrate_drop_class_level_column(
    conn: sqlite3.Connection,
    *,
    backup_table: str = _DEFAULT_BACKUP_TABLE,
) -> bool:
    if not _table_exists(conn, "characters"):
        return False

    columns = _table_columns(conn, "characters")
    if "class_level" not in columns:
        return False

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(f"DROP TABLE IF EXISTS {backup_table}")
        conn.execute(f"CREATE TABLE {backup_table} AS SELECT * FROM characters")

        canonical_rows: list[tuple[str, str, int, int, int | None, str]] = []
        for row in conn.execute(
            """
            SELECT character_id, name, ac, max_hp, initiative_mod, data_json
            FROM characters
            """
        ).fetchall():
            canonical_rows.append(
                (
                    str(row[0]),
                    str(row[1]),
                    int(row[2]),
                    int(row[3]),
                    int(row[4]) if row[4] is not None else None,
                    _canonicalize_character_data_json(str(row[5])),
                )
            )

        conn.execute(f"ALTER TABLE characters RENAME TO {_MIGRATION_SCRATCH_TABLE}")
        conn.execute(_CHARACTERS_SCHEMA_CANONICAL)
        conn.executemany(
            """
            INSERT INTO characters (character_id, name, ac, max_hp, initiative_mod, data_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            canonical_rows,
        )
        conn.execute(f"DROP TABLE {_MIGRATION_SCRATCH_TABLE}")
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
    return True


def rollback_restore_class_level_column(
    conn: sqlite3.Connection,
    *,
    backup_table: str = _DEFAULT_BACKUP_TABLE,
) -> bool:
    if not _table_exists(conn, "characters"):
        return False

    columns = _table_columns(conn, "characters")
    if "class_level" in columns:
        return False
    if not _table_exists(conn, backup_table):
        raise ValueError(
            "Cannot rollback character class_level migration: backup table is missing"
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        merged_rows: dict[str, tuple[str, str, str, int, int, int | None, str]] = {}
        for row in conn.execute(
            f"""
            SELECT character_id, name, class_level, ac, max_hp, initiative_mod, data_json
            FROM {backup_table}
            """
        ).fetchall():
            character_id = str(row[0])
            merged_rows[character_id] = (
                character_id,
                str(row[1]),
                str(row[2]),
                int(row[3]),
                int(row[4]),
                int(row[5]) if row[5] is not None else None,
                str(row[6]),
            )

        for row in conn.execute(
            """
            SELECT character_id, name, ac, max_hp, initiative_mod, data_json
            FROM characters
            """
        ).fetchall():
            payload = json.loads(str(row[5]))
            if not isinstance(payload, dict):
                raise ValueError("characters.data_json must be a JSON object during rollback")
            class_levels = normalize_class_levels(payload.get("class_levels"))
            if class_levels:
                class_level_text = canonical_class_level_text(class_levels)
            else:
                class_level_text = str(payload.get("class_level", "") or "").strip()
            if not class_level_text:
                raise ValueError(
                    f"characters.data_json for {row[0]} is missing class progression during rollback"
                )
            payload["class_level"] = class_level_text
            canonical_data_json = json.dumps(payload, sort_keys=True)
            character_id = str(row[0])
            merged_rows[character_id] = (
                character_id,
                str(row[1]),
                class_level_text,
                int(row[2]),
                int(row[3]),
                int(row[4]) if row[4] is not None else None,
                canonical_data_json,
            )

        conn.execute(f"ALTER TABLE characters RENAME TO {_ROLLBACK_SCRATCH_TABLE}")
        conn.execute(_CHARACTERS_SCHEMA_WITH_CLASS_LEVEL)
        conn.executemany(
            """
            INSERT INTO characters (character_id, name, class_level, ac, max_hp, initiative_mod, data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [merged_rows[key] for key in sorted(merged_rows.keys())],
        )
        conn.execute(f"DROP TABLE {_ROLLBACK_SCRATCH_TABLE}")
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
    return True


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Drop the legacy characters.class_level column while keeping a backup table "
            "for rollback."
        )
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=get_db_path(),
        help="Path to the SQLite database file.",
    )
    parser.add_argument(
        "--backup-table",
        default=_DEFAULT_BACKUP_TABLE,
        help="Backup table name to use during migration.",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Restore characters.class_level from the backup table.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    db_path: Path = Path(args.db_path)
    if not db_path.exists():
        print(f"[skip] database not found: {db_path}")
        return 0

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if args.rollback:
            changed = rollback_restore_class_level_column(conn, backup_table=args.backup_table)
            if changed:
                print(
                    f"[ok] rollback complete; restored characters.class_level from {args.backup_table}"
                )
            else:
                print("[skip] rollback not needed; schema already includes class_level")
            return 0

        changed = migrate_drop_class_level_column(conn, backup_table=args.backup_table)
        if changed:
            print(
                f"[ok] migrated characters schema; dropped class_level with backup {args.backup_table}"
            )
        else:
            print("[skip] migration not needed; characters.class_level already absent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
