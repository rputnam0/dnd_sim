from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from dnd_sim.engine import TurnDeclarationValidationError, run_simulation
from dnd_sim.engine_runtime import (
    _action_available,
    _build_actor_from_character,
    _execute_action,
    _resolve_targets_for_action,
    _run_opportunity_attacks_for_movement,
)
from dnd_sim.inventory import InventoryItem
from dnd_sim.io import load_character_db, load_runtime_scenario, load_strategy_registry
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.spatial import AABB
from dnd_sim.strategy_api import BaseStrategy, DeclaredAction, TargetRef, TurnDeclaration
from tests.helpers import build_character, build_enemy, with_class_levels, write_json


def _setup_env(
    tmp_path: Path,
    *,
    party: list[dict],
    enemies: list[dict],
    assumption_overrides: dict,
    burst_threshold: int = 3,
    max_rounds: int = 30,
) -> Path:
    db_dir = tmp_path / "db" / "characters"
    db_dir.mkdir(parents=True, exist_ok=True)

    canonical_party: list[dict] = []
    for character in party:
        canonical_party.append(with_class_levels(character))

    index = {
        "characters": [
            {
                "character_id": character["character_id"],
                "name": character["name"],
                "class_levels": character["class_levels"],
                "source_pdf": "fixture.pdf",
            }
            for character in canonical_party
        ]
    }
    write_json(db_dir / "index.json", index)
    for character in canonical_party:
        write_json(db_dir / f"{character['character_id']}.json", character)

    encounter_dir = tmp_path / "encounters" / "fixture"
    enemy_dir = encounter_dir / "enemies"
    scenario_dir = encounter_dir / "scenarios"
    enemy_dir.mkdir(parents=True, exist_ok=True)
    scenario_dir.mkdir(parents=True, exist_ok=True)

    for enemy in enemies:
        write_json(enemy_dir / f"{enemy['identity']['enemy_id']}.json", enemy)

    scenario = {
        "scenario_id": "fixture_scenario",
        "encounter_id": "fixture",
        "ruleset": "5e-2014",
        "character_db_dir": "../../../db/characters",
        "party": [character["character_id"] for character in party],
        "enemies": [enemy["identity"]["enemy_id"] for enemy in enemies],
        "initiative_mode": "individual",
        "battlefield": {},
        "termination_rules": {
            "party_defeat": "all_unconscious_or_dead",
            "enemy_defeat": "all_dead",
            "max_rounds": max_rounds,
        },
        "internal_harness": {"strategy_modules": [
            {
                "name": "focus_fire_lowest_hp",
                "source": "builtin",
                "class_name": "FocusFireLowestHPStrategy",
            },
            {
                "name": "boss_highest_threat_target",
                "source": "builtin",
                "class_name": "BossHighestThreatTargetStrategy",
            },
            {
                "name": "conserve_resources_then_burst",
                "source": "builtin",
                "class_name": "ConserveResourcesThenBurstStrategy",
            },
            {
                "name": "always_use_signature_ability_if_ready",
                "source": "builtin",
                "class_name": "AlwaysUseSignatureAbilityStrategy",
            },
            ]
        },
        "resource_policy": {
            "mode": "combat_and_utility",
            "burst_round_threshold": burst_threshold,
        },
        "assumption_overrides": assumption_overrides,
    }

    scenario_path = scenario_dir / "scenario.json"
    scenario_path.write_text(json.dumps(scenario, indent=2), encoding="utf-8")
    return scenario_path


class DeclaredTacticalChoiceStrategy(BaseStrategy):
    def __init__(self, *, bonus_action_name: str | None):
        self._bonus_action_name = bonus_action_name

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

        bonus_action = None
        if self._bonus_action_name is not None:
            bonus_target_id = (
                actor.actor_id if self._bonus_action_name == "second_wind" else target.actor_id
            )
            bonus_action = DeclaredAction(
                action_name=self._bonus_action_name,
                targets=[TargetRef(actor_id=bonus_target_id)],
            )

        return TurnDeclaration(
            movement_path=[actor.position, move_to],
            action=DeclaredAction(
                action_name="basic",
                targets=[TargetRef(actor_id=target.actor_id)],
            ),
            bonus_action=bonus_action,
            rationale={"tactical_choices": {"bonus_action": self._bonus_action_name}},
        )


class DeclaredMonkFlurryPlanStrategy(BaseStrategy):
    def __init__(self, *, include_action: bool, bonus_action_name: str = "flurry_of_blows"):
        self._include_action = include_action
        self._bonus_action_name = bonus_action_name

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

        action = None
        if self._include_action:
            action = DeclaredAction(
                action_name="basic",
                targets=[TargetRef(actor_id=target.actor_id)],
            )

        return TurnDeclaration(
            movement_path=[actor.position, move_to],
            action=action,
            bonus_action=DeclaredAction(
                action_name=self._bonus_action_name,
                targets=[TargetRef(actor_id=target.actor_id)],
            ),
        )


def test_fixed_seed_is_deterministic(tmp_path: Path) -> None:
    party = [
        build_character(
            character_id="hero",
            name="Hero",
            max_hp=28,
            ac=15,
            to_hit=7,
            damage="1d8+4",
        )
    ]
    enemies = [build_enemy(enemy_id="boss", name="Boss", hp=40, ac=13, to_hit=5, damage="1d10+3")]

    scenario_path = _setup_env(
        tmp_path,
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
    )

    loaded = load_runtime_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    db = load_character_db(Path(loaded.config.character_db_dir))

    run_a = run_simulation(
        loaded, db, {}, registry, trials=30, seed=9, run_id="a"
    ).summary.to_dict()
    run_b = run_simulation(
        loaded, db, {}, registry, trials=30, seed=9, run_id="b"
    ).summary.to_dict()

    run_a.pop("run_id", None)
    run_b.pop("run_id", None)
    assert run_a == run_b


def test_run_simulation_rejects_non_positive_trials(tmp_path: Path) -> None:
    party = [build_character("hero", "Hero", 28, 15, 7, "1d8+4")]
    enemies = [build_enemy(enemy_id="boss", name="Boss", hp=40, ac=13, to_hit=5, damage="1d10+3")]
    scenario_path = _setup_env(
        tmp_path,
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
    )

    loaded = load_runtime_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    db = load_character_db(Path(loaded.config.character_db_dir))

    with pytest.raises(ValueError, match="trials must be >= 1"):
        run_simulation(loaded, db, {}, registry, trials=0, seed=9, run_id="invalid")


