from __future__ import annotations

import random
from pathlib import Path

from dnd_sim.engine import (
    _break_concentration,
    _execute_action,
    _resolve_targets_for_action,
    run_simulation,
)
from dnd_sim.io import ActionConfig, load_character_db, load_scenario
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.spatial import AABB
from dnd_sim.strategy_api import BaseStrategy, DeclaredAction, TargetRef, TurnDeclaration
from tests.helpers import build_character, build_enemy
from tests.test_engine_integration import _setup_env


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self.values:
            raise AssertionError("RNG exhausted")
        return self.values.pop(0)


def _actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=30,
        hp=30,
        temp_hp=0,
        ac=12,
        initiative_mod=1,
        str_mod=0,
        dex_mod=1,
        con_mod=0,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 0, "dex": 1, "con": 0, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def _trackers(
    *actors: ActorRuntimeState,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    return (
        {actor.actor_id: 0 for actor in actors},
        {actor.actor_id: 0 for actor in actors},
        {actor.actor_id: 0 for actor in actors},
        {actor.actor_id: {} for actor in actors},
    )


class _Spl04SpellFamilyStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        enemies = [
            entry for entry in state.actors.values() if entry.team != actor.team and entry.hp > 0
        ]
        enemy_id = enemies[0].actor_id if enemies else None

        if actor.actor_id == "hero":
            if "hero_wolf" not in state.actors and "hero_hawk" not in state.actors:
                return TurnDeclaration(action=DeclaredAction(action_name="summon_wolf"))
            if "hero_wolf" in state.actors:
                return TurnDeclaration(action=DeclaredAction(action_name="conjure_hawk"))
            if "hero_hawk" in state.actors and "beast_form" not in actor.conditions:
                return TurnDeclaration(action=DeclaredAction(action_name="beast_shape"))
            if enemy_id is not None:
                return TurnDeclaration(
                    action=DeclaredAction(
                        action_name="basic",
                        targets=[TargetRef(actor_id=enemy_id)],
                    )
                )
            return TurnDeclaration()

        if actor.actor_id == "hero_wolf" and enemy_id is not None:
            return TurnDeclaration(
                action=DeclaredAction(
                    action_name="hero_wolf_attack",
                    targets=[TargetRef(actor_id=enemy_id)],
                )
            )
        if actor.actor_id == "hero_hawk" and enemy_id is not None:
            return TurnDeclaration(
                action=DeclaredAction(
                    action_name="hero_hawk_attack",
                    targets=[TargetRef(actor_id=enemy_id)],
                )
            )
        return None


class _NoOpStrategy(BaseStrategy):
    def declare_turn(self, _actor, _state):
        return TurnDeclaration()


def test_transform_effect_applies_and_clears_with_concentration_dependency() -> None:
    caster = _actor(actor_id="caster", team="party")
    target = _actor(actor_id="target", team="enemy")
    action = ActionDefinition(
        name="polymorph",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        concentration=True,
        tags=["spell"],
        effects=[
            {
                "effect_type": "transform",
                "target": "target",
                "condition": "polymorphed",
                "duration_rounds": 10,
            }
        ],
    )

    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=random.Random(7),
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

    assert "polymorphed" in target.conditions
    assert caster.concentrating is True
    assert "polymorphed" in caster.concentration_conditions

    _break_concentration(caster, actors, active_hazards)
    assert "polymorphed" not in target.conditions


def test_transform_schema_and_mechanics_validation_accept_transform() -> None:
    action = ActionConfig.model_validate(
        {
            "name": "beast_shape",
            "action_type": "utility",
            "action_cost": "action",
            "target_mode": "single_ally",
            "effects": [
                {
                    "effect_type": "transform",
                    "target": "target",
                    "condition": "beast_form",
                    "duration_rounds": 10,
                }
            ],
        }
    )
    assert action.effects[0].effect_type == "transform"

    legacy_action = ActionConfig.model_validate(
        {
            "name": "legacy_beast_shape",
            "action_type": "utility",
            "action_cost": "action",
            "target_mode": "single_ally",
            "effects": [
                {
                    "effect_type": "shapechange",
                    "target": "target",
                    "condition": "beast_form",
                    "duration_rounds": 10,
                }
            ],
        }
    )
    assert legacy_action.effects[0].effect_type == "transform"

    issues = validate_rule_mechanics_payload(
        kind="spell",
        payload={
            "name": "Beast Shape",
            "type": "spell",
            "mechanics": [
                {
                    "effect_type": "transform",
                    "target": "target",
                    "condition": "beast_form",
                    "duration_rounds": 10,
                }
            ],
        },
    )
    assert issues == []

    legacy_issues = validate_rule_mechanics_payload(
        kind="spell",
        payload={
            "name": "Legacy Beast Shape",
            "type": "spell",
            "mechanics": [
                {
                    "effect_type": "shapechange",
                    "target": "target",
                    "condition": "beast_form",
                    "duration_rounds": 10,
                }
            ],
        },
    )
    assert legacy_issues == []


def test_legacy_shapechange_effect_executes_via_transform_alias() -> None:
    caster = _actor(actor_id="caster", team="party")
    target = _actor(actor_id="target", team="enemy")
    action = ActionDefinition(
        name="legacy_shapechange_spell",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        concentration=True,
        tags=["spell"],
        effects=[
            {
                "effect_type": "shapechange",
                "target": "target",
                "condition": "beast_form",
                "duration_rounds": 10,
            }
        ],
    )
    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)

    _execute_action(
        rng=random.Random(9),
        actor=caster,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert "beast_form" in target.conditions


def test_transform_targeting_line_of_effect_and_suppression_are_enforced() -> None:
    caster = _actor(actor_id="caster", team="party")
    target = _actor(actor_id="target", team="enemy")
    caster.position = (0.0, 0.0, 0.0)
    target.position = (30.0, 0.0, 0.0)
    action = ActionDefinition(
        name="polymorph",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        concentration=True,
        tags=["spell", "requires_sight"],
        range_ft=60,
        effects=[{"effect_type": "transform", "target": "target", "condition": "polymorphed"}],
    )

    actors = {caster.actor_id: caster, target.actor_id: target}
    blockers = [AABB(min_pos=(10.0, -1.0, -1.0), max_pos=(20.0, 1.0, 1.0), cover_level="TOTAL")]
    resolved = _resolve_targets_for_action(
        rng=random.Random(5),
        actor=caster,
        action=action,
        actors=actors,
        requested=[TargetRef(actor_id=target.actor_id)],
        obstacles=blockers,
    )
    assert resolved == []

    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)
    caster.conditions.add("antimagic_suppressed")
    _execute_action(
        rng=random.Random(5),
        actor=caster,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    assert "polymorphed" not in target.conditions

    caster.conditions.clear()
    target.dead = True
    target.hp = 0
    _execute_action(
        rng=random.Random(5),
        actor=caster,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    assert "polymorphed" not in target.conditions


def test_dispel_magic_removes_non_concentration_transform_spell_effect() -> None:
    rng = FixedRng([10])  # 10 + INT 4 => DC 14 success for a 4th-level effect.
    source = _actor(actor_id="source", team="enemy")
    source.int_mod = 3
    dispeller = _actor(actor_id="dispeller", team="party")
    dispeller.int_mod = 4
    victim = _actor(actor_id="victim", team="party")

    transform_spell = ActionDefinition(
        name="beast_hex",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        concentration=False,
        tags=["spell", "spell_level:4"],
        effects=[
            {
                "effect_type": "transform",
                "condition": "beast_form",
                "target": "target",
                "duration_rounds": 10,
                "effect_id": "beast_hex",
            }
        ],
    )
    dispel_magic = ActionDefinition(
        name="dispel_magic",
        action_type="utility",
        action_cost="action",
        target_mode="single_ally",
        tags=["spell", "dispel"],
    )

    actors = {actor.actor_id: actor for actor in (source, dispeller, victim)}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(
        source, dispeller, victim
    )
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=random.Random(11),
        actor=source,
        action=transform_spell,
        targets=[victim],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    assert "beast_form" in victim.conditions

    _execute_action(
        rng=rng,
        actor=dispeller,
        action=dispel_magic,
        targets=[victim],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    assert "beast_form" not in victim.conditions


def test_spl04_integration_spell_family_sequence_is_deterministic(tmp_path: Path) -> None:
    hero = build_character(
        character_id="hero",
        name="Hero",
        max_hp=42,
        ac=15,
        to_hit=6,
        damage="1d8+3",
    )
    hero["spells"] = [
        {
            "name": "summon_wolf",
            "level": 0,
            "action_type": "utility",
            "action_cost": "action",
            "target_mode": "self",
            "concentration": True,
            "mechanics": [
                {
                    "effect_type": "summon",
                    "target": "source",
                    "actor_id": "hero_wolf",
                    "name": "Hero Wolf",
                    "max_hp": 18,
                    "ac": 13,
                    "to_hit": 6,
                    "damage": "1d8+2",
                }
            ],
        },
        {
            "name": "conjure_hawk",
            "level": 0,
            "action_type": "utility",
            "action_cost": "action",
            "target_mode": "self",
            "concentration": True,
            "mechanics": [
                {
                    "effect_type": "conjure",
                    "target": "source",
                    "actor_id": "hero_hawk",
                    "name": "Hero Hawk",
                    "max_hp": 14,
                    "ac": 14,
                    "to_hit": 7,
                    "damage": "1d6+3",
                }
            ],
        },
        {
            "name": "beast_shape",
            "level": 0,
            "action_type": "utility",
            "action_cost": "action",
            "target_mode": "self",
            "concentration": True,
            "mechanics": [
                {
                    "effect_type": "transform",
                    "target": "source",
                    "condition": "beast_form",
                    "duration_rounds": 10,
                }
            ],
        },
    ]
    enemy = build_enemy(
        enemy_id="dummy",
        name="Dummy",
        hp=200,
        ac=11,
        to_hit=0,
        damage="1",
    )

    scenario_path = _setup_env(
        tmp_path / "spl04_spell_family",
        party=[hero],
        enemies=[enemy],
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
        max_rounds=3,
    )
    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = {
        "party_strategy": _Spl04SpellFamilyStrategy(),
        "enemy_strategy": _NoOpStrategy(),
    }

    run_a = run_simulation(loaded, db, {}, registry, trials=1, seed=101, run_id="spl04_a")
    run_b = run_simulation(loaded, db, {}, registry, trials=1, seed=101, run_id="spl04_b")

    trial = run_a.trial_results[0]
    final_party = trial.state_snapshots[-1]["party"]
    assert "hero_wolf" in trial.damage_dealt
    assert "hero_hawk" in trial.damage_dealt
    assert "hero_wolf" not in final_party
    assert "hero_hawk" not in final_party
    assert "beast_form" in final_party["hero"]["conditions"]

    summary_a = run_a.summary.to_dict()
    summary_b = run_b.summary.to_dict()
    summary_a.pop("run_id", None)
    summary_b.pop("run_id", None)
    assert summary_a == summary_b
