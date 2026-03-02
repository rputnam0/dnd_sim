from __future__ import annotations

import json
from pathlib import Path

import pytest

from dnd_sim.engine import run_simulation
from dnd_sim.io import load_character_db, load_scenario, load_strategy_registry
from tests.helpers import build_character, build_enemy, write_json


def _setup_env(
    tmp_path: Path,
    *,
    party: list[dict],
    enemies: list[dict],
    assumption_overrides: dict,
    burst_threshold: int = 3,
) -> Path:
    db_dir = tmp_path / "db" / "characters"
    db_dir.mkdir(parents=True, exist_ok=True)

    index = {
        "characters": [
            {
                "character_id": character["character_id"],
                "name": character["name"],
                "class_level": character["class_level"],
                "source_pdf": "fixture.pdf",
            }
            for character in party
        ]
    }
    write_json(db_dir / "index.json", index)
    for character in party:
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
        "character_db_dir": str(db_dir),
        "party": [character["character_id"] for character in party],
        "enemies": [enemy["identity"]["enemy_id"] for enemy in enemies],
        "initiative_mode": "individual",
        "battlefield": {},
        "termination_rules": {
            "party_defeat": "all_unconscious_or_dead",
            "enemy_defeat": "all_dead",
            "max_rounds": 30,
        },
        "strategy_modules": [
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
        ],
        "resource_policy": {
            "mode": "combat_and_utility",
            "burst_round_threshold": burst_threshold,
        },
        "assumption_overrides": assumption_overrides,
    }

    scenario_path = scenario_dir / "scenario.json"
    scenario_path.write_text(json.dumps(scenario, indent=2), encoding="utf-8")
    return scenario_path


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

    loaded = load_scenario(scenario_path)
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

    loaded = load_scenario(scenario_path)
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
    loaded = load_scenario(scenario_path)
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
    loaded_always = load_scenario(scenario_always)
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
    loaded_conserve = load_scenario(scenario_conserve)
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
    loaded_plain = load_scenario(scenario_plain)
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
    loaded_legendary = load_scenario(scenario_legendary)
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
    loaded_focus = load_scenario(scenario_focus)
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
    loaded_optimal = load_scenario(scenario_optimal)
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

    loaded = load_scenario(scenario_path)
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

    loaded = load_scenario(scenario_path)
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
    loaded = load_scenario(scenario_path)
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
