from __future__ import annotations

from dnd_sim.engine import _build_actor_from_character, long_rest, short_rest
from tests.helpers import with_class_levels


def _wizard_character(
    *,
    class_level: str = "Wizard 5",
    traits: list[str] | None = None,
    resources: dict | None = None,
    current_resources: dict | None = None,
    spells: list[dict] | None = None,
) -> dict:
    payload: dict = {
        "character_id": "wizard_test",
        "name": "Wizard Test",
        "class_level": class_level,
        "max_hp": 24,
        "ac": 13,
        "speed_ft": 30,
        "ability_scores": {"str": 8, "dex": 14, "con": 12, "int": 18, "wis": 12, "cha": 10},
        "save_mods": {"str": -1, "dex": 2, "con": 1, "int": 7, "wis": 1, "cha": 0},
        "skill_mods": {},
        "attacks": [],
        "resources": resources or {},
        "traits": traits or [],
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }
    if current_resources is not None:
        payload["current_resources"] = current_resources
    if spells is not None:
        payload["spells"] = spells
    return with_class_levels(payload)


def test_build_actor_infers_arcane_recovery_resource() -> None:
    character = _wizard_character(
        class_level="Wizard 5",
        traits=["Arcane Recovery"],
        resources={"spell_slots": {"1": 4, "2": 3, "3": 2}},
    )

    actor = _build_actor_from_character(character, traits_db={})

    assert actor.max_resources["arcane_recovery"] == 1
    assert actor.resources["arcane_recovery"] == 1


def test_short_rest_arcane_recovery_recovers_slots_within_budget_once() -> None:
    character = _wizard_character(
        class_level="Wizard 5",
        traits=["Arcane Recovery"],
        resources={"spell_slots": {"1": 4, "2": 3, "3": 2}},
        current_resources={
            "spell_slot_1": 1,
            "spell_slot_2": 1,
            "spell_slot_3": 0,
            "arcane_recovery": 1,
        },
    )
    actor = _build_actor_from_character(character, traits_db={})

    short_rest(actor)

    assert actor.resources["spell_slot_3"] == 1
    assert actor.resources["spell_slot_2"] == 1
    assert actor.resources["spell_slot_1"] == 1
    assert actor.resources["arcane_recovery"] == 0

    actor.resources["spell_slot_3"] = 0
    short_rest(actor)
    assert actor.resources["spell_slot_3"] == 0


def test_long_rest_refreshes_arcane_recovery() -> None:
    character = _wizard_character(
        class_level="Wizard 5",
        traits=["Arcane Recovery"],
        resources={"spell_slots": {"1": 4, "2": 3, "3": 2}},
        current_resources={"spell_slot_3": 0, "arcane_recovery": 1},
    )
    actor = _build_actor_from_character(character, traits_db={})

    short_rest(actor)
    assert actor.resources["arcane_recovery"] == 0

    long_rest(actor)
    assert actor.resources["arcane_recovery"] == 1


def test_school_hooks_tag_matching_school_spells() -> None:
    character = _wizard_character(
        class_level="Wizard 7",
        traits=["School of Evocation"],
        resources={"spell_slots": {"1": 4, "2": 3, "3": 3, "4": 1}},
        spells=[
            {
                "name": "Fireball",
                "level": 3,
                "school": "evocation",
                "action_type": "save",
                "save_dc": 15,
                "save_ability": "dex",
                "damage": "8d6",
                "damage_type": "fire",
                "half_on_save": True,
            },
            {
                "name": "Shield",
                "level": 1,
                "school": "abjuration",
                "action_type": "utility",
                "action_cost": "reaction",
            },
        ],
    )

    actor = _build_actor_from_character(character, traits_db={})
    by_name = {action.name: action for action in actor.actions}

    assert "school:evocation" in by_name["Fireball"].tags
    assert "wizard_school_hook:evocation" in by_name["Fireball"].tags
    assert "school:abjuration" in by_name["Shield"].tags
    assert "wizard_school_hook:evocation" not in by_name["Shield"].tags
