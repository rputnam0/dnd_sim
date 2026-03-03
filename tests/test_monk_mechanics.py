from __future__ import annotations

import random

from dnd_sim.engine import (
    _action_available,
    _build_actor_from_character,
    _build_character_actions,
    _execute_action,
    _find_best_bonus_action,
    _spend_resources,
    _tick_conditions_for_actor,
    short_rest,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self.values:
            raise AssertionError("RNG exhausted")
        return self.values.pop(0)


def _actor(actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=40,
        hp=40,
        temp_hp=0,
        ac=12,
        initiative_mod=0,
        str_mod=2,
        dex_mod=3,
        con_mod=2,
        int_mod=0,
        wis_mod=3,
        cha_mod=0,
        save_mods={"str": 2, "dex": 3, "con": 2, "int": 0, "wis": 3, "cha": 0},
        actions=[],
    )


def _combat_trackers(
    *actors: ActorRuntimeState,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    damage_dealt = {actor.actor_id: 0 for actor in actors}
    damage_taken = {actor.actor_id: 0 for actor in actors}
    threat_scores = {actor.actor_id: 0 for actor in actors}
    resources_spent = {actor.actor_id: {} for actor in actors}
    return damage_dealt, damage_taken, threat_scores, resources_spent


def _monk_character(*, ki: int) -> dict:
    return {
        "character_id": "monk_legality",
        "name": "Monk",
        "class_level": "Monk 5",
        "max_hp": 38,
        "ac": 16,
        "speed_ft": 30,
        "ability_scores": {"str": 10, "dex": 18, "con": 14, "int": 10, "wis": 16, "cha": 8},
        "save_mods": {"str": 0, "dex": 7, "con": 2, "int": 0, "wis": 6, "cha": -1},
        "skill_mods": {},
        "attacks": [
            {"name": "Unarmed Strike", "to_hit": 7, "damage": "1d6+4", "damage_type": "bludgeoning"}
        ],
        "resources": {"ki": {"max": ki}},
        "traits": ["Extra Attack", "Martial Arts", "Flurry of Blows"],
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }


def test_build_character_actions_monk_flurry_and_ki_economy() -> None:
    character = {
        "character_id": "monk",
        "name": "Monk",
        "class_level": "Monk 5",
        "max_hp": 38,
        "ac": 16,
        "ability_scores": {"str": 10, "dex": 18, "con": 14, "int": 10, "wis": 16, "cha": 8},
        "save_mods": {"str": 0, "dex": 7, "con": 2, "int": 0, "wis": 6, "cha": -1},
        "attacks": [
            {"name": "Unarmed Strike", "to_hit": 7, "damage": "1d6+4", "damage_type": "bludgeoning"}
        ],
        "resources": {"ki": {"max": 5}},
        "traits": ["Martial Arts", "Flurry of Blows"],
    }

    actions = _build_character_actions(character)
    action_by_name = {action.name: action for action in actions}

    assert action_by_name["martial_arts_bonus"].resource_cost == {}
    assert action_by_name["flurry_of_blows"].resource_cost == {"ki": 1}
    assert action_by_name["flurry_of_blows"].attack_count == 2
    assert "flurry_of_blows" in action_by_name["flurry_of_blows"].tags
    assert "signature" not in action_by_name


def test_monk_bonus_actions_require_attack_action_timing_legality() -> None:
    monk = _build_actor_from_character(_monk_character(ki=2), traits_db={})
    martial_arts = next(action for action in monk.actions if action.name == "martial_arts_bonus")
    flurry = next(action for action in monk.actions if action.name == "flurry_of_blows")

    monk.took_attack_action_this_turn = False
    assert _action_available(monk, martial_arts) is False
    assert _action_available(monk, flurry) is False

    monk.took_attack_action_this_turn = True
    assert _action_available(monk, martial_arts) is True
    assert _action_available(monk, flurry) is True

    monk.resources["ki"] = 0
    assert _action_available(monk, martial_arts) is True
    assert _action_available(monk, flurry) is False


def test_find_best_bonus_action_falls_back_to_martial_arts_when_ki_is_empty() -> None:
    monk = _actor("monk", "party")
    monk.took_attack_action_this_turn = True
    monk.resources = {"ki": 0}
    monk.actions = [
        ActionDefinition(
            name="martial_arts_bonus",
            action_type="attack",
            action_cost="bonus",
            tags=["bonus", "martial_arts"],
        ),
        ActionDefinition(
            name="flurry_of_blows",
            action_type="attack",
            action_cost="bonus",
            resource_cost={"ki": 1},
            tags=["bonus", "martial_arts", "flurry_of_blows"],
        ),
    ]

    selected = _find_best_bonus_action(monk)

    assert selected is not None
    assert selected.name == "martial_arts_bonus"


def test_ki_spend_then_short_rest_restores_pool() -> None:
    monk = _build_actor_from_character(_monk_character(ki=2), traits_db={})
    flurry = next(action for action in monk.actions if action.name == "flurry_of_blows")

    spent = _spend_resources(monk, flurry.resource_cost)
    assert spent == {"ki": 1}
    assert monk.resources["ki"] == 1

    short_rest(monk)
    assert monk.resources["ki"] == 2


def test_stunning_strike_spends_ki_on_hit_and_applies_stunned() -> None:
    monk = _actor("monk", "party")
    monk.level = 5
    monk.resources = {"ki": 2}
    monk.traits = {"stunning strike": {}}
    target = _actor("target", "enemy")
    target.ac = 10
    target.save_mods["con"] = 0

    damage_dealt, damage_taken, threat_scores, resources_spent = _combat_trackers(monk, target)
    attack = ActionDefinition(
        name="unarmed_strike",
        action_type="attack",
        to_hit=8,
        damage="1",
        damage_type="bludgeoning",
    )

    _execute_action(
        rng=FixedRng([15, 2]),
        actor=monk,
        action=attack,
        targets=[target],
        actors={monk.actor_id: monk, target.actor_id: target},
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert monk.resources["ki"] == 1
    assert resources_spent["monk"]["ki"] == 1
    assert "stunned" in target.conditions
    assert "incapacitated" in target.conditions


def test_stunning_strike_does_not_spend_ki_on_miss() -> None:
    monk = _actor("monk", "party")
    monk.level = 5
    monk.resources = {"ki": 2}
    monk.traits = {"stunning strike": {}}
    target = _actor("target", "enemy")
    target.ac = 20

    damage_dealt, damage_taken, threat_scores, resources_spent = _combat_trackers(monk, target)
    attack = ActionDefinition(
        name="unarmed_strike",
        action_type="attack",
        to_hit=5,
        damage="1",
        damage_type="bludgeoning",
    )

    _execute_action(
        rng=FixedRng([1]),
        actor=monk,
        action=attack,
        targets=[target],
        actors={monk.actor_id: monk, target.actor_id: target},
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert monk.resources["ki"] == 2
    assert resources_spent["monk"].get("ki", 0) == 0
    assert "stunned" not in target.conditions


def test_open_hand_riders_apply_prone_push_and_reaction_lock() -> None:
    prone_monk = _actor("monk_prone", "party")
    prone_monk.level = 5
    prone_monk.traits = {"open hand technique": {}}
    prone_target = _actor("target_prone", "enemy")
    prone_target.save_mods["dex"] = 0
    prone_action = ActionDefinition(
        name="flurry_of_blows",
        action_type="attack",
        to_hit=8,
        damage="1",
        tags=["flurry_of_blows", "open_hand_rider:prone"],
    )
    damage_dealt, damage_taken, threat_scores, resources_spent = _combat_trackers(
        prone_monk, prone_target
    )
    _execute_action(
        rng=FixedRng([15, 1]),
        actor=prone_monk,
        action=prone_action,
        targets=[prone_target],
        actors={prone_monk.actor_id: prone_monk, prone_target.actor_id: prone_target},
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    assert "prone" in prone_target.conditions

    push_monk = _actor("monk_push", "party")
    push_monk.level = 5
    push_monk.traits = {"open hand technique": {}}
    push_monk.position = (0.0, 0.0, 0.0)
    push_target = _actor("target_push", "enemy")
    push_target.position = (0.0, 10.0, 0.0)
    push_target.save_mods["str"] = 0
    push_action = ActionDefinition(
        name="flurry_of_blows",
        action_type="attack",
        to_hit=8,
        damage="1",
        tags=["flurry_of_blows", "open_hand_rider:push"],
    )
    damage_dealt, damage_taken, threat_scores, resources_spent = _combat_trackers(
        push_monk, push_target
    )
    _execute_action(
        rng=FixedRng([15, 1]),
        actor=push_monk,
        action=push_action,
        targets=[push_target],
        actors={push_monk.actor_id: push_monk, push_target.actor_id: push_target},
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    assert push_target.position == (0.0, 25.0, 0.0)

    lock_monk = _actor("monk_lock", "party")
    lock_monk.level = 5
    lock_monk.traits = {"open hand technique": {}}
    lock_target = _actor("target_lock", "enemy")
    lock_action = ActionDefinition(
        name="flurry_of_blows",
        action_type="attack",
        to_hit=8,
        damage="1",
        tags=["flurry_of_blows", "open_hand_rider:no_reactions"],
    )
    damage_dealt, damage_taken, threat_scores, resources_spent = _combat_trackers(
        lock_monk, lock_target
    )
    _execute_action(
        rng=FixedRng([15]),
        actor=lock_monk,
        action=lock_action,
        targets=[lock_target],
        actors={lock_monk.actor_id: lock_monk, lock_target.actor_id: lock_target},
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    assert lock_target.reaction_available is False
    assert "open_hand_no_reactions" in lock_target.conditions


def test_open_hand_reaction_lock_persists_until_later_turn_start() -> None:
    monk = _actor("monk_lock_timing", "party")
    monk.level = 5
    monk.traits = {"open hand technique": {}}
    target = _actor("target_lock_timing", "enemy")
    target.actions = [
        ActionDefinition(
            name="riposte",
            action_type="attack",
            action_cost="reaction",
            to_hit=0,
            damage="1",
        )
    ]
    lock_action = ActionDefinition(
        name="flurry_of_blows",
        action_type="attack",
        to_hit=8,
        damage="1",
        tags=["flurry_of_blows", "open_hand_rider:no_reactions"],
    )
    damage_dealt, damage_taken, threat_scores, resources_spent = _combat_trackers(monk, target)

    _execute_action(
        rng=FixedRng([15]),
        actor=monk,
        action=lock_action,
        targets=[target],
        actors={monk.actor_id: monk, target.actor_id: target},
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    target.reaction_available = True
    _tick_conditions_for_actor(random.Random(1), target, boundary="turn_start")
    assert "open_hand_no_reactions" in target.conditions
    assert _action_available(target, target.actions[0]) is False

    target.reaction_available = True
    _tick_conditions_for_actor(random.Random(2), target, boundary="turn_start")
    assert "open_hand_no_reactions" not in target.conditions
    assert _action_available(target, target.actions[0]) is True