def test_n_vs_n_runs_with_all_combatants_present(tmp_path: Path) -> None:
    party = [
        build_character("alpha", "Alpha", 32, 16, 7, "1d8+4"),
        build_character("bravo", "Bravo", 26, 14, 6, "1d6+4"),
    ]
    enemies = [
        build_enemy(enemy_id="ogre", name="Ogre", hp=50, ac=12, to_hit=6, damage="2d8+3"),
        build_enemy(enemy_id="mage", name="Mage", hp=24, ac=12, to_hit=5, damage="2d6+2"),
    ]

    scenario_path = _setup_env(
        tmp_path,
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
    )
    loaded = load_runtime_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    db = load_character_db(Path(loaded.config.character_db_dir))

    artifacts = run_simulation(loaded, db, {}, registry, trials=20, seed=3, run_id="n2")
    actor_ids = set(artifacts.summary.per_actor_damage_taken.keys())
    assert actor_ids == {"alpha", "bravo", "ogre", "mage"}
    assert artifacts.summary.rounds.mean > 0


def test_resource_policy_changes_resource_usage(tmp_path: Path) -> None:
    party = [
        build_character(
            character_id="monk",
            name="Monk",
            max_hp=36,
            ac=16,
            to_hit=7,
            damage="1d8+4",
            ki=8,
        )
    ]
    enemies = [build_enemy(enemy_id="tank", name="Tank", hp=120, ac=15, to_hit=6, damage="1d10+3")]

    scenario_always = _setup_env(
        tmp_path / "always",
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "always_use_signature_ability_if_ready",
            "enemy_strategy": "boss_highest_threat_target",
        },
        burst_threshold=2,
    )
    loaded_always = load_runtime_scenario(scenario_always)
    db_always = load_character_db(Path(loaded_always.config.character_db_dir))
    reg_always = load_strategy_registry(loaded_always)
    always_summary = run_simulation(
        loaded_always,
        db_always,
        {},
        reg_always,
        trials=40,
        seed=11,
        run_id="always",
    ).summary.to_dict()

    scenario_conserve = _setup_env(
        tmp_path / "conserve",
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "conserve_resources_then_burst",
            "enemy_strategy": "boss_highest_threat_target",
        },
        burst_threshold=99,
    )
    loaded_conserve = load_runtime_scenario(scenario_conserve)
    db_conserve = load_character_db(Path(loaded_conserve.config.character_db_dir))
    reg_conserve = load_strategy_registry(loaded_conserve)
    conserve_summary = run_simulation(
        loaded_conserve,
        db_conserve,
        {},
        reg_conserve,
        trials=40,
        seed=11,
        run_id="conserve",
    ).summary.to_dict()

    always_ki = always_summary["per_actor_resources_spent"]["monk"]["ki"]["mean"]
    conserve_ki = conserve_summary["per_actor_resources_spent"]["monk"]["ki"]["mean"]
    assert always_ki > conserve_ki


def test_two_weapon_legacy_strategy_does_not_auto_spend_offhand_bonus_action(
    tmp_path: Path,
) -> None:
    def build_dual_wielder(character_id: str, *, include_offhand: bool) -> dict:
        fighter = build_character(
            character_id=character_id,
            name=character_id,
            max_hp=45,
            ac=16,
            to_hit=9,
            damage="1d1+4",
            damage_type="piercing",
        )
        fighter["class_level"] = "Fighter 5"
        fighter["class_levels"] = {"fighter": 5}
        fighter["ability_scores"]["str"] = 10
        fighter["ability_scores"]["dex"] = 18
        fighter["save_mods"]["str"] = 0
        fighter["save_mods"]["dex"] = 4
        fighter["traits"] = ["Extra Attack"]
        fighter["attacks"] = [
            {
                "attack_profile_id": f"{character_id}_main_profile",
                "weapon_id": f"{character_id}_main_weapon",
                "item_id": f"{character_id}_main_item",
                "name": "Mainhand Shortsword",
                "to_hit": 9,
                "damage": "1d1+4",
                "damage_type": "piercing",
                "weapon_properties": ["light", "finesse"],
            }
        ]
        if include_offhand:
            fighter["attacks"].append(
                {
                    "attack_profile_id": f"{character_id}_off_profile",
                    "weapon_id": f"{character_id}_off_weapon",
                    "item_id": f"{character_id}_off_item",
                    "name": "Offhand Dagger",
                    "to_hit": 9,
                    "damage": "1d1+4",
                    "damage_type": "piercing",
                    "weapon_properties": ["light", "finesse"],
                }
            )
        return fighter

    def run_one_round_damage(character: dict, run_label: str) -> float:
        enemies = [build_enemy(enemy_id="dummy", name="Dummy", hp=400, ac=5, to_hit=0, damage="1")]
        scenario_path = _setup_env(
            tmp_path / run_label,
            party=[character],
            enemies=enemies,
            assumption_overrides={
                "party_strategy": "focus_fire_lowest_hp",
                "enemy_strategy": "boss_highest_threat_target",
            },
        )
        payload = json.loads(scenario_path.read_text(encoding="utf-8"))
        payload["termination_rules"]["max_rounds"] = 1
        scenario_path.write_text(json.dumps(payload), encoding="utf-8")

        loaded = load_runtime_scenario(scenario_path)
        registry = load_strategy_registry(loaded)
        db = load_character_db(Path(loaded.config.character_db_dir))
        summary = run_simulation(
            loaded,
            db,
            {},
            registry,
            trials=120,
            seed=31,
            run_id=run_label,
        ).summary.to_dict()
        return float(summary["per_actor_damage_dealt"][character["character_id"]]["mean"])

    dual_mean = run_one_round_damage(
        build_dual_wielder("dual_wielder", include_offhand=True),
        run_label="dual_wielder",
    )
    single_mean = run_one_round_damage(
        build_dual_wielder("single_weapon", include_offhand=False),
        run_label="single_weapon",
    )

    assert dual_mean == pytest.approx(single_mean, abs=1e-9)


