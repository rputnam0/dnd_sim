from __future__ import annotations

from pathlib import Path

from dnd_sim.engine import run_simulation
from dnd_sim.io import (
    load_character_db,
    load_public_scenario,
    load_strategy_registry,
    load_traits_db,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PHASE_2_SCENARIO = REPO_ROOT / "river_line/encounters/ley_heart/scenarios/ley_heart_phase_2.json"


def test_shipped_public_phase2_scenario_executes_end_to_end() -> None:
    loaded = load_public_scenario(PHASE_2_SCENARIO)
    character_db = load_character_db(Path(loaded.config.character_db_dir))
    traits_db = load_traits_db(REPO_ROOT / "db/rules/2014/traits")

    artifacts = run_simulation(
        loaded,
        character_db,
        traits_db,
        load_strategy_registry(loaded),
        trials=1,
        seed=1,
        run_id="shipped_phase2_regression",
    )

    assert len(artifacts.trial_results) == 1
