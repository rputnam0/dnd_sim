from __future__ import annotations

import json
from pathlib import Path

from dnd_sim.engine import (
    _extract_spellcasting_profile_from_raw_fields,
    _extract_spells_from_raw_fields,
    _load_spell_definition,
    _resolve_character_traits,
)
from dnd_sim.spells import clear_spell_database_cache


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


def test_load_spell_definition_returns_none_when_spell_directory_missing(
    tmp_path: Path, monkeypatch
) -> None:
    missing_spells_dir = tmp_path / "missing_spells"
    clear_spell_database_cache()
    monkeypatch.setattr("dnd_sim.engine._spell_root_dir", lambda: missing_spells_dir)

    assert _load_spell_definition("Detect Magic [R]") is None


def test_load_spell_definition_returns_none_when_spell_database_is_malformed(
    tmp_path: Path, monkeypatch
) -> None:
    spells_dir = tmp_path / "spells"
    spells_dir.mkdir(parents=True, exist_ok=True)
    (spells_dir / "detect_magic.json").write_text("{not valid json", encoding="utf-8")
    clear_spell_database_cache()
    monkeypatch.setattr("dnd_sim.engine._spell_root_dir", lambda: spells_dir)

    assert _load_spell_definition("Detect Magic [R]") is None


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


def test_extract_spellcasting_profile_parses_spell_attack_bonus() -> None:
    character = {
        "raw_fields": [
            {"field": "spellAtkBonus0", "value": "+7"},
            {"field": "spellSaveDC0", "value": "15"},
        ]
    }
    profile = _extract_spellcasting_profile_from_raw_fields(character)
    assert profile["to_hit"] == 7
    assert profile["save_dc"] == 15


def test_extract_spells_casting_time_hour_not_misclassified_as_reaction(monkeypatch) -> None:
    monkeypatch.setattr("dnd_sim.engine._load_spell_definition", lambda _name: {"level": 1})
    character = {
        "raw_fields": [
            {"field": "spellHeader1", "value": "=== 1st LEVEL ==="},
            {"field": "spellName1", "value": "Long Cast"},
            {"field": "spellPrepared1", "value": "O"},
            {"field": "spellCastingTime1", "value": "1 hour"},
            {"field": "spellName2", "value": "Quick Cast"},
            {"field": "spellPrepared2", "value": "O"},
            {"field": "spellCastingTime2", "value": "R"},
        ],
        "ability_scores": {},
    }
    spells = _extract_spells_from_raw_fields(character)
    by_name = {row["name"]: row for row in spells}
    assert by_name["Long Cast"]["action_cost"] == "action"
    assert by_name["Quick Cast"]["action_cost"] == "reaction"


def test_extract_spells_includes_unprepared_leveled_spells_for_known_casters(monkeypatch) -> None:
    monkeypatch.setattr("dnd_sim.engine._load_spell_definition", lambda _name: {"level": 1})
    character = {
        "class_level": "Bard 5",
        "raw_fields": [
            {"field": "spellHeader1", "value": "=== 1st LEVEL ==="},
            {"field": "spellName1", "value": "Dissonant Whispers"},
            {"field": "spellPrepared1", "value": ""},
            {"field": "spellName2", "value": "Healing Word"},
            {"field": "spellPrepared2", "value": ""},
        ],
        "ability_scores": {},
    }

    spells = _extract_spells_from_raw_fields(character)
    assert {row["name"] for row in spells} == {"Dissonant Whispers", "Healing Word"}


def test_extract_spells_rejects_unprepared_leveled_for_prepared_casters(monkeypatch) -> None:
    monkeypatch.setattr("dnd_sim.engine._load_spell_definition", lambda _name: {"level": 1})
    character = {
        "class_level": "Cleric 5",
        "raw_fields": [
            {"field": "spellHeader0", "value": "=== CANTRIPS ==="},
            {"field": "spellName0", "value": "Guidance"},
            {"field": "spellPrepared0", "value": ""},
            {"field": "spellHeader1", "value": "=== 1st LEVEL ==="},
            {"field": "spellName1", "value": "Bless"},
            {"field": "spellPrepared1", "value": ""},
            {"field": "spellName2", "value": "Shield of Faith"},
            {"field": "spellPrepared2", "value": "O"},
        ],
        "ability_scores": {},
    }

    spells = _extract_spells_from_raw_fields(character)
    names = {row["name"] for row in spells}
    assert "Guidance" in names
    assert "Shield of Faith" in names
    assert "Bless" not in names


def test_extract_spells_dedupe_preserves_non_concentration_false(monkeypatch) -> None:
    monkeypatch.setattr("dnd_sim.engine._load_spell_definition", lambda _name: {"level": 1})
    character = {
        "raw_fields": [
            {"field": "spellHeader1", "value": "=== 1st LEVEL ==="},
            {"field": "spellName1", "value": "Duplicate Spell"},
            {"field": "spellPrepared1", "value": "O"},
            {"field": "spellDuration1", "value": "Instantaneous"},
            {"field": "spellName2", "value": "Duplicate Spell"},
            {"field": "spellPrepared2", "value": "O"},
            {"field": "spellDuration2", "value": "Concentration, up to 1 minute"},
        ],
        "ability_scores": {},
    }
    spells = _extract_spells_from_raw_fields(character)
    assert len(spells) == 1
    assert spells[0]["concentration"] is False


def test_extract_spells_hydrates_duration_rounds_from_canonical_spell_db(monkeypatch) -> None:
    monkeypatch.setattr(
        "dnd_sim.engine._load_spell_definition",
        lambda _name: {
            "name": "Detect Magic",
            "type": "spell",
            "level": 1,
            "casting_time": "1 action",
            "range_ft": 30,
            "concentration": True,
            "duration_rounds": 10,
            "description": "For the duration, you sense the presence of magic.",
            "mechanics": [],
        },
    )
    character = {
        "raw_fields": [
            {"field": "spellHeader1", "value": "=== 1st LEVEL ==="},
            {"field": "spellName1", "value": "Detect Magic"},
            {"field": "spellPrepared1", "value": "O"},
            {"field": "spellComponents1", "value": "V, S"},
        ],
        "ability_scores": {},
    }

    spells = _extract_spells_from_raw_fields(character)
    assert len(spells) == 1
    assert spells[0]["concentration"] is True
    assert spells[0]["duration_rounds"] == 10
    assert spells[0]["duration"] == "Concentration, up to 1 minute"
    assert spells[0]["components"] == "V, S"
