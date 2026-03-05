from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any, TypeAlias

logger = logging.getLogger(__name__)

TELEMETRY_SCHEMA_VERSION = "obs.v1"

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


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
