from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import dnd_sim.db as db_module
from scripts.migrations.content_metadata_tables import (
    migrate_add_content_metadata_tables,
    rollback_drop_content_metadata_tables,
)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [str(row[1]) for row in rows]


def _create_legacy_core_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE traits (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            data_json TEXT NOT NULL
        )
        """)
    conn.execute("""
        CREATE TABLE characters (
            character_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            ac INTEGER NOT NULL,
            max_hp INTEGER NOT NULL,
            initiative_mod INTEGER,
            data_json TEXT NOT NULL
        )
        """)
    conn.execute("""
        CREATE TABLE enemies (
            enemy_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            team TEXT NOT NULL,
            cr REAL,
            ac INTEGER NOT NULL,
            max_hp INTEGER NOT NULL,
            initiative_mod INTEGER,
            data_json TEXT NOT NULL
        )
        """)
    conn.commit()


def test_content_metadata_migration_adds_canonical_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "content_metadata.db"
    with sqlite3.connect(db_path) as conn:
        _create_legacy_core_tables(conn)

        changed = migrate_add_content_metadata_tables(conn)
        assert changed is True

        assert _columns(conn, "content_records") == [
            "content_id",
            "content_type",
            "source_book",
            "schema_version",
            "source_path",
            "source_hash",
            "canonicalization_hash",
            "payload_json",
            "imported_at",
        ]
        assert _columns(conn, "content_capabilities") == [
            "content_id",
            "content_type",
            "support_state",
            "unsupported_reason",
            "last_verified_commit",
        ]

        assert migrate_add_content_metadata_tables(conn) is False


def test_content_metadata_tables_round_trip_insert_and_query(tmp_path: Path) -> None:
    db_path = tmp_path / "round_trip.db"
    with sqlite3.connect(db_path) as conn:
        _create_legacy_core_tables(conn)
        assert migrate_add_content_metadata_tables(conn) is True

        db_module.upsert_content_record(
            conn,
            content_id="spell:magic_missile|PHB",
            content_type="spell",
            source_book="PHB",
            schema_version="2014.1",
            source_path="db/rules/2014/spells/magic_missile.json",
            source_hash="sha256:abc123",
            canonicalization_hash="sha256:def456",
            payload_json={"name": "Magic Missile", "level": 1},
            imported_at="2026-03-05T10:00:00+00:00",
        )
        db_module.upsert_content_capability(
            conn,
            content_id="spell:magic_missile|PHB",
            content_type="spell",
            support_state="tested",
            unsupported_reason=None,
            last_verified_commit="f00ba47",
        )

        row = conn.execute(
            """
            SELECT
                r.content_id,
                r.content_type,
                r.source_book,
                r.schema_version,
                r.source_path,
                r.source_hash,
                r.canonicalization_hash,
                r.payload_json,
                r.imported_at,
                c.support_state,
                c.unsupported_reason,
                c.last_verified_commit
            FROM content_records r
            JOIN content_capabilities c ON c.content_id = r.content_id
            WHERE r.content_id = ?
            """,
            ("spell:magic_missile|PHB",),
        ).fetchone()

        assert row is not None
        assert row[0:7] == (
            "spell:magic_missile|PHB",
            "spell",
            "PHB",
            "2014.1",
            "db/rules/2014/spells/magic_missile.json",
            "sha256:abc123",
            "sha256:def456",
        )
        assert json.loads(row[7]) == {"level": 1, "name": "Magic Missile"}
        assert row[8] == "2026-03-05T10:00:00+00:00"
        assert row[9:12] == ("tested", None, "f00ba47")


def test_content_metadata_rollback_drops_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "rollback.db"
    with sqlite3.connect(db_path) as conn:
        _create_legacy_core_tables(conn)
        assert migrate_add_content_metadata_tables(conn) is True

        assert rollback_drop_content_metadata_tables(conn) is True
        assert not _table_exists(conn, "content_capabilities")
        assert not _table_exists(conn, "content_records")

        assert rollback_drop_content_metadata_tables(conn) is False


def test_init_db_creates_content_metadata_tables(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "canonical_init.db"
    monkeypatch.setattr(db_module, "get_db_path", lambda: db_path)

    db_module.init_db()

    with sqlite3.connect(db_path) as conn:
        assert _table_exists(conn, "content_records")
        assert _table_exists(conn, "content_capabilities")
