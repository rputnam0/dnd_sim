from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

logger = logging.getLogger(__name__)

_LIFECYCLE_EVENT_TYPE_BY_TRANSITION = {
    "apply": "effect_apply",
    "tick": "effect_tick",
    "refresh": "effect_refresh",
    "expire": "effect_expire",
    "concentration_break": "effect_concentration_break",
}

_MISSING = object()


def _coerce_json_value(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            normalized[key_text] = _coerce_json_value(item, path=f"{path}.{key_text}")
        return normalized

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_coerce_json_value(item, path=f"{path}[{idx}]") for idx, item in enumerate(value)]

    raise TypeError(
        f"{path} must be JSON-compatible; unsupported value type: {type(value).__name__}"
    )


def _normalize_snapshot(snapshot: Mapping[str, Any], *, path: str) -> dict[str, Any]:
    normalized = _coerce_json_value(snapshot, path=path)
    if not isinstance(normalized, dict):
        raise TypeError(f"{path} must be a JSON-compatible object")
    return normalized


def _normalize_required_text(*, name: str, value: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _normalize_optional_text(*, name: str, value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty when provided")
    return normalized


def _delta_path(prefix: str, key: str) -> str:
    return key if not prefix else f"{prefix}.{key}"


def _append_delta(*, deltas: list[dict[str, Any]], path: str, before: Any, after: Any) -> None:
    row: dict[str, Any] = {
        "path": path,
        "before": None if before is _MISSING else before,
        "after": None if after is _MISSING else after,
    }
    if before is _MISSING:
        row["before_missing"] = True
    if after is _MISSING:
        row["after_missing"] = True
    deltas.append(row)


def _collect_state_deltas(
    *, before: Any, after: Any, path: str, deltas: list[dict[str, Any]]
) -> None:
    if isinstance(before, dict) and isinstance(after, dict):
        keys = sorted(set(before) | set(after), key=str.casefold)
        for key in keys:
            before_value = before.get(key, _MISSING)
            after_value = after.get(key, _MISSING)
            child_path = _delta_path(path, key)
            if before_value is _MISSING or after_value is _MISSING:
                _append_delta(
                    deltas=deltas, path=child_path, before=before_value, after=after_value
                )
                continue
            _collect_state_deltas(
                before=before_value,
                after=after_value,
                path=child_path,
                deltas=deltas,
            )
        return

    if isinstance(before, list) and isinstance(after, list):
        if before != after:
            _append_delta(deltas=deltas, path=path, before=before, after=after)
        return

    if before != after:
        _append_delta(deltas=deltas, path=path, before=before, after=after)


def effect_lifecycle_event_type(transition: str) -> str:
    normalized = str(transition).strip().lower()
    event_type = _LIFECYCLE_EVENT_TYPE_BY_TRANSITION.get(normalized)
    if event_type is None:
        supported = ", ".join(sorted(_LIFECYCLE_EVENT_TYPE_BY_TRANSITION))
        raise ValueError(
            f"unsupported effect lifecycle transition '{transition}' " f"(supported: {supported})"
        )
    return event_type


def build_actor_state_delta_trace(
    *,
    actor_id: str,
    round_number: int | None,
    turn_token: str | None,
    before_state: Mapping[str, Any],
    after_state: Mapping[str, Any],
    transition: str | None = None,
) -> dict[str, Any] | None:
    normalized_actor_id = _normalize_required_text(name="actor_id", value=actor_id)
    normalized_before = _normalize_snapshot(before_state, path="before_state")
    normalized_after = _normalize_snapshot(after_state, path="after_state")

    deltas: list[dict[str, Any]] = []
    _collect_state_deltas(before=normalized_before, after=normalized_after, path="", deltas=deltas)
    if not deltas:
        return None

    deltas.sort(key=lambda row: str(row.get("path", "")).casefold())
    changed_fields = [str(row["path"]) for row in deltas]

    payload: dict[str, Any] = {
        "round": round_number,
        "turn_token": turn_token,
        "actor_id": normalized_actor_id,
        "delta_count": len(deltas),
        "changed_fields": changed_fields,
        "deltas": deltas,
        "before": normalized_before,
        "after": normalized_after,
    }
    if transition is not None:
        payload["transition"] = str(transition).strip().lower()
    return payload


def build_effect_lifecycle_trace(
    *,
    transition: str,
    actor_id: str,
    effect_id: str,
    effect_type: str | None = None,
    round_number: int | None = None,
    turn_token: str | None = None,
    source_actor_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_transition = str(transition).strip().lower()
    effect_lifecycle_event_type(normalized_transition)

    payload: dict[str, Any] = {
        "round": round_number,
        "turn_token": turn_token,
        "transition": normalized_transition,
        "actor_id": _normalize_required_text(name="actor_id", value=actor_id),
        "effect_id": _normalize_required_text(name="effect_id", value=effect_id),
    }

    normalized_effect_type = _normalize_optional_text(name="effect_type", value=effect_type)
    if normalized_effect_type is not None:
        payload["effect_type"] = normalized_effect_type

    normalized_source_actor = _normalize_optional_text(
        name="source_actor_id",
        value=source_actor_id,
    )
    if normalized_source_actor is not None:
        payload["source_actor_id"] = normalized_source_actor

    if metadata is not None:
        payload["metadata"] = _normalize_snapshot(metadata, path="metadata")

    return payload
