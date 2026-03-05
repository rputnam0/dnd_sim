from __future__ import annotations

import json

from dnd_sim.models import TrialResult
from dnd_sim.replay import build_trial_rows, diff_trial_rows, flatten_trial_result


def _trial(*, trial_index: int, winner: str, damage_taken: dict[str, int]) -> TrialResult:
    return TrialResult(
        trial_index=trial_index,
        rounds=3 + trial_index,
        winner=winner,
        damage_taken=damage_taken,
        damage_dealt={"hero": 12 + trial_index, "boss": 5 + trial_index},
        resources_spent={"hero": {"ki": trial_index}, "boss": {}},
        downed_counts={"hero": 0, "boss": 1 if winner == "party" else 0},
        death_counts={"hero": 0, "boss": 1 if winner == "party" else 0},
        remaining_hp={"hero": 10 + trial_index, "boss": 0 if winner == "party" else 3},
        telemetry=[{"event": "round_end", "round": trial_index + 1}],
        encounter_outcomes=[{"encounter_index": 0, "winner": winner}],
        state_snapshots=[{"checkpoint_id": f"cp-{trial_index}", "winner": winner}],
    )


def test_flatten_trial_result_serializes_json_fields_with_stable_key_order() -> None:
    trial = _trial(trial_index=0, winner="party", damage_taken={"boss": 3, "hero": 9})

    row = flatten_trial_result(trial)

    assert row["trial_index"] == 0
    assert row["winner"] == "party"
    assert row["damage_taken"] == json.dumps({"boss": 3, "hero": 9}, sort_keys=True)
    assert row["telemetry"] == json.dumps(
        [{"event": "round_end", "round": 1}],
        sort_keys=True,
    )


def test_build_trial_rows_preserves_trial_order_for_deterministic_replay() -> None:
    trials = [
        _trial(trial_index=2, winner="enemy", damage_taken={"hero": 10, "boss": 0}),
        _trial(trial_index=1, winner="party", damage_taken={"hero": 7, "boss": 2}),
    ]

    rows = build_trial_rows(trials)

    assert [row["trial_index"] for row in rows] == [2, 1]


def test_diff_trial_rows_reports_missing_and_changed_rows_deterministically() -> None:
    baseline = build_trial_rows(
        [
            _trial(trial_index=0, winner="party", damage_taken={"hero": 4, "boss": 9}),
            _trial(trial_index=1, winner="enemy", damage_taken={"hero": 12, "boss": 0}),
        ]
    )
    candidate = [dict(row) for row in baseline if int(row["trial_index"]) != 1]
    candidate[0]["winner"] = "enemy"
    candidate.append(
        flatten_trial_result(
            _trial(trial_index=2, winner="party", damage_taken={"hero": 5, "boss": 1})
        )
    )

    diff = diff_trial_rows(baseline, candidate)

    assert diff["missing_in_rhs"] == [1]
    assert diff["missing_in_lhs"] == [2]
    assert diff["changed"] == [{"fields": ["winner"], "trial_index": 0}]