def test_rage_is_not_auto_activated_without_declared_bonus_action(tmp_path: Path) -> None:
    party = [
        {
            "character_id": "barb",
            "name": "Barbarian",
            "class_level": "Barbarian 5",
            "max_hp": 45,
            "ac": 16,
            "speed_ft": 30,
            "ability_scores": {
                "str": 18,
                "dex": 14,
                "con": 16,
                "int": 8,
                "wis": 10,
                "cha": 10,
            },
            "save_mods": {"str": 7, "dex": 2, "con": 6, "int": -1, "wis": 0, "cha": 0},
            "skill_mods": {},
            "attacks": [
                {
                    "name": "Greataxe",
                    "to_hit": 7,
                    "damage": "1d12+4",
                    "damage_type": "slashing",
                }
            ],
            "resources": {"rage": {"max": 1}},
            "traits": ["Rage"],
            "raw_fields": [],
            "source": {"pdf_name": "fixture.pdf"},
        }
    ]
    enemies = [
        {
            "identity": {"enemy_id": "dummy", "name": "Dummy", "team": "enemy"},
            "stat_block": {
                "max_hp": 500,
                "ac": 30,
                "initiative_mod": 0,
                "dex_mod": 0,
                "con_mod": 0,
                "save_mods": {"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
            },
            "actions": [
                {
                    "name": "tap",
                    "action_type": "attack",
                    "to_hit": -2,
                    "damage": "1",
                    "damage_type": "bludgeoning",
                    "attack_count": 1,
                    "resource_cost": {},
                }
            ],
            "bonus_actions": [],
            "reactions": [],
            "legendary_actions": [],
            "lair_actions": [],
            "resources": {},
            "damage_resistances": [],
            "damage_immunities": [],
            "damage_vulnerabilities": [],
            "condition_immunities": [],
            "script_hooks": {},
        }
    ]

    scenario_path = _setup_env(
        tmp_path / "rage_persist",
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
    )
    payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    payload["termination_rules"]["max_rounds"] = 2
    scenario_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = load_strategy_registry(loaded)
    artifacts = run_simulation(
        loaded,
        db,
        {},
        registry,
        trials=1,
        seed=13,
        run_id="rage_persist",
    )

    trial = artifacts.trial_results[0]
    assert trial.rounds == 2
    assert trial.resources_spent["barb"].get("rage", 0) == 0
    assert "raging" not in trial.state_snapshots[-1]["party"]["barb"]["conditions"]


def test_monk_flurry_is_not_auto_spent_without_declared_bonus_action(tmp_path: Path) -> None:
    monk = build_character(
        character_id="monk",
        name="Monk",
        max_hp=38,
        ac=16,
        to_hit=7,
        damage="1d8+4",
        ki=4,
    )
    monk["class_level"] = "Monk 5"
    monk["class_levels"] = {"monk": 5}
    monk["traits"] = ["Extra Attack", "Martial Arts", "Flurry of Blows"]

    enemies = [build_enemy(enemy_id="tank", name="Tank", hp=200, ac=12, to_hit=1, damage="1")]
    scenario_path = _setup_env(
        tmp_path / "monk_flurry",
        party=[monk],
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "always_use_signature_ability_if_ready",
            "enemy_strategy": "boss_highest_threat_target",
        },
    )
    payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    payload["termination_rules"]["max_rounds"] = 1
    scenario_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_runtime_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    db = load_character_db(Path(loaded.config.character_db_dir))
    summary = run_simulation(
        loaded,
        db,
        {},
        registry,
        trials=20,
        seed=83,
        run_id="monk_flurry",
    ).summary.to_dict()

    assert summary["per_actor_resources_spent"]["monk"]["ki"]["mean"] == pytest.approx(0.0)


def test_declared_monk_flurry_requires_attack_action_before_bonus_step(tmp_path: Path) -> None:
    monk = build_character(
        character_id="monk",
        name="Monk",
        max_hp=38,
        ac=16,
        to_hit=7,
        damage="1d8+4",
        ki=2,
    )
    monk["class_level"] = "Monk 5"
    monk["class_levels"] = {"monk": 5}
    monk["traits"] = ["Extra Attack", "Martial Arts", "Flurry of Blows"]

    enemies = [build_enemy(enemy_id="tank", name="Tank", hp=80, ac=12, to_hit=1, damage="1")]
    scenario_path = _setup_env(
        tmp_path / "monk_illegal_bonus",
        party=[monk],
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
        max_rounds=1,
    )

    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        run_simulation(
            loaded,
            db,
            {},
            {
                "party_strategy": DeclaredMonkFlurryPlanStrategy(include_action=False),
                "enemy_strategy": BaseStrategy(),
            },
            trials=1,
            seed=29,
            run_id="monk_illegal_bonus",
        )

    assert exc_info.value.code == "unavailable_action"
    assert exc_info.value.actor_id == "monk"
    assert exc_info.value.field == "bonus_action.action_name"


def test_declared_monk_martial_arts_bonus_requires_attack_action_before_bonus_step(
    tmp_path: Path,
) -> None:
    monk = build_character(
        character_id="monk",
        name="Monk",
        max_hp=38,
        ac=16,
        to_hit=7,
        damage="1d8+4",
        ki=1,
    )
    monk["class_level"] = "Monk 5"
    monk["class_levels"] = {"monk": 5}
    monk["traits"] = ["Extra Attack", "Martial Arts", "Flurry of Blows"]

    enemies = [build_enemy(enemy_id="tank", name="Tank", hp=80, ac=12, to_hit=1, damage="1")]
    scenario_path = _setup_env(
        tmp_path / "monk_illegal_martial_arts_bonus",
        party=[monk],
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
        max_rounds=1,
    )
    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        run_simulation(
            loaded,
            db,
            {},
            {
                "party_strategy": DeclaredMonkFlurryPlanStrategy(
                    include_action=False, bonus_action_name="martial_arts_bonus"
                ),
                "enemy_strategy": BaseStrategy(),
            },
            trials=1,
            seed=43,
            run_id="monk_illegal_martial_arts_bonus",
        )

    assert exc_info.value.code == "unavailable_action"
    assert exc_info.value.actor_id == "monk"
    assert exc_info.value.field == "bonus_action.action_name"

    legal_run = run_simulation(
        loaded,
        db,
        {},
        {
            "party_strategy": DeclaredMonkFlurryPlanStrategy(
                include_action=True, bonus_action_name="martial_arts_bonus"
            ),
            "enemy_strategy": BaseStrategy(),
        },
        trials=1,
        seed=43,
        run_id="monk_legal_martial_arts_bonus",
    )
    assert legal_run.trial_results[0].resources_spent["monk"].get("ki", 0) == 0


def test_declared_monk_flurry_spends_ki_deterministically(tmp_path: Path) -> None:
    monk = build_character(
        character_id="monk",
        name="Monk",
        max_hp=38,
        ac=16,
        to_hit=7,
        damage="1d8+4",
        ki=2,
    )
    monk["class_level"] = "Monk 5"
    monk["class_levels"] = {"monk": 5}
    monk["traits"] = ["Extra Attack", "Martial Arts", "Flurry of Blows"]
    enemies = [build_enemy(enemy_id="tank", name="Tank", hp=200, ac=12, to_hit=1, damage="1")]
    scenario_path = _setup_env(
        tmp_path / "monk_flurry_declared",
        party=[monk],
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
        max_rounds=1,
    )

    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    run_a = run_simulation(
        loaded,
        db,
        {},
        {
            "party_strategy": DeclaredMonkFlurryPlanStrategy(include_action=True),
            "enemy_strategy": BaseStrategy(),
        },
        trials=1,
        seed=77,
        run_id="monk_flurry_a",
    )
    run_b = run_simulation(
        loaded,
        db,
        {},
        {
            "party_strategy": DeclaredMonkFlurryPlanStrategy(include_action=True),
            "enemy_strategy": BaseStrategy(),
        },
        trials=1,
        seed=77,
        run_id="monk_flurry_b",
    )

    assert run_a.trial_results[0].resources_spent["monk"].get("ki", 0) == 1
    assert run_b.trial_results[0].resources_spent["monk"].get("ki", 0) == 1
    summary_a = run_a.summary.to_dict()
    summary_b = run_b.summary.to_dict()
    summary_a.pop("run_id", None)
    summary_b.pop("run_id", None)
    assert summary_a == summary_b


