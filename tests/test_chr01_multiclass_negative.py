from __future__ import annotations

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
