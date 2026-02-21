from __future__ import annotations

import json
from pathlib import Path

from dnd_sim.engine import _load_spell_definition, _resolve_character_traits


def test_load_spell_definition_accepts_sheet_ritual_suffix(tmp_path: Path, monkeypatch) -> None:
    spells_dir = tmp_path / "spells"
    spells_dir.mkdir(parents=True, exist_ok=True)
    (spells_dir / "detect_magic.json").write_text(
        json.dumps({"name": "Detect Magic", "level": 1}),
        encoding="utf-8",
    )

    monkeypatch.setattr("dnd_sim.engine._spell_root_dir", lambda: spells_dir)

    spell = _load_spell_definition("Detect Magic [R]")
    assert spell is not None
    assert spell["name"] == "Detect Magic"


def test_resolve_character_traits_maps_sheet_aliases_to_canonical_db() -> None:
    character = {
        "traits": [
            "Gnomish Lineage Spells",
            "Sage Ability Score Improvements",
        ],
        "raw_fields": [],
    }
    traits_db = {
        "gnomish lineage": {"name": "Gnomish Lineage", "mechanics": []},
        "ability score improvement": {
            "name": "Ability Score Improvement",
            "mechanics": [],
        },
    }

    resolved = _resolve_character_traits(character, traits_db)

    assert "gnomish lineage" in resolved
    assert resolved["gnomish lineage"]["name"] == "Gnomish Lineage"
    assert "ability score improvement" in resolved
    assert resolved["ability score improvement"]["name"] == "Ability Score Improvement"


def test_resolve_character_traits_ignores_non_feature_sheet_sections() -> None:
    character = {
        "traits": ["Hit Points", "Skills", "Proficiencies"],
        "raw_fields": [],
    }

    resolved = _resolve_character_traits(character, traits_db={})
    assert resolved == {}