def test_declared_monk_flurry_ki_restores_after_long_rest_between_encounters(
    tmp_path: Path,
) -> None:
    monk = build_character(
        character_id="monk",
        name="Monk",
        max_hp=38,
        ac=16,
        to_hit=7,
        damage="1d8+4",
        ki=1,
    )
    monk["class_level"] = "Monk 5"
    monk["class_levels"] = {"monk": 5}
    monk["traits"] = ["Extra Attack", "Martial Arts", "Flurry of Blows"]
    enemies = [build_enemy(enemy_id="spark", name="Spark", hp=20, ac=10, to_hit=0, damage="0")]

    scenario_path = _setup_env(
        tmp_path / "monk_ki_lifecycle",
        party=[monk],
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
        max_rounds=1,
    )
    payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    payload["enemies"] = []
    payload["encounters"] = [
        {"enemies": ["spark"], "long_rest_after": True, "checkpoint": "after_first"},
        {"enemies": ["spark"], "checkpoint": "after_second"},
    ]
    scenario_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    run = run_simulation(
        loaded,
        db,
        {},
        {
            "party_strategy": DeclaredMonkFlurryPlanStrategy(include_action=True),
            "enemy_strategy": BaseStrategy(),
        },
        trials=1,
        seed=101,
        run_id="monk_ki_lifecycle",
    )
    trial = run.trial_results[0]

    assert trial.rounds == 2
    assert trial.resources_spent["monk"].get("ki", 0) == 2
    assert trial.state_snapshots[0]["party"]["monk"]["resources"]["ki"] == 1
    assert trial.state_snapshots[1]["party"]["monk"]["resources"]["ki"] == 0


def test_legendary_actions_increase_enemy_damage_output(tmp_path: Path) -> None:
    party = [
        build_character(
            character_id="hero",
            name="Hero",
            max_hp=120,
            ac=14,
            to_hit=6,
            damage="1d8+3",
        )
    ]

    enemies_plain = [
        build_enemy(enemy_id="boss", name="Boss", hp=80, ac=13, to_hit=4, damage="1d4+1")
    ]
    scenario_plain = _setup_env(
        tmp_path / "plain",
        party=party,
        enemies=enemies_plain,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
    )
    loaded_plain = load_runtime_scenario(scenario_plain)
    db_plain = load_character_db(Path(loaded_plain.config.character_db_dir))
    reg_plain = load_strategy_registry(loaded_plain)
    plain_summary = run_simulation(
        loaded_plain,
        db_plain,
        {},
        reg_plain,
        trials=30,
        seed=19,
        run_id="plain",
    ).summary.to_dict()

    enemies_legendary = [
        build_enemy(
            enemy_id="boss",
            name="Boss",
            hp=80,
            ac=13,
            to_hit=4,
            damage="1d4+1",
            legendary_to_hit=7,
            legendary_damage="2d8+4",
            legendary_pool=1,
        )
    ]
    scenario_legendary = _setup_env(
        tmp_path / "legendary",
        party=party,
        enemies=enemies_legendary,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
    )
    loaded_legendary = load_runtime_scenario(scenario_legendary)
    db_legendary = load_character_db(Path(loaded_legendary.config.character_db_dir))
    reg_legendary = load_strategy_registry(loaded_legendary)
    legendary_summary = run_simulation(
        loaded_legendary,
        db_legendary,
        {},
        reg_legendary,
        trials=30,
        seed=19,
        run_id="legendary",
    ).summary.to_dict()

    assert (
        legendary_summary["per_actor_damage_dealt"]["boss"]["mean"]
        > plain_summary["per_actor_damage_dealt"]["boss"]["mean"]
    )


def test_legendary_actions_refresh_on_own_turn_before_later_turn_windows(tmp_path: Path) -> None:
    alpha = build_character("alpha", "Alpha", 200, 20, 0, "1")
    alpha["initiative_mod"] = 30
    beta = build_character("beta", "Beta", 200, 20, 0, "1")
    beta["initiative_mod"] = -10
    party = [alpha, beta]

    boss = build_enemy(
        enemy_id="boss",
        name="Boss",
        hp=500,
        ac=30,
        to_hit=100,
        damage="1",
        legendary_to_hit=100,
        legendary_damage="1",
        legendary_pool=1,
    )
    boss["stat_block"]["initiative_mod"] = 10
    boss["actions"] = [
        {
            "name": "basic_pulse",
            "action_type": "save",
            "save_dc": 100,
            "save_ability": "dex",
            "half_on_save": False,
            "damage": "1",
            "damage_type": "force",
            "resource_cost": {},
        }
    ]
    boss["legendary_actions"] = [
        {
            "name": "legendary_pulse",
            "action_type": "save",
            "save_dc": 100,
            "save_ability": "dex",
            "half_on_save": False,
            "damage": "1",
            "damage_type": "force",
            "resource_cost": {},
        }
    ]
    enemies = [boss]

    scenario_path = _setup_env(
        tmp_path / "legendary_refresh_window",
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
        max_rounds=1,
    )
    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = load_strategy_registry(loaded)
    summary = run_simulation(
        loaded,
        db,
        {},
        registry,
        trials=1,
        seed=17,
        run_id="legendary_refresh_window",
    ).summary.to_dict()

    # alpha turn-end legendary + boss main turn + beta turn-end legendary
    assert summary["per_actor_damage_dealt"]["boss"]["mean"] == pytest.approx(3.0)


def test_lair_action_does_not_fire_before_initiative_20_if_lair_actor_is_killed(
    tmp_path: Path,
) -> None:
    striker = build_character("striker", "Striker", 120, 14, 100, "400")
    striker["initiative_mod"] = 30
    party = [striker]

    lair_boss = {
        "identity": {"enemy_id": "lair_boss", "name": "Lair Boss", "team": "enemy"},
        "stat_block": {
            "max_hp": 120,
            "ac": 10,
            "initiative_mod": -5,
            "dex_mod": 0,
            "con_mod": 1,
            "save_mods": {"str": 0, "dex": 0, "con": 1, "int": 0, "wis": 0, "cha": 0},
        },
        "actions": [
            {
                "name": "basic",
                "action_type": "attack",
                "to_hit": 0,
                "damage": "1",
                "damage_type": "slashing",
                "attack_count": 1,
                "resource_cost": {},
            }
        ],
        "bonus_actions": [],
        "reactions": [],
        "legendary_actions": [],
        "lair_actions": [
            {
                "name": "lair_bolt",
                "action_type": "save",
                "save_dc": 100,
                "save_ability": "dex",
                "half_on_save": False,
                "damage": "10",
                "damage_type": "force",
                "resource_cost": {},
            }
        ],
        "resources": {},
        "damage_resistances": [],
        "damage_immunities": [],
        "damage_vulnerabilities": [],
        "condition_immunities": [],
        "script_hooks": {},
    }

    scenario_path = _setup_env(
        tmp_path / "lair_init_20_window",
        party=party,
        enemies=[lair_boss],
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
        max_rounds=1,
    )
    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = load_strategy_registry(loaded)
    summary = run_simulation(
        loaded,
        db,
        {},
        registry,
        trials=1,
        seed=23,
        run_id="lair_init_20_window",
    ).summary.to_dict()

    # The boss dies to the high-initiative striker before initiative count 20.
    assert summary["per_actor_damage_taken"]["striker"]["mean"] == pytest.approx(0.0)


