from __future__ import annotations

import csv
import json
import sys
import types
from pathlib import Path

from dnd_sim import report as report_cli
from dnd_sim.engine import run_simulation
from dnd_sim.io import load_character_db, load_runtime_scenario, load_strategy_registry
from dnd_sim.reporting import build_report_markdown, generate_plots_from_trials
from tests.helpers import build_character, build_enemy, write_json


def _setup_reporting_fixture(tmp_path: Path) -> Path:
    db_dir = tmp_path / "db" / "characters"
    db_dir.mkdir(parents=True, exist_ok=True)

    character = build_character(
        character_id="hero",
        name="Hero",
        max_hp=30,
        ac=15,
        to_hit=7,
        damage="1d8+4",
        ki=4,
    )
    write_json(
        db_dir / "index.json",
        {
            "characters": [
                {
                    "character_id": "hero",
                    "name": "Hero",
                    "class_level": "Monk 8",
                    "source_pdf": "fixture.pdf",
                }
            ]
        },
    )
    write_json(db_dir / "hero.json", character)

    encounter_dir = tmp_path / "encounters" / "report_case"
    enemy_dir = encounter_dir / "enemies"
    scenario_dir = encounter_dir / "scenarios"
    enemy_dir.mkdir(parents=True, exist_ok=True)
    scenario_dir.mkdir(parents=True, exist_ok=True)

    write_json(
        enemy_dir / "boss.json",
        build_enemy(enemy_id="boss", name="Boss", hp=80, ac=14, to_hit=6, damage="1d10+3"),
    )

    scenario = {
        "scenario_id": "report_case",
        "encounter_id": "report_case",
        "ruleset": "5e-2014",
        "character_db_dir": "../../../db/characters",
        "party": ["hero"],
        "enemies": ["boss"],
        "initiative_mode": "individual",
        "battlefield": {},
        "termination_rules": {
            "party_defeat": "all_unconscious_or_dead",
            "enemy_defeat": "all_dead",
            "max_rounds": 20,
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
        "resource_policy": {
            "mode": "combat_and_utility",
            "burst_round_threshold": 1,
        },
        "assumption_overrides": {
            "party_strategy": "always_use_signature_ability_if_ready",
            "enemy_strategy": "boss_highest_threat_target",
        },
    }
    scenario_path = scenario_dir / "scenario.json"
    scenario_path.write_text(json.dumps(scenario, indent=2), encoding="utf-8")
    return scenario_path


def test_report_contains_required_sections_and_pngs(tmp_path: Path) -> None:
    scenario_path = _setup_reporting_fixture(tmp_path)
    loaded = load_runtime_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    db = load_character_db(Path(loaded.config.character_db_dir))

    artifacts = run_simulation(loaded, db, {}, registry, trials=12, seed=5, run_id="report")
    summary = artifacts.summary.to_dict()

    assert "rounds" in summary
    assert "party_win_rate" in summary

    plot_paths = generate_plots_from_trials(artifacts.trial_results, tmp_path / "plots")
    assert plot_paths
    for file_path in plot_paths.values():
        path = Path(file_path)
        assert path.exists()
        assert path.stat().st_size > 0

    report = build_report_markdown(
        summary=summary,
        run_config={"scenario_id": loaded.config.scenario_id, "seed": 5},
        plot_paths=plot_paths,
    )
    assert "## Scenario Config Snapshot" in report
    assert "## Outcome Overview" in report
    assert "## Per-Combatant Metrics" in report
    assert "## Resource Consumption" in report


def test_report_cli_uses_trial_rows_path_from_run_config(tmp_path: Path, monkeypatch) -> None:
    scenario_path = _setup_reporting_fixture(tmp_path)
    loaded = load_runtime_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    db = load_character_db(Path(loaded.config.character_db_dir))
    artifacts = run_simulation(loaded, db, {}, registry, trials=6, seed=7, run_id="report")

    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(artifacts.summary.to_dict()), encoding="utf-8")

    custom_trial_rows_path = run_dir / "custom_trial_rows.csv"
    rows = [
        {
            "trial_index": trial.trial_index,
            "rounds": trial.rounds,
            "winner": trial.winner,
            "damage_taken": json.dumps(trial.damage_taken, sort_keys=True),
            "damage_dealt": json.dumps(trial.damage_dealt, sort_keys=True),
            "resources_spent": json.dumps(trial.resources_spent, sort_keys=True),
            "downed_counts": json.dumps(trial.downed_counts, sort_keys=True),
            "death_counts": json.dumps(trial.death_counts, sort_keys=True),
            "remaining_hp": json.dumps(trial.remaining_hp, sort_keys=True),
        }
        for trial in artifacts.trial_results
    ]
    with custom_trial_rows_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    run_config = {
        "scenario_id": loaded.config.scenario_id,
        "seed": 7,
        "trial_rows_path": str(custom_trial_rows_path),
    }
    (run_dir / "run_config.json").write_text(json.dumps(run_config), encoding="utf-8")

    out_dir = tmp_path / "report_out"
    monkeypatch.setattr(
        sys,
        "argv",
        ["dnd_sim.report", "--run", str(summary_path), "--out", str(out_dir)],
    )
    report_cli.main()

    assert (out_dir / "plots" / "rounds_histogram.png").exists()
    report_text = (out_dir / "report.md").read_text(encoding="utf-8")
    assert "## Visualizations" in report_text


def test_load_trial_results_supports_parquet_without_engine(tmp_path: Path, monkeypatch) -> None:
    parquet_path = tmp_path / "trial_rows.parquet"
    parquet_path.write_text("placeholder", encoding="utf-8")

    row = {
        "trial_index": 0,
        "rounds": 3,
        "winner": "party",
        "damage_taken": {"hero": 5},
        "damage_dealt": {"hero": 10},
        "resources_spent": {"hero": {"ki": 1}},
        "downed_counts": {"hero": 0},
        "death_counts": {"hero": 0},
        "remaining_hp": {"hero": 12},
    }

    class _FakeFrame:
        def __init__(self, payload):
            self.payload = payload

        def to_dict(self, orient: str) -> list[dict]:
            assert orient == "records"
            return self.payload

    fake_pandas = types.SimpleNamespace(read_parquet=lambda _path: _FakeFrame([row]))
    monkeypatch.setitem(sys.modules, "pandas", fake_pandas)

    results = report_cli._load_trial_results(parquet_path)
    assert len(results) == 1
    assert results[0].winner == "party"
    assert results[0].resources_spent["hero"]["ki"] == 1
