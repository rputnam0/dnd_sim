from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypeAlias

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]

REPLAY_BUNDLE_SCHEMA_VERSION = "replay.v1"
GOLDEN_TRACE_MANIFEST_SCHEMA_VERSION = "golden_traces.v2"
REPLAY_BUNDLE_REQUIRED_KEYS: tuple[str, ...] = (
    "schema_version",
    "run_id",
    "scenario_id",
    "inputs",
    "summary",
    "trials",
)
REPLAY_TRIAL_REQUIRED_KEYS: tuple[str, ...] = (
    "trial_index",
    "rounds",
    "winner",
    "damage_taken",
    "damage_dealt",
    "resources_spent",
    "downed_counts",
    "death_counts",
    "remaining_hp",
    "telemetry",
    "encounter_outcomes",
    "state_snapshots",
)


def _coerce_json_value(value: Any, *, path: str) -> JSONValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        normalized: dict[str, JSONValue] = {}
        for key, item in value.items():
            key_text = str(key)
            normalized[key_text] = _coerce_json_value(item, path=f"{path}.{key_text}")
        return normalized

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_coerce_json_value(item, path=f"{path}[{idx}]") for idx, item in enumerate(value)]

    raise TypeError(
        f"{path} must be JSON-compatible; unsupported value type: {type(value).__name__}"
    )


def _non_empty_text(value: Any, *, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def normalize_replay_bundle(bundle: Mapping[str, Any]) -> dict[str, JSONValue]:
    normalized = _coerce_json_value(bundle, path="bundle")
    if not isinstance(normalized, dict):
        raise TypeError("bundle must be a JSON-compatible object")

    missing = [key for key in REPLAY_BUNDLE_REQUIRED_KEYS if key not in normalized]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"Replay bundle missing required keys: {joined}")

    schema_version = _non_empty_text(normalized.get("schema_version"), field_name="schema_version")
    if schema_version != REPLAY_BUNDLE_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported replay schema_version '{schema_version}'. "
            f"Expected '{REPLAY_BUNDLE_SCHEMA_VERSION}'."
        )

    normalized["run_id"] = _non_empty_text(normalized.get("run_id"), field_name="run_id")
    normalized["scenario_id"] = _non_empty_text(
        normalized.get("scenario_id"),
        field_name="scenario_id",
    )

    inputs = normalized.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("inputs must be a JSON object")

    summary = normalized.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("summary must be a JSON object")

    trials = normalized.get("trials")
    if not isinstance(trials, list):
        raise ValueError("trials must be a JSON array")

    normalized_trials: list[dict[str, JSONValue]] = []
    for idx, trial in enumerate(trials):
        if not isinstance(trial, dict):
            raise ValueError(f"trials[{idx}] must be a JSON object")
        missing_trial = [key for key in REPLAY_TRIAL_REQUIRED_KEYS if key not in trial]
        if missing_trial:
            joined = ", ".join(missing_trial)
            raise ValueError(f"trials[{idx}] missing required keys: {joined}")

        normalized_trial = dict(trial)
        normalized_trial["trial_index"] = int(normalized_trial["trial_index"])
        normalized_trial["rounds"] = int(normalized_trial["rounds"])
        normalized_trial["winner"] = _non_empty_text(
            normalized_trial.get("winner"),
            field_name=f"trials[{idx}].winner",
        )

        for dict_field in (
            "damage_taken",
            "damage_dealt",
            "resources_spent",
            "downed_counts",
            "death_counts",
            "remaining_hp",
        ):
            if not isinstance(normalized_trial.get(dict_field), dict):
                raise ValueError(f"trials[{idx}].{dict_field} must be a JSON object")

        for list_field in ("telemetry", "encounter_outcomes", "state_snapshots"):
            if not isinstance(normalized_trial.get(list_field), list):
                raise ValueError(f"trials[{idx}].{list_field} must be a JSON array")

        normalized_trials.append(normalized_trial)

    normalized_trials.sort(key=lambda trial: int(trial["trial_index"]))
    normalized["trials"] = normalized_trials
    return normalized
