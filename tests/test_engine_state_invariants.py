from __future__ import annotations

from pathlib import Path

from dnd_sim.engine_runtime import _break_concentration, _execute_action
from dnd_sim.engine import run_simulation
from dnd_sim.io import load_character_db, load_scenario, load_strategy_registry
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from tests.helpers import build_character, build_enemy
from tests.test_engine_integration import _setup_env


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


def test_break_concentration_removes_condition_and_hazard_effects() -> None:
    caster = _actor("caster", "party")
    target = _actor("target", "enemy")
    caster.position = (0.0, 0.0, 0.0)
    target.position = (10.0, 0.0, 0.0)

    action = ActionDefinition(
        name="hold_person",
        action_type="utility",
        concentration=True,
        tags=["spell"],
        effects=[
            {
                "effect_type": "apply_condition",
                "target": "target",
                "condition": "paralyzed",
                "duration_rounds": 10,
            },
            {
                "effect_type": "hazard",
                "target": "target",
                "hazard_type": "magical_darkness",
                "duration": 10,
                "radius": 15,
            },
        ],
    )

    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt = {caster.actor_id: 0, target.actor_id: 0}
    damage_taken = {caster.actor_id: 0, target.actor_id: 0}
    threat_scores = {caster.actor_id: 0, target.actor_id: 0}
    resources_spent = {caster.actor_id: {}, target.actor_id: {}}
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=FixedRng([10]),
        actor=caster,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert caster.concentrating is True
    assert target.actor_id in caster.concentrated_targets
    assert "paralyzed" in caster.concentration_conditions
    assert "paralyzed" in target.conditions
    assert len(active_hazards) == 1

    _break_concentration(caster, actors, active_hazards)

    assert caster.concentrating is False
    assert not caster.concentrated_targets
    assert not caster.concentration_conditions
    assert "paralyzed" not in target.conditions
    assert active_hazards == []


def test_sneak_attack_applies_once_per_turn_across_multiattack() -> None:
    rogue = _actor("rogue", "party")
    ally = _actor("ally", "party")
    target = _actor("target", "enemy")

    rogue.level = 3
    rogue.traits = {"sneak attack": {}}
    rogue.position = (0.0, 0.0, 0.0)
    ally.position = (10.0, 0.0, 0.0)
    target.position = (10.0, 0.0, 0.0)

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
    )

    # Hit 1: 1d1 + sneak(2d6=11) = 12, Hit 2: 1d1 = 1 => total 13
    assert damage_dealt[rogue.actor_id] == 13
    assert rogue.sneak_attack_used_this_turn is True


