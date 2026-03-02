from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Add src to python path to import dnd_sim
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dnd_sim.db import get_connection, init_db
from dnd_sim.io import load_character_db
from dnd_sim.monster_backfill import backfill_monster_payload


def _upsert_enemy(cursor: Any, payload: dict[str, Any]) -> bool:
    identity = payload.get("identity", {}) if isinstance(payload.get("identity"), dict) else {}
    stat_block = (
        payload.get("stat_block", {}) if isinstance(payload.get("stat_block"), dict) else {}
    )

    enemy_id = str(identity.get("enemy_id", "")).strip()
    if not enemy_id:
        return False

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
    return True


def _migrate_characters(base_dir: Path, cursor: Any) -> int:
    char_db_path = base_dir / "river_line" / "db" / "characters"
    if not char_db_path.exists():
        return 0

    characters = load_character_db(char_db_path)
    for char_id, char_data in characters.items():
        name = char_data.get("name", char_id)
        class_level = char_data.get("class_level", "1")
        ac = int(char_data.get("ac", 10))
        max_hp = int(char_data.get("max_hp", 10))
        initiative_mod = char_data.get("initiative_mod")

        cursor.execute(
            """
            INSERT OR REPLACE INTO characters (character_id, name, class_level, ac, max_hp, initiative_mod, data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (char_id, name, class_level, ac, max_hp, initiative_mod, json.dumps(char_data)),
        )
    return len(characters)


def _migrate_enemies_from_files(base_dir: Path, cursor: Any) -> int:
    count = 0

    # Canonical monster directory.
    canonical_dir = base_dir / "db" / "rules" / "2014" / "monsters"
    if canonical_dir.exists():
        for enemy_file in sorted(canonical_dir.glob("*.json")):
            try:
                enemy_data = json.loads(enemy_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            normalized = backfill_monster_payload(enemy_data)
            if _upsert_enemy(cursor, normalized):
                count += 1

    # Encounter-local enemy definitions.
    encounters_dir = base_dir / "river_line" / "encounters"
    if encounters_dir.exists():
        for enemy_file in sorted(encounters_dir.rglob("enemies/*.json")):
            try:
                enemy_data = json.loads(enemy_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            normalized = backfill_monster_payload(enemy_data)
            if _upsert_enemy(cursor, normalized):
                count += 1

    return count


def _backfill_existing_enemy_rows(cursor: Any) -> int:
    rows = cursor.execute("SELECT enemy_id, data_json FROM enemies").fetchall()
    changed = 0
    for row in rows:
        try:
            payload = json.loads(row["data_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue

        normalized = backfill_monster_payload(payload)
        if normalized != payload:
            if _upsert_enemy(cursor, normalized):
                changed += 1
    return changed


def main() -> None:
    base_dir = Path(__file__).resolve().parent.parent

    print("Initializing SQLite database...")
    init_db()

    with get_connection() as conn:
        cursor = conn.cursor()

        character_count = _migrate_characters(base_dir, cursor)
        print(f"Migrated {character_count} characters.")

        enemy_count = _migrate_enemies_from_files(base_dir, cursor)
        print(f"Migrated {enemy_count} enemy payloads from JSON files.")

        backfilled = _backfill_existing_enemy_rows(cursor)
        print(f"Backfilled {backfilled} existing SQLite enemy rows.")

        conn.commit()

    print("Database migration complete.")


if __name__ == "__main__":
    main()
