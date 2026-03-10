from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dnd_sim.engine import run_simulation
from dnd_sim.io import load_character_db, load_runtime_scenario, load_strategy_registry
from tests.helpers import build_character, build_enemy, write_json


def _setup_campaign_env(
    tmp_path: Path,
    *,
    party: list[dict[str, Any]],
    enemies: list[dict[str, Any]],
    encounters: list[dict[str, Any]],
    termination_rules: dict[str, Any] | None = None,
    assumption_overrides: dict[str, Any] | None = None,
    exploration: dict[str, Any] | None = None,
    resource_policy: dict[str, Any] | None = None,
) -> Path:
    db_dir = tmp_path / "db" / "characters"
    db_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        db_dir / "index.json",
        {
            "characters": [
                {
                    "character_id": character["character_id"],
                    "name": character["name"],
                    "class_levels": character["class_levels"],
                    "source_pdf": "fixture.pdf",
                }
                for character in party
            ]
        },
    )
    for character in party:
        write_json(db_dir / f"{character['character_id']}.json", character)

    encounter_dir = tmp_path / "encounters" / "campaign_fixture"
    enemy_dir = encounter_dir / "enemies"
    scenario_dir = encounter_dir / "scenarios"
    enemy_dir.mkdir(parents=True, exist_ok=True)
    scenario_dir.mkdir(parents=True, exist_ok=True)
    for enemy in enemies:
        write_json(enemy_dir / f"{enemy['identity']['enemy_id']}.json", enemy)

    scenario = {
        "scenario_id": "campaign_fixture",
        "encounter_id": "campaign_fixture",
        "ruleset": "5e-2014",
        "character_db_dir": "../../../db/characters",
        "party": [character["character_id"] for character in party],
        "enemies": [],
        "encounters": encounters,
        "initiative_mode": "individual",
        "battlefield": {},
        "exploration": exploration or {},
        "termination_rules": termination_rules
        or {
            "party_defeat": "all_unconscious_or_dead",
            "enemy_defeat": "all_dead",
            "max_rounds": 1,
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
                "name": "always_use_signature_ability_if_ready",
                "source": "builtin",
                "class_name": "AlwaysUseSignatureAbilityStrategy",
            },
            ]
        },
        "resource_policy": resource_policy
        or {
            "mode": "combat_and_utility",
            "burst_round_threshold": 1,
        },
        "assumption_overrides": assumption_overrides
        or {
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
    }

    scenario_path = scenario_dir / "scenario.json"
    scenario_path.write_text(json.dumps(scenario, indent=2), encoding="utf-8")
    return scenario_path


def _load_for_run(
    scenario_path: Path,
) -> tuple[Any, dict[str, dict[str, Any]], dict[str, Any]]:
    loaded = load_runtime_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    db = load_character_db(Path(loaded.config.character_db_dir))
    return loaded, db, registry


def test_encounter_arrays_execute_and_short_rests_restore_resources(tmp_path: Path) -> None:
    party = [
        build_character(
            character_id="monk",
            name="Monk",
            max_hp=30,
            ac=16,
            to_hit=7,
            damage="1d8+4",
            ki=1,
        )
    ]
    enemies = [build_enemy(enemy_id="spark", name="Spark", hp=5, ac=20, to_hit=0, damage="0")]
    base_encounters = [{"enemies": ["spark"]}, {"enemies": ["spark"]}]

    no_rest_path = _setup_campaign_env(
        tmp_path / "no_rest",
        party=party,
        enemies=enemies,
        encounters=base_encounters,
        assumption_overrides={
            "party_strategy": "always_use_signature_ability_if_ready",
            "enemy_strategy": "boss_highest_threat_target",
        },
    )
    loaded, db, registry = _load_for_run(no_rest_path)
    no_rest_trial = run_simulation(
        loaded, db, {}, registry, trials=1, seed=7, run_id="no_rest"
    ).trial_results[0]

    rest_path = _setup_campaign_env(
        tmp_path / "with_rest",
        party=party,
        enemies=enemies,
        encounters=[{"enemies": ["spark"], "short_rest_after": True}, {"enemies": ["spark"]}],
        assumption_overrides={
            "party_strategy": "always_use_signature_ability_if_ready",
            "enemy_strategy": "boss_highest_threat_target",
        },
    )
    loaded_rest, db_rest, registry_rest = _load_for_run(rest_path)
    rest_trial = run_simulation(
        loaded_rest, db_rest, {}, registry_rest, trials=1, seed=7, run_id="with_rest"
    ).trial_results[0]

    assert no_rest_trial.rounds == 2
    assert rest_trial.rounds == 2
    assert no_rest_trial.resources_spent["monk"]["ki"] == 1
    assert rest_trial.resources_spent["monk"]["ki"] == 2


