from __future__ import annotations

from typing import Any

from dnd_sim.engine_runtime import (
    _action_available,
    _build_actor_from_character,
    _execute_action,
    _spend_resources,
    long_rest,
    short_rest,
)
from dnd_sim.models import ActorRuntimeState
from tests.helpers import with_class_levels


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self.values:
            raise AssertionError("RNG exhausted")
        return self.values.pop(0)


def _warlock_character(
    *,
    level: int,
    traits: list[str],
    spells: list[dict[str, Any]],
    resources: dict[str, Any],
    raw_fields: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return with_class_levels(
        {
            "character_id": f"warlock_{level}",
            "name": f"Warlock {level}",
            "class_level": f"Warlock {level}",
            "max_hp": 38,
            "ac": 14,
            "speed_ft": 30,
            "ability_scores": {
                "str": 8,
                "dex": 14,
                "con": 14,
                "int": 12,
                "wis": 10,
                "cha": 18,
            },
            "save_mods": {"str": -1, "dex": 2, "con": 2, "int": 1, "wis": 0, "cha": 4},
            "skill_mods": {},
            "attacks": [],
            "spells": spells,
            "resources": resources,
            "traits": traits,
            "raw_fields": raw_fields or [],
            "source": {"pdf_name": "fixture.pdf"},
        }
    )


def _enemy(actor_id: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team="enemy",
        name=actor_id,
        max_hp=40,
        hp=40,
        temp_hp=0,
        ac=12,
        initiative_mod=0,
        str_mod=0,
        dex_mod=0,
        con_mod=0,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def test_pact_slot_resource_uses_warlock_cadence_and_short_rest_refresh() -> None:
    character = _warlock_character(
        level=5,
        traits=["Pact Magic"],
        spells=[
            {"name": "Hex", "level": 1, "action_type": "save", "save_dc": 14, "damage": "1d6"},
            {
                "name": "Hunger of Hadar",
                "level": 3,
                "action_type": "save",
                "save_dc": 14,
                "damage": "2d6",
            },
        ],
        resources={"spell_slots": {"1": 0, "2": 0, "3": 2}},
    )

    actor = _build_actor_from_character(character, traits_db={})

    assert actor.max_resources["warlock_spell_slot_3"] == 2
    assert "spell_slot_3" not in actor.max_resources
    hex_action = next(action for action in actor.actions if action.name == "Hex")
    hunger_action = next(action for action in actor.actions if action.name == "Hunger of Hadar")
    assert hex_action.resource_cost == {"warlock_spell_slot_3": 1}
    assert hunger_action.resource_cost == {"warlock_spell_slot_3": 1}

    _spend_resources(actor, hex_action.resource_cost)
    _spend_resources(actor, hunger_action.resource_cost)
    assert actor.resources["warlock_spell_slot_3"] == 0

    short_rest(actor)

    assert actor.resources["warlock_spell_slot_3"] == 2


def test_agonizing_and_repelling_blast_invocations_apply_to_eldritch_blast() -> None:
    character = _warlock_character(
        level=2,
        traits=["Eldritch Invocations"],
        spells=[
            {
                "name": "Eldritch Blast",
                "level": 0,
                "action_type": "attack",
                "to_hit": 8,
                "damage": "1d10",
                "damage_type": "force",
            }
        ],
        resources={"spell_slots": {"1": 2}},
        raw_fields=[
            {
                "field": "FeaturesTraits1",
                "value": (
                    "* Eldritch Invocations • PHB\n"
                    "| Agonizing Blast • PHB\n"
                    "| Repelling Blast • PHB\n"
                ),
            }
        ],
    )
    actor = _build_actor_from_character(character, traits_db={})
    blast = next(action for action in actor.actions if action.name == "Eldritch Blast")

    assert "agonizing_blast" in blast.tags
    assert any(
        effect.get("effect_type") == "forced_movement"
        and effect.get("distance_ft") == 10
        and effect.get("direction") == "away_from_source"
        for effect in blast.mechanics
    )

    target = _enemy("ogre")
    actor.position = (0.0, 0.0, 0.0)
    target.position = (0.0, 10.0, 0.0)
    actors = {actor.actor_id: actor, target.actor_id: target}
    damage_dealt = {actor.actor_id: 0, target.actor_id: 0}
    damage_taken = {actor.actor_id: 0, target.actor_id: 0}
    threat_scores = {actor.actor_id: 0, target.actor_id: 0}
    resources_spent = {actor.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=FixedRng([12, 5]),
        actor=actor,
        action=blast,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert damage_dealt[actor.actor_id] == 9
    assert target.position == (0.0, 20.0, 0.0)


def test_mystic_arcanum_is_once_per_long_rest_not_short_rest() -> None:
    character = _warlock_character(
        level=13,
        traits=["Pact Magic", "Mystic Arcanum"],
        spells=[
            {
                "name": "Forcecage",
                "level": 7,
                "action_type": "utility",
                "target_mode": "single_enemy",
            }
        ],
        resources={"spell_slots": {"5": 3}},
    )
    actor = _build_actor_from_character(character, traits_db={})
    arcanum_action = next(action for action in actor.actions if action.name == "Forcecage")

    assert arcanum_action.max_uses == 1
    assert arcanum_action.resource_cost == {}
    assert "mystic_arcanum" in arcanum_action.tags
    assert _action_available(actor, arcanum_action) is True

    actor.per_action_uses[arcanum_action.name] = 1
    assert _action_available(actor, arcanum_action) is False

    short_rest(actor)
    assert _action_available(actor, arcanum_action) is False

    long_rest(actor)
    assert _action_available(actor, arcanum_action) is True
