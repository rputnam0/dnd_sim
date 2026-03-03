from __future__ import annotations

import random

from dnd_sim.engine import (
    _action_available,
    _build_actor_from_character,
    _execute_action,
    _find_best_bonus_action,
    _spend_action_resource_cost,
    _tick_conditions_for_actor,
    long_rest,
    short_rest,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState


def _barbarian_character(*, level: int, traits: list[str], resources: dict | None = None) -> dict:
    return {
        "character_id": f"barbarian_{level}",
        "name": f"Barbarian {level}",
        "class_level": f"Barbarian {level}",
        "max_hp": 58,
        "ac": 15,
        "speed_ft": 30,
        "ability_scores": {
            "str": 18,
            "dex": 14,
            "con": 16,
            "int": 8,
            "wis": 10,
            "cha": 10,
        },
        "save_mods": {"str": 7, "dex": 2, "con": 6, "int": -1, "wis": 0, "cha": 0},
        "skill_mods": {},
        "attacks": [
            {"name": "Greataxe", "to_hit": 7, "damage": "1d12+4", "damage_type": "slashing"}
        ],
        "resources": resources or {},
        "traits": traits,
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }


def _base_actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=40,
        hp=40,
        temp_hp=0,
        ac=12,
        initiative_mod=0,
        str_mod=4,
        dex_mod=2,
        con_mod=3,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 4, "dex": 2, "con": 3, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def test_build_actor_infers_barbarian_rage_resource_from_level() -> None:
    character = _barbarian_character(level=6, traits=["Rage"])

    actor = _build_actor_from_character(character, traits_db={})

    assert actor.max_resources["rage"] == 4
    assert actor.resources["rage"] == 4


def test_rage_resource_lifecycle_spend_short_rest_and_long_rest_recovery() -> None:
    rng = random.Random(3)
    actor = _build_actor_from_character(
        _barbarian_character(level=6, traits=["Rage"]), traits_db={}
    )

    rage_action = _find_best_bonus_action(actor)
    assert rage_action is not None
    assert rage_action.name == "rage_activation"

    resources_spent = {actor.actor_id: {}}
    assert _action_available(actor, rage_action)
    assert _spend_action_resource_cost(actor, rage_action, resources_spent)

    _execute_action(
        rng=rng,
        actor=actor,
        action=rage_action,
        targets=[actor],
        actors={actor.actor_id: actor},
        damage_dealt={actor.actor_id: 0},
        damage_taken={actor.actor_id: 0},
        threat_scores={actor.actor_id: 0},
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert actor.resources["rage"] == 3
    assert resources_spent[actor.actor_id]["rage"] == 1

    short_rest(actor)
    assert actor.resources["rage"] == 3

    long_rest(actor)
    assert actor.resources["rage"] == 4


def test_rage_activation_is_illegal_while_already_raging() -> None:
    actor = _base_actor(actor_id="barb", team="party")
    actor.traits = {"rage": {}}
    actor.resources = {"rage": 1}
    actor.max_resources = {"rage": 1}
    actor.conditions.add("raging")

    action = ActionDefinition(
        name="rage_activation",
        action_type="buff",
        action_cost="bonus",
        target_mode="self",
        resource_cost={"rage": 1},
    )

    assert _action_available(actor, action) is False


def test_persistent_rage_prevents_cross_turn_expiration() -> None:
    actor = _base_actor(actor_id="barb", team="party")
    actor.traits = {"rage": {}, "persistent rage": {}}
    actor.conditions.add("raging")

    _tick_conditions_for_actor(random.Random(7), actor)

    assert "raging" in actor.conditions
