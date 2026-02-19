from __future__ import annotations

import json
from pathlib import Path

import pytest

from dnd_sim.io import (
    build_run_dir,
    default_results_dir,
    load_custom_simulation_runner,
    load_scenario,
    load_strategy_registry,
)

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_PATH = (
    ROOT / "river_line" / "encounters" / "ley_heart" / "scenarios" / "ley_heart_phase_1.json"
)


def test_load_valid_scenario() -> None:
    loaded = load_scenario(SCENARIO_PATH)
    assert loaded.config.ruleset == "5e-2014"
    assert loaded.config.party
    assert set(loaded.enemies.keys()) == {"past_pylon", "present_pylon", "future_pylon"}


def test_invalid_scenario_schema_has_path_in_error(tmp_path: Path) -> None:
    payload = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    payload["party"] = "not-a-list"

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        load_scenario(invalid_path)

    message = str(exc.value)
    assert "Invalid scenario schema" in message
    assert str(invalid_path) in message


def test_missing_strategy_module_fails_before_simulation(tmp_path: Path) -> None:
    payload = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    payload["strategy_modules"].append(
        {
            "name": "bad_strategy",
            "source": "encounter",
            "module": "missing_module",
            "class_name": "MissingClass",
        }
    )

    base = tmp_path / "encounters" / "x"
    (base / "scenarios").mkdir(parents=True, exist_ok=True)
    (base / "enemies").mkdir(parents=True, exist_ok=True)

    for enemy_id in payload["enemies"]:
        src = ROOT / "river_line" / "encounters" / "ley_heart" / "enemies" / f"{enemy_id}.json"
        (base / "enemies" / f"{enemy_id}.json").write_text(src.read_text(encoding="utf-8"))

    scenario_path = base / "scenarios" / "broken.json"
    scenario_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_scenario(scenario_path)
    with pytest.raises(ValueError) as exc:
        load_strategy_registry(loaded)

    assert "Strategy module file not found" in str(exc.value)


def test_default_results_dir_and_descriptive_folder_name(tmp_path: Path) -> None:
    results_root = default_results_dir()
    assert results_root.as_posix().endswith("/river_line/results")

    run_dir = build_run_dir(tmp_path, "Ley Heart Phase 1 Focus Fire")
    assert run_dir.parent == tmp_path
    assert "ley_heart_phase_1_focus_fire" in run_dir.name
    assert (run_dir / "plots").exists()


def test_load_custom_simulation_runner() -> None:
    loaded = load_scenario(SCENARIO_PATH)
    runner = load_custom_simulation_runner(loaded)
    assert callable(runner)
