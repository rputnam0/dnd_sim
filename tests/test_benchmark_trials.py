from __future__ import annotations

from pathlib import Path

import pytest

from dnd_sim.benchmarks.trials import derive_trial_seed, run_trial, wilson_interval
from dnd_sim.io import load_character_db, load_runtime_scenario, load_strategy_registry
from dnd_sim.strategy_api import BaseStrategy, TurnDeclaration
from tests.helpers import build_character, build_enemy
from tests.runtime_test_support import _setup_env


def _scenario(tmp_path: Path):
    path = _setup_env(
        tmp_path,
        party=[build_character("hero", "Hero", 30, 15, 6, "1d8+3")],
        enemies=[build_enemy("enemy", "Enemy", 24, 13, 5, "1d6+2")],
        assumption_overrides={},
    )
    loaded = load_runtime_scenario(path)
    return loaded, load_character_db(Path(loaded.config.character_db_dir))


def test_individual_trials_replay_independently_of_execution_order(tmp_path: Path) -> None:
    scenario, characters = _scenario(tmp_path)
    seeds = [derive_trial_seed(41, "microcase", index) for index in range(3)]
    assert len(set(seeds)) == 3

    def run(index: int, record: bool = False):
        return run_trial(
            scenario,
            characters,
            {},
            lambda: load_strategy_registry(scenario),
            trial_index=index,
            seed=seeds[index],
            record_rolls=record,
        )

    expected = {index: run(index).result for index in range(3)}
    for index in (2, 0, 1):
        assert run(index).result == expected[index]
    recorded = run(1, True)
    assert recorded.result == expected[1]
    assert recorded.random_draws
    assert recorded.roll_records
    assert recorded == run(1, True)
    assert recorded.result.trial_index == 1


@pytest.mark.parametrize(
    "wins,n,lower,upper",
    [(0, 10, 0, 0.2775328), (10, 10, 0.7224672, 1), (5, 10, 0.2365931, 0.7634069)],
)
def test_wilson_bounds_match_independent_binomial_examples(wins, n, lower, upper) -> None:
    interval = wilson_interval(wins, n)
    assert interval[0] == pytest.approx(lower, abs=1e-7)
    assert interval[1] == pytest.approx(upper, abs=1e-7)


@pytest.mark.parametrize("wins,n", [(-1, 10), (11, 10), (0, 0), (True, 10)])
def test_invalid_binomial_counts_are_rejected(wins, n) -> None:
    with pytest.raises(ValueError):
        wilson_interval(wins, n)


class _HoldPosition(BaseStrategy):
    def declare_turn(self, actor, state):
        return TurnDeclaration()


def test_batch_respects_explicit_party_and_enemy_starting_positions(tmp_path: Path) -> None:
    scenario, characters = _scenario(tmp_path)
    scenario.config.battlefield["starting_positions"] = {
        "hero": [5, 10, 0],
        "enemy": [40, 25, 0],
    }
    scenario.config.termination_rules["max_rounds"] = 1
    scenario.config.assumption_overrides.update(party_strategy="hold", enemy_strategy="hold")
    trial = run_trial(
        scenario, characters, {}, lambda: {"hold": _HoldPosition()}, trial_index=0, seed=1
    ).result
    snapshot = trial.state_snapshots[-1]
    assert snapshot["party"]["hero"]["position"] == [5.0, 10.0, 0.0]
    assert snapshot["enemies"]["enemy"]["position"] == [40.0, 25.0, 0.0]


@pytest.mark.parametrize("position", [[1, 2], [0, float("nan"), 0], [False, 0, 0]])
def test_invalid_starting_coordinates_fail_before_simulation(tmp_path: Path, position) -> None:
    scenario, characters = _scenario(tmp_path)
    scenario.config.battlefield["starting_positions"] = {"hero": position}
    with pytest.raises(ValueError, match="starting_positions"):
        run_trial(
            scenario,
            characters,
            {},
            lambda: load_strategy_registry(scenario),
            trial_index=0,
            seed=1,
        )
