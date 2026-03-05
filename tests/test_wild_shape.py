from __future__ import annotations

import random

from dnd_sim.engine_runtime import (
    _build_actor_from_character,
    _execute_action,
    _spend_resources,
    short_rest,
)
from dnd_sim.rules_2014 import apply_damage
from dnd_sim.spatial import can_see
from tests.helpers import with_class_levels


def _druid_character() -> dict:
    return with_class_levels(
        {
            "character_id": "druid",
            "name": "Druid",
            "class_level": "Druid 4",
            "max_hp": 20,
            "ac": 14,
            "speed_ft": 30,
            "ability_scores": {"str": 10, "dex": 14, "con": 12, "int": 10, "wis": 16, "cha": 10},
            "save_mods": {"str": 0, "dex": 2, "con": 1, "int": 0, "wis": 5, "cha": 0},
            "skill_mods": {},
            "attacks": [
                {
                    "name": "Quarterstaff",
                    "to_hit": 4,
                    "damage": "1d6+2",
                    "damage_type": "bludgeoning",
                }
            ],
            "resources": {"wild_shape": {"max": 2}},
            "traits": ["Wild Shape"],
            "wild_shape_forms": [
                {
                    "name": "wolf",
                    "cr": "1/4",
                    "max_hp": 11,
                    "ac": 13,
                    "speed_ft": 40,
                    "str_mod": 1,
                    "dex_mod": 2,
                    "con_mod": 1,
                    "attacks": [{"name": "bite", "to_hit": 4, "damage": "2d4+2"}],
                }
            ],
            "raw_fields": [],
            "source": {"pdf_name": "fixture.pdf"},
        }
    )


def _activate_wild_shape(actor, action_name: str = "wild_shape") -> None:
    action = next(entry for entry in actor.actions if entry.name == action_name)
    actors = {actor.actor_id: actor}
    damage_dealt = {actor.actor_id: 0}
    damage_taken = {actor.actor_id: 0}
    threat_scores = {actor.actor_id: 0}
    resources_spent = {actor.actor_id: {}}
    spent = _spend_resources(actor, action.resource_cost)
    resources_spent[actor.actor_id].update(spent)
    _execute_action(
        rng=random.Random(1),
        actor=actor,
        action=action,
        targets=[actor],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )


def test_build_actor_includes_wild_shape_action() -> None:
    actor = _build_actor_from_character(_druid_character(), traits_db={})
    action = next((entry for entry in actor.actions if entry.name == "wild_shape"), None)

    assert action is not None
    assert action.action_type == "utility"
    assert action.target_mode == "self"
    assert action.resource_cost == {"wild_shape": 1}
    assert action.effects and action.effects[0]["effect_type"] == "wild_shape"


def test_wild_shape_transform_and_overflow_damage_revert() -> None:
    actor = _build_actor_from_character(_druid_character(), traits_db={})
    base_hp = actor.hp
    base_ac = actor.ac
    base_speed = actor.speed_ft
    base_movement = dict(actor.movement_modes)
    pre_actions = [entry.name for entry in actor.actions]

    _activate_wild_shape(actor)

    assert actor.wild_shape_active is True
    assert actor.wild_shape_form_name == "wolf"
    assert actor.hp == 11
    assert actor.ac == 13
    assert actor.speed_ft == 40
    assert actor.movement_modes["walk"] == 40.0
    transformed_actions = [entry.name for entry in actor.actions]
    assert "wild_shape" not in transformed_actions
    assert "revert_wild_shape" in transformed_actions
    assert "attack_1" in transformed_actions

    apply_damage(actor, 15, "slashing")

    assert actor.wild_shape_active is False
    assert actor.hp == base_hp - 4
    assert actor.ac == base_ac
    assert actor.speed_ft == base_speed
    assert actor.movement_modes == base_movement
    assert "wild_shaped" not in actor.conditions
    assert [entry.name for entry in actor.actions] == pre_actions


