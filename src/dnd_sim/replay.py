from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from dnd_sim.replay_schema import JSONValue, REPLAY_BUNDLE_SCHEMA_VERSION, normalize_replay_bundle


def _as_dict(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return dict(record)
    if is_dataclass(record):
        return asdict(record)
    if hasattr(record, "to_dict") and callable(record.to_dict):
        payload = record.to_dict()
        if isinstance(payload, dict):
            return dict(payload)
    raise TypeError(f"Unsupported replay record type: {type(record).__name__}")


def _normalize_trial_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    normalized.setdefault("damage_taken", {})
    normalized.setdefault("damage_dealt", {})
    normalized.setdefault("resources_spent", {})
    normalized.setdefault("downed_counts", {})
    normalized.setdefault("death_counts", {})
    normalized.setdefault("remaining_hp", {})
    normalized.setdefault("telemetry", [])
    normalized.setdefault("encounter_outcomes", [])
    normalized.setdefault("state_snapshots", [])
    return normalized


def build_replay_bundle(
    *,
    run_id: str,
    scenario_id: str,
    run_config: dict[str, Any],
    summary: dict[str, Any],
    trial_results: list[dict[str, Any]] | tuple[dict[str, Any], ...] | list[Any] | tuple[Any, ...],
) -> dict[str, JSONValue]:
    trials = [_normalize_trial_record(_as_dict(record)) for record in trial_results]
    bundle: dict[str, Any] = {
        "schema_version": REPLAY_BUNDLE_SCHEMA_VERSION,
        "run_id": run_id,
        "scenario_id": scenario_id,
        "inputs": dict(run_config),
        "summary": dict(summary),
        "trials": trials,
    }
    return normalize_replay_bundle(bundle)


def write_replay_bundle(path: Path, bundle: dict[str, Any]) -> Path:
    normalized = normalize_replay_bundle(bundle)
    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
        encoding="utf-8",
    )
    return destination


def load_replay_bundle(path: Path) -> dict[str, JSONValue]:
    source = path.resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Replay bundle root must be a JSON object")
    return normalize_replay_bundle(payload)


def _flatten_json(
    value: JSONValue,
    *,
    path: str,
    out: dict[str, JSONValue],
) -> None:
    if isinstance(value, dict):
        for key in sorted(value):
            child_path = f"{path}.{key}" if path else key
            _flatten_json(value[key], path=child_path, out=out)
        return

    if isinstance(value, list):
        for idx, item in enumerate(value):
            child_path = f"{path}[{idx}]"
            _flatten_json(item, path=child_path, out=out)
        return

    out[path] = value


def diff_replay_bundles(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    ignore_paths: set[str] | None = None,
) -> dict[str, Any]:
    normalized_left = normalize_replay_bundle(left)
    normalized_right = normalize_replay_bundle(right)

    left_flat: dict[str, JSONValue] = {}
    right_flat: dict[str, JSONValue] = {}
    _flatten_json(normalized_left, path="", out=left_flat)
    _flatten_json(normalized_right, path="", out=right_flat)

    ignored = set(ignore_paths or set())
    all_paths = sorted(set(left_flat) | set(right_flat))
    changes: list[dict[str, Any]] = []
    for path in all_paths:
        if path in ignored:
            continue
        left_value = left_flat.get(path, None)
        right_value = right_flat.get(path, None)
        if left_value != right_value:
            changes.append(
                {
                    "path": path,
                    "left": left_value,
                    "right": right_value,
                }
            )

    return {
        "equal": len(changes) == 0,
        "change_count": len(changes),
        "changes": changes,
    }
