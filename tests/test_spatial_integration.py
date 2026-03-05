from __future__ import annotations

from dnd_sim.engine_runtime import _execute_action
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.spatial import AABB


class CountingRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)
        self.calls = 0

    def randint(self, _a: int, _b: int) -> int:
        self.calls += 1
        if not self.values:
            raise AssertionError("RNG exhausted in test")
        return self.values.pop(0)


def _runtime_actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=30,
        hp=30,
        temp_hp=0,
        ac=15,
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


def test_attack_loop_unseen_attacker_unseen_target_cancels_to_single_roll() -> None:
    attacker = _runtime_actor(actor_id="attacker", team="party")
    target = _runtime_actor(actor_id="target", team="enemy")
    attacker.position = (0.0, 0.0, 0.0)
    target.position = (10.0, 0.0, 0.0)

    action = ActionDefinition(
        name="longbow",
        action_type="attack",
        to_hit=0,
        damage="1d8",
        damage_type="piercing",
        range_ft=150,
    )

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt = {attacker.actor_id: 0, target.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, target.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, target.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, target.actor_id: {}}

    rng = CountingRng([2, 20, 8])
    _execute_action(
        rng=rng,
        actor=attacker,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[{"type": "magical_darkness", "position": (5.0, 0.0, 0.0), "radius": 20.0}],
    )

    assert rng.calls == 1
    assert target.hp == 30
    assert damage_dealt[attacker.actor_id] == 0


def test_cover_half_applies_ac_bonus_in_attack_resolution() -> None:
    attacker = _runtime_actor(actor_id="attacker", team="party")
    target = _runtime_actor(actor_id="target", team="enemy")
    attacker.position = (0.0, 0.0, 0.0)
    target.position = (30.0, 0.0, 0.0)

    action = ActionDefinition(
        name="longbow",
        action_type="attack",
        to_hit=5,
        damage="1d8",
        damage_type="piercing",
        range_ft=150,
    )

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt = {attacker.actor_id: 0, target.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, target.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, target.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=CountingRng([10]),
        actor=attacker,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        obstacles=[AABB(min_pos=(10.0, -1.0, -1.0), max_pos=(20.0, 1.0, 1.0), cover_level="HALF")],
    )

    assert target.hp == 30
    assert damage_dealt[attacker.actor_id] == 0
