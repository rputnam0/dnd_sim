from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

from dnd_sim import db_content_store, db_schema

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts/migrations/backfill_legacy_blob_content.py"

spec = importlib.util.spec_from_file_location("backfill_legacy_blob_content", SCRIPT_PATH)
if spec is None or spec.loader is None:  # pragma: no cover
    raise RuntimeError(f"Unable to load module from {SCRIPT_PATH}")
backfill_script = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backfill_script
spec.loader.exec_module(backfill_script)


def _memory_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _create_legacy_blob_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE traits (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
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


def _insert_legacy_rows(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO traits (id, name, data_json) VALUES (?, ?, ?)
        """,
        (
            "alertness",
            "Alertness",
            json.dumps({"name": "Alertness", "source": "PHB", "mechanics": []}),
        ),
    )
    conn.execute(
        """
        INSERT INTO enemies (enemy_id, name, team, cr, ac, max_hp, initiative_mod, data_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "goblin_1",
            "Goblin",
            "enemy",
            0.25,
            15,
            7,
            2,
            json.dumps({"name": "Goblin", "source_book": "MM", "ac": 15, "max_hp": 7}),
        ),
    )
    conn.execute(
        """
        INSERT INTO characters (character_id, name, ac, max_hp, initiative_mod, data_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "hero_1",
            "Hero",
            16,
            20,
            2,
            json.dumps({"name": "Hero", "class_levels": {"fighter": 3}, "source": "PHB"}),
        ),
    )


def test_backfill_migrates_legacy_blob_rows_into_canonical_tables() -> None:
    with _memory_connection() as conn:
        _create_legacy_blob_tables(conn)
        _insert_legacy_rows(conn)

        stats = backfill_script.migrate_backfill_legacy_blob_content(conn)

        assert stats["migrated_records"] == 3
        assert stats["skipped_existing"] == 0
        assert stats["invalid_payloads"] == 0

        rows = conn.execute("""
            SELECT content_id, content_type, source_book, schema_version, source_path
            FROM content_records
            ORDER BY content_id
            """).fetchall()
        assert [row[0] for row in rows] == [
            "character:hero_1",
            "enemy:goblin_1",
            "trait:alertness",
        ]
        assert all(row[3] == db_schema.LEGACY_BLOB_SCHEMA_VERSION for row in rows)
        assert rows[0][4] == "legacy_db/characters/hero_1"
        assert rows[1][4] == "legacy_db/enemies/goblin_1"
        assert rows[2][4] == "legacy_db/traits/alertness"

        capability_rows = conn.execute("""
            SELECT content_id, support_state, unsupported_reason, last_verified_commit
            FROM content_capabilities
            ORDER BY content_id
            """).fetchall()
        assert all(row[1] == db_schema.LEGACY_BLOB_SUPPORT_STATE for row in capability_rows)
        assert all(row[2] is None for row in capability_rows)
        assert all(row[3] == db_schema.LEGACY_BLOB_LAST_VERIFIED_COMMIT for row in capability_rows)

        # DBS-06 migration should leave canonical state tables present for mixed persistence reads.
        for table in ("campaign_states", "encounter_states", "world_states", "faction_states"):
            assert (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (table,),
                ).fetchone()
                is not None
            )


def test_backfill_rollback_removes_only_legacy_backfilled_rows() -> None:
    with _memory_connection() as conn:
        _create_legacy_blob_tables(conn)
        _insert_legacy_rows(conn)
        db_schema.create_content_metadata_tables(conn)

        db_content_store.upsert_content_record(
            conn,
            content_id="spell:shield|PHB",
            content_type="spell",
            source_book="PHB",
            schema_version="2014.2",
            source_path="db/rules/2014/spells/shield.json",
            source_hash="sha256:111",
            canonicalization_hash="sha256:222",
            payload_json={"name": "Shield", "level": 1},
            imported_at="2026-03-05T10:00:00+00:00",
        )
        db_content_store.upsert_content_capability(
            conn,
            content_id="spell:shield|PHB",
            content_type="spell",
            support_state="tested",
            unsupported_reason=None,
            last_verified_commit="abc1234",
        )

        stats = backfill_script.migrate_backfill_legacy_blob_content(conn)
        assert stats["migrated_records"] == 3

        deleted = backfill_script.rollback_backfill_legacy_blob_content(conn)
        assert deleted == 3

        remaining = conn.execute(
            "SELECT content_id, source_path FROM content_records ORDER BY content_id"
        ).fetchall()
        assert [tuple(row) for row in remaining] == [
            ("spell:shield|PHB", "db/rules/2014/spells/shield.json")
        ]


def test_mixed_old_new_read_prefers_canonical_and_falls_back_to_legacy_blob() -> None:
    with _memory_connection() as conn:
        _create_legacy_blob_tables(conn)
        _insert_legacy_rows(conn)
        db_schema.create_content_metadata_tables(conn)

        db_content_store.upsert_content_record(
            conn,
            content_id="trait:alertness",
            content_type="trait",
            source_book="PHB",
            schema_version="2014.2",
            source_path="db/rules/2014/traits/alertness.json",
            source_hash="sha256:canonical_trait",
            canonicalization_hash="sha256:canonical_trait",
            payload_json={"name": "Alertness", "mechanics": [{"effect_type": "sense"}]},
            imported_at="2026-03-05T10:00:00+00:00",
        )
        db_content_store.upsert_content_capability(
            conn,
            content_id="trait:alertness",
            content_type="trait",
            support_state="tested",
            unsupported_reason=None,
            last_verified_commit="def5678",
        )

        trait_record = db_content_store.fetch_content_record_compatible(
            conn,
            content_id="trait:alertness",
        )
        enemy_record = db_content_store.fetch_content_record_compatible(
            conn,
            content_id="enemy:goblin_1",
        )

        assert trait_record is not None
        assert trait_record["storage_origin"] == "canonical"
        assert trait_record["support_state"] == "tested"
        assert trait_record["source_path"] == "db/rules/2014/traits/alertness.json"

        assert enemy_record is not None
        assert enemy_record["storage_origin"] == "legacy_blob"
        assert enemy_record["content_id"] == "enemy:goblin_1"
        assert enemy_record["source_path"] == "legacy_db/enemies/goblin_1"
        assert enemy_record["support_state"] == db_schema.LEGACY_BLOB_SUPPORT_STATE
        assert enemy_record["payload_json"]["name"] == "Goblin"

        all_records = db_content_store.fetch_content_records_compatible(conn)
        assert [row["content_id"] for row in all_records] == [
            "character:hero_1",
            "enemy:goblin_1",
            "trait:alertness",
        ]
