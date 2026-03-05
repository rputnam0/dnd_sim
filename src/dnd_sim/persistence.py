from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dnd_sim.campaign_runtime import (
    AdventuringActorState,
    AdventuringDayState,
    EncounterCheckpoint,
)
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


def _serialize_adventuring_actor_state(actor: AdventuringActorState) -> dict[str, Any]:
    return {
        "actor_id": actor.actor_id,
        "hit_points": actor.hit_points,
        "max_hit_points": actor.max_hit_points,
        "resources": dict(actor.resources),
        "max_resources": dict(actor.max_resources),
        "short_rest_recovery": list(actor.short_rest_recovery),
        "conditions": list(actor.conditions),
    }


def _deserialize_adventuring_actor_state(payload: Mapping[str, Any]) -> AdventuringActorState:
    if not isinstance(payload, Mapping):
        raise ValueError("actor payload must be a mapping")

    return AdventuringActorState(
        actor_id=_required_text(payload.get("actor_id"), field_name="actor_id"),
        hit_points=_required_int(payload.get("hit_points"), field_name="hit_points"),
        max_hit_points=_required_int(payload.get("max_hit_points"), field_name="max_hit_points"),
        resources=dict(payload.get("resources", {})),
        max_resources=dict(payload.get("max_resources", {})),
        short_rest_recovery=tuple(payload.get("short_rest_recovery", ())),
        conditions=tuple(payload.get("conditions", ())),
    )


def _serialize_adventuring_party(
    party: Mapping[str, AdventuringActorState],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for actor_id, actor in sorted(dict(party).items()):
        if actor.actor_id != actor_id:
            raise ValueError("party actor key must match actor_id")
        rows.append(_serialize_adventuring_actor_state(actor))
    return rows


def _deserialize_adventuring_party(raw: Any) -> dict[str, AdventuringActorState]:
    if raw is None:
        return {}

    rows: list[tuple[str, Mapping[str, Any]]] = []
    if isinstance(raw, Mapping):
        for actor_id, payload in sorted(raw.items()):
            if not isinstance(payload, Mapping):
                raise ValueError("party mapping values must be mappings")
            merged_payload = dict(payload)
            merged_payload.setdefault("actor_id", actor_id)
            rows.append((str(actor_id), merged_payload))
    elif isinstance(raw, list):
        for payload in raw:
            if not isinstance(payload, Mapping):
                raise ValueError("party list entries must be mappings")
            actor_id = _required_text(payload.get("actor_id"), field_name="actor_id")
            rows.append((actor_id, payload))
    else:
        raise ValueError("party must be a list or mapping")

    party: dict[str, AdventuringActorState] = {}
    for actor_id, payload in rows:
        actor = _deserialize_adventuring_actor_state(payload)
        if actor.actor_id != actor_id:
            raise ValueError("party actor key must match actor_id")
        party[actor_id] = actor
    return party


def serialize_adventuring_day_state(state: AdventuringDayState) -> dict[str, Any]:
    if not isinstance(state, AdventuringDayState):
        raise ValueError("state must be an AdventuringDayState")

    return {
        "campaign_id": state.campaign_id,
        "day_number": state.day_number,
        "encounter_order": list(state.encounter_order),
        "current_encounter_index": state.current_encounter_index,
        "completed": state.completed,
        "party": _serialize_adventuring_party(state.party),
        "world_state": serialize_world_exploration_state(state.world_state),
        "encounter_history": [
            {
                "encounter_id": checkpoint.encounter_id,
                "outcome": checkpoint.outcome,
                "rest_applied": checkpoint.rest_applied,
                "world_day": checkpoint.world_day,
                "world_minute_of_day": checkpoint.world_minute_of_day,
                "party": _serialize_adventuring_party(checkpoint.party),
            }
            for checkpoint in state.encounter_history
        ],
    }


def deserialize_adventuring_day_state(payload: Mapping[str, Any]) -> AdventuringDayState:
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a mapping")

    encounter_order_raw = payload.get("encounter_order", [])
    if not isinstance(encounter_order_raw, (list, tuple)):
        raise ValueError("encounter_order must be a list or tuple")
    encounter_order = tuple(
        _required_text(entry, field_name="encounter_order entry") for entry in encounter_order_raw
    )

    completed_raw = payload.get("completed", False)
    if not isinstance(completed_raw, bool):
        raise ValueError("completed must be a bool")

    history_raw = payload.get("encounter_history", [])
    if not isinstance(history_raw, list):
        raise ValueError("encounter_history must be a list")
    encounter_history: list[EncounterCheckpoint] = []
    for row in history_raw:
        if not isinstance(row, Mapping):
            raise ValueError("encounter_history entries must be mappings")
        encounter_history.append(
            EncounterCheckpoint(
                encounter_id=_required_text(row.get("encounter_id"), field_name="encounter_id"),
                outcome=_required_text(row.get("outcome"), field_name="outcome"),
                rest_applied=_required_text(
                    row.get("rest_applied", row.get("rest", "none")),
                    field_name="rest_applied",
                ),
                party=_deserialize_adventuring_party(row.get("party")),
                world_day=_required_int(row.get("world_day"), field_name="world_day"),
                world_minute_of_day=_required_int(
                    row.get("world_minute_of_day"),
                    field_name="world_minute_of_day",
                ),
            )
        )

    world_state_payload = payload.get("world_state")
    if not isinstance(world_state_payload, Mapping):
        raise ValueError("world_state must be a mapping")

    return AdventuringDayState(
        campaign_id=_required_text(payload.get("campaign_id"), field_name="campaign_id"),
        day_number=_required_int(payload.get("day_number"), field_name="day_number"),
        encounter_order=encounter_order,
        current_encounter_index=_required_int(
            payload.get("current_encounter_index"),
            field_name="current_encounter_index",
        ),
        party=_deserialize_adventuring_party(payload.get("party")),
        world_state=deserialize_world_exploration_state(world_state_payload),
        encounter_history=tuple(encounter_history),
        completed=completed_raw,
    )