def test_conditions_and_hp_persist_between_encounters_with_snapshots(tmp_path: Path) -> None:
    party = [build_character("hero", "Hero", 20, 15, 6, "1d8+3")]
    hexer = {
        "identity": {"enemy_id": "hexer", "name": "Hexer", "team": "enemy"},
        "stat_block": {
            "max_hp": 1,
            "ac": 12,
            "initiative_mod": 100,
            "dex_mod": 0,
            "con_mod": 0,
            "save_mods": {"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        },
        "actions": [
            {
                "name": "toxic_pulse",
                "action_type": "save",
                "save_dc": 30,
                "save_ability": "con",
                "half_on_save": False,
                "damage": "3",
                "damage_type": "poison",
                "target_mode": "all_enemies",
                "effects": [
                    {
                        "effect_type": "apply_condition",
                        "apply_on": "save_fail",
                        "target": "target",
                        "condition": "poisoned",
                        "duration_rounds": 5,
                    }
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
    mop_up = build_enemy(enemy_id="mop_up", name="Mop Up", hp=1, ac=12, to_hit=0, damage="0")

    scenario_path = _setup_campaign_env(
        tmp_path,
        party=party,
        enemies=[hexer, mop_up],
        encounters=[
            {"enemies": ["hexer"], "checkpoint": "after_hex"},
            {"enemies": ["mop_up"], "checkpoint": "after_mop_up"},
        ],
    )
    loaded, db, registry = _load_for_run(scenario_path)
    trial = run_simulation(
        loaded, db, {}, registry, trials=1, seed=11, run_id="persist"
    ).trial_results[0]

    assert len(trial.state_snapshots) == 2
    first = trial.state_snapshots[0]
    second = trial.state_snapshots[1]
    assert first["checkpoint_id"] == "after_hex"
    assert second["checkpoint_id"] == "after_mop_up"
    assert first["party"]["hero"]["hp"] == 17
    assert "poisoned" in first["party"]["hero"]["conditions"]
    assert second["party"]["hero"]["hp"] == 17
    assert "poisoned" in second["party"]["hero"]["conditions"]


def test_long_rest_and_exploration_legs_apply_and_remain_deterministic(tmp_path: Path) -> None:
    party = [build_character("hero", "Hero", 20, 15, 8, "1d8+3", ki=2)]
    toxic_scout = {
        "identity": {"enemy_id": "toxic_scout", "name": "Toxic Scout", "team": "enemy"},
        "stat_block": {
            "max_hp": 1,
            "ac": 12,
            "initiative_mod": 100,
            "dex_mod": 0,
            "con_mod": 0,
            "save_mods": {"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        },
        "actions": [
            {
                "name": "toxic_burst",
                "action_type": "save",
                "save_dc": 30,
                "save_ability": "con",
                "half_on_save": False,
                "damage": "0",
                "damage_type": "poison",
                "target_mode": "all_enemies",
                "effects": [
                    {
                        "effect_type": "apply_condition",
                        "apply_on": "save_fail",
                        "target": "target",
                        "condition": "poisoned",
                        "duration_rounds": 5,
                    },
                    {
                        "effect_type": "damage",
                        "apply_on": "always",
                        "target": "source",
                        "damage": "20",
                        "damage_type": "force",
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
    mop_up = build_enemy(enemy_id="mop_up", name="Mop Up", hp=1, ac=12, to_hit=0, damage="0")

    scenario_path = _setup_campaign_env(
        tmp_path,
        party=party,
        enemies=[toxic_scout, mop_up],
        encounters=[
            {"enemies": ["toxic_scout"], "long_rest_after": True, "checkpoint": "after_scout"},
            {"enemies": ["mop_up"], "checkpoint": "after_mop_up"},
        ],
        exploration={"legs": [{"hp_attrition": 2, "resource_attrition": {"ki": 1}}]},
    )
    loaded, db, registry = _load_for_run(scenario_path)
    trial_a = run_simulation(
        loaded, db, {}, registry, trials=1, seed=17, run_id="long_rest_exploration_a"
    ).trial_results[0]
    trial_b = run_simulation(
        loaded, db, {}, registry, trials=1, seed=17, run_id="long_rest_exploration_b"
    ).trial_results[0]

    first_snapshot = trial_a.state_snapshots[0]
    assert first_snapshot["checkpoint_id"] == "after_scout"
    assert first_snapshot["party"]["hero"]["hp"] == 18
    assert first_snapshot["party"]["hero"]["conditions"] == []
    assert first_snapshot["party"]["hero"]["resources"]["ki"] == 1
    assert trial_a.resources_spent["hero"]["ki"] == 1

    assert trial_a.state_snapshots == trial_b.state_snapshots
    assert trial_a.resources_spent == trial_b.resources_spent
    assert trial_a.remaining_hp == trial_b.remaining_hp


def test_long_rest_after_does_not_restore_dead_party_members(tmp_path: Path) -> None:
    party = [
        build_character("fallen", "Fallen", 10, 15, 6, "1d8+3"),
        build_character("survivor", "Survivor", 30, 15, 6, "1d8+3"),
    ]
    executioner = {
        "identity": {"enemy_id": "executioner", "name": "Executioner", "team": "enemy"},
        "stat_block": {
            "max_hp": 10,
            "ac": 12,
            "initiative_mod": 100,
            "dex_mod": 0,
            "con_mod": 0,
            "save_mods": {"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        },
        "actions": [
            {
                "name": "basic",
                "action_type": "save",
                "save_dc": 30,
                "save_ability": "con",
                "half_on_save": False,
                "damage": "25",
                "damage_type": "necrotic",
                "target_mode": "all_enemies",
                "effects": [
                    {
                        "effect_type": "damage",
                        "apply_on": "always",
                        "target": "source",
                        "damage": "999",
                        "damage_type": "force",
                    }
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
    mop_up = build_enemy(enemy_id="mop_up", name="Mop Up", hp=1, ac=12, to_hit=0, damage="0")

    scenario_path = _setup_campaign_env(
        tmp_path,
        party=party,
        enemies=[executioner, mop_up],
        encounters=[
            {
                "enemies": ["executioner"],
                "long_rest_after": True,
                "checkpoint": "after_executioner",
            },
            {"enemies": ["mop_up"], "checkpoint": "after_mop_up"},
        ],
    )
    loaded, db, registry = _load_for_run(scenario_path)
    trial = run_simulation(
        loaded, db, {}, registry, trials=1, seed=101, run_id="long_rest_dead_guard"
    ).trial_results[0]

    first_snapshot = trial.state_snapshots[0]
    assert first_snapshot["checkpoint_id"] == "after_executioner"
    assert first_snapshot["party"]["fallen"]["dead"] is True
    assert first_snapshot["party"]["fallen"]["hp"] == 0
    assert first_snapshot["party"]["survivor"]["dead"] is False
    assert first_snapshot["party"]["survivor"]["hp"] == 30


def test_party_defeat_rule_variant_any_unconscious_changes_outcome(tmp_path: Path) -> None:
    party = [
        build_character("low", "Low", 5, 15, 6, "1d8+3"),
        build_character("high", "High", 30, 15, 6, "1d8+3"),
    ]
    reaper = {
        "identity": {"enemy_id": "reaper", "name": "Reaper", "team": "enemy"},
        "stat_block": {
            "max_hp": 10,
            "ac": 12,
            "initiative_mod": 100,
            "dex_mod": 0,
            "con_mod": 0,
            "save_mods": {"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        },
        "actions": [
            {
                "name": "sweep_and_burn",
                "action_type": "save",
                "save_dc": 30,
                "save_ability": "dex",
                "half_on_save": False,
                "damage": "10",
                "damage_type": "necrotic",
                "target_mode": "all_enemies",
                "effects": [
                    {
                        "effect_type": "damage",
                        "apply_on": "always",
                        "target": "source",
                        "damage": "20",
                        "damage_type": "force",
                    }
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

    default_path = _setup_campaign_env(
        tmp_path / "default_rule",
        party=party,
        enemies=[reaper],
        encounters=[{"enemies": ["reaper"]}],
    )
    loaded_default, db_default, registry_default = _load_for_run(default_path)
    default_trial = run_simulation(
        loaded_default, db_default, {}, registry_default, trials=1, seed=23, run_id="default"
    ).trial_results[0]

    any_down_path = _setup_campaign_env(
        tmp_path / "any_down_rule",
        party=party,
        enemies=[reaper],
        encounters=[{"enemies": ["reaper"]}],
        termination_rules={
            "party_defeat": "any_unconscious_or_dead",
            "enemy_defeat": "all_dead",
            "max_rounds": 1,
        },
    )
    loaded_any, db_any, registry_any = _load_for_run(any_down_path)
    any_down_trial = run_simulation(
        loaded_any, db_any, {}, registry_any, trials=1, seed=23, run_id="any_down"
    ).trial_results[0]

    assert default_trial.winner == "party"
    assert any_down_trial.winner == "enemy"


def test_custom_enemy_defeat_predicate_drives_branching_and_checkpoints(tmp_path: Path) -> None:
    party = [build_character("hero", "Hero", 20, 15, 6, "1d8+3")]
    kamikaze = {
        "identity": {"enemy_id": "kamikaze", "name": "Kamikaze", "team": "enemy"},
        "stat_block": {
            "max_hp": 8,
            "ac": 12,
            "initiative_mod": 100,
            "dex_mod": 0,
            "con_mod": 0,
            "save_mods": {"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        },
        "actions": [
            {
                "name": "self_destruct",
                "action_type": "save",
                "save_dc": 30,
                "save_ability": "dex",
                "half_on_save": False,
                "damage": "0",
                "damage_type": "force",
                "target_mode": "all_enemies",
                "effects": [
                    {
                        "effect_type": "damage",
                        "apply_on": "always",
                        "target": "source",
                        "damage": "20",
                        "damage_type": "force",
                    }
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
    juggernaut = build_enemy(
        enemy_id="juggernaut",
        name="Juggernaut",
        hp=200,
        ac=20,
        to_hit=0,
        damage="0",
    )
    left_path = build_enemy(
        enemy_id="left_path", name="Left Path", hp=5, ac=12, to_hit=0, damage="0"
    )
    right_path = build_enemy(
        enemy_id="right_path",
        name="Right Path",
        hp=5,
        ac=12,
        to_hit=0,
        damage="0",
    )

    scenario_path = _setup_campaign_env(
        tmp_path,
        party=party,
        enemies=[kamikaze, juggernaut, left_path, right_path],
        encounters=[
            {
                "enemies": ["kamikaze", "juggernaut"],
                "checkpoint": "split",
                "branches": {"party": 2, "default": 1},
            },
            {"enemies": ["left_path"], "checkpoint": "left_path_checkpoint"},
            {"enemies": ["right_path"], "checkpoint": "right_path_checkpoint"},
        ],
        termination_rules={
            "party_defeat": "all_unconscious_or_dead",
            "enemy_defeat": {"metric": "alive_count", "op": "<=", "value": 1},
            "max_rounds": 1,
        },
    )
    loaded, db, registry = _load_for_run(scenario_path)
    trial = run_simulation(
        loaded, db, {}, registry, trials=1, seed=41, run_id="branching"
    ).trial_results[0]

    assert [snap["checkpoint_id"] for snap in trial.state_snapshots] == [
        "split",
        "right_path_checkpoint",
    ]
    assert trial.encounter_outcomes[0]["next_encounter_index"] == 2