def test_sneak_attack_applies_when_advantage_and_disadvantage_cancel() -> None:
    rogue = _actor("rogue", "party")
    ally = _actor("ally", "party")
    target = _actor("target", "enemy")

    rogue.level = 3
    rogue.traits = {"sneak attack": {}}
    rogue.next_attack_advantage = True
    rogue.position = (0.0, 0.0, 0.0)
    ally.position = (5.0, 0.0, 0.0)
    target.position = (5.0, 0.0, 0.0)
    target.conditions.add("dodging")

    action = ActionDefinition(
        name="rapier",
        action_type="attack",
        to_hit=10,
        damage="1d1",
        damage_type="piercing",
    )

    actors = {rogue.actor_id: rogue, ally.actor_id: ally, target.actor_id: target}
    damage_dealt = {rogue.actor_id: 0, ally.actor_id: 0, target.actor_id: 0}
    damage_taken = {rogue.actor_id: 0, ally.actor_id: 0, target.actor_id: 0}
    threat_scores = {rogue.actor_id: 0, ally.actor_id: 0, target.actor_id: 0}
    resources_spent = {rogue.actor_id: {}, ally.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=FixedRng([15, 1, 6, 5]),
        actor=rogue,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    # Base: 1d1=1, Sneak: 2d6=11
    assert damage_dealt[rogue.actor_id] == 12
    assert rogue.sneak_attack_used_this_turn is True


def test_sneak_attack_does_not_use_incapacitated_adjacent_ally() -> None:
    rogue = _actor("rogue", "party")
    ally = _actor("ally", "party")
    target = _actor("target", "enemy")

    rogue.level = 3
    rogue.traits = {"sneak attack": {}}
    rogue.position = (0.0, 0.0, 0.0)
    ally.position = (5.0, 0.0, 0.0)
    ally.conditions.add("incapacitated")
    target.position = (5.0, 0.0, 0.0)

    action = ActionDefinition(
        name="rapier",
        action_type="attack",
        to_hit=10,
        damage="1d1",
        damage_type="piercing",
    )

    actors = {rogue.actor_id: rogue, ally.actor_id: ally, target.actor_id: target}
    damage_dealt = {rogue.actor_id: 0, ally.actor_id: 0, target.actor_id: 0}
    damage_taken = {rogue.actor_id: 0, ally.actor_id: 0, target.actor_id: 0}
    threat_scores = {rogue.actor_id: 0, ally.actor_id: 0, target.actor_id: 0}
    resources_spent = {rogue.actor_id: {}, ally.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=FixedRng([15, 1, 6, 5]),
        actor=rogue,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert damage_dealt[rogue.actor_id] == 1
    assert rogue.sneak_attack_used_this_turn is False


def test_sneak_attack_does_not_apply_to_spell_attack() -> None:
    rogue = _actor("rogue", "party")
    ally = _actor("ally", "party")
    target = _actor("target", "enemy")

    rogue.level = 3
    rogue.traits = {"sneak attack": {}}
    rogue.position = (0.0, 0.0, 0.0)
    ally.position = (10.0, 0.0, 0.0)
    target.position = (10.0, 0.0, 0.0)

    action = ActionDefinition(
        name="fire bolt",
        action_type="attack",
        to_hit=10,
        damage="1d1",
        damage_type="fire",
        range_ft=120,
        tags=["spell"],
    )

    actors = {rogue.actor_id: rogue, ally.actor_id: ally, target.actor_id: target}
    damage_dealt = {rogue.actor_id: 0, ally.actor_id: 0, target.actor_id: 0}
    damage_taken = {rogue.actor_id: 0, ally.actor_id: 0, target.actor_id: 0}
    threat_scores = {rogue.actor_id: 0, ally.actor_id: 0, target.actor_id: 0}
    resources_spent = {rogue.actor_id: {}, ally.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=FixedRng([15, 1, 6, 5]),
        actor=rogue,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert damage_dealt[rogue.actor_id] == 1
    assert rogue.sneak_attack_used_this_turn is False


def test_uncanny_dodge_halves_attack_damage_and_spends_reaction() -> None:
    attacker = _actor("attacker", "enemy")
    rogue = _actor("rogue", "party")
    rogue.traits = {"uncanny dodge": {}}
    attacker.position = (0.0, 0.0, 0.0)
    rogue.position = (5.0, 0.0, 0.0)

    action = ActionDefinition(
        name="longsword",
        action_type="attack",
        to_hit=10,
        damage="1d9",
        damage_type="slashing",
    )

    actors = {attacker.actor_id: attacker, rogue.actor_id: rogue}
    damage_dealt = {attacker.actor_id: 0, rogue.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, rogue.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, rogue.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, rogue.actor_id: {}}

    _execute_action(
        rng=FixedRng([15, 7]),
        actor=attacker,
        action=action,
        targets=[rogue],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert damage_dealt[attacker.actor_id] == 3
    assert damage_taken[rogue.actor_id] == 3
    assert rogue.reaction_available is False


def test_uncanny_dodge_requires_attacker_to_be_seen() -> None:
    attacker = _actor("attacker", "enemy")
    rogue = _actor("rogue", "party")
    rogue.traits = {"uncanny dodge": {}}
    attacker.conditions.add("invisible")
    attacker.position = (0.0, 0.0, 0.0)
    rogue.position = (5.0, 0.0, 0.0)

    action = ActionDefinition(
        name="longsword",
        action_type="attack",
        to_hit=10,
        damage="1d9",
        damage_type="slashing",
    )

    actors = {attacker.actor_id: attacker, rogue.actor_id: rogue}
    damage_dealt = {attacker.actor_id: 0, rogue.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, rogue.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, rogue.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, rogue.actor_id: {}}

    _execute_action(
        rng=FixedRng([15, 5, 7]),
        actor=attacker,
        action=action,
        targets=[rogue],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert damage_dealt[attacker.actor_id] == 7
    assert damage_taken[rogue.actor_id] == 7
    assert rogue.reaction_available is True


def test_evasion_failed_dex_save_takes_half_damage() -> None:
    caster = _actor("caster", "enemy")
    rogue = _actor("rogue", "party")
    rogue.traits = {"evasion": {}}

    action = ActionDefinition(
        name="fireball",
        action_type="save",
        save_dc=20,
        save_ability="dex",
        half_on_save=True,
        damage="9",
        damage_type="fire",
    )

    actors = {caster.actor_id: caster, rogue.actor_id: rogue}
    damage_dealt = {caster.actor_id: 0, rogue.actor_id: 0}
    damage_taken = {caster.actor_id: 0, rogue.actor_id: 0}
    threat_scores = {caster.actor_id: 0, rogue.actor_id: 0}
    resources_spent = {caster.actor_id: {}, rogue.actor_id: {}}

    _execute_action(
        rng=FixedRng([1]),
        actor=caster,
        action=action,
        targets=[rogue],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert damage_dealt[caster.actor_id] == 4
    assert damage_taken[rogue.actor_id] == 4


def test_evasion_does_not_spend_shield_master_reaction_on_success() -> None:
    caster = _actor("caster", "enemy")
    rogue = _actor("rogue", "party")
    rogue.traits = {"evasion": {}, "shield master": {}}

    action = ActionDefinition(
        name="fireball",
        action_type="save",
        save_dc=10,
        save_ability="dex",
        half_on_save=True,
        damage="10",
        damage_type="fire",
    )

    actors = {caster.actor_id: caster, rogue.actor_id: rogue}
    damage_dealt = {caster.actor_id: 0, rogue.actor_id: 0}
    damage_taken = {caster.actor_id: 0, rogue.actor_id: 0}
    threat_scores = {caster.actor_id: 0, rogue.actor_id: 0}
    resources_spent = {caster.actor_id: {}, rogue.actor_id: {}}

    _execute_action(
        rng=FixedRng([7]),
        actor=caster,
        action=action,
        targets=[rogue],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert damage_dealt[caster.actor_id] == 0
    assert damage_taken[rogue.actor_id] == 0
    assert rogue.reaction_available is True


def test_action_surge_resource_spend_is_bounded_per_trial(tmp_path: Path) -> None:
    party = [
        build_character(
            character_id="fighter",
            name="Fighter",
            max_hp=44,
            ac=16,
            to_hit=7,
            damage="1d8+4",
        )
    ]
    party[0]["traits"].append("Action Surge")
    party[0]["resources"]["action_surge"] = {"max": 1}
    enemies = [build_enemy(enemy_id="ogre", name="Ogre", hp=100, ac=13, to_hit=5, damage="1d10+3")]

    scenario_path = _setup_env(
        tmp_path,
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
    )
    loaded = load_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    db = load_character_db(Path(loaded.config.character_db_dir))

    artifacts = run_simulation(loaded, db, {}, registry, trials=1, seed=13, run_id="resource_bound")
    spent = artifacts.trial_results[0].resources_spent["fighter"].get("action_surge", 0)

    assert spent in {0, 1}
