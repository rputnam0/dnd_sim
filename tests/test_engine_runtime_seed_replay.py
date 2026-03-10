from __future__ import annotations

from pathlib import Path

from dnd_sim.engine import run_simulation
from dnd_sim.io import load_character_db, load_runtime_scenario, load_strategy_registry
from tests.helpers import build_character, build_enemy
from tests.runtime_test_support import _setup_env


def test_runtime_entrypoint_fixed_seed_replays_identically(tmp_path: Path) -> None:
    party = [
        build_character(
            character_id="hero",
            name="Hero",
            max_hp=28,
            ac=15,
            to_hit=7,
            damage="1d8+4",
        )
    ]
    enemies = [build_enemy(enemy_id="boss", name="Boss", hp=40, ac=13, to_hit=5, damage="1d10+3")]

    scenario_path = _setup_env(
        tmp_path,
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
    )

    loaded = load_runtime_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    db = load_character_db(Path(loaded.config.character_db_dir))

    run_a = run_simulation(loaded, db, {}, registry, trials=20, seed=17, run_id="runtime_a")
    run_b = run_simulation(loaded, db, {}, registry, trials=20, seed=17, run_id="runtime_b")

    summary_a = run_a.summary.to_dict()
    summary_b = run_b.summary.to_dict()
    summary_a.pop("run_id", None)
    summary_b.pop("run_id", None)

    assert summary_a == summary_b
    assert run_a.trial_rows == run_b.trial_rows
