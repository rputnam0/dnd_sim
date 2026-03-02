from __future__ import annotations

import json
from pathlib import Path

from dnd_sim.calibration import run_calibration_harness
from tests.helpers import build_character, build_enemy, write_json


def _setup_benchmark_scenario(
    tmp_path: Path,
    *,
    scenario_id: str,
    hero_hp: int,
    hero_damage: str,
    enemy_hp: int,
    enemy_to_hit: int,
    enemy_damage: str,
    max_rounds: int,
    benchmark_expectations: dict,
) -> Path:
    db_dir = tmp_path / "db" / "characters"
    db_dir.mkdir(parents=True, exist_ok=True)
    hero = build_character("hero", "Hero", hero_hp, 14, 5, hero_damage)
    write_json(
        db_dir / "index.json",
        {
            "characters": [
                {
                    "character_id": "hero",
                    "name": "Hero",
                    "class_level": "Fighter 8",
                    "source_pdf": "fixture.pdf",
                }
            ]
        },
    )
    write_json(db_dir / "hero.json", hero)

    encounter_dir = tmp_path / "encounters" / scenario_id
    enemy_dir = encounter_dir / "enemies"
    scenario_dir = encounter_dir / "scenarios"
    enemy_dir.mkdir(parents=True, exist_ok=True)
    scenario_dir.mkdir(parents=True, exist_ok=True)

    enemy = build_enemy(
        enemy_id="boss",
        name="Boss",
        hp=enemy_hp,
        ac=13,
        to_hit=enemy_to_hit,
        damage=enemy_damage,
    )
    enemy["stat_block"]["initiative_mod"] = 100
    write_json(enemy_dir / "boss.json", enemy)

    payload = {
        "scenario_id": scenario_id,
        "encounter_id": scenario_id,
        "ruleset": "5e-2014",
        "character_db_dir": str(db_dir),
        "party": ["hero"],
        "enemies": ["boss"],
        "initiative_mode": "individual",
        "battlefield": {},
        "termination_rules": {
            "party_defeat": "all_unconscious_or_dead",
            "enemy_defeat": "all_dead",
            "max_rounds": max_rounds,
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
        ],
        "resource_policy": {"mode": "combat_and_utility", "burst_round_threshold": 3},
        "assumption_overrides": {
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
            "benchmark_expectations": benchmark_expectations,
        },
    }
    path = scenario_dir / "scenario.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_calibration_harness_reports_passing_benchmark_metrics(tmp_path: Path) -> None:
    scenario_path = _setup_benchmark_scenario(
        tmp_path / "passing",
        scenario_id="benchmark_pass",
        hero_hp=30,
        hero_damage="1d8+4",
        enemy_hp=40,
        enemy_to_hit=5,
        enemy_damage="1d8+2",
        max_rounds=10,
        benchmark_expectations={
            "party_win_rate": {"min": 0.0, "max": 1.0},
            "rounds_mean": {"min": 1.0, "max": 15.0},
        },
    )

    result = run_calibration_harness([scenario_path], trials=4, seed=7)

    assert result["all_passed"] is True
    benchmark = result["benchmarks"][0]
    assert benchmark["scenario_id"] == "benchmark_pass"
    assert benchmark["metrics"]["party_win_rate"]["pass"] is True
    assert benchmark["metrics"]["rounds_mean"]["pass"] is True


def test_calibration_harness_flags_failed_metric_bounds(tmp_path: Path) -> None:
    scenario_path = _setup_benchmark_scenario(
        tmp_path / "failing",
        scenario_id="benchmark_fail",
        hero_hp=8,
        hero_damage="1",
        enemy_hp=80,
        enemy_to_hit=50,
        enemy_damage="20",
        max_rounds=1,
        benchmark_expectations={
            "party_win_rate": {"min": 0.5, "max": 1.0},
        },
    )

    result = run_calibration_harness([scenario_path], trials=4, seed=3)

    assert result["all_passed"] is False
    benchmark = result["benchmarks"][0]
    assert benchmark["metrics"]["party_win_rate"]["pass"] is False
