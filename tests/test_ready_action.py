from __future__ import annotations

import random

import pytest

import dnd_sim.engine_runtime as engine_module
from dnd_sim.engine import TurnDeclarationValidationError
from dnd_sim.engine_runtime import (
    _actor_state_snapshot,
    _build_actor_views,
    _execute_action,
    _execute_declared_turn_or_error,
    _run_opportunity_attacks_for_movement,
    _validate_declared_ready_or_error,
    short_rest,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.strategy_api import (
    DeclaredAction,
    ReactionPolicy,
    ReadyDeclaration,
    TurnDeclaration,
)


class _SequenceRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, low: int, high: int) -> int:
        if not self.values:
            raise AssertionError("unexpected RNG consumption")
        value = self.values.pop(0)
        assert low <= value <= high
        return value


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


def test_readied_melee_attack_honors_declared_knockout_intent() -> None:
    ready_actor = _base_actor(actor_id="ready_actor", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")
    enemy.hp = 1
    enemy.uses_death_saves = False
    enemy.position = (5.0, 0.0, 0.0)
    ready_action = ActionDefinition(
        name="ready",
        action_type="utility",
        action_cost="action",
        target_mode="self",
    )
    readied_attack = ActionDefinition(
        name="club",
        action_type="attack",
        attack_delivery="melee_weapon_attack",
        action_cost="action",
        to_hit=5,
        damage="1",
        damage_type="bludgeoning",
        reach_ft=5,
    )
    ready_actor.actions = [ready_action, readied_attack]
    actors = {ready_actor.actor_id: ready_actor, enemy.actor_id: enemy}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(ready_actor, enemy)
    telemetry: list[dict[str, object]] = []
    rng = _SequenceRng([15, 2])

    _execute_declared_turn_or_error(
        rng=rng,
        actor=ready_actor,
        declaration=TurnDeclaration(
            action=DeclaredAction(
                action_name="ready",
                targets=[],
            ),
            ready=ReadyDeclaration(
                trigger=" enemy_turn_start ",
                response_action_name=" club ",
                zero_hp_intent=" KNOCK_OUT ",
            ),
        ),
        strategy_name="test",
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        telemetry=telemetry,
        round_number=1,
        turn_token="1:ready_actor",
    )

    assert ready_actor.readied_zero_hp_intent == "knock_out"
    snapshot = _actor_state_snapshot(ready_actor)
    assert snapshot["readied_action_name"] == "club"
    assert snapshot["readied_trigger"] == "enemy_turn_start"
    assert snapshot["readied_zero_hp_intent"] == "knock_out"
    assert snapshot["readied_reaction_reserved"] is True
    actor_view = _build_actor_views(
        actors,
        actor_order=[ready_actor.actor_id, enemy.actor_id],
        round_number=1,
        metadata={},
    ).actors[ready_actor.actor_id]
    assert actor_view.reaction_available is True
    assert actor_view.readied_action_name == "club"
    assert actor_view.readied_zero_hp_intent == "knock_out"
    trigger_ready = getattr(engine_module, "_trigger_readied_actions")
    trigger_ready(
        rng=rng,
        trigger_actor=enemy,
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:enemy",
        telemetry=telemetry,
    )

    assert enemy.hp == 0
    assert enemy.stable is True
    assert enemy.dead is False
    assert enemy.stable_recovery_hours_remaining == 2
    assert ready_actor.readied_zero_hp_intent == "normal"
    assert any(
        row.get("telemetry_type") == "decision" and row.get("ready_zero_hp_intent") == "knock_out"
        for row in telemetry
    )
    assert any(
        row.get("telemetry_type") == "knockout_resolution"
        and row.get("requested") is True
        and row.get("applied") is True
        for row in telemetry
    )
    assert rng.values == []


@pytest.mark.parametrize("attack_delivery", ["ranged_weapon_attack", None])
def test_ready_declaration_rejects_non_melee_knockout_intent(
    attack_delivery: str | None,
) -> None:
    ready_actor = _base_actor(actor_id="ready_actor", team="party")
    ready_action = ActionDefinition(name="ready", action_type="utility", action_cost="action")
    readied_attack = ActionDefinition(
        name="longbow",
        action_type="attack",
        attack_delivery=attack_delivery,
        action_cost="action",
        to_hit=5,
        damage="1",
        range_ft=150,
    )
    ready_actor.actions = [ready_action, readied_attack]

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        _validate_declared_ready_or_error(
            ready_actor,
            TurnDeclaration(
                action=DeclaredAction(action_name="ready"),
                ready=ReadyDeclaration(
                    trigger="enemy_turn_start",
                    response_action_name="longbow",
                    zero_hp_intent="knock_out",
                ),
            ),
        )

    assert exc_info.value.code == "illegal_knockout_intent"
    assert exc_info.value.field == "ready.zero_hp_intent"


def test_ready_declaration_rejects_unknown_zero_hp_intent() -> None:
    ready_actor = _base_actor(actor_id="ready_actor", team="party")
    ready_actor.actions = [
        ActionDefinition(name="ready", action_type="utility", action_cost="action"),
        ActionDefinition(
            name="club",
            action_type="attack",
            attack_delivery="melee_weapon_attack",
            action_cost="action",
            to_hit=5,
            damage="1",
            reach_ft=5,
        ),
    ]

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        _validate_declared_ready_or_error(
            ready_actor,
            TurnDeclaration(
                action=DeclaredAction(action_name="ready"),
                ready=ReadyDeclaration(
                    trigger="enemy_turn_start",
                    response_action_name="club",
                    zero_hp_intent="maybe",
                ),
            ),
        )

    assert exc_info.value.code == "invalid_zero_hp_intent"
    assert exc_info.value.field == "ready.zero_hp_intent"


def test_ready_declaration_rejects_unsupported_trigger() -> None:
    actor = _base_actor(actor_id="ready_actor", team="party")
    actor.actions = [
        ActionDefinition(name="ready", action_type="utility", action_cost="action"),
        ActionDefinition(
            name="club",
            action_type="attack",
            attack_delivery="melee_weapon_attack",
            action_cost="action",
            to_hit=5,
            damage="1",
            reach_ft=5,
        ),
    ]

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        _validate_declared_ready_or_error(
            actor,
            TurnDeclaration(
                action=DeclaredAction(action_name="ready"),
                ready=ReadyDeclaration(
                    trigger="enemy_enter_reach",
                    response_action_name="club",
                ),
            ),
        )

    assert exc_info.value.code == "unsupported_ready_trigger"
    assert exc_info.value.field == "ready.trigger"


def test_ready_declaration_accepts_all_melee_attack_sequence() -> None:
    actor = _base_actor(actor_id="ready_actor", team="party")
    actor.actions = [
        ActionDefinition(name="ready", action_type="utility", action_cost="action"),
        ActionDefinition(
            name="club",
            action_type="attack",
            attack_delivery="melee_weapon_attack",
            action_cost="action",
            to_hit=5,
            damage="1",
        ),
        ActionDefinition(
            name="shocking_grasp",
            action_type="attack",
            attack_delivery="melee_spell_attack",
            action_cost="action",
            to_hit=5,
            damage="1",
        ),
        ActionDefinition(
            name="multiattack",
            action_type="attack",
            action_cost="action",
            mechanics=[
                {
                    "effect_type": "attack_sequence",
                    "sequence": [
                        {"action_name": "club"},
                        {"action_name": "shocking_grasp"},
                    ],
                }
            ],
        ),
    ]

    ready = _validate_declared_ready_or_error(
        actor,
        TurnDeclaration(
            action=DeclaredAction(action_name="ready"),
            ready=ReadyDeclaration(
                trigger="enemy_turn_start",
                response_action_name="multiattack",
                zero_hp_intent="knock_out",
            ),
        ),
    )

    assert ready is not None
    assert ready.zero_hp_intent == "knock_out"


def test_ready_declaration_rejects_mixed_delivery_attack_sequence() -> None:
    actor = _base_actor(actor_id="ready_actor", team="party")
    actor.actions = [
        ActionDefinition(name="ready", action_type="utility", action_cost="action"),
        ActionDefinition(
            name="club",
            action_type="attack",
            attack_delivery="melee_weapon_attack",
            action_cost="action",
            to_hit=5,
            damage="1",
        ),
        ActionDefinition(
            name="longbow",
            action_type="attack",
            attack_delivery="ranged_weapon_attack",
            action_cost="action",
            to_hit=5,
            damage="1",
        ),
        ActionDefinition(
            name="multiattack",
            action_type="attack",
            action_cost="action",
            mechanics=[
                {
                    "effect_type": "attack_sequence",
                    "sequence": [
                        {"action_name": "club"},
                        {"action_name": "longbow"},
                    ],
                }
            ],
        ),
    ]

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        _validate_declared_ready_or_error(
            actor,
            TurnDeclaration(
                action=DeclaredAction(action_name="ready"),
                ready=ReadyDeclaration(
                    trigger="enemy_turn_start",
                    response_action_name="multiattack",
                    zero_hp_intent="knock_out",
                ),
            ),
        )

    assert exc_info.value.code == "illegal_knockout_intent"
    assert exc_info.value.field == "ready.zero_hp_intent"


def test_short_rest_clears_readied_intent_and_held_spell_state() -> None:
    actor = _base_actor(actor_id="ready_actor", team="party")
    actor.add_manual_condition("readying")
    actor.readied_action_name = "guiding_bolt"
    actor.readied_trigger = "enemy_turn_start"
    actor.readied_zero_hp_intent = "knock_out"
    actor.readied_reaction_reserved = True
    actor.readied_spell_slot_level = 1
    actor.readied_spell_held = True
    actor.concentrating = True
    actor.concentrated_spell = "guiding_bolt"
    actor.concentrated_spell_level = 1

    short_rest(actor)

    assert "readying" not in actor.conditions
    assert actor.readied_action_name is None
    assert actor.readied_trigger is None
    assert actor.readied_zero_hp_intent == "normal"
    assert actor.readied_reaction_reserved is False
    assert actor.readied_spell_slot_level is None
    assert actor.readied_spell_held is False
    assert actor.concentrating is False
    assert actor.concentrated_spell is None
    assert actor.concentrated_spell_level is None


def test_readied_reach_trigger_honors_knockout_intent() -> None:
    ready_actor = _base_actor(actor_id="ready_actor", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")
    ready_actor.position = (0.0, 0.0, 0.0)
    enemy.position = (0.0, 0.0, 0.0)
    enemy.hp = 1
    enemy.uses_death_saves = False
    ready_actor.actions = [
        ActionDefinition(
            name="ready",
            action_type="utility",
            action_cost="action",
            target_mode="self",
        ),
        ActionDefinition(
            name="club",
            action_type="attack",
            attack_delivery="melee_weapon_attack",
            action_cost="action",
            to_hit=5,
            damage="1",
            damage_type="bludgeoning",
            reach_ft=5,
        ),
    ]
    actors = {ready_actor.actor_id: ready_actor, enemy.actor_id: enemy}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(ready_actor, enemy)
    rng = _SequenceRng([15, 3])

    _execute_declared_turn_or_error(
        rng=rng,
        actor=ready_actor,
        declaration=TurnDeclaration(
            action=DeclaredAction(action_name="ready"),
            ready=ReadyDeclaration(
                trigger="enemy_enters_reach",
                response_action_name="club",
                zero_hp_intent="knock_out",
            ),
        ),
        strategy_name="test",
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    _run_opportunity_attacks_for_movement(
        rng=rng,
        mover=enemy,
        start_pos=(20.0, 0.0, 0.0),
        end_pos=(0.0, 0.0, 0.0),
        movement_path=[(20.0, 0.0, 0.0), (0.0, 0.0, 0.0)],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert enemy.hp == 0
    assert enemy.stable is True
    assert enemy.dead is False
    assert enemy.stable_recovery_hours_remaining == 3
    assert ready_actor.readied_zero_hp_intent == "normal"
    assert rng.values == []


def test_invalid_ready_declaration_is_rejected_before_movement() -> None:
    actor = _base_actor(actor_id="ready_actor", team="party")
    actor.movement_remaining = 30.0
    actor.actions = [
        ActionDefinition(
            name="ready",
            action_type="utility",
            action_cost="action",
            target_mode="self",
        ),
        ActionDefinition(
            name="longbow",
            action_type="attack",
            attack_delivery="ranged_weapon_attack",
            action_cost="action",
            to_hit=5,
            damage="1",
            range_ft=150,
        ),
    ]
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(actor)

    with pytest.raises(TurnDeclarationValidationError):
        _execute_declared_turn_or_error(
            rng=_SequenceRng([]),
            actor=actor,
            declaration=TurnDeclaration(
                movement_path=[(0.0, 0.0, 0.0), (5.0, 0.0, 0.0)],
                action=DeclaredAction(action_name="ready"),
                ready=ReadyDeclaration(
                    trigger="enemy_turn_start",
                    response_action_name="longbow",
                    zero_hp_intent="knock_out",
                ),
            ),
            strategy_name="test",
            actors={actor.actor_id: actor},
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=[],
        )

    assert actor.position == (0.0, 0.0, 0.0)
    assert actor.movement_remaining == 30.0


def test_conflicting_ready_policy_does_not_consume_reaction() -> None:
    actor = _base_actor(actor_id="ready_actor", team="party")
    actor.actions = [
        ActionDefinition(
            name="ready",
            action_type="utility",
            action_cost="action",
            target_mode="self",
        ),
        ActionDefinition(
            name="club",
            action_type="attack",
            attack_delivery="melee_weapon_attack",
            action_cost="action",
            to_hit=5,
            damage="1",
            reach_ft=5,
        ),
    ]
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(actor)

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        _execute_declared_turn_or_error(
            rng=_SequenceRng([]),
            actor=actor,
            declaration=TurnDeclaration(
                action=DeclaredAction(action_name="ready"),
                reaction_policy=ReactionPolicy(mode="none"),
                ready=ReadyDeclaration(
                    trigger="enemy_turn_start",
                    response_action_name="club",
                ),
            ),
            strategy_name="test",
            actors={actor.actor_id: actor},
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=[],
        )

    assert exc_info.value.code == "conflicting_reaction_policy"
    assert actor.reaction_available is True
