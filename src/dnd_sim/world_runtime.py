from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dnd_sim.world_hazards import (
    HazardActorState,
    HazardResolution,
    WorldHazardState,
    advance_disease_progression,
    advance_poison,
    apply_disease_exposure,
    apply_poison_exposure,
    create_world_hazard_state as _create_world_hazard_state,
    deserialize_world_hazard_state as _deserialize_world_hazard_state,
    resolve_environmental_exposure,
    serialize_world_hazard_state as _serialize_world_hazard_state,
)

MINUTES_PER_DAY = 24 * 60
TURN_PHASES = (
    "declare_intent",
    "resolve_activity",
    "advance_time",
    "update_lights",
)


@dataclass(frozen=True, slots=True)
class WorldClock:
    day: int
    minute_of_day: int

    def __post_init__(self) -> None:
        if not isinstance(self.day, int) or isinstance(self.day, bool) or self.day < 1:
            raise ValueError("day must be an integer >= 1")
        if (
            not isinstance(self.minute_of_day, int)
            or isinstance(self.minute_of_day, bool)
            or self.minute_of_day < 0
            or self.minute_of_day >= MINUTES_PER_DAY
        ):
            raise ValueError("minute_of_day must be an integer from 0 to 1439")

    @property
    def hour(self) -> int:
        return self.minute_of_day // 60

    @property
    def minute(self) -> int:
        return self.minute_of_day % 60


@dataclass(frozen=True, slots=True)
class LightSourceState:
    source_id: str
    remaining_minutes: int
    is_lit: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str):
            raise ValueError("source_id must be a string")
        normalized = self.source_id.strip()
        if not normalized:
            raise ValueError("source_id must be non-empty")
        if (
            not isinstance(self.remaining_minutes, int)
            or isinstance(self.remaining_minutes, bool)
            or self.remaining_minutes < 0
        ):
            raise ValueError("remaining_minutes must be an integer >= 0")
        if not isinstance(self.is_lit, bool):
            raise ValueError("is_lit must be a bool")
        object.__setattr__(self, "source_id", normalized)


@dataclass(frozen=True, slots=True)
class ExplorationState:
    turn_index: int
    clock: WorldClock
    light_sources: dict[str, LightSourceState]
    location_id: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.turn_index, int)
            or isinstance(self.turn_index, bool)
            or self.turn_index < 0
        ):
            raise ValueError("turn_index must be an integer >= 0")
        if not isinstance(self.clock, WorldClock):
            raise ValueError("clock must be a WorldClock")

        location = self.location_id
        if location is not None:
            if not isinstance(location, str):
                raise ValueError("location_id must be a string when provided")
            location = location.strip() or None

        normalized_lights: dict[str, LightSourceState] = {}
        for source_id, light in sorted(dict(self.light_sources).items()):
            if not isinstance(source_id, str):
                raise ValueError("light source ids must be strings")
            key = source_id.strip()
            if not key:
                raise ValueError("light source ids must be non-empty")
            if not isinstance(light, LightSourceState):
                raise ValueError("light_sources must contain LightSourceState values")
            normalized_light = _canonicalize_light(light)
            if normalized_light.source_id != key:
                normalized_light = LightSourceState(
                    source_id=key,
                    remaining_minutes=normalized_light.remaining_minutes,
                    is_lit=normalized_light.is_lit,
                )
            normalized_lights[key] = normalized_light

        object.__setattr__(self, "location_id", location)
        object.__setattr__(self, "light_sources", normalized_lights)


@dataclass(frozen=True, slots=True)
class ExplorationTurnResult:
    state: ExplorationState
    activity: str
    elapsed_minutes: int
    phases: tuple[str, ...]
    start_clock: WorldClock
    end_clock: WorldClock
    depleted_light_sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorldHazardTurnResult:
    state: WorldHazardState
    elapsed_minutes: int
    events: tuple[HazardResolution, ...]
    poison_tick: HazardResolution
    disease_tick: HazardResolution


def _required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _canonicalize_light(light: LightSourceState) -> LightSourceState:
    if light.remaining_minutes == 0 and light.is_lit:
        return LightSourceState(
            source_id=light.source_id,
            remaining_minutes=0,
            is_lit=False,
        )
    return light


