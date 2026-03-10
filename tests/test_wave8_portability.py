from __future__ import annotations

import json
from pathlib import Path

from dnd_sim.io import load_public_scenario

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_PORTABLE_FILES = (
    REPO_ROOT / "river_line/encounters/ley_heart/scenarios/ley_heart_phase_1.json",
    REPO_ROOT / "river_line/encounters/ley_heart/scenarios/ley_heart_phase_1_proc_advantage.json",
    REPO_ROOT / "river_line/encounters/ley_heart/scenarios/ley_heart_phase_1_double_monk_flurry.json",
    REPO_ROOT / "river_line/encounters/ley_heart/scenarios/ley_heart_phase_1_boss_scalar_1.json",
    REPO_ROOT / "river_line/encounters/ley_heart/scenarios/ley_heart_phase_1_split_two_pylons.json",
    REPO_ROOT / "river_line/encounters/ley_heart/scenarios/ley_heart_phase_2.json",
    REPO_ROOT / "river_line/encounters/ley_heart/phase_1/phase_1_dm_encounter_card.md",
    REPO_ROOT / "river_line/encounters/ley_heart/tools/phase1_sweep.py",
)


def test_live_portable_content_contains_no_machine_local_absolute_paths() -> None:
    for path in LIVE_PORTABLE_FILES:
        text = path.read_text(encoding="utf-8")
        assert "/Users/" not in text, path.as_posix()
        assert "/home/" not in text, path.as_posix()


def test_public_phase2_scenario_loads_without_internal_harness_fields() -> None:
    scenario_path = (
        REPO_ROOT / "river_line/encounters/ley_heart/scenarios/ley_heart_phase_2.json"
    )

    loaded = load_public_scenario(scenario_path)

    assert loaded.config.internal_harness is None
    assert loaded.config.character_db_dir.endswith("river_line/db/characters")


def test_shipped_scenarios_use_only_portable_character_db_dir_refs() -> None:
    scenario_paths = sorted(
        (REPO_ROOT / "river_line/encounters/ley_heart/scenarios").glob("*.json")
    )

    for scenario_path in scenario_paths:
        payload = json.loads(scenario_path.read_text(encoding="utf-8"))
        character_db_dir = payload["character_db_dir"]
        assert not Path(character_db_dir).is_absolute(), scenario_path.as_posix()
