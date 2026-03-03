from __future__ import annotations

import json

import pytest

from dnd_sim.io import load_character_db
from tests.helpers import build_character, write_json


def test_load_character_db_rejects_invalid_multiclass_class_level_encoding(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("dnd_sim.db.execute_query", lambda *_args, **_kwargs: [])

    db_dir = tmp_path / "characters"
    db_dir.mkdir(parents=True, exist_ok=True)

    write_json(
        db_dir / "index.json",
        {
            "characters": [
                {
                    "character_id": "broken_multiclass",
                    "name": "Broken Multiclass",
                    "class_level": "Wizard 3 /",
                    "source_pdf": "fixture.pdf",
                }
            ]
        },
    )

    character = build_character(
        character_id="broken_multiclass",
        name="Broken Multiclass",
        max_hp=20,
        ac=13,
        to_hit=5,
        damage="1d8+2",
    )
    character["class_level"] = "Wizard 3 /"
    write_json(db_dir / "broken_multiclass.json", character)

    with pytest.raises(ValueError, match="invalid class_level"):
        load_character_db(db_dir)


def test_load_character_db_skips_sqlite_rows_with_invalid_multiclass_class_level(
    tmp_path, monkeypatch
) -> None:
    valid_character = build_character(
        character_id="valid_from_sqlite",
        name="Valid From SQLite",
        max_hp=20,
        ac=13,
        to_hit=5,
        damage="1d8+2",
    )
    invalid_character = build_character(
        character_id="broken_from_sqlite",
        name="Broken From SQLite",
        max_hp=20,
        ac=13,
        to_hit=5,
        damage="1d8+2",
    )
    invalid_character["class_level"] = "Wizard 3 /"

    sqlite_rows = [
        {
            "character_id": "valid_from_sqlite",
            "data_json": json.dumps(valid_character),
        },
        {
            "character_id": "broken_from_sqlite",
            "data_json": json.dumps(invalid_character),
        },
    ]
    monkeypatch.setattr("dnd_sim.db.execute_query", lambda *_args, **_kwargs: sqlite_rows)

    db = load_character_db(tmp_path / "characters")

    assert "valid_from_sqlite" in db
    assert "broken_from_sqlite" not in db