def test_optimal_strategy_uses_resources_for_damage(tmp_path: Path) -> None:
    party = [
        build_character(
            character_id="monk",
            name="Monk",
            max_hp=42,
            ac=16,
            to_hit=7,
            damage="1d8+4",
            ki=6,
        )
    ]
    enemies = [build_enemy(enemy_id="tank", name="Tank", hp=120, ac=15, to_hit=5, damage="1d10+2")]

    scenario_focus = _setup_env(
        tmp_path / "focus",
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
    )
    loaded_focus = load_runtime_scenario(scenario_focus)
    db_focus = load_character_db(Path(loaded_focus.config.character_db_dir))
    reg_focus = load_strategy_registry(loaded_focus)
    focus_summary = run_simulation(
        loaded_focus,
        db_focus,
        {},
        reg_focus,
        trials=40,
        seed=31,
        run_id="focus",
    ).summary.to_dict()

    scenario_optimal = _setup_env(
        tmp_path / "optimal",
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "optimal_expected_damage",
            "enemy_strategy": "boss_highest_threat_target",
        },
    )
    loaded_optimal = load_runtime_scenario(scenario_optimal)
    db_optimal = load_character_db(Path(loaded_optimal.config.character_db_dir))
    reg_optimal = load_strategy_registry(loaded_optimal)
    optimal_summary = run_simulation(
        loaded_optimal,
        db_optimal,
        {},
        reg_optimal,
        trials=40,
        seed=31,
        run_id="optimal",
    ).summary.to_dict()

    assert optimal_summary["per_actor_resources_spent"]["monk"]["ki"]["mean"] > 0.0
    assert (
        optimal_summary["per_actor_damage_dealt"]["monk"]["mean"]
        >= focus_summary["per_actor_damage_dealt"]["monk"]["mean"]
    )


def test_schema_target_mode_all_enemies_hits_each_party_member(tmp_path: Path) -> None:
    party = [
        build_character("alpha", "Alpha", 30, 15, 6, "1d8+3"),
        build_character("bravo", "Bravo", 30, 15, 6, "1d8+3"),
    ]
    enemies = [
        {
            "identity": {"enemy_id": "storm_node", "name": "Storm Node", "team": "enemy"},
            "stat_block": {
                "max_hp": 300,
                "ac": 12,
                "initiative_mod": 100,
                "dex_mod": 0,
                "con_mod": 2,
                "save_mods": {"dex": 0, "con": 2, "wis": 0},
            },
            "actions": [
                {
                    "name": "storm_burst",
                    "action_type": "save",
                    "save_dc": 30,
                    "save_ability": "dex",
                    "half_on_save": False,
                    "damage": "5",
                    "damage_type": "lightning",
                    "target_mode": "all_enemies",
                    "resource_cost": {},
                }
            ],
            "bonus_actions": [],
            "reactions": [],
            "legendary_actions": [],
            "lair_actions": [],
            "resources": {},
            "damage_resistances": [],
            "damage_immunities": [],
            "damage_vulnerabilities": [],
            "condition_immunities": [],
            "script_hooks": {},
        }
    ]

    scenario_path = _setup_env(
        tmp_path / "schema_all_enemies",
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "optimal_expected_damage",
        },
    )
    payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    payload["termination_rules"]["max_rounds"] = 1
    scenario_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = load_strategy_registry(loaded)
    summary = run_simulation(
        loaded,
        db,
        {},
        registry,
        trials=20,
        seed=57,
        run_id="schema_all_enemies",
    ).summary.to_dict()

    assert summary["per_actor_damage_taken"]["alpha"]["mean"] >= 4.5
    assert summary["per_actor_damage_taken"]["bravo"]["mean"] >= 4.5


def test_schema_total_cover_blocks_line_of_effect_for_all_enemies_save(tmp_path: Path) -> None:
    party = [
        build_character("alpha", "Alpha", 30, 15, 6, "1d8+3"),
        build_character("bravo", "Bravo", 30, 15, 6, "1d8+3"),
    ]
    enemies = [
        {
            "identity": {"enemy_id": "storm_node", "name": "Storm Node", "team": "enemy"},
            "stat_block": {
                "max_hp": 300,
                "ac": 12,
                "initiative_mod": 100,
                "dex_mod": 0,
                "con_mod": 2,
                "save_mods": {"dex": 0, "con": 2, "wis": 0},
            },
            "actions": [
                {
                    "name": "storm_burst",
                    "action_type": "save",
                    "save_dc": 30,
                    "save_ability": "dex",
                    "half_on_save": False,
                    "damage": "5",
                    "damage_type": "lightning",
                    "target_mode": "all_enemies",
                    "resource_cost": {},
                }
            ],
            "bonus_actions": [],
            "reactions": [],
            "legendary_actions": [],
            "lair_actions": [],
            "resources": {},
            "damage_resistances": [],
            "damage_immunities": [],
            "damage_vulnerabilities": [],
            "condition_immunities": [],
            "script_hooks": {},
        }
    ]

    scenario_path = _setup_env(
        tmp_path / "schema_total_cover",
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "optimal_expected_damage",
        },
    )
    payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    payload["termination_rules"]["max_rounds"] = 1
    payload["battlefield"] = {
        "obstacles": [
            {
                "min_pos": [-5.0, 10.0, -5.0],
                "max_pos": [5.0, 20.0, 5.0],
                "cover_level": "TOTAL",
            }
        ]
    }
    scenario_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = load_strategy_registry(loaded)
    summary = run_simulation(
        loaded,
        db,
        {},
        registry,
        trials=20,
        seed=59,
        run_id="schema_total_cover",
    ).summary.to_dict()

    assert summary["per_actor_damage_taken"]["alpha"]["mean"] == 0.0
    assert summary["per_actor_damage_taken"]["bravo"]["mean"] == 0.0


