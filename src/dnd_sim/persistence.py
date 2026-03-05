from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dnd_sim.world_runtime import (
    LightSourceState,
    ExplorationState,
    WorldClock,
)


def _required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _required_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _deserialize_light_sources(raw: Any) -> dict[str, LightSourceState]:
    if raw is None:
        return {}

    if isinstance(raw, list):
        normalized: dict[str, LightSourceState] = {}
        for item in raw:
            if not isinstance(item, Mapping):
                raise ValueError("light_sources list entries must be mappings")
            source_id = _required_text(item.get("source_id"), field_name="source_id")
            remaining_minutes = _required_int(
                item.get("remaining_minutes"),
                field_name="remaining_minutes",
            )
            is_lit_raw = item.get("is_lit", remaining_minutes > 0)
            if not isinstance(is_lit_raw, bool):
                raise ValueError("is_lit must be a bool")
            normalized[source_id] = LightSourceState(
                source_id=source_id,
                remaining_minutes=remaining_minutes,
                is_lit=is_lit_raw,
            )
        return normalized

    if isinstance(raw, Mapping):
        normalized = {}
        for source_id, source_payload in raw.items():
            normalized_source_id = _required_text(source_id, field_name="source_id")
            if isinstance(source_payload, Mapping):
                remaining_minutes = _required_int(
                    source_payload.get("remaining_minutes"),
                    field_name="remaining_minutes",
                )
                is_lit_raw = source_payload.get("is_lit", remaining_minutes > 0)
                if not isinstance(is_lit_raw, bool):
                    raise ValueError("is_lit must be a bool")
                normalized[normalized_source_id] = LightSourceState(
                    source_id=normalized_source_id,
                    remaining_minutes=remaining_minutes,
                    is_lit=is_lit_raw,
                )
            elif isinstance(source_payload, int) and not isinstance(source_payload, bool):
                normalized[normalized_source_id] = LightSourceState(
                    source_id=normalized_source_id,
                    remaining_minutes=source_payload,
                    is_lit=source_payload > 0,
                )
            else:
                raise ValueError("light_sources mapping values must be mappings or integer minutes")
        return normalized

    raise ValueError("light_sources must be a list or mapping")


def serialize_world_exploration_state(state: ExplorationState) -> dict[str, Any]:
    if not isinstance(state, ExplorationState):
        raise ValueError("state must be an ExplorationState")

    return {
        "turn_index": state.turn_index,
        "clock": {
            "day": state.clock.day,
            "minute_of_day": state.clock.minute_of_day,
        },
        "location_id": state.location_id,
        "light_sources": [
            {
                "source_id": light.source_id,
                "remaining_minutes": light.remaining_minutes,
                "is_lit": light.is_lit,
            }
            for _, light in sorted(state.light_sources.items())
        ],
    }


def deserialize_world_exploration_state(payload: Mapping[str, Any]) -> ExplorationState:
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a mapping")

    clock_payload = payload.get("clock")
    if not isinstance(clock_payload, Mapping):
        raise ValueError("clock must be a mapping")

    day = _required_int(clock_payload.get("day"), field_name="day")
    minute_of_day = _required_int(
        clock_payload.get("minute_of_day"),
        field_name="minute_of_day",
    )

    location_id: str | None = None
    if payload.get("location_id") is not None:
        location_id = _required_text(payload.get("location_id"), field_name="location_id")

    light_sources = _deserialize_light_sources(payload.get("light_sources"))
    turn_index = _required_int(payload.get("turn_index", 0), field_name="turn_index")

    return ExplorationState(
        turn_index=turn_index,
        clock=WorldClock(day=day, minute_of_day=minute_of_day),
        light_sources=light_sources,
        location_id=location_id,
    )
