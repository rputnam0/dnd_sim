from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from dnd_sim.db import get_connection, init_db
from dnd_sim.monster_backfill import backfill_monster_payload


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def backfill_monster_files(monsters_dir: Path, *, write: bool) -> dict[str, int]:
    stats = {"processed": 0, "changed": 0, "skipped": 0}
    if not monsters_dir.exists():
        return stats

    for file_path in sorted(monsters_dir.glob("*.json")):
        payload = _load_json(file_path)
        if payload is None:
            stats["skipped"] += 1
            continue

        stats["processed"] += 1
        normalized = backfill_monster_payload(payload)
        if normalized != payload:
            stats["changed"] += 1
            if write:
                _write_json(file_path, normalized)

    return stats


def _upsert_enemy(cursor: Any, payload: dict[str, Any]) -> None:
    identity = payload.get("identity", {}) if isinstance(payload.get("identity"), dict) else {}
    stat_block = (
        payload.get("stat_block", {}) if isinstance(payload.get("stat_block"), dict) else {}
    )

    enemy_id = str(identity.get("enemy_id", ""))
    if not enemy_id:
        return

    cursor.execute(
        """
        INSERT OR REPLACE INTO enemies (enemy_id, name, team, cr, ac, max_hp, initiative_mod, data_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            enemy_id,
            str(identity.get("name", enemy_id)),
            str(identity.get("team", "enemy")),
            stat_block.get("cr"),
            int(stat_block.get("ac", 10) or 10),
            int(stat_block.get("max_hp", 1) or 1),
            stat_block.get("initiative_mod"),
            json.dumps(payload),
        ),
    )


def backfill_enemy_table(*, write: bool) -> dict[str, int]:
    init_db()
    stats = {"processed": 0, "changed": 0}

    with get_connection() as conn:
        cursor = conn.cursor()
        rows = cursor.execute("SELECT enemy_id, data_json FROM enemies").fetchall()
        for row in rows:
            stats["processed"] += 1
            try:
                payload = json.loads(row["data_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            normalized = backfill_monster_payload(payload)
            if normalized != payload:
                stats["changed"] += 1
                if write:
                    _upsert_enemy(cursor, normalized)

        if write:
            conn.commit()

    return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill legacy monster JSON payloads into canonical enemy schema."
    )
    parser.add_argument(
        "--monsters-dir",
        type=Path,
        default=Path("db/rules/2014/monsters"),
        help="Directory with canonical monster JSON files",
    )
    parser.add_argument(
        "--include-sqlite",
        action="store_true",
        help="Also backfill entries already stored in the SQLite enemies table",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist changes. Without this flag the script runs in dry-run mode.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    file_stats = backfill_monster_files(args.monsters_dir, write=bool(args.write))
    print(
        "Files:",
        f"processed={file_stats['processed']}",
        f"changed={file_stats['changed']}",
        f"skipped={file_stats['skipped']}",
    )

    if args.include_sqlite:
        sqlite_stats = backfill_enemy_table(write=bool(args.write))
        print(
            "SQLite:",
            f"processed={sqlite_stats['processed']}",
            f"changed={sqlite_stats['changed']}",
        )


if __name__ == "__main__":
    main()
