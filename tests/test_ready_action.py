from __future__ import annotations

import random

import pytest

import dnd_sim.engine as engine_module
from dnd_sim.engine import TurnDeclarationValidationError
from dnd_sim.engine_runtime import _execute_action, _validate_declared_ready_or_error
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.strategy_api import DeclaredAction, ReadyDeclaration, TurnDeclaration


def _base_actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=30,
        hp=30,
        temp_hp=0,
        ac=12,
        initiative_mod=0,
        str_mod=2,
        dex_mod=2,
        con_mod=2,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 2, "dex": 2, "con": 2, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def _trackers(
    *actors: ActorRuntimeState,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    damage_dealt = {actor.actor_id: 0 for actor in actors}
    damage_taken = {actor.actor_id: 0 for actor in actors}
    threat_scores = {actor.actor_id: 0 for actor in actors}
    resources_spent = {actor.actor_id: {} for actor in actors}
    return damage_dealt, damage_taken, threat_scores, resources_spent


def test_ready_attack_fires_when_enemy_enters_reach() -> None:
    ready_actor = _base_actor(actor_id="ready_actor", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")
    ready_actor.position = (0.0, 0.0, 0.0)
    enemy.position = (20.0, 0.0, 0.0)
    enemy.speed_ft = 30
    enemy.movement_remaining = 30.0

    ready_action = ActionDefinition(
        name="ready",
        action_type="utility",
        action_cost="action",
        event_trigger="enemy_enters_reach",
    )
    readied_attack = ActionDefinition(
        name="basic",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1d4",
        damage_type="slashing",
        range_ft=5,
    )
    enemy_attack = ActionDefinition(
        name="claw",
        action_type="attack",
        action_cost="action",
        to_hit=0,
        damage="1d4",
        damage_type="slashing",
        range_ft=5,
    )
    ready_actor.actions = [ready_action, readied_attack]
    enemy.actions = [enemy_attack]

    actors = {ready_actor.actor_id: ready_actor, enemy.actor_id: enemy}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(ready_actor, enemy)

    _execute_action(
        rng=random.Random(10),
        actor=ready_actor,
        action=ready_action,
        targets=[enemy],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    assert "readying" in ready_actor.conditions

    _execute_action(
        rng=random.Random(11),
        actor=enemy,
        action=enemy_attack,
        targets=[ready_actor],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert enemy.hp < enemy.max_hp
    assert ready_actor.reaction_available is False
    assert "readying" not in ready_actor.conditions


def test_readied_spell_consumes_slot_immediately_and_holds_concentration() -> None:
    ready_actor = _base_actor(actor_id="ready_actor", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")

    ready_action = ActionDefinition(name="ready", action_type="utility", action_cost="action")
    readied_spell = ActionDefinition(
        name="guiding_bolt",
        action_type="attack",
        action_cost="action",
        to_hit=6,
        damage="4d6",
        damage_type="radiant",
        range_ft=120,
        resource_cost={"spell_slot_1": 1},
        tags=["spell"],
    )
    ready_actor.actions = [ready_action, readied_spell]
    ready_actor.resources["spell_slot_1"] = 1

    actors = {ready_actor.actor_id: ready_actor, enemy.actor_id: enemy}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(ready_actor, enemy)

    _execute_action(
        rng=random.Random(12),
        actor=ready_actor,
        action=ready_action,
        targets=[enemy],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        ready_declaration=ReadyDeclaration(
            trigger="enemy_turn_start",
            response_action_name="guiding_bolt",
        ),
    )

    assert ready_actor.resources["spell_slot_1"] == 0
    assert resources_spent[ready_actor.actor_id]["spell_slot_1"] == 1
    assert ready_actor.concentrating is True
    assert ready_actor.concentrated_spell == "guiding_bolt"


def test_readied_response_cannot_fire_without_reaction() -> None:
    ready_actor = _base_actor(actor_id="ready_actor", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")
    ready_actor.position = (0.0, 0.0, 0.0)
    enemy.position = (5.0, 0.0, 0.0)

    ready_action = ActionDefinition(name="ready", action_type="utility", action_cost="action")
    readied_attack = ActionDefinition(
        name="basic",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1d4",
        damage_type="slashing",
        range_ft=5,
    )
    ready_actor.actions = [ready_action, readied_attack]

    actors = {ready_actor.actor_id: ready_actor, enemy.actor_id: enemy}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(ready_actor, enemy)

    _execute_action(
        rng=random.Random(13),
        actor=ready_actor,
        action=ready_action,
        targets=[enemy],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    ready_actor.reaction_available = False

    trigger_ready = getattr(engine_module, "_trigger_readied_actions")
    trigger_ready(
        rng=random.Random(14),
        trigger_actor=enemy,
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert enemy.hp == enemy.max_hp
    assert "readying" in ready_actor.conditions


def test_readied_action_surge_is_illegal_off_turn_and_not_spent() -> None:
    ready_actor = _base_actor(actor_id="ready_actor", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")
    ready_actor.position = (0.0, 0.0, 0.0)
    enemy.position = (5.0, 0.0, 0.0)

    ready_action = ActionDefinition(name="ready", action_type="utility", action_cost="action")
    readied_action_surge = ActionDefinition(
        name="action_surge",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1",
        damage_type="slashing",
        attack_count=4,
        range_ft=5,
        resource_cost={"action_surge": 1},
        tags=["action_surge", "fighter_action_surge"],
    )
    ready_actor.actions = [ready_action, readied_action_surge]
    ready_actor.resources["action_surge"] = 1

    actors = {ready_actor.actor_id: ready_actor, enemy.actor_id: enemy}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(ready_actor, enemy)

    _execute_action(
        rng=random.Random(15),
        actor=ready_actor,
        action=ready_action,
        targets=[enemy],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        ready_declaration=ReadyDeclaration(
            trigger="enemy_turn_start",
            response_action_name="action_surge",
        ),
    )
    assert "readying" in ready_actor.conditions

    trigger_ready = getattr(engine_module, "_trigger_readied_actions")
    trigger_ready(
        rng=random.Random(16),
        trigger_actor=enemy,
        turn_token="1:enemy",
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert enemy.hp == enemy.max_hp
    assert ready_actor.reaction_available is True
    assert "readying" in ready_actor.conditions
    assert ready_actor.resources["action_surge"] == 1
    assert resources_spent[ready_actor.actor_id].get("action_surge", 0) == 0


def test_readied_wild_shape_action_executes_successfully() -> None:
    ready_actor = _base_actor(actor_id="ready_actor", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")

    ready_action = ActionDefinition(name="ready", action_type="utility", action_cost="action")
    wild_shape = ActionDefinition(
        name="wild_shape",
        action_type="utility",
        action_cost="action",
        target_mode="self",
        resource_cost={"wild_shape": 1},
        effects=[
            {
                "effect_type": "apply_condition",
                "target": "target",
                "condition": "wild_shaped",
                "stack_policy": "refresh",
            }
        ],
        tags=["wild_shape", "shapechange"],
    )
    ready_actor.actions = [ready_action, wild_shape]
    ready_actor.traits["wild shape"] = {}
    ready_actor.resources["wild_shape"] = 1
    ready_actor.max_resources["wild_shape"] = 1

    actors = {ready_actor.actor_id: ready_actor, enemy.actor_id: enemy}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(ready_actor, enemy)

    _execute_action(
        rng=random.Random(17),
        actor=ready_actor,
        action=ready_action,
        targets=[enemy],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        ready_declaration=ReadyDeclaration(
            trigger="enemy_turn_start",
            response_action_name="wild_shape",
        ),
    )

    trigger_ready = getattr(engine_module, "_trigger_readied_actions")
    trigger_ready(
        rng=random.Random(18),
        trigger_actor=enemy,
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert "wild_shaped" in ready_actor.conditions
    assert ready_actor.resources["wild_shape"] == 0
    assert resources_spent[ready_actor.actor_id]["wild_shape"] == 1
    assert ready_actor.reaction_available is False
    assert "readying" not in ready_actor.conditions


def test_ready_declaration_rejects_bonus_action_wild_shape_response() -> None:
    ready_actor = _base_actor(actor_id="ready_actor", team="party")
    ready_action = ActionDefinition(name="ready", action_type="utility", action_cost="action")
    moon_wild_shape = ActionDefinition(
        name="wild_shape",
        action_type="utility",
        action_cost="bonus",
        tags=["wild_shape", "shapechange"],
    )
    ready_actor.actions = [ready_action, moon_wild_shape]
    ready_actor.traits["wild shape"] = {}
    ready_actor.traits["combat wild shape"] = {}

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        _validate_declared_ready_or_error(
            ready_actor,
            TurnDeclaration(
                action=DeclaredAction(action_name="ready"),
                ready=ReadyDeclaration(
                    trigger="enemy_turn_start",
                    response_action_name="wild_shape",
                ),
            ),
        )

    assert exc_info.value.code == "illegal_ready_response"
    assert exc_info.value.field == "ready.response_action_name"
