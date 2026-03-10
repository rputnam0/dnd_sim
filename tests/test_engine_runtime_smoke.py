from __future__ import annotations

from pathlib import Path

from dnd_sim.engine import run_simulation
from dnd_sim.io import load_character_db, load_runtime_scenario, load_strategy_registry
from tests.helpers import build_character, build_enemy
from tests.runtime_test_support import _setup_env


def test_runtime_entrypoint_smoke_returns_trial_and_summary(tmp_path: Path) -> None:
    party = [build_character("hero", "Hero", 24, 14, 6, "1d8+3")]
    enemies = [build_enemy(enemy_id="wolf", name="Wolf", hp=16, ac=12, to_hit=4, damage="1d6+2")]

    scenario_path = _setup_env(
        tmp_path,
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
        max_rounds=10,
    )

    loaded = load_runtime_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    db = load_character_db(Path(loaded.config.character_db_dir))

    artifacts = run_simulation(
        loaded,
        db,
        {},
        registry,
        trials=1,
        seed=5,
        run_id="runtime_smoke",
    )

    assert artifacts.summary.trials == 1
    assert len(artifacts.trial_results) == 1
    assert artifacts.trial_results[0].winner in {"party", "enemy", "draw"}
    assert artifacts.trial_rows[0]["trial_index"] == 0