def test_schema_effect_damage_and_resource_change_are_tracked(tmp_path: Path) -> None:
    party = [
        build_character(
            character_id="monk",
            name="Monk",
            max_hp=36,
            ac=16,
            to_hit=7,
            damage="1d8+4",
            ki=5,
        )
    ]
    enemies = [
        {
            "identity": {"enemy_id": "drain_node", "name": "Drain Node", "team": "enemy"},
            "stat_block": {
                "max_hp": 150,
                "ac": 12,
                "initiative_mod": 100,
                "dex_mod": 0,
                "con_mod": 2,
                "save_mods": {"dex": 0, "con": 2, "wis": 0},
            },
            "actions": [
                {
                    "name": "essence_drain",
                    "action_type": "save",
                    "save_dc": 30,
                    "save_ability": "wis",
                    "half_on_save": False,
                    "target_mode": "single_enemy",
                    "effects": [
                        {
                            "effect_type": "damage",
                            "apply_on": "save_fail",
                            "target": "target",
                            "damage": "3",
                            "damage_type": "necrotic",
                        },
                        {
                            "effect_type": "resource_change",
                            "apply_on": "save_fail",
                            "target": "target",
                            "resource": "ki",
                            "amount": -1,
                            "min_value": 0,
                        },
                    ],
                    "resource_cost": {},
                }
            ],
            "bonus_actions": [],
            "reactions": [],
            "legendary_actions": [],
            "lair_actions": [],
            "resources": {},
            "damage_resistances": [],
            "damage_immunities": [],
            "damage_vulnerabilities": [],
            "condition_immunities": [],
            "script_hooks": {},
        }
    ]

    scenario_path = _setup_env(
        tmp_path / "schema_effects",
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "optimal_expected_damage",
        },
    )
    payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    payload["termination_rules"]["max_rounds"] = 1
    scenario_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = load_strategy_registry(loaded)
    summary = run_simulation(
        loaded,
        db,
        {},
        registry,
        trials=20,
        seed=58,
        run_id="schema_effects",
    ).summary.to_dict()

    assert summary["per_actor_damage_taken"]["monk"]["mean"] >= 2.5
    assert summary["per_actor_resources_spent"]["monk"]["ki"]["mean"] >= 0.9


def test_trial_rows_include_strategy_decision_rationale_telemetry(tmp_path: Path) -> None:
    party = [build_character("hero", "Hero", 32, 15, 7, "1d8+4", ki=2)]
    enemies = [build_enemy(enemy_id="boss", name="Boss", hp=48, ac=13, to_hit=5, damage="1d8+2")]

    scenario_path = _setup_env(
        tmp_path / "telemetry",
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "optimal_expected_damage",
            "enemy_strategy": "boss_highest_threat_target",
        },
    )
    loaded = load_runtime_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    db = load_character_db(Path(loaded.config.character_db_dir))

    artifacts = run_simulation(
        loaded,
        db,
        {},
        registry,
        trials=2,
        seed=99,
        run_id="telemetry",
    )

    decision_events = [
        event
        for event in artifacts.trial_results[0].telemetry
        if event.get("telemetry_type") == "decision"
    ]
    assert decision_events
    assert "rationale" in decision_events[0]

    row_payload = json.loads(artifacts.trial_rows[0]["telemetry"])
    assert any(event.get("telemetry_type") == "decision" for event in row_payload)


def test_multiattack_sequence_integration_executes_defined_subactions(tmp_path: Path) -> None:
    party = [
        build_character(
            character_id="hero",
            name="Hero",
            max_hp=220,
            ac=15,
            to_hit=1,
            damage="1",
        )
    ]
    enemies = [
        {
            "identity": {"enemy_id": "hydra", "name": "Hydra", "team": "enemy"},
            "stat_block": {
                "max_hp": 200,
                "ac": 14,
                "initiative_mod": 100,
                "dex_mod": 0,
                "con_mod": 2,
                "save_mods": {"dex": 0, "con": 2, "wis": 0},
            },
            "actions": [
                {
                    "name": "multiattack",
                    "action_type": "utility",
                    "target_mode": "single_enemy",
                    "resource_cost": {},
                    "mechanics": [
                        {
                            "effect_type": "attack_sequence",
                            "sequence": [{"action_name": "bite"}, {"action_name": "tail"}],
                        }
                    ],
                },
                {
                    "name": "bite",
                    "action_type": "attack",
                    "to_hit": 100,
                    "damage": "1",
                    "damage_type": "piercing",
                    "attack_count": 1,
                    "resource_cost": {},
                },
                {
                    "name": "tail",
                    "action_type": "attack",
                    "to_hit": 100,
                    "damage": "1",
                    "damage_type": "bludgeoning",
                    "attack_count": 1,
                    "resource_cost": {},
                },
            ],
            "bonus_actions": [],
            "reactions": [],
            "legendary_actions": [],
            "lair_actions": [],
            "resources": {},
            "damage_resistances": [],
            "damage_immunities": [],
            "damage_vulnerabilities": [],
            "condition_immunities": [],
            "script_hooks": {},
        }
    ]

    scenario_path = _setup_env(
        tmp_path / "multiattack_sequence",
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
    )
    payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    payload["termination_rules"]["max_rounds"] = 1
    scenario_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = load_strategy_registry(loaded)
    summary = run_simulation(
        loaded,
        db,
        {},
        registry,
        trials=40,
        seed=77,
        run_id="multiattack_sequence",
    ).summary.to_dict()

    assert summary["per_actor_damage_dealt"]["hydra"]["mean"] >= 1.75


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
        max_hp=60,
        hp=60,
        temp_hp=0,
        ac=10,
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


def _runtime_actor(*, actor_id: str, team: str, hp: int = 30) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=hp,
        hp=hp,
        temp_hp=0,
        ac=13,
        initiative_mod=0,
        str_mod=0,
        dex_mod=2,
        con_mod=1,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 0, "dex": 2, "con": 1, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def _rogue_character_payload(*, level: int, traits: list[str] | None = None) -> dict[str, object]:
    return with_class_levels(
        {
            "character_id": f"rogue_{level}",
            "name": f"Rogue {level}",
            "class_level": f"Rogue {level}",
            "max_hp": 34,
            "ac": 15,
            "speed_ft": 30,
            "ability_scores": {"str": 10, "dex": 18, "con": 14, "int": 12, "wis": 10, "cha": 12},
            "save_mods": {"str": 0, "dex": 6, "con": 2, "int": 1, "wis": 0, "cha": 1},
            "skill_mods": {},
            "attacks": [
                {
                    "name": "Rapier",
                    "to_hit": 10,
                    "damage": "1d1",
                    "damage_type": "piercing",
                    "weapon_properties": ["finesse"],
                }
            ],
            "resources": {},
            "traits": list(traits or []),
            "raw_fields": [],
            "source": {"pdf_name": "fixture.pdf"},
        }
    )


