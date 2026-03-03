from __future__ import annotations

from dnd_sim.engine import (
    _apply_condition,
    _execute_action,
    _remove_condition,
    _saving_throw_succeeds,
    query_attack_condition_modifiers,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState


class _FixedRng:
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
        max_hp=30,
        hp=30,
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


def _trackers(
    *actors: ActorRuntimeState,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    damage_dealt = {actor.actor_id: 0 for actor in actors}
    damage_taken = {actor.actor_id: 0 for actor in actors}
    threat_scores = {actor.actor_id: 0 for actor in actors}
    resources_spent = {actor.actor_id: {} for actor in actors}
    return damage_dealt, damage_taken, threat_scores, resources_spent


def test_unit_stunned_grants_advantage_without_forced_critical() -> None:
    attacker = _actor("attacker", "party")
    target = _actor("target", "enemy")
    target.conditions.add("stunned")

    modifiers = query_attack_condition_modifiers(
        attacker=attacker,
        target=target,
        is_melee_attack=True,
        distance_ft=5.0,
    )

    assert modifiers.advantage is True
    assert modifiers.force_critical is False


def test_unit_paralyzed_forces_critical_only_within_five_feet() -> None:
    attacker = _actor("attacker", "party")
    target = _actor("target", "enemy")
    target.conditions.add("paralyzed")

    close_modifiers = query_attack_condition_modifiers(
        attacker=attacker,
        target=target,
        is_melee_attack=True,
        distance_ft=5.0,
    )
    reach_modifiers = query_attack_condition_modifiers(
        attacker=attacker,
        target=target,
        is_melee_attack=True,
        distance_ft=10.0,
    )

    assert close_modifiers.force_critical is True
    assert reach_modifiers.force_critical is False


def test_integration_stunned_target_is_not_auto_crit_on_non_nat20_hit() -> None:
    attacker = _actor("attacker", "party")
    target = _actor("target", "enemy")
    attacker.position = (0.0, 0.0, 0.0)
    target.position = (5.0, 0.0, 0.0)
    target.ac = 10
    target.conditions.add("stunned")
    attack = ActionDefinition(
        name="mace",
        action_type="attack",
        action_cost="action",
        to_hit=5,
        damage="1d4",
        damage_type="bludgeoning",
        reach_ft=5.0,
    )

    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(attacker, target)
    _execute_action(
        rng=_FixedRng([12, 7, 2, 3]),
        actor=attacker,
        action=attack,
        targets=[target],
        actors={attacker.actor_id: attacker, target.actor_id: target},
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.hp == target.max_hp - 2


def test_integration_stunned_target_auto_fails_strength_save() -> None:
    caster = _actor("caster", "enemy")
    target = _actor("target", "party")
    target.conditions.add("stunned")
    target.save_mods["str"] = 12
    action = ActionDefinition(
        name="kinetic_pulse",
        action_type="save",
        action_cost="action",
        damage="3",
        damage_type="force",
        save_dc=20,
        save_ability="str",
        half_on_save=True,
    )

    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)
    _execute_action(
        rng=_FixedRng([20]),
        actor=caster,
        action=action,
        targets=[target],
        actors={caster.actor_id: caster, target.actor_id: target},
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.hp == target.max_hp - 3


def test_negative_prone_does_not_auto_fail_dexterity_saves() -> None:
    target = _actor("target", "party")
    target.conditions.add("prone")
    target.save_mods["dex"] = 2
    resources_spent = {target.actor_id: {}}

    success = _saving_throw_succeeds(
        rng=_FixedRng([18]),
        target=target,
        ability="dex",
        dc=15,
        resources_spent=resources_spent,
    )

    assert success is True


def test_integration_unconscious_applies_prone_and_waking_does_not_clear_prone() -> None:
    target = _actor("target", "party")

    _apply_condition(target, "unconscious", duration_rounds=2)
    assert "unconscious" in target.conditions
    assert "prone" in target.conditions

    _remove_condition(target, "unconscious")
    assert "unconscious" not in target.conditions
    assert "prone" in target.conditions
