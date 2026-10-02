from pathlib import Path

import pytest

from dnd_sim.benchmarks.level_five import (
    load_party,
    run_benchmark,
    validate_trial_scope,
    replay_sample,
)
from dnd_sim.benchmarks.reporting import summarize


def _row(outcome, *, down=False, death=False, all_dead=False):
    return dict(
        outcome=outcome,
        any_down=down,
        any_death=death,
        all_dead_at_stop=all_dead,
        censored=outcome == "timeout",
        rounds=3,
        party_hp=20,
        resources_spent={},
        actions={"fighter:basic": 2},
        bonuses={},
        movement_turns=1,
        turns=3,
    )


def test_report_keeps_defeat_death_and_censoring_separate():
    rows = [
        _row("party_victory"),
        _row("party_victory", down=True),
        _row("enemy_victory", down=True, death=True),
        _row("timeout"),
    ]
    summary = summarize(rows)
    assert summary["win"]["rate"] == 0.5
    assert summary["defeat"]["rate"] == 0.25
    assert summary["any_down"]["rate"] == 0.5
    assert summary["any_death"]["rate"] == 0.25
    assert summary["all_dead_at_stop"]["rate"] == 0
    assert summary["censored"]["rate"] == 0.25
    assert summary["win"]["ci95"] == pytest.approx([0.15003899, 0.84996101])
    assert summary["actions"]["fighter:basic"] == 8


def test_party_loading_does_not_query_local_character_database(monkeypatch):
    import dnd_sim.db_schema

    monkeypatch.setattr(
        dnd_sim.db_schema, "execute_query", lambda *a, **k: pytest.fail("Local DB read")
    )
    assert set(load_party()) == {"fighter", "rogue", "cleric", "wizard"}


def test_small_benchmark_preserves_replayable_rolls_and_report(tmp_path: Path):
    report = run_benchmark(
        trials=2,
        master_seed=101,
        output=tmp_path,
        scenario_ids=["01_raider_patrol"],
        policies=["typical"],
    )
    assert report["groups"][0]["summary"]["n"] == 2
    assert report["groups"][0]["samples"][0]["replay_matches"] is True
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "trials.jsonl.gz").exists()
    assert (tmp_path / "rolls.md").exists()
    assert list((tmp_path / "samples").glob("*.json.gz"))
    for sample in (tmp_path / "samples").glob("*.json.gz"):
        assert replay_sample(sample)


def test_report_rejects_empty_sample():
    with pytest.raises(ValueError):
        summarize([])


def test_unverified_action_is_rejected_instead_of_counted_as_a_valid_trial():
    from types import SimpleNamespace

    result = SimpleNamespace(
        telemetry=[
            dict(
                telemetry_type="decision",
                team="party",
                actor_id="wizard",
                action_plan="Unverified Spell",
            )
        ]
    )
    with pytest.raises(ValueError, match="Unverified Spell"):
        validate_trial_scope(result, {"wizard": {"Fire Bolt": "wizard_spells"}})


def test_parallel_groups_preserve_serial_trial_data_and_samples(tmp_path):
    serial, parallel = tmp_path / "serial", tmp_path / "parallel"
    args = dict(
        trials=2,
        master_seed=20261002,
        scenario_ids=["01_raider_patrol"],
        policies=["conservative", "typical"],
    )
    a = run_benchmark(output=serial, **args)
    b = run_benchmark(output=parallel, workers=2, **args)
    assert a == b
    assert (serial / "trials.jsonl.gz").read_bytes() == (parallel / "trials.jsonl.gz").read_bytes()
    for path in (serial / "samples").glob("*"):
        assert path.read_bytes() == (parallel / "samples" / path.name).read_bytes()
