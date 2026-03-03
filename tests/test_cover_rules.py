from __future__ import annotations

from dnd_sim.engine import _execute_action, _resolve_targets_for_action
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.spatial import AABB
from dnd_sim.strategy_api import TargetRef


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
        save_mods={"str": 2, "dex": 0, "con": 2, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def _fresh_trackers(
    attacker: ActorRuntimeState, target: ActorRuntimeState
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    damage_dealt = {attacker.actor_id: 0, target.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, target.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, target.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, target.actor_id: {}}
    return damage_dealt, damage_taken, threat_scores, resources_spent


def test_cover_half_grants_attack_ac_bonus() -> None:
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
        target_mode="single_enemy",
        range_ft=150,
    )

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _fresh_trackers(attacker, target)

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


def test_cover_half_grants_dex_save_bonus() -> None:
    caster = _runtime_actor(actor_id="caster", team="party")
    target = _runtime_actor(actor_id="target", team="enemy")
    caster.position = (0.0, 0.0, 0.0)
    target.position = (30.0, 0.0, 0.0)
    action = ActionDefinition(
        name="burning_hands",
        action_type="save",
        save_dc=15,
        save_ability="dex",
        half_on_save=False,
        damage="6",
        damage_type="fire",
        target_mode="single_enemy",
    )

    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _fresh_trackers(caster, target)

    _execute_action(
        rng=CountingRng([14]),
        actor=caster,
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
    assert damage_dealt[caster.actor_id] == 0


def test_no_cover_dex_save_gets_no_bonus() -> None:
    caster = _runtime_actor(actor_id="caster", team="party")
    target = _runtime_actor(actor_id="target", team="enemy")
    caster.position = (0.0, 0.0, 0.0)
    target.position = (30.0, 0.0, 0.0)
    action = ActionDefinition(
        name="burning_hands",
        action_type="save",
        save_dc=15,
        save_ability="dex",
        half_on_save=False,
        damage="6",
        damage_type="fire",
        target_mode="single_enemy",
    )

    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _fresh_trackers(caster, target)

    _execute_action(
        rng=CountingRng([14]),
        actor=caster,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        obstacles=[],
    )

    assert target.hp == 24
    assert damage_dealt[caster.actor_id] == 6


def test_total_cover_blocks_line_of_effect_targeting_and_resolution() -> None:
    caster = _runtime_actor(actor_id="caster", team="party")
    target = _runtime_actor(actor_id="target", team="enemy")
    caster.position = (0.0, 0.0, 0.0)
    target.position = (30.0, 0.0, 0.0)
    action = ActionDefinition(
        name="lightning_bolt",
        action_type="save",
        save_dc=15,
        save_ability="dex",
        half_on_save=False,
        damage="6",
        damage_type="lightning",
        target_mode="single_enemy",
    )
    total_cover = [AABB(min_pos=(10.0, -1.0, -1.0), max_pos=(20.0, 1.0, 1.0), cover_level="TOTAL")]
    actors = {caster.actor_id: caster, target.actor_id: target}

    resolved_targets = _resolve_targets_for_action(
        rng=CountingRng([]),
        actor=caster,
        action=action,
        actors=actors,
        requested=[TargetRef(target.actor_id)],
        obstacles=total_cover,
    )
    assert resolved_targets == []

    damage_dealt, damage_taken, threat_scores, resources_spent = _fresh_trackers(caster, target)
    rng = CountingRng([20])
    _execute_action(
        rng=rng,
        actor=caster,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        obstacles=total_cover,
    )

    assert rng.calls == 0
    assert target.hp == 30
    assert damage_dealt[caster.actor_id] == 0
