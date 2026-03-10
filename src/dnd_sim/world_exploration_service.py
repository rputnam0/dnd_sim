from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dnd_sim.exploration_interaction import (
    ExplorationInteractionState,
    deserialize_interaction_state,
)
from dnd_sim.world_contracts import (
    MINUTES_PER_DAY,
    TURN_PHASES,
    ExplorationState,
    ExplorationTurnResult,
    LightSourceState,
    WorldClock,
    _canonicalize_light,
    _normalize_light_source_entry,
    _required_text,
)


def create_exploration_state(
    *,
    day: int,
    hour: int,
    minute: int,
    location_id: str | None = None,
    turn_index: int = 0,
    light_sources: dict[str, int | LightSourceState] | None = None,
    interaction_state: ExplorationInteractionState | Mapping[str, Any] | None = None,
) -> ExplorationState:
    if not isinstance(hour, int) or isinstance(hour, bool) or hour < 0 or hour > 23:
        raise ValueError("hour must be an integer from 0 to 23")
    if not isinstance(minute, int) or isinstance(minute, bool) or minute < 0 or minute > 59:
        raise ValueError("minute must be an integer from 0 to 59")

    if interaction_state is None:
        normalized_interaction_state = ExplorationInteractionState()
    elif isinstance(interaction_state, ExplorationInteractionState):
        normalized_interaction_state = interaction_state
    elif isinstance(interaction_state, Mapping):
        normalized_interaction_state = deserialize_interaction_state(interaction_state)
    else:
        raise ValueError("interaction_state must be ExplorationInteractionState, mapping, or None")

    normalized_lights: dict[str, LightSourceState] = {}
    for source_id, value in sorted((light_sources or {}).items()):
        normalized_source_id = _required_text(source_id, field_name="source_id")
        normalized_lights[normalized_source_id] = _normalize_light_source_entry(
            normalized_source_id,
            value,
        )

    return ExplorationState(
        turn_index=turn_index,
        clock=WorldClock(day=day, minute_of_day=(hour * 60) + minute),
        location_id=location_id,
        light_sources=normalized_lights,
        interaction_state=normalized_interaction_state,
    )


def advance_world_clock(clock: WorldClock, *, elapsed_minutes: int) -> WorldClock:
    if (
        not isinstance(elapsed_minutes, int)
        or isinstance(elapsed_minutes, bool)
        or elapsed_minutes < 0
    ):
        raise ValueError("elapsed_minutes must be an integer >= 0")

    absolute_minutes = ((clock.day - 1) * MINUTES_PER_DAY) + clock.minute_of_day + elapsed_minutes
    day = (absolute_minutes // MINUTES_PER_DAY) + 1
    minute_of_day = absolute_minutes % MINUTES_PER_DAY
    return WorldClock(day=day, minute_of_day=minute_of_day)


def _decay_lights(
    light_sources: dict[str, LightSourceState],
    *,
    elapsed_minutes: int,
) -> tuple[dict[str, LightSourceState], tuple[str, ...]]:
    decayed: dict[str, LightSourceState] = {}
    depleted: list[str] = []

    for source_id, light in sorted(light_sources.items()):
        normalized = _canonicalize_light(light)
        if not normalized.is_lit:
            decayed[source_id] = normalized
            continue

        remaining = max(0, normalized.remaining_minutes - elapsed_minutes)
        is_lit = remaining > 0
        decayed[source_id] = LightSourceState(
            source_id=source_id,
            remaining_minutes=remaining,
            is_lit=is_lit,
        )
        if normalized.remaining_minutes > 0 and remaining == 0:
            depleted.append(source_id)

    return decayed, tuple(depleted)


def run_exploration_turn(
    state: ExplorationState,
    *,
    activity: str,
    elapsed_minutes: int,
) -> ExplorationTurnResult:
    activity_name = _required_text(activity, field_name="activity")
    if (
        not isinstance(elapsed_minutes, int)
        or isinstance(elapsed_minutes, bool)
        or elapsed_minutes <= 0
    ):
        raise ValueError("elapsed_minutes must be > 0")

    start_clock = state.clock
    end_clock = advance_world_clock(start_clock, elapsed_minutes=elapsed_minutes)
    light_sources, depleted_light_sources = _decay_lights(
        state.light_sources,
        elapsed_minutes=elapsed_minutes,
    )

    next_state = ExplorationState(
        turn_index=state.turn_index + 1,
        clock=end_clock,
        location_id=state.location_id,
        light_sources=light_sources,
        interaction_state=state.interaction_state,
    )

    return ExplorationTurnResult(
        state=next_state,
        activity=activity_name,
        elapsed_minutes=elapsed_minutes,
        phases=TURN_PHASES,
        start_clock=start_clock,
        end_clock=end_clock,
        depleted_light_sources=depleted_light_sources,
    )


def day_cycle_phase(clock: WorldClock) -> str:
    if not isinstance(clock, WorldClock):
        raise ValueError("clock must be a WorldClock")

    minute = clock.minute_of_day
    if 5 * 60 <= minute < 8 * 60:
        return "dawn"
    if 8 * 60 <= minute < 18 * 60:
        return "day"
    if 18 * 60 <= minute < 20 * 60:
        return "dusk"
    return "night"
