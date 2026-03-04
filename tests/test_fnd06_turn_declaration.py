from __future__ import annotations

import json
from pathlib import Path

import pytest

from dnd_sim.engine import TurnDeclarationValidationError, run_simulation
from dnd_sim.io import load_character_db, load_scenario
from dnd_sim.strategy_api import (
    BaseStrategy,
    DeclaredAction,
    ReactionPolicy,
    TargetRef,
    TurnDeclaration,
    validate_strategy_instance,
)
from tests.helpers import build_enemy, write_json


class LegacyBasicStrategy(BaseStrategy):
    def choose_action(self, actor, state):
        return super().choose_action(actor, state)

    def choose_targets(self, actor, intent, state):
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]
        if not enemies:
            return []
        return [TargetRef(actor_id=enemies[0].actor_id)]


class ExplicitBasicPlanStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()
        target = enemies[0]
        move_to = (
            float(target.position[0]),
            float(target.position[1] - 5.0),
            float(target.position[2]),
        )
        return TurnDeclaration(
            movement_path=[actor.position, move_to],
            action=DeclaredAction(
                action_name="basic",
                targets=[TargetRef(actor_id=target.actor_id)],
            ),
            reaction_policy=ReactionPolicy(mode="auto"),
        )


class IllegalBonusPlanStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()
        target = enemies[0]
        move_to = (
            float(target.position[0]),
            float(target.position[1] - 5.0),
            float(target.position[2]),
        )
        return TurnDeclaration(
            movement_path=[actor.position, move_to],
            action=DeclaredAction(
                action_name="basic",
                targets=[TargetRef(actor_id=target.actor_id)],
            ),
            bonus_action=DeclaredAction(
                action_name="basic",
                targets=[TargetRef(actor_id=target.actor_id)],
            ),
        )


class TurnOnlyNoLegacyFallbackStrategy:
    def declare_turn(self, actor, state):
        return None

    def on_round_start(self, state):
        return None


class MixedModeDeclareTurnNoneStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        return None


class NoTurnNoLegacyStrategy:
    def on_round_start(self, state):
        return None


def _build_action_surge_character(character_id: str) -> dict:
    return {
        "character_id": character_id,
        "name": "Planner",
        "class_level": "Fighter 8",
        "max_hp": 34,
        "ac": 15,
        "speed_ft": 30,
        "ability_scores": {
            "str": 16,
            "dex": 14,
            "con": 14,
            "int": 10,
            "wis": 10,
            "cha": 10,
        },
        "save_mods": {
            "str": 3,
            "dex": 2,
            "con": 2,
            "int": 0,
            "wis": 0,
            "cha": 0,
        },
        "skill_mods": {},
        "attacks": [
            {
                "name": "Longsword",
                "to_hit": 7,
                "damage": "1d8+4",
                "damage_type": "slashing",
            }
        ],
        "resources": {},
        "traits": ["Extra Attack", "Action Surge"],
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }


def _setup_env(tmp_path: Path) -> Path:
    db_dir = tmp_path / "db" / "characters"
    db_dir.mkdir(parents=True, exist_ok=True)

    hero = _build_action_surge_character("hero")
    write_json(
        db_dir / "index.json",
        {
            "characters": [
                {
                    "character_id": "hero",
                    "name": "Planner",
                    "class_level": "Fighter 8",
                    "source_pdf": "fixture.pdf",
                }
            ]
        },
    )
    write_json(db_dir / "hero.json", hero)

    encounter_dir = tmp_path / "encounters" / "fixture"
    enemy_dir = encounter_dir / "enemies"
    scenario_dir = encounter_dir / "scenarios"
    enemy_dir.mkdir(parents=True, exist_ok=True)
    scenario_dir.mkdir(parents=True, exist_ok=True)

    enemy = build_enemy(
        enemy_id="boss",
        name="Boss",
        hp=80,
        ac=13,
        to_hit=5,
        damage="1d8+2",
    )
    write_json(enemy_dir / "boss.json", enemy)

    scenario = {
        "scenario_id": "fnd06_fixture",
        "encounter_id": "fixture",
        "ruleset": "5e-2014",
        "character_db_dir": str(db_dir),
        "party": ["hero"],
        "enemies": ["boss"],
        "initiative_mode": "individual",
        "battlefield": {},
        "termination_rules": {
            "party_defeat": "all_unconscious_or_dead",
            "enemy_defeat": "all_dead",
            "max_rounds": 3,
        },
        "strategy_modules": [],
        "resource_policy": {"mode": "combat_and_utility", "burst_round_threshold": 1},
        "assumption_overrides": {
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
    }
    scenario_path = scenario_dir / "scenario.json"
    scenario_path.write_text(json.dumps(scenario, indent=2), encoding="utf-8")
    return scenario_path


def test_validate_strategy_instance_accepts_declare_turn_without_legacy_fallback() -> None:
    validate_strategy_instance(TurnOnlyNoLegacyFallbackStrategy())


def test_validate_strategy_instance_rejects_missing_declare_turn_and_legacy_fallback() -> None:
    with pytest.raises(ValueError, match="must implement declare_turn"):
        validate_strategy_instance(NoTurnNoLegacyStrategy())


def test_turn_only_strategy_without_legacy_methods_can_noop_turns(tmp_path: Path) -> None:
    scenario_path = _setup_env(tmp_path)
    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))

    registry = {
        "party_strategy": TurnOnlyNoLegacyFallbackStrategy(),
        "enemy_strategy": LegacyBasicStrategy(),
    }
    result = run_simulation(loaded, db, {}, registry, trials=1, seed=23, run_id="noop")

    assert len(result.trial_results) == 1
    assert result.trial_results[0].resources_spent["hero"].get("action_surge", 0) == 0
    hero_decisions = [
        event
        for event in result.trial_results[0].telemetry
        if event.get("telemetry_type") == "decision" and event.get("actor_id") == "hero"
    ]
    assert any(
        event.get("fallback_reason") == "declare_turn_none_no_legacy_fallback"
        for event in hero_decisions
    )


def test_strategy_with_legacy_methods_falls_back_when_declare_turn_returns_none(
    tmp_path: Path,
) -> None:
    scenario_path = _setup_env(tmp_path)
    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))

    noop_registry = {
        "party_strategy": TurnOnlyNoLegacyFallbackStrategy(),
        "enemy_strategy": LegacyBasicStrategy(),
    }
    fallback_registry = {
        "party_strategy": MixedModeDeclareTurnNoneStrategy(),
        "enemy_strategy": LegacyBasicStrategy(),
    }
    noop_result = run_simulation(loaded, db, {}, noop_registry, trials=8, seed=23, run_id="noop")
    fallback_result = run_simulation(
        loaded, db, {}, fallback_registry, trials=8, seed=23, run_id="fallback"
    )

    noop_damage = sum(trial.damage_dealt.get("hero", 0) for trial in noop_result.trial_results)
    fallback_damage = sum(
        trial.damage_dealt.get("hero", 0) for trial in fallback_result.trial_results
    )
    assert noop_damage == 0
    assert fallback_damage > noop_damage


def test_hidden_action_surge_is_removed_for_legacy_and_explicit_turn_plans(
    tmp_path: Path,
) -> None:
    scenario_path = _setup_env(tmp_path)
    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))

    legacy_registry = {
        "party_strategy": LegacyBasicStrategy(),
        "enemy_strategy": LegacyBasicStrategy(),
    }
    legacy = run_simulation(loaded, db, {}, legacy_registry, trials=1, seed=17, run_id="legacy")
    assert legacy.trial_results[0].resources_spent["hero"].get("action_surge", 0) == 0

    explicit_registry = {
        "party_strategy": ExplicitBasicPlanStrategy(),
        "enemy_strategy": LegacyBasicStrategy(),
    }
    run_a = run_simulation(loaded, db, {}, explicit_registry, trials=8, seed=17, run_id="a")
    run_b = run_simulation(loaded, db, {}, explicit_registry, trials=8, seed=17, run_id="b")

    assert run_a.trial_results[0].resources_spent["hero"].get("action_surge", 0) == 0
    summary_a = run_a.summary.to_dict()
    summary_b = run_b.summary.to_dict()
    summary_a.pop("run_id", None)
    summary_b.pop("run_id", None)
    assert summary_a == summary_b


def test_illegal_turn_plan_raises_structured_bonus_action_error(tmp_path: Path) -> None:
    scenario_path = _setup_env(tmp_path)
    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))

    registry = {
        "party_strategy": IllegalBonusPlanStrategy(),
        "enemy_strategy": LegacyBasicStrategy(),
    }
    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        run_simulation(loaded, db, {}, registry, trials=1, seed=29, run_id="illegal")

    assert exc_info.value.code == "illegal_bonus_action"
    assert exc_info.value.actor_id == "hero"
    assert exc_info.value.field == "bonus_action.action_name"
