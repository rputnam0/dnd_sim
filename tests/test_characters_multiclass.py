from __future__ import annotations

from dnd_sim.characters import (
    canonical_class_level_text,
    parse_class_levels,
    spell_slots_for_multiclass,
    validate_multiclass_prerequisites,
)


def test_parse_class_levels_and_canonicalize_multiclass_text() -> None:
    parsed = parse_class_levels("Wizard 3 / cleric 1")

    assert parsed == {"wizard": 3, "cleric": 1}
    assert canonical_class_level_text(parsed) == "Cleric 1 / Wizard 3"


def test_validate_multiclass_prerequisites_for_new_class_transition() -> None:
    errors = validate_multiclass_prerequisites(
        class_levels={"fighter": 5},
        ability_scores={"str": 10, "dex": 10, "int": 12},
        adding_class="wizard",
    )

    assert errors == [
        "fighter requires strength 13 or dexterity 13 for multiclassing.",
        "wizard requires intelligence 13 for multiclassing.",
    ]


def test_spell_slots_for_multiclass_uses_combined_caster_level_table() -> None:
    slots = spell_slots_for_multiclass({"paladin": 2, "sorcerer": 3})

    assert slots == {1: 4, 2: 3}