def test_sneak_attack_applies_on_rogue_turn_and_opportunity_attack_enemy_turn() -> None:
    rogue = _actor("rogue", "party")
    ally = _actor("ally", "party")
    enemy = _actor("enemy", "enemy")

    rogue.level = 3
    rogue.traits = {"sneak attack": {}}
    rogue.position = (0.0, 0.0, 0.0)
    ally.position = (5.0, 0.0, 0.0)
    enemy.position = (5.0, 0.0, 0.0)
    rogue.actions = [
        ActionDefinition(
            name="rapier",
            action_type="attack",
            to_hit=10,
            damage="1d1",
            damage_type="piercing",
        )
    ]

    actors = {rogue.actor_id: rogue, ally.actor_id: ally, enemy.actor_id: enemy}
    damage_dealt = {rogue.actor_id: 0, ally.actor_id: 0, enemy.actor_id: 0}
    damage_taken = {rogue.actor_id: 0, ally.actor_id: 0, enemy.actor_id: 0}
    threat_scores = {rogue.actor_id: 0, ally.actor_id: 0, enemy.actor_id: 0}
    resources_spent = {rogue.actor_id: {}, ally.actor_id: {}, enemy.actor_id: {}}

    _execute_action(
        rng=_FixedRng([15, 1, 6, 5]),
        actor=rogue,
        action=rogue.actions[0],
        targets=[enemy],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:rogue",
    )

    _run_opportunity_attacks_for_movement(
        rng=_FixedRng([15, 1, 4, 3]),
        mover=enemy,
        start_pos=(5.0, 0.0, 0.0),
        end_pos=(20.0, 0.0, 0.0),
        movement_path=[(5.0, 0.0, 0.0), (20.0, 0.0, 0.0)],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:enemy",
    )

    # Rogue should land Sneak Attack on own turn (12) and again on enemy turn OA (8).
    assert damage_dealt[rogue.actor_id] == 20
    assert rogue.reaction_available is False


def test_rogue_package_applies_sneak_attack_on_turn_and_enemy_turn_reaction() -> None:
    rogue = _build_actor_from_character(_rogue_character_payload(level=3), traits_db={})
    ally = _actor("ally", "party")
    enemy = _actor("enemy", "enemy")

    rogue.position = (0.0, 0.0, 0.0)
    ally.position = (5.0, 0.0, 0.0)
    enemy.position = (5.0, 0.0, 0.0)
    basic_attack = next(action for action in rogue.actions if action.name == "basic")

    actors = {rogue.actor_id: rogue, ally.actor_id: ally, enemy.actor_id: enemy}
    damage_dealt = {rogue.actor_id: 0, ally.actor_id: 0, enemy.actor_id: 0}
    damage_taken = {rogue.actor_id: 0, ally.actor_id: 0, enemy.actor_id: 0}
    threat_scores = {rogue.actor_id: 0, ally.actor_id: 0, enemy.actor_id: 0}
    resources_spent = {rogue.actor_id: {}, ally.actor_id: {}, enemy.actor_id: {}}

    _execute_action(
        rng=_FixedRng([15, 1, 6, 5]),
        actor=rogue,
        action=basic_attack,
        targets=[enemy],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:rogue",
    )

    _run_opportunity_attacks_for_movement(
        rng=_FixedRng([15, 1, 4, 3]),
        mover=enemy,
        start_pos=(5.0, 0.0, 0.0),
        end_pos=(20.0, 0.0, 0.0),
        movement_path=[(5.0, 0.0, 0.0), (20.0, 0.0, 0.0)],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:enemy",
    )

    assert "sneak attack" in rogue.traits
    assert damage_dealt[rogue.actor_id] == 20
    assert rogue.reaction_available is False


def test_line_of_effect_blocked_prevents_many_spells_even_with_line_of_sight(
    tmp_path: Path,
) -> None:
    party = [build_character("hero", "Hero", 40, 16, 7, "1d8+4")]
    enemies = [
        {
            "identity": {"enemy_id": "mage", "name": "Mage", "team": "enemy"},
            "stat_block": {
                "max_hp": 30,
                "ac": 12,
                "initiative_mod": 100,
                "dex_mod": 1,
                "con_mod": 1,
                "save_mods": {"str": 1, "dex": 1, "con": 1, "wis": 0},
            },
            "actions": [
                {
                    "name": "force_lance",
                    "action_type": "save",
                    "save_dc": 30,
                    "save_ability": "dex",
                    "half_on_save": False,
                    "damage": "8",
                    "damage_type": "force",
                    "target_mode": "single_enemy",
                    "range_ft": 120,
                    "resource_cost": {},
                    "tags": ["spell"],
                }
            ],
            "bonus_actions": [],
            "reactions": [],
            "legendary_actions": [],
            "lair_actions": [],
            "resources": {},
            "damage_resistances": [],
            "damage_immunities": [],
            "damage_vulnerabilities": [],
            "condition_immunities": [],
            "script_hooks": {},
        }
    ]
    scenario_path = _setup_env(
        tmp_path / "line_of_effect_blocked",
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "optimal_expected_damage",
        },
    )
    payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    payload["termination_rules"]["max_rounds"] = 1
    payload["battlefield"] = {
        "light_level": "bright",
        "obstacles": [
            {
                "min_pos": (-1.0, 10.0, -1.0),
                "max_pos": (1.0, 20.0, 1.0),
                "cover_level": "TOTAL",
            }
        ],
    }
    scenario_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = load_strategy_registry(loaded)
    summary = run_simulation(
        loaded,
        db,
        {},
        registry,
        trials=10,
        seed=73,
        run_id="line_of_effect_blocked",
    ).summary.to_dict()

    assert summary["per_actor_damage_taken"]["hero"]["mean"] == 0.0


def test_origin_obstacle_changes_sphere_target_set() -> None:
    caster = _runtime_actor(actor_id="caster", team="party")
    primary = _runtime_actor(actor_id="primary", team="enemy")
    blocked = _runtime_actor(actor_id="blocked", team="enemy")
    side = _runtime_actor(actor_id="side", team="enemy")

    caster.position = (0.0, 0.0, 0.0)
    primary.position = (20.0, 0.0, 0.0)
    blocked.position = (30.0, 0.0, 0.0)
    side.position = (20.0, 10.0, 0.0)

    actors = {a.actor_id: a for a in (caster, primary, blocked, side)}
    action = ActionDefinition(
        name="fireball_like",
        action_type="save",
        save_dc=15,
        save_ability="dex",
        target_mode="single_enemy",
        aoe_type="sphere",
        aoe_size_ft=15,
        tags=["spell"],
    )

    clear_targets = _resolve_targets_for_action(
        rng=random.Random(12),
        actor=caster,
        action=action,
        actors=actors,
        requested=[TargetRef("primary")],
    )
    assert {target.actor_id for target in clear_targets} == {"primary", "blocked", "side"}

    wall = [AABB(min_pos=(24.0, -1.0, -2.0), max_pos=(26.0, 1.0, 2.0), cover_level="TOTAL")]
    blocked_targets = _resolve_targets_for_action(
        rng=random.Random(12),
        actor=caster,
        action=action,
        actors=actors,
        requested=[TargetRef("primary")],
        obstacles=wall,
    )
    assert {target.actor_id for target in blocked_targets} == {"primary", "side"}


