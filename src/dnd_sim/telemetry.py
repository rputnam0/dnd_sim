from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any, TypeAlias

logger = logging.getLogger(__name__)

TELEMETRY_SCHEMA_VERSION = "obs.v1"
TURN_TRACE_EVENT_TYPES: tuple[str, str, str, str] = (
    "declaration_validation",
    "action_selection",
    "action_resolution",
    "action_outcome",
)
STATE_DELTA_EVENT_TYPE = "actor_state_delta"
EFFECT_LIFECYCLE_EVENT_TYPES: tuple[str, str, str, str, str] = (
    "effect_apply",
    "effect_tick",
    "effect_refresh",
    "effect_expire",
    "effect_concentration_break",
)
RESOURCE_DELTA_EVENT_TYPE = "resource_delta"
RNG_AUDIT_EVENT_TYPE = "rng_audit"
INVARIANT_VIOLATION_EVENT_TYPE = "invariant_violation"
AI_TRACE_EVENT_TYPES: tuple[str, str] = ("ai_candidate_scoring", "ai_action_rationale")

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


def _normalize_non_empty_text(value: Any, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


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


def _normalize_payload(payload: Mapping[str, Any]) -> dict[str, JSONValue]:
    normalized = _coerce_json_value(payload, path="payload")
    if not isinstance(normalized, dict):
        raise TypeError("payload must be a JSON-compatible object")
    return normalized


def build_event_envelope(
    *,
    event_type: str,
    payload: Mapping[str, Any],
    source: str,
) -> dict[str, JSONValue]:
    normalized_event_type = str(event_type).strip()
    if not normalized_event_type:
        raise ValueError("event_type must not be empty")

    normalized_source = str(source).strip()
    if not normalized_source:
        raise ValueError("source must not be empty")

    normalized_payload = _normalize_payload(payload)
    envelope: dict[str, JSONValue] = {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "event_type": normalized_event_type,
        "telemetry_type": normalized_event_type,
        "source": normalized_source,
        "payload": normalized_payload,
    }
    for key, value in normalized_payload.items():
        envelope.setdefault(key, value)
    return envelope


def build_ai_candidate_scoring_trace(
    *,
    actor_id: str,
    team: str,
    strategy: str,
    round_number: int | None,
    selected_action: str | None,
    evaluation_mode: str,
    candidate_rows: Sequence[Mapping[str, Any]],
    source: str,
) -> dict[str, JSONValue]:
    payload = {
        "actor_id": actor_id,
        "team": team,
        "strategy": strategy,
        "round": round_number,
        "selected_action": selected_action,
        "evaluation_mode": evaluation_mode,
        "candidate_rows": list(candidate_rows),
    }
    return build_event_envelope(
        event_type="ai_candidate_scoring",
        payload=payload,
        source=source,
    )


def build_ai_action_rationale_trace(
    *,
    actor_id: str,
    team: str,
    strategy: str,
    round_number: int | None,
    selected_action: str | None,
    evaluation_mode: str,
    enabled_policies: Sequence[str],
    selected_candidate: Mapping[str, Any] | None,
    source: str,
) -> dict[str, JSONValue]:
    payload = {
        "actor_id": actor_id,
        "team": team,
        "strategy": strategy,
        "round": round_number,
        "selected_action": selected_action,
        "evaluation_mode": evaluation_mode,
        "enabled_policies": list(enabled_policies),
        "selected_candidate": (
            dict(selected_candidate) if selected_candidate is not None else None
        ),
    }
    return build_event_envelope(
        event_type="ai_action_rationale",
        payload=payload,
        source=source,
    )


def serialize_event(event: Mapping[str, Any]) -> str:
    normalized_event = _coerce_json_value(event, path="event")
    if not isinstance(normalized_event, dict):
        raise TypeError("event must be a JSON-compatible object")
    return json.dumps(normalized_event, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def emit_event(
    event_logger: logging.Logger,
    *,
    event_type: str,
    payload: Mapping[str, Any],
    source: str,
    level: int = logging.INFO,
) -> dict[str, JSONValue]:
    envelope = build_event_envelope(event_type=event_type, payload=payload, source=source)
    event_logger.log(level, serialize_event(envelope))
    return envelope


def build_resource_delta_event(
    *,
    source: str,
    actor_id: str,
    resource: str,
    before: int,
    after: int,
    reason: str,
    context: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, JSONValue]:
    normalized_actor_id = _normalize_non_empty_text(actor_id, field_name="actor_id")
    normalized_resource = _normalize_non_empty_text(resource, field_name="resource")
    normalized_reason = _normalize_non_empty_text(reason, field_name="reason")
    before_int = int(before)
    after_int = int(after)
    delta = after_int - before_int
    direction = "recover" if delta > 0 else "spend" if delta < 0 else "none"

    payload: dict[str, Any] = {
        "actor_id": normalized_actor_id,
        "resource": normalized_resource,
        "before": before_int,
        "after": after_int,
        "delta": delta,
        "direction": direction,
        "reason": normalized_reason,
    }
    if context is not None:
        payload["context"] = _normalize_non_empty_text(context, field_name="context")
    if metadata is not None:
        payload["metadata"] = metadata

    return build_event_envelope(
        event_type=RESOURCE_DELTA_EVENT_TYPE,
        payload=payload,
        source=source,
    )


def build_rng_audit_event(
    *,
    source: str,
    seed: int | None,
    context: str,
    draw_index: int,
    die_sides: int | None = None,
    roll_value: int | None = None,
    actor_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, JSONValue]:
    draw_idx = int(draw_index)
    if draw_idx < 0:
        raise ValueError("draw_index must be non-negative")

    payload: dict[str, Any] = {
        "rng_seed": None if seed is None else int(seed),
        "rng_context": _normalize_non_empty_text(context, field_name="context"),
        "draw_index": draw_idx,
    }
    if die_sides is not None:
        payload["die_sides"] = int(die_sides)
    if roll_value is not None:
        payload["roll_value"] = int(roll_value)
    if actor_id is not None:
        payload["actor_id"] = _normalize_non_empty_text(actor_id, field_name="actor_id")
    if metadata is not None:
        payload["metadata"] = metadata

    return build_event_envelope(
        event_type=RNG_AUDIT_EVENT_TYPE,
        payload=payload,
        source=source,
    )


def build_invariant_violation_event(
    *,
    source: str,
    invariant_code: str,
    message: str,
    severity: str = "error",
    actor_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, JSONValue]:
    normalized_severity = _normalize_non_empty_text(severity, field_name="severity").lower()
    if normalized_severity not in {"warning", "error", "critical"}:
        raise ValueError("severity must be one of: warning, error, critical")

    payload: dict[str, Any] = {
        "invariant_code": _normalize_non_empty_text(
            invariant_code,
            field_name="invariant_code",
        ).upper(),
        "message": _normalize_non_empty_text(message, field_name="message"),
        "severity": normalized_severity,
    }
    if actor_id is not None:
        payload["actor_id"] = _normalize_non_empty_text(actor_id, field_name="actor_id")
    if details is not None:
        payload["details"] = details

    return build_event_envelope(
        event_type=INVARIANT_VIOLATION_EVENT_TYPE,
        payload=payload,
        source=source,
    )
