from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import dnd_sim.db as db_module
from scripts.migrations.drop_characters_class_level_column import (
    migrate_drop_class_level_column,
    rollback_restore_class_level_column,
)


def _columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [str(row[1]) for row in rows]


def _create_legacy_characters_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
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
    )
    conn.execute(
        """
        INSERT INTO characters (character_id, name, class_level, ac, max_hp, initiative_mod, data_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "hero_1",
            "Hero One",
            "Fighter 8",
            18,
            70,
            2,
            '{"character_id":"hero_1","class_level":"Fighter 8"}',
        ),
    )
    conn.commit()


def _create_canonical_characters_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE characters (
            character_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            ac INTEGER NOT NULL,
            max_hp INTEGER NOT NULL,
            initiative_mod INTEGER,
            data_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO characters (character_id, name, ac, max_hp, initiative_mod, data_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("hero_1", "Hero One", 18, 70, 2, '{"character_id":"hero_1","class_levels":{"fighter":8}}'),
    )
    conn.commit()


def test_drop_characters_class_level_migrates_existing_db(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        _create_legacy_characters_table(conn)

        changed = migrate_drop_class_level_column(conn)
        assert changed is True

        assert "class_level" not in _columns(conn, "characters")
        assert "class_level" in _columns(conn, "characters_class_level_backup")
        row = conn.execute(
            "SELECT character_id, name, ac, max_hp, initiative_mod, data_json FROM characters"
        ).fetchone()
        assert row[0:5] == ("hero_1", "Hero One", 18, 70, 2)
        payload = json.loads(row[5])
        assert payload["class_levels"] == {"fighter": 8}
        assert "class_level" not in payload

        assert migrate_drop_class_level_column(conn) is False


def test_drop_characters_class_level_noops_for_new_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "canonical.db"
    with sqlite3.connect(db_path) as conn:
        _create_canonical_characters_table(conn)
        assert migrate_drop_class_level_column(conn) is False
        assert "class_level" not in _columns(conn, "characters")


def test_drop_characters_class_level_rollback_restores_column(tmp_path: Path) -> None:
    db_path = tmp_path / "rollback.db"
    with sqlite3.connect(db_path) as conn:
        _create_legacy_characters_table(conn)
        assert migrate_drop_class_level_column(conn) is True
        assert rollback_restore_class_level_column(conn) is True

        assert "class_level" in _columns(conn, "characters")
        row = conn.execute(
            "SELECT character_id, class_level, data_json FROM characters"
        ).fetchone()
        assert row[0:2] == ("hero_1", "Fighter 8")
        payload = json.loads(row[2])
        assert payload["class_level"] == "Fighter 8"
        assert payload.get("class_levels") == {"fighter": 8}

        assert rollback_restore_class_level_column(conn) is False


def test_rollback_preserves_rows_created_after_migration(tmp_path: Path) -> None:
    db_path = tmp_path / "rollback_preserve.db"
    with sqlite3.connect(db_path) as conn:
        _create_legacy_characters_table(conn)
        assert migrate_drop_class_level_column(conn) is True

        conn.execute(
            """
            INSERT INTO characters (character_id, name, ac, max_hp, initiative_mod, data_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "new_hero",
                "New Hero",
                16,
                40,
                1,
                '{"character_id":"new_hero","class_levels":{"wizard":2}}',
            ),
        )
        conn.commit()

        assert rollback_restore_class_level_column(conn) is True
        row = conn.execute(
            "SELECT character_id, class_level, data_json FROM characters WHERE character_id = ?",
            ("new_hero",),
        ).fetchone()
        assert row is not None
        assert row[0] == "new_hero"
        assert row[1] == "Wizard 2"
        payload = json.loads(row[2])
        assert payload["class_level"] == "Wizard 2"
        assert payload["class_levels"] == {"wizard": 2}


def test_init_db_creates_canonical_characters_schema(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "canonical_init.db"
    monkeypatch.setattr(db_module, "get_db_path", lambda: db_path)

    db_module.init_db()

    with sqlite3.connect(db_path) as conn:
        assert "class_level" not in _columns(conn, "characters")