def test_wild_shape_preserves_distance_already_moved_on_transform() -> None:
    actor = _build_actor_from_character(_druid_character(), traits_db={})
    actor.movement_remaining = 10.0  # 20 ft already moved from base 30 ft speed.

    _activate_wild_shape(actor)

    assert actor.speed_ft == 40
    assert actor.movement_remaining == 20.0


def test_wild_shape_preserves_distance_already_moved_on_revert() -> None:
    actor = _build_actor_from_character(_druid_character(), traits_db={})
    actor.movement_remaining = 10.0  # 20 ft moved at base speed.

    _activate_wild_shape(actor)
    actor.movement_remaining = 5.0  # 35 ft moved total while in 40 ft form.
    _activate_wild_shape(actor, action_name="wild_shape_revert")

    assert actor.wild_shape_active is False
    assert actor.speed_ft == 30
    assert actor.movement_remaining == 0.0


def test_wild_shape_applies_form_senses_and_reverts_them() -> None:
    character = _druid_character()
    character["wild_shape_forms"] = [
        {
            "name": "reef_hunter",
            "cr": "1/4",
            "max_hp": 11,
            "ac": 12,
            "movement": {"walk": 5, "swim": 40},
            "senses": {"darkvision": 120, "blindsight": 10},
            "attacks": [
                {"name": "talons", "to_hit": 3, "damage": "1d4+1", "damage_type": "slashing"}
            ],
        }
    ]
    actor = _build_actor_from_character(character, traits_db={})

    assert (
        can_see(
            observer_pos=(0.0, 0.0, 0.0),
            target_pos=(20.0, 0.0, 0.0),
            observer_traits=actor.traits,
            target_conditions=set(),
            active_hazards=[],
            light_level="darkness",
        )
        is False
    )

    _activate_wild_shape(actor)
    assert actor.speed_ft == 5
    assert actor.movement_modes.get("swim") == 40.0
    assert (
        can_see(
            observer_pos=(0.0, 0.0, 0.0),
            target_pos=(20.0, 0.0, 0.0),
            observer_traits=actor.traits,
            target_conditions=set(),
            active_hazards=[],
            light_level="darkness",
        )
        is True
    )
    assert (
        can_see(
            observer_pos=(0.0, 0.0, 0.0),
            target_pos=(5.0, 0.0, 0.0),
            observer_traits=actor.traits,
            target_conditions={"invisible"},
            active_hazards=[],
            light_level="darkness",
        )
        is True
    )

    apply_damage(actor, 20, "slashing")
    assert actor.wild_shape_active is False
    assert (
        can_see(
            observer_pos=(0.0, 0.0, 0.0),
            target_pos=(20.0, 0.0, 0.0),
            observer_traits=actor.traits,
            target_conditions=set(),
            active_hazards=[],
            light_level="darkness",
        )
        is False
    )


def test_wild_shape_replaces_spell_actions_while_transformed() -> None:
    character = _druid_character()
    character["spells"] = [
        {
            "name": "Moonbeam",
            "level": 2,
            "action_type": "save",
            "save_dc": 14,
            "save_ability": "con",
            "damage": "2d10",
            "damage_type": "radiant",
            "concentration": True,
        }
    ]
    character["resources"]["spell_slots"] = {"2": 2}
    actor = _build_actor_from_character(character, traits_db={})

    assert any("spell" in action.tags for action in actor.actions)
    _activate_wild_shape(actor)
    assert all("spell" not in action.tags for action in actor.actions)


def test_wild_shape_uses_best_legal_form_for_level() -> None:
    character = _druid_character()
    character["class_levels"] = {"druid": 2}
    character["wild_shape_forms"] = [
        {"name": "bear", "cr": "1", "max_hp": 34, "ac": 11, "speed_ft": 40},
        {"name": "wolf", "cr": "1/4", "max_hp": 11, "ac": 13, "speed_ft": 40},
    ]
    actor = _build_actor_from_character(character, traits_db={})
    _activate_wild_shape(actor)
    assert actor.wild_shape_form_name == "wolf"


