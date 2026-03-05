from __future__ import annotations

from dnd_sim.models import TrialResult
from dnd_sim.reporting_runtime import build_simulation_summary


def _trial(
    *,
    trial_index: int,
    winner: str,
    hero_damage_taken: int,
    boss_damage_taken: int,
    hero_ki_spent: int,
) -> TrialResult:
    return TrialResult(
        trial_index=trial_index,
        rounds=trial_index + 2,
        winner=winner,
        damage_taken={"hero": hero_damage_taken, "boss": boss_damage_taken},
        damage_dealt={"hero": boss_damage_taken, "boss": hero_damage_taken},
        resources_spent={"hero": {"ki": hero_ki_spent}, "boss": {}},
        downed_counts={"hero": 0, "boss": 1 if winner == "party" else 0},
        death_counts={"hero": 0, "boss": 1 if winner == "party" else 0},
        remaining_hp={"hero": 12 - trial_index, "boss": 3 if winner == "enemy" else 0},
        telemetry=[],
        encounter_outcomes=[],
        state_snapshots=[],
    )


def test_build_simulation_summary_aggregates_actor_metrics_and_resources() -> None:
    trials = [
        _trial(
            trial_index=0,
            winner="party",
            hero_damage_taken=6,
            boss_damage_taken=18,
            hero_ki_spent=1,
        ),
        _trial(
            trial_index=1,
            winner="enemy",
            hero_damage_taken=11,
            boss_damage_taken=9,
            hero_ki_spent=0,
        ),
    ]

    summary = build_simulation_summary(
        run_id="arc08",
        scenario_id="fixture",
        trials=2,
        trial_results=trials,
        tracked_resource_names={"hero": {"ki"}, "boss": set()},
    )

    assert summary.run_id == "arc08"
    assert summary.scenario_id == "fixture"
    assert summary.party_win_rate == 0.5
    assert summary.enemy_win_rate == 0.5
    assert summary.per_actor_damage_taken["hero"].mean == 8.5
    assert summary.per_actor_damage_dealt["hero"].mean == 13.5
    assert summary.per_actor_resources_spent["hero"]["ki"].mean == 0.5
    assert summary.per_actor_resources_spent["boss"] == {}


def test_build_simulation_summary_is_deterministic_for_equivalent_trials() -> None:
    trials_a = [
        _trial(
            trial_index=0,
            winner="party",
            hero_damage_taken=5,
            boss_damage_taken=13,
            hero_ki_spent=1,
        ),
        _trial(
            trial_index=1,
            winner="enemy",
            hero_damage_taken=10,
            boss_damage_taken=8,
            hero_ki_spent=0,
        ),
    ]
    trials_b = [
        _trial(
            trial_index=1,
            winner="enemy",
            hero_damage_taken=10,
            boss_damage_taken=8,
            hero_ki_spent=0,
        ),
        _trial(
            trial_index=0,
            winner="party",
            hero_damage_taken=5,
            boss_damage_taken=13,
            hero_ki_spent=1,
        ),
    ]

    summary_a = build_simulation_summary(
        run_id="run_a",
        scenario_id="fixture",
        trials=2,
        trial_results=trials_a,
        tracked_resource_names={"hero": {"ki"}, "boss": set()},
    ).to_dict()
    summary_b = build_simulation_summary(
        run_id="run_b",
        scenario_id="fixture",
        trials=2,
        trial_results=trials_b,
        tracked_resource_names={"hero": {"ki"}, "boss": set()},
    ).to_dict()

    summary_a.pop("run_id", None)
    summary_b.pop("run_id", None)
    assert summary_a == summary_b
