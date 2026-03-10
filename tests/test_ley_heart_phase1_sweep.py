from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "river_line"
    / "encounters"
    / "ley_heart"
    / "tools"
    / "phase1_sweep.py"
)

spec = importlib.util.spec_from_file_location("ley_heart_phase1_sweep", SCRIPT_PATH)
if spec is None or spec.loader is None:  # pragma: no cover
    raise RuntimeError(f"Unable to load module from {SCRIPT_PATH}")
phase1_sweep = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = phase1_sweep
spec.loader.exec_module(phase1_sweep)


def test_phase1_sweep_reads_custom_sim_from_internal_harness() -> None:
    payload = {
        "internal_harness": {
            "custom_sim_settings": {
                "breakpoint_thresholds": [30, 15],
                "boss_phase_1": {"enabled": True},
            }
        },
        "assumption_overrides": {
            "custom_sim": {
                "breakpoint_thresholds": [999, 1],
            }
        },
    }

    result = phase1_sweep._get_internal_custom_sim_settings(payload)

    assert result == {
        "breakpoint_thresholds": [30, 15],
        "boss_phase_1": {"enabled": True},
    }


def test_phase1_sweep_sets_custom_sim_under_internal_harness_only() -> None:
    payload = {
        "scenario_id": "ley_heart_phase_1",
        "assumption_overrides": {"enemy_strategy": "boss_highest_threat_target"},
    }

    phase1_sweep._set_internal_custom_sim_settings(
        payload,
        custom_sim_settings={"pylon_hp": 39, "boss_phase_1": {"enabled": False}},
    )

    assert payload["internal_harness"]["custom_sim_settings"] == {
        "pylon_hp": 39,
        "boss_phase_1": {"enabled": False},
    }
    assert payload["assumption_overrides"] == {"enemy_strategy": "boss_highest_threat_target"}
    assert "custom_sim" not in payload["assumption_overrides"]


def test_phase1_sweep_grid_help_references_internal_harness_path() -> None:
    parser = phase1_sweep.build_parser()
    grid_action = next(action for action in parser._actions if action.dest == "grid")

    assert "internal_harness.custom_sim_settings" in grid_action.help
