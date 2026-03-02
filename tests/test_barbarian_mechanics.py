from __future__ import annotations

import random

from dnd_sim.engine import _execute_action, _find_best_bonus_action, _tick_conditions_for_actor
from dnd_sim.models import ActionDefinition, ActorRuntimeState


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self.values:
            raise AssertionError("RNG exhausted")
        return self.values.pop(0)


def _base_actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=40,
        hp=40,
        temp_hp=0,
        ac=12,
        initiative_mod=2,
        str_mod=0,
        dex_mod=2,
        con_mod=1,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 0, "dex": 0, "con": 1, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def test_rage_lifecycle_activates_and_expires() -> None:
    rng = random.Random(1)
    barbarian = _base_actor(actor_id="barb", team="party")
    barbarian.traits = {"rage": {}}
    barbarian.resources = {"rage": 2}
    barbarian.max_resources = {"rage": 2}

    rage_action = _find_best_bonus_action(barbarian)
    assert rage_action is not None
    assert rage_action.name == "rage_activation"

    damage_dealt = {barbarian.actor_id: 0}
    damage_taken = {barbarian.actor_id: 0}
    threat_scores = {barbarian.actor_id: 0}
    resources_spent = {barbarian.actor_id: {}}
    actors = {barbarian.actor_id: barbarian}
    _execute_action(
        rng=rng,
        actor=barbarian,
        action=rage_action,
        targets=[barbarian],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    assert "raging" in barbarian.conditions

    for _ in range(10):
        _tick_conditions_for_actor(rng, barbarian)
    assert "raging" not in barbarian.conditions


def test_reckless_attack_applies_self_condition_for_enemy_advantage() -> None:
    rng = random.Random(2)
    barbarian = _base_actor(actor_id="barb", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")
    attack = ActionDefinition(
        name="greataxe",
        action_type="attack",
        to_hit=6,
        damage="1d12",
        damage_type="slashing",
        action_cost="action",
        target_mode="single_enemy",
    )
    barbarian.actions = [attack]
    barbarian.traits = {"reckless attack": {}}
    actors = {barbarian.actor_id: barbarian, enemy.actor_id: enemy}
    damage_dealt = {barbarian.actor_id: 0, enemy.actor_id: 0}
    damage_taken = {barbarian.actor_id: 0, enemy.actor_id: 0}
    threat_scores = {barbarian.actor_id: 0, enemy.actor_id: 0}
    resources_spent = {barbarian.actor_id: {}, enemy.actor_id: {}}

    _execute_action(
        rng=rng,
        actor=barbarian,
        action=attack,
        targets=[enemy],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert "reckless_attacking" in barbarian.conditions


def test_danger_sense_grants_advantage_on_dex_saves() -> None:
    rng = FixedRng([1, 1, 5, 16])  # damage rolls then save rolls
    caster = _base_actor(actor_id="caster", team="enemy")
    barbarian = _base_actor(actor_id="barb", team="party")
    barbarian.traits = {"danger sense": {}}
    save_spell = ActionDefinition(
        name="line_blast",
        action_type="save",
        save_dc=15,
        save_ability="dex",
        damage="2d6",
        damage_type="fire",
        half_on_save=False,
        tags=["spell"],
    )

    actors = {caster.actor_id: caster, barbarian.actor_id: barbarian}
    damage_dealt = {caster.actor_id: 0, barbarian.actor_id: 0}
    damage_taken = {caster.actor_id: 0, barbarian.actor_id: 0}
    threat_scores = {caster.actor_id: 0, barbarian.actor_id: 0}
    resources_spent = {caster.actor_id: {}, barbarian.actor_id: {}}

    _execute_action(
        rng=rng,
        actor=caster,
        action=save_spell,
        targets=[barbarian],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert damage_taken[barbarian.actor_id] == 0


def test_brutal_critical_scales_extra_weapon_dice() -> None:
    rng = FixedRng([20, 6, 6, 6, 6])  # crit + four d12 rolls
    barbarian = _base_actor(actor_id="barb", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    barbarian.level = 13
    barbarian.traits = {"brutal critical": {}}
    attack = ActionDefinition(
        name="greataxe",
        action_type="attack",
        to_hit=5,
        damage="1d12",
        damage_type="slashing",
        target_mode="single_enemy",
    )

    actors = {barbarian.actor_id: barbarian, target.actor_id: target}
    damage_dealt = {barbarian.actor_id: 0, target.actor_id: 0}
    damage_taken = {barbarian.actor_id: 0, target.actor_id: 0}
    threat_scores = {barbarian.actor_id: 0, target.actor_id: 0}
    resources_spent = {barbarian.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=rng,
        actor=barbarian,
        action=attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    # Crit doubles weapon dice (2d12) and Brutal Critical at level 13 adds 2d12.
    assert damage_dealt[barbarian.actor_id] == 24
