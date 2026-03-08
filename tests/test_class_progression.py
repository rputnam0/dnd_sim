from __future__ import annotations

import json
from pathlib import Path

from dnd_sim.class_progression import (
    build_character_progression,
    load_default_class_catalog,
    load_class_catalog,
)


def _write_payload(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_class_catalog_progression_grants_class_and_subclass_features(tmp_path: Path) -> None:
    classes_dir = tmp_path / "classes"
    subclasses_dir = tmp_path / "subclasses"
    classes_dir.mkdir()
    subclasses_dir.mkdir()

    _write_payload(
        classes_dir / "fighter.json",
        {
            "content_id": "class:fighter|PHB",
            "class_id": "fighter",
            "name": "Fighter",
            "source_book": "PHB",
            "features": [
                {"name": "Fighting Style", "level": 1},
                {"name": "Second Wind", "level": 1},
                {"name": "Action Surge", "level": 2},
                {"name": "Martial Archetype", "level": 3, "subclass_unlock": True},
            ],
            "spellcasting": {"progression": "none"},
        },
    )
    _write_payload(
        subclasses_dir / "fighter__battle_master.json",
        {
            "content_id": "subclass:battle_master_fighter|PHB",
            "subclass_id": "battle_master",
            "class_id": "fighter",
            "name": "Battle Master",
            "source_book": "PHB",
            "features": [{"name": "Combat Superiority", "level": 3}],
        },
    )

    catalog = load_class_catalog(classes_dir=classes_dir, subclasses_dir=subclasses_dir)
    progression = build_character_progression(
        class_levels={"fighter": 3},
        subclass_choices={"fighter": "battle_master"},
        catalog=catalog,
    )

    assert progression.total_level == 3
    assert progression.feature_names == (
        "action surge",
        "combat superiority",
        "fighting style",
        "martial archetype",
        "second wind",
    )
    assert progression.subclass_unlock_levels["fighter"] == 3
    assert progression.errors == ()


def test_default_class_catalog_is_populated_with_classes_and_subclasses() -> None:
    catalog = load_default_class_catalog()

    assert "fighter" in catalog.classes
    assert "warlock" in catalog.classes
    assert ("fighter", "battle_master") in catalog.subclasses
    assert ("wizard", "abjuration") in catalog.subclasses


def test_multiclass_progression_tracks_spell_slots_and_pact_slots(tmp_path: Path) -> None:
    classes_dir = tmp_path / "classes"
    subclasses_dir = tmp_path / "subclasses"
    classes_dir.mkdir()
    subclasses_dir.mkdir()

    _write_payload(
        classes_dir / "paladin.json",
        {
            "content_id": "class:paladin|PHB",
            "class_id": "paladin",
            "name": "Paladin",
            "source_book": "PHB",
            "features": [{"name": "Divine Sense", "level": 1}],
            "spellcasting": {"progression": "half"},
        },
    )
    _write_payload(
        classes_dir / "sorcerer.json",
        {
            "content_id": "class:sorcerer|PHB",
            "class_id": "sorcerer",
            "name": "Sorcerer",
            "source_book": "PHB",
            "features": [{"name": "Font of Magic", "level": 2}],
            "spellcasting": {"progression": "full"},
        },
    )
    _write_payload(
        classes_dir / "warlock.json",
        {
            "content_id": "class:warlock|PHB",
            "class_id": "warlock",
            "name": "Warlock",
            "source_book": "PHB",
            "features": [{"name": "Pact Magic", "level": 1}],
            "spellcasting": {
                "progression": "pact",
                "pact_slots_by_level": {"5": {"slot_level": 3, "slots": 2}},
            },
        },
    )

    catalog = load_class_catalog(classes_dir=classes_dir, subclasses_dir=subclasses_dir)
    progression = build_character_progression(
        class_levels={"paladin": 2, "sorcerer": 3, "warlock": 5},
        subclass_choices={},
        catalog=catalog,
    )

    assert progression.spell_slots == {1: 4, 2: 3}
    assert progression.pact_slots == {3: 2}
    assert progression.errors == ()


def test_progression_rejects_unknown_class_and_invalid_subclass_reference(tmp_path: Path) -> None:
    classes_dir = tmp_path / "classes"
    subclasses_dir = tmp_path / "subclasses"
    classes_dir.mkdir()
    subclasses_dir.mkdir()

    _write_payload(
        classes_dir / "wizard.json",
        {
            "content_id": "class:wizard|PHB",
            "class_id": "wizard",
            "name": "Wizard",
            "source_book": "PHB",
            "features": [{"name": "Spellcasting", "level": 1}],
            "spellcasting": {"progression": "full"},
        },
    )

    catalog = load_class_catalog(classes_dir=classes_dir, subclasses_dir=subclasses_dir)
    progression = build_character_progression(
        class_levels={"wizard": 2, "invalid_class": 1},
        subclass_choices={"wizard": "evoker"},
        catalog=catalog,
    )

    assert "unknown class reference 'invalid_class'" in progression.errors
    assert "invalid subclass reference 'evoker' for class 'wizard'" in progression.errors


def test_progression_rejects_subclass_choice_before_unlock_threshold(tmp_path: Path) -> None:
    classes_dir = tmp_path / "classes"
    subclasses_dir = tmp_path / "subclasses"
    classes_dir.mkdir()
    subclasses_dir.mkdir()

    _write_payload(
        classes_dir / "fighter.json",
        {
            "content_id": "class:fighter|PHB",
            "class_id": "fighter",
            "name": "Fighter",
            "source_book": "PHB",
            "features": [
                {"name": "Second Wind", "level": 1},
                {"name": "Martial Archetype", "level": 3, "subclass_unlock": True},
            ],
            "spellcasting": {"progression": "none"},
        },
    )
    _write_payload(
        subclasses_dir / "fighter__battle_master.json",
        {
            "content_id": "subclass:battle_master_fighter|PHB",
            "subclass_id": "battle_master",
            "class_id": "fighter",
            "name": "Battle Master",
            "source_book": "PHB",
            "features": [{"name": "Combat Superiority", "level": 3}],
        },
    )

    catalog = load_class_catalog(classes_dir=classes_dir, subclasses_dir=subclasses_dir)
    progression = build_character_progression(
        class_levels={"fighter": 2},
        subclass_choices={"fighter": "battle_master"},
        catalog=catalog,
    )

    assert (
        "subclass reference 'battle_master' for class 'fighter' requires class level 3"
        in progression.errors
    )
    assert "combat superiority" not in progression.feature_names
