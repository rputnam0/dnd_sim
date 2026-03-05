from __future__ import annotations

import json
import logging
from typing import Any

from dnd_sim.models import TrialResult

logger = logging.getLogger(__name__)


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def flatten_trial_result(trial: TrialResult) -> dict[str, Any]:
    return {
        "trial_index": trial.trial_index,
        "rounds": trial.rounds,
        "winner": trial.winner,
        "damage_taken": _stable_json(trial.damage_taken),
        "damage_dealt": _stable_json(trial.damage_dealt),
        "resources_spent": _stable_json(trial.resources_spent),
        "downed_counts": _stable_json(trial.downed_counts),
        "death_counts": _stable_json(trial.death_counts),
        "remaining_hp": _stable_json(trial.remaining_hp),
        "telemetry": _stable_json(trial.telemetry),
        "encounter_outcomes": _stable_json(trial.encounter_outcomes),
        "state_snapshots": _stable_json(trial.state_snapshots),
    }


def build_trial_rows(trials: list[TrialResult]) -> list[dict[str, Any]]:
    return [flatten_trial_result(trial) for trial in trials]


def _trial_index(row: dict[str, Any]) -> int:
    return int(row.get("trial_index", -1))


def diff_trial_rows(
    baseline_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
) -> dict[str, list[Any]]:
    baseline_by_index = {_trial_index(row): row for row in baseline_rows}
    candidate_by_index = {_trial_index(row): row for row in candidate_rows}

    missing_in_rhs = sorted(set(baseline_by_index) - set(candidate_by_index))
    missing_in_lhs = sorted(set(candidate_by_index) - set(baseline_by_index))

    changed: list[dict[str, Any]] = []
    for trial_index in sorted(set(baseline_by_index).intersection(candidate_by_index)):
        before = baseline_by_index[trial_index]
        after = candidate_by_index[trial_index]
        changed_fields = sorted(
            field_name
            for field_name in sorted(set(before).union(after))
            if before.get(field_name) != after.get(field_name)
        )
        if changed_fields:
            changed.append({"trial_index": trial_index, "fields": changed_fields})

    return {
        "missing_in_rhs": missing_in_rhs,
        "missing_in_lhs": missing_in_lhs,
        "changed": changed,
    }
