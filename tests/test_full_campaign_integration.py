from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dnd_sim.engine import run_simulation
from dnd_sim.io import load_character_db, load_scenario, load_strategy_registry

REPO_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_FIXTURE_PATH = (
    REPO_ROOT / "artifacts" / "integration_campaigns" / "branching_world_combat.json"
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _materialize_campaign_fixture(tmp_path: Path) -> tuple[Path, dict[str, Any], int]:
    fixture = json.loads(CAMPAIGN_FIXTURE_PATH.read_text(encoding="utf-8"))

    db_dir = tmp_path / "db" / "characters"
    _write_json(
        db_dir / "index.json",
        {
            "characters": [
                {
                    "character_id": character["character_id"],
                    "name": character["name"],
                    "class_levels": character["class_levels"],
                    "source_pdf": "fixture.pdf",
                }
                for character in fixture["party"]
            ]
        },
    )
    for character in fixture["party"]:
        _write_json(db_dir / f"{character['character_id']}.json", character)

    encounter_root = tmp_path / "encounters" / fixture["campaign_id"]
    enemy_dir = encounter_root / "enemies"
    scenario_dir = encounter_root / "scenarios"
    enemy_dir.mkdir(parents=True, exist_ok=True)
    scenario_dir.mkdir(parents=True, exist_ok=True)
    for enemy in fixture["enemies"]:
        _write_json(enemy_dir / f"{enemy['identity']['enemy_id']}.json", enemy)

    scenario = dict(fixture["scenario"])
    scenario["character_db_dir"] = str(db_dir)
    scenario_path = scenario_dir / "scenario.json"
    _write_json(scenario_path, scenario)

    expected = dict(fixture["expected"])
    return scenario_path, expected, int(fixture["seed"])


def _run_trial(scenario_path: Path, *, seed: int, run_id: str):
    loaded = load_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    db = load_character_db(Path(loaded.config.character_db_dir))
    summary = run_simulation(loaded, db, {}, registry, trials=1, seed=seed, run_id=run_id)
    return summary.trial_results[0]


def test_integrated_campaign_world_combat_fixture_runs_end_to_end(tmp_path: Path) -> None:
    scenario_path, expected, seed = _materialize_campaign_fixture(tmp_path)
    trial = _run_trial(scenario_path, seed=seed, run_id="fin04_integrated")

    assert trial.winner == expected["winner"]
    assert [snapshot["checkpoint_id"] for snapshot in trial.state_snapshots] == expected[
        "checkpoint_sequence"
    ]

    first_snapshot_party = trial.state_snapshots[0]["party"]["hero"]
    assert first_snapshot_party["hp"] == expected["first_snapshot_hp"]
    assert first_snapshot_party["resources"]["ki"] == expected["first_snapshot_ki"]


def test_encounter_branching_gate_uses_expected_wave_path(tmp_path: Path) -> None:
    scenario_path, expected, seed = _materialize_campaign_fixture(tmp_path)
    trial = _run_trial(scenario_path, seed=seed, run_id="fin04_branching")

    assert len(trial.encounter_outcomes) == 2
    first_outcome = trial.encounter_outcomes[0]
    assert first_outcome["winner"] == "party"
    assert first_outcome["branch_key"] == "party"
    assert first_outcome["next_encounter_index"] == expected["next_encounter_index_after_split"]


def test_campaign_state_snapshot_persistence_reload_is_stable(tmp_path: Path) -> None:
    scenario_path, _expected, seed = _materialize_campaign_fixture(tmp_path)
    trial_a = _run_trial(scenario_path, seed=seed, run_id="fin04_persist_a")

    persisted_path = tmp_path / "persisted_campaign_state.json"
    persisted_path.write_text(
        json.dumps(
            {
                "encounter_outcomes": trial_a.encounter_outcomes,
                "state_snapshots": trial_a.state_snapshots,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    reloaded = json.loads(persisted_path.read_text(encoding="utf-8"))

    trial_b = _run_trial(scenario_path, seed=seed, run_id="fin04_persist_b")
    assert reloaded["encounter_outcomes"] == trial_b.encounter_outcomes
    assert reloaded["state_snapshots"] == trial_b.state_snapshots
