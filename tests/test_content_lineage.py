from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import dnd_sim.db as db_module
from dnd_sim.io import persist_content_lineage_record, replay_content_lineage, stable_content_hash


def _columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [str(row[1]) for row in rows]


def _create_dbs01_content_records_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE content_records (
            content_id TEXT PRIMARY KEY,
            content_type TEXT NOT NULL,
            source_book TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """)
    conn.execute("""
        CREATE TABLE content_capabilities (
            content_id TEXT PRIMARY KEY,
            content_type TEXT NOT NULL,
            support_state TEXT NOT NULL,
            unsupported_reason TEXT,
            last_verified_commit TEXT NOT NULL,
            FOREIGN KEY (content_id) REFERENCES content_records(content_id) ON DELETE CASCADE
        )
        """)
    conn.commit()


def test_content_hash_stability_is_independent_of_key_order() -> None:
    left = {"name": "Magic Missile", "level": 1, "tags": ["evocation", "force"]}
    right = {"tags": ["evocation", "force"], "level": 1, "name": "Magic Missile"}

    assert stable_content_hash(left) == stable_content_hash(right)


def test_content_records_lineage_migration_adds_required_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "lineage_migration.db"
    with sqlite3.connect(db_path) as conn:
        _create_dbs01_content_records_schema(conn)
        conn.execute(
            """
            INSERT INTO content_records (
                content_id, content_type, source_book, schema_version, source_hash, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "spell:magic_missile|PHB",
                "spell",
                "PHB",
                "2014.1",
                "sha256:seeded",
                json.dumps({"name": "Magic Missile", "level": 1}),
            ),
        )
        conn.commit()

        db_module.create_content_metadata_tables(conn)

        assert set(_columns(conn, "content_records")) == {
            "content_id",
            "content_type",
            "source_book",
            "schema_version",
            "source_path",
            "source_hash",
            "canonicalization_hash",
            "payload_json",
            "imported_at",
        }

        row = conn.execute(
            """
            SELECT source_path, canonicalization_hash, imported_at
            FROM content_records
            WHERE content_id = ?
            """,
            ("spell:magic_missile|PHB",),
        ).fetchone()
        assert row is not None
        assert row[0] == "legacy:spell:magic_missile|PHB"
        assert row[1] == stable_content_hash({"name": "Magic Missile", "level": 1})
        assert row[2] == db_module.LEGACY_IMPORTED_AT


def test_duplicate_hashes_are_allowed_for_distinct_content_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "duplicate_hashes.db"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        db_module.create_content_metadata_tables(conn)

        source_payload = {"name": "Shared", "value": 1}
        canonical_payload = {"name": "Shared", "value": 1}

        persist_content_lineage_record(
            conn,
            content_id="trait:shared_a|PHB",
            content_type="trait",
            source_book="PHB",
            schema_version="2014.2",
            source_path="db/rules/2014/traits/shared_a.json",
            source_payload=source_payload,
            canonical_payload=canonical_payload,
            imported_at="2026-03-05T10:00:00+00:00",
        )
        persist_content_lineage_record(
            conn,
            content_id="trait:shared_b|PHB",
            content_type="trait",
            source_book="PHB",
            schema_version="2014.2",
            source_path="db/rules/2014/traits/shared_b.json",
            source_payload=source_payload,
            canonical_payload=canonical_payload,
            imported_at="2026-03-05T10:00:01+00:00",
        )

        rows = conn.execute("""
            SELECT content_id, source_hash, canonicalization_hash
            FROM content_records
            ORDER BY content_id
            """).fetchall()
        assert [row[0] for row in rows] == ["trait:shared_a|PHB", "trait:shared_b|PHB"]
        assert rows[0][1] == rows[1][1]
        assert rows[0][2] == rows[1][2]


def test_replay_content_lineage_returns_deterministic_order(tmp_path: Path) -> None:
    db_path = tmp_path / "replay_order.db"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        db_module.create_content_metadata_tables(conn)

        persist_content_lineage_record(
            conn,
            content_id="spell:zeta|PHB",
            content_type="spell",
            source_book="PHB",
            schema_version="2014.2",
            source_path="db/rules/2014/spells/zeta.json",
            source_payload={"name": "Zeta", "level": 3},
            canonical_payload={"name": "Zeta", "level": 3},
            imported_at="2026-03-05T10:00:00+00:00",
        )
        persist_content_lineage_record(
            conn,
            content_id="spell:alpha|PHB",
            content_type="spell",
            source_book="PHB",
            schema_version="2014.2",
            source_path="db/rules/2014/spells/alpha.json",
            source_payload={"name": "Alpha", "level": 1},
            canonical_payload={"name": "Alpha", "level": 1},
            imported_at="2026-03-05T10:00:00+00:00",
        )

        lineage = replay_content_lineage(conn, content_type="spell")

        assert [row["content_id"] for row in lineage] == ["spell:alpha|PHB", "spell:zeta|PHB"]
        assert lineage[0]["canonicalization_hash"] == stable_content_hash(
            {"name": "Alpha", "level": 1}
        )