def test_wild_shape_swim_fly_gates_by_level() -> None:
    character = _druid_character()
    character["class_levels"] = {"druid": 2}
    character["wild_shape_forms"] = [
        {"name": "reef_shark", "cr": "1/2", "max_hp": 22, "ac": 12, "movement": {"swim": 40}},
        {"name": "giant_eagle", "cr": "1", "max_hp": 26, "ac": 13, "movement": {"fly": 80}},
    ]
    low_level_actor = _build_actor_from_character(character, traits_db={})
    assert not any(action.name == "wild_shape" for action in low_level_actor.actions)

    character["class_levels"] = {"druid": 4}
    mid_actor = _build_actor_from_character(character, traits_db={})
    _activate_wild_shape(mid_actor)
    assert mid_actor.wild_shape_form_name == "reef_shark"

    character["class_levels"] = {"druid": 8}
    high_actor = _build_actor_from_character(character, traits_db={})
    _activate_wild_shape(high_actor)
    assert high_actor.wild_shape_form_name == "giant_eagle"


def test_combat_wild_shape_uses_bonus_action_and_moon_cr_limit() -> None:
    character = _druid_character()
    character["class_levels"] = {"druid": 6}
    character["traits"] = ["Wild Shape", "Combat Wild Shape", "Circle of the Moon"]
    character["wild_shape_forms"] = [
        {"name": "polar_bear", "cr": "2", "max_hp": 42, "ac": 12, "speed_ft": 40},
        {"name": "dire_wolf", "cr": "1", "max_hp": 37, "ac": 14, "speed_ft": 50},
    ]
    actor = _build_actor_from_character(character, traits_db={})
    action = next(entry for entry in actor.actions if entry.name == "wild_shape")
    assert action.action_cost == "bonus"

    _activate_wild_shape(actor)
    assert actor.wild_shape_form_name == "polar_bear"


def test_elemental_wild_shape_requires_level_10_and_costs_two_uses() -> None:
    character = _druid_character()
    character["class_levels"] = {"druid": 9}
    character["traits"] = ["Wild Shape", "Combat Wild Shape", "Circle of the Moon"]
    character["wild_shape_forms"] = [
        {"name": "wolf", "cr": "1/4", "max_hp": 11, "ac": 13, "speed_ft": 40},
        {
            "name": "air_elemental",
            "cr": "3",
            "max_hp": 90,
            "ac": 15,
            "speed_ft": 90,
            "form_type": "elemental",
        },
    ]
    actor_lvl9 = _build_actor_from_character(character, traits_db={})
    assert not any(action.name == "wild_shape_elemental" for action in actor_lvl9.actions)

    character["class_levels"] = {"druid": 10}
    actor_lvl10 = _build_actor_from_character(character, traits_db={})
    elemental_action = next(
        (action for action in actor_lvl10.actions if action.name == "wild_shape_elemental"),
        None,
    )
    assert elemental_action is not None
    assert elemental_action.resource_cost == {"wild_shape": 2}
    assert actor_lvl10.resources["wild_shape"] == 2

    _activate_wild_shape(actor_lvl10, action_name="wild_shape_elemental")
    assert actor_lvl10.wild_shape_form_name == "air_elemental"
    assert actor_lvl10.resources["wild_shape"] == 0


def test_elemental_wild_shape_can_be_enabled_by_explicit_trait() -> None:
    character = _druid_character()
    character["class_levels"] = {"druid": 10}
    character["traits"] = ["Wild Shape", "Elemental Wild Shape"]
    character["wild_shape_forms"] = [
        {"name": "wolf", "cr": "1/4", "max_hp": 11, "ac": 13, "speed_ft": 40},
        {
            "name": "small_earth_elemental",
            "cr": "1",
            "max_hp": 26,
            "ac": 13,
            "speed_ft": 30,
            "form_type": "elemental",
        },
    ]
    actor = _build_actor_from_character(character, traits_db={})
    assert any(action.name == "wild_shape_elemental" for action in actor.actions)


def test_short_rest_recovers_wild_shape_uses() -> None:
    character = _druid_character()
    character["current_resources"] = {"wild_shape": 0}
    actor = _build_actor_from_character(character, traits_db={})

    assert actor.resources["wild_shape"] == 0
    short_rest(actor)
    assert actor.resources["wild_shape"] == 2