def test_same_strategy_different_tactical_offhand_bonus_action_choices_change_damage(
    tmp_path: Path,
) -> None:
    hero = build_character(
        character_id="hero",
        name="Hero",
        max_hp=42,
        ac=16,
        to_hit=8,
        damage="1d8+4",
    )
    hero["traits"] = ["Extra Attack", "Two-Weapon Fighting"]
    hero["attacks"] = [
        {
            "attack_profile_id": "hero_main_profile",
            "weapon_id": "hero_main_weapon",
            "item_id": "hero_main_item",
            "name": "Mainhand Shortsword",
            "to_hit": 8,
            "damage": "1d8+4",
            "damage_type": "slashing",
            "weapon_properties": ["light", "finesse"],
        },
        {
            "attack_profile_id": "hero_off_profile",
            "weapon_id": "hero_off_weapon",
            "item_id": "hero_off_item",
            "name": "Offhand Shortsword",
            "to_hit": 8,
            "damage": "1d6+4",
            "damage_type": "piercing",
            "weapon_properties": ["light", "finesse"],
        },
    ]
    enemies = [build_enemy(enemy_id="boss", name="Boss", hp=500, ac=13, to_hit=5, damage="1d8+2")]

    scenario_path = _setup_env(
        tmp_path / "tactical_offhand",
        party=[hero],
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
    )
    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))

    with_offhand = run_simulation(
        loaded,
        db,
        {},
        {
            "party_strategy": DeclaredTacticalChoiceStrategy(bonus_action_name="off_hand_attack"),
            "enemy_strategy": BaseStrategy(),
        },
        trials=12,
        seed=73,
        run_id="with_offhand",
    ).summary.to_dict()
    without_offhand = run_simulation(
        loaded,
        db,
        {},
        {
            "party_strategy": DeclaredTacticalChoiceStrategy(bonus_action_name=None),
            "enemy_strategy": BaseStrategy(),
        },
        trials=12,
        seed=73,
        run_id="without_offhand",
    ).summary.to_dict()

    assert (
        with_offhand["per_actor_damage_dealt"]["hero"]["mean"]
        > without_offhand["per_actor_damage_dealt"]["hero"]["mean"]
    )


def test_legacy_omitted_bonus_action_remains_unused(tmp_path: Path) -> None:
    hero = build_character(
        character_id="hero",
        name="Hero",
        max_hp=34,
        ac=15,
        to_hit=7,
        damage="1d8+4",
    )
    hero["traits"] = ["Extra Attack", "Second Wind"]

    enemy = build_enemy(enemy_id="boss", name="Boss", hp=80, ac=13, to_hit=20, damage="2")
    enemy["stat_block"]["initiative_mod"] = 100

    scenario_path = _setup_env(
        tmp_path / "omit_bonus",
        party=[hero],
        enemies=[enemy],
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
    )
    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))

    artifacts = run_simulation(
        loaded,
        db,
        {},
        {
            "party_strategy": BaseStrategy(),
            "enemy_strategy": BaseStrategy(),
        },
        trials=1,
        seed=101,
        run_id="omit_bonus",
    )

    assert artifacts.trial_results[0].resources_spent["hero"].get("second_wind", 0) == 0


def test_legacy_strategy_does_not_auto_spend_action_surge(tmp_path: Path) -> None:
    hero = build_character(
        character_id="hero",
        name="Hero",
        max_hp=40,
        ac=16,
        to_hit=8,
        damage="1d8+4",
    )
    hero["traits"] = ["Extra Attack", "Action Surge"]

    enemies = [build_enemy(enemy_id="boss", name="Boss", hp=180, ac=13, to_hit=5, damage="1d8+2")]

    scenario_path = _setup_env(
        tmp_path / "action_surge",
        party=[hero],
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
    )
    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))

    artifacts = run_simulation(
        loaded,
        db,
        {},
        {
            "party_strategy": BaseStrategy(),
            "enemy_strategy": BaseStrategy(),
        },
        trials=1,
        seed=202,
        run_id="action_surge",
    )

    assert artifacts.trial_results[0].resources_spent["hero"].get("action_surge", 0) == 0


def test_ammunition_attack_consumes_ammo_and_becomes_illegal_when_empty() -> None:
    rng = _FixedRng([15, 15, 1, 1])
    archer = _actor("archer", "party")
    target = _actor("target", "enemy")
    target.hp = 99
    target.max_hp = 99

    arrow_attack = ActionDefinition(
        name="longbow_shot",
        action_type="attack",
        action_cost="action",
        target_mode="single_enemy",
        to_hit=5,
        damage="1",
        damage_type="piercing",
        attack_count=2,
        item_id="longbow",
        weapon_properties=["ammunition", "ranged", "two_handed"],
    )
    archer.actions = [arrow_attack]
    archer.inventory.add_item(
        InventoryItem(
            item_id="longbow",
            name="Longbow",
            equip_slots=("main_hand",),
            metadata={"ammo_item_id": "arrows"},
        )
    )
    archer.inventory.add_item(
        InventoryItem(
            item_id="arrows",
            name="Arrows",
            quantity=2,
            metadata={"ammo_type": "arrow"},
        )
    )
    archer.inventory.equip_item("longbow")

    actors = {archer.actor_id: archer, target.actor_id: target}
    damage_dealt = {archer.actor_id: 0, target.actor_id: 0}
    damage_taken = {archer.actor_id: 0, target.actor_id: 0}
    threat_scores = {archer.actor_id: 0, target.actor_id: 0}
    resources_spent = {archer.actor_id: {}, target.actor_id: {}}

    assert _action_available(archer, arrow_attack) is True

    _execute_action(
        rng=rng,
        actor=archer,
        action=arrow_attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert "arrows" not in archer.inventory.items
    assert resources_spent["archer"]["ammo:arrows"] == 2
    assert _action_available(archer, arrow_attack) is False


def test_shield_master_requires_equipped_shield() -> None:
    caster = _actor("caster", "enemy")
    unshielded = _actor("unshielded", "party")
    shielded = _actor("shielded", "party")
    unshielded.traits = {"shield master": {}}
    shielded.traits = {"shield master": {}}
    shielded.inventory.add_item(
        InventoryItem(
            item_id="shield",
            name="Shield",
            equip_slots=("shield",),
            metadata={"armor_type": "shield"},
        )
    )
    shielded.inventory.equip_item("shield")

    action = ActionDefinition(
        name="burning_hands",
        action_type="save",
        save_dc=10,
        save_ability="dex",
        half_on_save=True,
        damage="10",
        damage_type="fire",
    )

    actors = {
        caster.actor_id: caster,
        unshielded.actor_id: unshielded,
        shielded.actor_id: shielded,
    }
    damage_dealt = {caster.actor_id: 0, unshielded.actor_id: 0, shielded.actor_id: 0}
    damage_taken = {caster.actor_id: 0, unshielded.actor_id: 0, shielded.actor_id: 0}
    threat_scores = {caster.actor_id: 0, unshielded.actor_id: 0, shielded.actor_id: 0}
    resources_spent = {caster.actor_id: {}, unshielded.actor_id: {}, shielded.actor_id: {}}

    _execute_action(
        rng=_FixedRng([7]),
        actor=caster,
        action=action,
        targets=[unshielded],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    _execute_action(
        rng=_FixedRng([7]),
        actor=caster,
        action=action,
        targets=[shielded],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert unshielded.hp == unshielded.max_hp - 5
    assert unshielded.reaction_available is True
    assert shielded.hp == shielded.max_hp
    assert shielded.reaction_available is False
