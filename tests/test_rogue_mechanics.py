from __future__ import annotations

from dnd_sim.engine import _execute_action
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
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 2, "dex": 3, "con": 2, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def test_sneak_attack_applies_only_once_when_two_attacks_share_turn_token() -> None:
    rogue = _actor("rogue", "party")
    ally = _actor("ally", "party")
    target = _actor("target", "enemy")

    rogue.level = 3
    rogue.traits = {"sneak attack": {}}
    rogue.position = (0.0, 0.0, 0.0)
    target.position = (30.0, 0.0, 0.0)
    # Keep ally adjacent to the target so Sneak Attack remains legal without
    # forcing ranged-in-melee disadvantage on the rogue.
    ally.position = (25.0, 0.0, 0.0)

    action = ActionDefinition(
        name="shortbow",
        action_type="attack",
        to_hit=10,
        damage="1d1",
        damage_type="piercing",
        range_ft=80,
        attack_count=2,
    )

    actors = {rogue.actor_id: rogue, ally.actor_id: ally, target.actor_id: target}
    damage_dealt = {rogue.actor_id: 0, ally.actor_id: 0, target.actor_id: 0}
    damage_taken = {rogue.actor_id: 0, ally.actor_id: 0, target.actor_id: 0}
    threat_scores = {rogue.actor_id: 0, ally.actor_id: 0, target.actor_id: 0}
    resources_spent = {rogue.actor_id: {}, ally.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=FixedRng([15, 1, 6, 5, 15, 1]),
        actor=rogue,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:rogue",
    )

    # Hit 1: 1d1 + sneak(2d6=11) = 12, Hit 2: 1d1 = 1 => total 13
    assert damage_dealt[rogue.actor_id] == 13
    assert rogue.sneak_attack_used_this_turn is True
