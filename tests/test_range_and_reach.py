from __future__ import annotations

from dnd_sim.engine_runtime import _execute_action
from dnd_sim.models import ActionDefinition, ActorRuntimeState


class SequenceRng:
    def __init__(self, values: list[int]) -> None:
        self._values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self._values:
            raise AssertionError("RNG exhausted")
        return self._values.pop(0)


class NoRollRng:
    def randint(self, _a: int, _b: int) -> int:
        raise AssertionError("Attack roll should not happen for illegal attacks")


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
        dex_mod=2,
        con_mod=2,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 2, "dex": 2, "con": 2, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def _resources_for(*actors: ActorRuntimeState) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    damage_dealt = {actor.actor_id: 0 for actor in actors}
    damage_taken = {actor.actor_id: 0 for actor in actors}
    threat_scores = {actor.actor_id: 0 for actor in actors}
    resources_spent = {actor.actor_id: {} for actor in actors}
    return damage_dealt, damage_taken, threat_scores, resources_spent


def test_melee_attack_fails_outside_reach() -> None:
    attacker = _actor("attacker", "party")
    target = _actor("target", "enemy")
    attacker.position = (0.0, 0.0, 0.0)
    target.position = (15.0, 0.0, 0.0)
    attacker.speed_ft = 0
    attacker.movement_remaining = 0.0

    attack = ActionDefinition(
        name="glaive",
        action_type="attack",
        action_cost="action",
        to_hit=10,
        damage="1d8",
        damage_type="slashing",
        weapon_properties=["reach"],
        reach_ft=10,
        range_ft=10,
        range_normal_ft=10,
        range_long_ft=10,
    )
    attacker.actions = [attack]

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _resources_for(attacker, target)

    _execute_action(
        rng=NoRollRng(),
        actor=attacker,
        action=attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.hp == target.max_hp
    assert damage_dealt[attacker.actor_id] == 0


def test_ranged_long_range_has_disadvantage_and_beyond_long_is_illegal() -> None:
    attacker = _actor("attacker", "party")
    long_target = _actor("long_target", "enemy")
    far_target = _actor("far_target", "enemy")

    attacker.position = (0.0, 0.0, 0.0)
    long_target.position = (40.0, 0.0, 0.0)
    far_target.position = (70.0, 0.0, 0.0)
    long_target.ac = 13
    attacker.speed_ft = 0
    attacker.movement_remaining = 0.0

    attack = ActionDefinition(
        name="shortbow",
        action_type="attack",
        action_cost="action",
        to_hit=10,
        damage="1d8",
        damage_type="piercing",
        weapon_properties=["ammunition", "ranged"],
        range_ft=20,
        range_normal_ft=20,
        range_long_ft=60,
    )
    attacker.actions = [attack]

    actors = {
        attacker.actor_id: attacker,
        long_target.actor_id: long_target,
        far_target.actor_id: far_target,
    }
    damage_dealt, damage_taken, threat_scores, resources_spent = _resources_for(
        attacker, long_target, far_target
    )

    long_range_rng = SequenceRng([19, 2, 8])
    _execute_action(
        rng=long_range_rng,
        actor=attacker,
        action=attack,
        targets=[long_target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert long_target.hp == long_target.max_hp

    _execute_action(
        rng=NoRollRng(),
        actor=attacker,
        action=attack,
        targets=[far_target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert far_target.hp == far_target.max_hp


def test_ranged_attack_adjacent_hostile_has_disadvantage() -> None:
    attacker = _actor("attacker", "party")
    target = _actor("target", "enemy")
    adjacent_hostile = _actor("adjacent", "enemy")

    attacker.position = (0.0, 0.0, 0.0)
    target.position = (20.0, 0.0, 0.0)
    adjacent_hostile.position = (5.0, 0.0, 0.0)
    target.ac = 13

    attack = ActionDefinition(
        name="shortbow",
        action_type="attack",
        action_cost="action",
        to_hit=10,
        damage="1d8",
        damage_type="piercing",
        weapon_properties=["ammunition", "ranged"],
        range_ft=30,
        range_normal_ft=30,
        range_long_ft=120,
    )
    attacker.actions = [attack]

    actors = {
        attacker.actor_id: attacker,
        target.actor_id: target,
        adjacent_hostile.actor_id: adjacent_hostile,
    }
    damage_dealt, damage_taken, threat_scores, resources_spent = _resources_for(
        attacker, target, adjacent_hostile
    )

    _execute_action(
        rng=SequenceRng([19, 2, 8]),
        actor=attacker,
        action=attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.hp == target.max_hp
    assert damage_dealt[attacker.actor_id] == 0


def test_ranged_attack_in_normal_range_resolves_normally() -> None:
    attacker = _actor("attacker", "party")
    target = _actor("target", "enemy")
    attacker.position = (0.0, 0.0, 0.0)
    target.position = (20.0, 0.0, 0.0)
    target.ac = 13

    attack = ActionDefinition(
        name="shortbow",
        action_type="attack",
        action_cost="action",
        to_hit=10,
        damage="1d8",
        damage_type="piercing",
        weapon_properties=["ammunition", "ranged"],
        range_ft=30,
        range_normal_ft=30,
        range_long_ft=120,
    )
    attacker.actions = [attack]

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _resources_for(attacker, target)

    _execute_action(
        rng=SequenceRng([19, 8]),
        actor=attacker,
        action=attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.hp < target.max_hp
    assert damage_dealt[attacker.actor_id] > 0
