from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import dnd_sim.db as db_module
import dnd_sim.content_index as content_index
import dnd_sim.cli as cli_module


def _seed_content(conn: sqlite3.Connection) -> None:
    db_module.create_content_metadata_tables(conn)

    db_module.upsert_content_record(
        conn,
        content_id="spell:shield|PHB",
        content_type="spell",
        source_book="PHB",
        schema_version="2014.2",
        source_path="db/rules/2014/spells/shield.json",
        source_hash="sha256:shield_source",
        canonicalization_hash="sha256:shield_canonical",
        payload_json={"name": "Shield", "level": 1},
        imported_at="2026-03-05T10:00:00+00:00",
    )
    db_module.upsert_content_capability(
        conn,
        content_id="spell:shield|PHB",
        content_type="spell",
        support_state="tested",
        unsupported_reason=None,
        last_verified_commit="abc1234",
    )

    db_module.upsert_content_record(
        conn,
        content_id="spell:misty_step|PHB",
        content_type="spell",
        source_book="PHB",
        schema_version="2014.1",
        source_path="db/rules/2014/spells/misty_step.json",
        source_hash="sha256:misty_source",
        canonicalization_hash="sha256:misty_canonical",
        payload_json={"name": "Misty Step", "level": 2},
        imported_at="2026-03-05T10:00:01+00:00",
    )
    db_module.upsert_content_capability(
        conn,
        content_id="spell:misty_step|PHB",
        content_type="spell",
        support_state="tested",
        unsupported_reason=None,
        last_verified_commit="abc1234",
    )

    db_module.upsert_content_record(
        conn,
        content_id="trait:alertness",
        content_type="trait",
        source_book="PHB",
        schema_version="legacy_blob.v1",
        source_path="legacy_db/traits/alertness",
        source_hash="sha256:trait_source",
        canonicalization_hash="sha256:trait_canonical",
        payload_json={"name": "Alertness", "mechanics": []},
        imported_at="1970-01-01T00:00:00+00:00",
    )
    db_module.upsert_content_capability(
        conn,
        content_id="trait:alertness",
        content_type="trait",
        support_state="blocked",
        unsupported_reason="missing_runtime_hook_family",
        last_verified_commit="legacy",
    )

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


def _build_seeded_db_path(tmp_path: Path) -> Path:
    db_path = tmp_path / "content_queries.db"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        _seed_content(conn)
        conn.commit()
    return db_path


def test_query_api_filters_support_schema_and_lineage_fields(tmp_path: Path) -> None:
    db_path = _build_seeded_db_path(tmp_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")

        spell_rows = content_index.query_content_records(
            conn,
            content_type="spell",
            support_state="tested",
            source_book="PHB",
            schema_version="2014.2",
        )
        assert [row["content_id"] for row in spell_rows] == ["spell:shield|PHB"]
        assert spell_rows[0]["source_path"] == "db/rules/2014/spells/shield.json"
        assert spell_rows[0]["source_hash"] == "sha256:shield_source"
        assert spell_rows[0]["canonicalization_hash"] == "sha256:shield_canonical"
        assert spell_rows[0]["imported_at"] == "2026-03-05T10:00:00+00:00"

        blocked_rows = content_index.query_content_records(
            conn,
            support_state="blocked",
            unsupported_reason="missing_runtime_hook_family",
        )
        assert [row["content_id"] for row in blocked_rows] == ["trait:alertness"]

        legacy_enemy_rows = content_index.query_content_records(conn, content_type="enemy")
        assert [row["content_id"] for row in legacy_enemy_rows] == ["enemy:goblin_1"]
        assert legacy_enemy_rows[0]["storage_origin"] == "legacy_blob"
        assert legacy_enemy_rows[0]["support_state"] == db_module.LEGACY_BLOB_SUPPORT_STATE


def test_cli_coverage_snapshot(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = _build_seeded_db_path(tmp_path)

    exit_code = cli_module.main(
        [
            "content-coverage",
            "--db-path",
            str(db_path),
            "--source-book",
            "PHB",
        ]
    )
    assert exit_code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "records_total": 3,
        "schema_version_counts": [
            {"count": 1, "schema_version": "2014.1"},
            {"count": 1, "schema_version": "2014.2"},
            {"count": 1, "schema_version": "legacy_blob.v1"},
        ],
        "support_state_counts": [
            {"count": 1, "support_state": "blocked"},
            {"count": 2, "support_state": "tested"},
        ],
    }


def test_invalid_query_filters_raise_and_cli_returns_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = _build_seeded_db_path(tmp_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")

        with pytest.raises(ValueError, match="unsupported_reason filter requires"):
            content_index.query_content_records(
                conn,
                support_state="tested",
                unsupported_reason="missing_runtime_hook_family",
            )

    exit_code = cli_module.main(
        [
            "query-content",
            "--db-path",
            str(db_path),
            "--support-state",
            "tested",
            "--unsupported-reason",
            "missing_runtime_hook_family",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "unsupported_reason filter requires" in captured.err
