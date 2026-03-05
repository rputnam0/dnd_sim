from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dnd_sim.replay import (
    build_replay_bundle,
    diff_replay_bundles,
    load_replay_bundle,
    write_replay_bundle,
)
from dnd_sim.replay_schema import REPLAY_BUNDLE_SCHEMA_VERSION


def _sample_summary() -> dict[str, object]:
    return {
        "run_id": "obs06_sample",
        "scenario_id": "fixture_scenario",
        "trials": 2,
        "party_win_rate": 0.5,
        "enemy_win_rate": 0.5,
        "rounds": {"mean": 2.0, "median": 2.0, "p10": 1.0, "p90": 3.0, "p95": 3.0},
    }


def _sample_trials() -> list[dict[str, object]]:
    return [
        {
            "trial_index": 1,
            "rounds": 2,
            "winner": "party",
            "damage_taken": {"hero": 8},
            "damage_dealt": {"hero": 11},
            "resources_spent": {"hero": {"spell_slot_1": 1}},
            "downed_counts": {"hero": 0},
            "death_counts": {"hero": 0},
            "remaining_hp": {"hero": 9},
            "telemetry": [{"telemetry_type": "decision", "round": 1, "actor_id": "hero"}],
            "encounter_outcomes": [{"encounter_index": 0, "winner": "party"}],
            "state_snapshots": [{"round": 1, "party": {"hero": {"hp": 17}}}],
        },
        {
            "trial_index": 0,
            "rounds": 3,
            "winner": "enemy",
            "damage_taken": {"hero": 20},
            "damage_dealt": {"hero": 9},
            "resources_spent": {"hero": {"spell_slot_1": 1}},
            "downed_counts": {"hero": 1},
            "death_counts": {"hero": 0},
            "remaining_hp": {"hero": 0},
            "telemetry": [{"telemetry_type": "action_outcome", "round": 2, "actor_id": "hero"}],
            "encounter_outcomes": [{"encounter_index": 0, "winner": "enemy"}],
            "state_snapshots": [{"round": 2, "party": {"hero": {"hp": 0}}}],
        },
    ]


def test_replay_bundle_round_trip_preserves_canonical_order(tmp_path: Path) -> None:
    bundle = build_replay_bundle(
        run_id="obs06_run",
        scenario_id="fixture_scenario",
        run_config={"seed": 41, "trials": 2, "ruleset": "5e-2014"},
        summary=_sample_summary(),
        trial_results=_sample_trials(),
    )

    path = tmp_path / "bundle.json"
    write_replay_bundle(path, bundle)
    loaded = load_replay_bundle(path)

    assert loaded["schema_version"] == REPLAY_BUNDLE_SCHEMA_VERSION
    assert [row["trial_index"] for row in loaded["trials"]] == [0, 1]

    baseline = path.read_text(encoding="utf-8")
    write_replay_bundle(path, loaded)
    assert path.read_text(encoding="utf-8") == baseline


def test_replay_bundle_contains_inputs_seed_summary_and_traces() -> None:
    bundle = build_replay_bundle(
        run_id="obs06_run",
        scenario_id="fixture_scenario",
        run_config={
            "seed": 777,
            "trials": 2,
            "scenario_path": "/tmp/scenario.json",
            "ruleset": "5e-2014",
        },
        summary=_sample_summary(),
        trial_results=_sample_trials(),
    )

    assert bundle["inputs"]["seed"] == 777
    assert bundle["summary"]["scenario_id"] == "fixture_scenario"
    assert bundle["trials"][0]["telemetry"]
    assert bundle["trials"][0]["state_snapshots"]
    assert bundle["trials"][0]["encounter_outcomes"]


def test_load_replay_bundle_rejects_missing_required_fields(tmp_path: Path) -> None:
    invalid = {"schema_version": REPLAY_BUNDLE_SCHEMA_VERSION, "run_id": "obs06_missing"}
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(invalid), encoding="utf-8")

    with pytest.raises(ValueError, match="missing required keys"):
        load_replay_bundle(path)


def test_diff_replay_bundles_is_path_sorted_and_deterministic() -> None:
    left = build_replay_bundle(
        run_id="obs06_left",
        scenario_id="fixture_scenario",
        run_config={"seed": 10, "trials": 1},
        summary=_sample_summary(),
        trial_results=_sample_trials()[:1],
    )
    right = build_replay_bundle(
        run_id="obs06_right",
        scenario_id="fixture_scenario",
        run_config={"seed": 11, "trials": 1},
        summary={**_sample_summary(), "party_win_rate": 1.0},
        trial_results=_sample_trials()[:1],
    )

    diff_a = diff_replay_bundles(left, right)
    diff_b = diff_replay_bundles(left, right)

    assert diff_a == diff_b
    assert diff_a["equal"] is False
    assert [change["path"] for change in diff_a["changes"]] == sorted(
        change["path"] for change in diff_a["changes"]
    )
    assert "inputs.seed" in {change["path"] for change in diff_a["changes"]}
    assert "summary.party_win_rate" in {change["path"] for change in diff_a["changes"]}


def test_diff_runs_cli_emits_deterministic_json_report(tmp_path: Path) -> None:
    left_path = tmp_path / "left.json"
    right_path = tmp_path / "right.json"

    write_replay_bundle(
        left_path,
        build_replay_bundle(
            run_id="obs06_left",
            scenario_id="fixture_scenario",
            run_config={"seed": 100, "trials": 1},
            summary=_sample_summary(),
            trial_results=_sample_trials()[:1],
        ),
    )
    write_replay_bundle(
        right_path,
        build_replay_bundle(
            run_id="obs06_right",
            scenario_id="fixture_scenario",
            run_config={"seed": 101, "trials": 1},
            summary=_sample_summary(),
            trial_results=_sample_trials()[:1],
        ),
    )

    script = Path(__file__).resolve().parents[1] / "scripts" / "replay" / "diff_runs.py"
    result = subprocess.run(
        [sys.executable, str(script), str(left_path), str(right_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["equal"] is False
    assert payload["left_path"] == str(left_path.resolve())
    assert payload["right_path"] == str(right_path.resolve())