def _normalize_light_source_entry(
    source_id: str, value: int | LightSourceState
) -> LightSourceState:
    if isinstance(value, LightSourceState):
        light = value
    elif isinstance(value, int) and not isinstance(value, bool):
        if value < 0:
            raise ValueError("remaining_minutes must be an integer >= 0")
        light = LightSourceState(
            source_id=source_id,
            remaining_minutes=value,
            is_lit=value > 0,
        )
    else:
        raise ValueError("light source values must be integers or LightSourceState")

    if light.source_id != source_id:
        light = LightSourceState(
            source_id=source_id,
            remaining_minutes=light.remaining_minutes,
            is_lit=light.is_lit,
        )
    return _canonicalize_light(light)


def create_exploration_state(
    *,
    day: int,
    hour: int,
    minute: int,
    location_id: str | None = None,
    turn_index: int = 0,
    light_sources: dict[str, int | LightSourceState] | None = None,
) -> ExplorationState:
    if not isinstance(hour, int) or isinstance(hour, bool) or hour < 0 or hour > 23:
        raise ValueError("hour must be an integer from 0 to 23")
    if not isinstance(minute, int) or isinstance(minute, bool) or minute < 0 or minute > 59:
        raise ValueError("minute must be an integer from 0 to 59")

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


def create_world_hazard_state(
    *,
    actors: dict[str, HazardActorState | dict[str, Any]] | None = None,
    minute_index: int = 0,
) -> WorldHazardState:
    return _create_world_hazard_state(actors=actors, minute_index=minute_index)


def serialize_world_hazard_state(state: WorldHazardState) -> dict[str, Any]:
    return _serialize_world_hazard_state(state)


def deserialize_world_hazard_state(payload: dict[str, Any]) -> WorldHazardState:
    return _deserialize_world_hazard_state(payload)


def run_world_hazard_turn(
    state: WorldHazardState,
    *,
    elapsed_minutes: int,
    exposure_checks: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    disease_save_outcomes: dict[str, bool] | None = None,
) -> WorldHazardTurnResult:
    if (
        not isinstance(elapsed_minutes, int)
        or isinstance(elapsed_minutes, bool)
        or elapsed_minutes <= 0
    ):
        raise ValueError("elapsed_minutes must be > 0")

    current_state = state
    events: list[HazardResolution] = []

    for check in exposure_checks:
        if not isinstance(check, dict):
            raise ValueError("exposure_checks must contain mapping entries")
        actor_id = check.get("actor_id")
        hazard_type = check.get("hazard_type")
        if actor_id is None or hazard_type is None:
            raise ValueError("exposure checks require actor_id and hazard_type")

        exposure = resolve_environmental_exposure(
            current_state,
            actor_id=str(actor_id),
            hazard_type=str(hazard_type),
            save_succeeded=bool(check.get("save_succeeded", False)),
            on_failure_damage=int(check.get("on_failure_damage", 0)),
            failure_exhaustion=int(check.get("failure_exhaustion", 1)),
        )
        current_state = exposure.state
        events.append(exposure)

        poison_duration = check.get("poison_duration_minutes")
        if poison_duration is not None:
            poison_exposure = apply_poison_exposure(
                current_state,
                actor_id=str(actor_id),
                duration_minutes=int(poison_duration),
                save_succeeded=bool(check.get("save_succeeded", False)),
            )
            current_state = poison_exposure.state
            events.append(poison_exposure)

        disease_id = check.get("disease_id")
        if disease_id is not None:
            disease_exposure = apply_disease_exposure(
                current_state,
                actor_id=str(actor_id),
                disease_id=str(disease_id),
                incubation_hours=int(check.get("incubation_hours", 24)),
                save_succeeded=bool(check.get("save_succeeded", False)),
            )
            current_state = disease_exposure.state
            events.append(disease_exposure)

    poison_tick = advance_poison(current_state, elapsed_minutes=elapsed_minutes)
    disease_tick = advance_disease_progression(
        poison_tick.state,
        elapsed_minutes=elapsed_minutes,
        save_outcomes=disease_save_outcomes,
    )

    return WorldHazardTurnResult(
        state=disease_tick.state,
        elapsed_minutes=elapsed_minutes,
        events=tuple(events),
        poison_tick=poison_tick,
        disease_tick=disease_tick,
    )
