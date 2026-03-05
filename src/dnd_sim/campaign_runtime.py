from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from dnd_sim.world_runtime import ExplorationState, run_exploration_turn

REST_NONE = "none"
REST_SHORT = "short"
REST_LONG = "long"
REST_MODES = (REST_NONE, REST_SHORT, REST_LONG)


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


def _validate_resource_mapping(value: Mapping[str, Any], *, field_name: str) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for key, raw_amount in sorted(dict(value).items()):
        resource_key = _required_text(key, field_name=f"{field_name} key")
        amount = _required_int(raw_amount, field_name=f"{field_name}[{resource_key}]")
        if amount < 0:
            raise ValueError(f"{field_name}[{resource_key}] must be >= 0")
        normalized[resource_key] = amount
    return normalized


def _normalize_text_tuple(values: Any, *, field_name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field_name} must be a list or tuple")
    normalized = sorted({_required_text(value, field_name=field_name) for value in values})
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class AdventuringActorState:
    actor_id: str
    hit_points: int
    max_hit_points: int
    resources: dict[str, int]
    max_resources: dict[str, int]
    short_rest_recovery: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        actor_id = _required_text(self.actor_id, field_name="actor_id")
        hit_points = _required_int(self.hit_points, field_name="hit_points")
        max_hit_points = _required_int(self.max_hit_points, field_name="max_hit_points")
        if max_hit_points <= 0:
            raise ValueError("max_hit_points must be > 0")
        if hit_points < 0 or hit_points > max_hit_points:
            raise ValueError("hit_points must be between 0 and max_hit_points")

        if not isinstance(self.resources, Mapping):
            raise ValueError("resources must be a mapping")
        if not isinstance(self.max_resources, Mapping):
            raise ValueError("max_resources must be a mapping")

        max_resources = _validate_resource_mapping(self.max_resources, field_name="max_resources")
        resources = _validate_resource_mapping(self.resources, field_name="resources")
        for resource_key, amount in resources.items():
            max_value = max_resources.get(resource_key)
            if max_value is not None and amount > max_value:
                raise ValueError(
                    f"resources[{resource_key}] cannot exceed max_resources[{resource_key}]"
                )

        short_rest_recovery = _normalize_text_tuple(
            self.short_rest_recovery,
            field_name="short_rest_recovery",
        )
        conditions = _normalize_text_tuple(self.conditions, field_name="conditions")

        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "hit_points", hit_points)
        object.__setattr__(self, "max_hit_points", max_hit_points)
        object.__setattr__(self, "resources", resources)
        object.__setattr__(self, "max_resources", max_resources)
        object.__setattr__(self, "short_rest_recovery", short_rest_recovery)
        object.__setattr__(self, "conditions", conditions)


@dataclass(frozen=True, slots=True)
class EncounterCheckpoint:
    encounter_id: str
    outcome: str
    rest_applied: str
    party: dict[str, AdventuringActorState]
    world_day: int
    world_minute_of_day: int

    def __post_init__(self) -> None:
        encounter_id = _required_text(self.encounter_id, field_name="encounter_id")
        outcome = _required_text(self.outcome, field_name="outcome")
        rest_applied = _required_text(self.rest_applied, field_name="rest_applied")
        if rest_applied not in REST_MODES:
            raise ValueError(f"rest_applied must be one of {REST_MODES}")

        if not isinstance(self.party, Mapping):
            raise ValueError("party must be a mapping")
        normalized_party: dict[str, AdventuringActorState] = {}
        for actor_id, actor in sorted(dict(self.party).items()):
            key = _required_text(actor_id, field_name="party actor_id")
            if not isinstance(actor, AdventuringActorState):
                raise ValueError("party values must be AdventuringActorState")
            if actor.actor_id != key:
                raise ValueError("party actor key must match actor_id")
            normalized_party[key] = actor

        world_day = _required_int(self.world_day, field_name="world_day")
        world_minute_of_day = _required_int(
            self.world_minute_of_day,
            field_name="world_minute_of_day",
        )
        if world_day < 1:
            raise ValueError("world_day must be >= 1")
        if world_minute_of_day < 0 or world_minute_of_day >= (24 * 60):
            raise ValueError("world_minute_of_day must be between 0 and 1439")

        object.__setattr__(self, "encounter_id", encounter_id)
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "rest_applied", rest_applied)
        object.__setattr__(self, "party", normalized_party)
        object.__setattr__(self, "world_day", world_day)
        object.__setattr__(self, "world_minute_of_day", world_minute_of_day)


@dataclass(frozen=True, slots=True)
class AdventuringDayState:
    campaign_id: str
    day_number: int
    encounter_order: tuple[str, ...]
    current_encounter_index: int
    party: dict[str, AdventuringActorState]
    world_state: ExplorationState
    encounter_history: tuple[EncounterCheckpoint, ...] = ()
    completed: bool = False

    def __post_init__(self) -> None:
        campaign_id = _required_text(self.campaign_id, field_name="campaign_id")
        day_number = _required_int(self.day_number, field_name="day_number")
        if day_number < 1:
            raise ValueError("day_number must be >= 1")

        if not isinstance(self.encounter_order, (list, tuple)):
            raise ValueError("encounter_order must be a sequence")
        encounter_order = tuple(
            _required_text(encounter_id, field_name="encounter_order entry")
            for encounter_id in self.encounter_order
        )

        current_encounter_index = _required_int(
            self.current_encounter_index,
            field_name="current_encounter_index",
        )
        if current_encounter_index < 0 or current_encounter_index > len(encounter_order):
            raise ValueError("current_encounter_index is out of range")

        if not isinstance(self.party, Mapping):
            raise ValueError("party must be a mapping")
        normalized_party: dict[str, AdventuringActorState] = {}
        for actor_id, actor in sorted(dict(self.party).items()):
            key = _required_text(actor_id, field_name="party actor_id")
            if not isinstance(actor, AdventuringActorState):
                raise ValueError("party values must be AdventuringActorState")
            if actor.actor_id != key:
                raise ValueError("party actor key must match actor_id")
            normalized_party[key] = actor

        if not isinstance(self.world_state, ExplorationState):
            raise ValueError("world_state must be an ExplorationState")

        if not isinstance(self.encounter_history, (list, tuple)):
            raise ValueError("encounter_history must be a sequence")
        history = tuple(self.encounter_history)
        for item in history:
            if not isinstance(item, EncounterCheckpoint):
                raise ValueError("encounter_history entries must be EncounterCheckpoint")

        completed = bool(self.completed)
        if current_encounter_index >= len(encounter_order):
            completed = True

        object.__setattr__(self, "campaign_id", campaign_id)
        object.__setattr__(self, "day_number", day_number)
        object.__setattr__(self, "encounter_order", encounter_order)
        object.__setattr__(self, "current_encounter_index", current_encounter_index)
        object.__setattr__(self, "party", normalized_party)
        object.__setattr__(self, "encounter_history", history)
        object.__setattr__(self, "completed", completed)


def _actor_state_from_mapping(actor_id: str, payload: Mapping[str, Any]) -> AdventuringActorState:
    return AdventuringActorState(
        actor_id=_required_text(payload.get("actor_id", actor_id), field_name="actor_id"),
        hit_points=_required_int(payload.get("hit_points"), field_name="hit_points"),
        max_hit_points=_required_int(payload.get("max_hit_points"), field_name="max_hit_points"),
        resources=dict(payload.get("resources", {})),
        max_resources=dict(payload.get("max_resources", {})),
        short_rest_recovery=tuple(payload.get("short_rest_recovery", ())),
        conditions=tuple(payload.get("conditions", ())),
    )


def _normalize_party_input(
    party: Mapping[str, AdventuringActorState | Mapping[str, Any]],
) -> dict[str, AdventuringActorState]:
    if not isinstance(party, Mapping):
        raise ValueError("party must be a mapping")

    normalized: dict[str, AdventuringActorState] = {}
    for actor_id, actor_payload in sorted(dict(party).items()):
        key = _required_text(actor_id, field_name="party actor_id")
        if isinstance(actor_payload, AdventuringActorState):
            actor = actor_payload
        elif isinstance(actor_payload, Mapping):
            actor = _actor_state_from_mapping(key, actor_payload)
        else:
            raise ValueError("party values must be AdventuringActorState or mappings")
        if actor.actor_id != key:
            raise ValueError("party actor key must match actor_id")
        normalized[key] = actor
    return normalized


def create_adventuring_day_state(
    *,
    campaign_id: str,
    day_number: int,
    encounter_order: tuple[str, ...] | list[str],
    party: Mapping[str, AdventuringActorState | Mapping[str, Any]],
    world_state: ExplorationState,
) -> AdventuringDayState:
    normalized_party = _normalize_party_input(party)
    return AdventuringDayState(
        campaign_id=campaign_id,
        day_number=day_number,
        encounter_order=tuple(encounter_order),
        current_encounter_index=0,
        party=normalized_party,
        world_state=world_state,
        encounter_history=(),
        completed=len(tuple(encounter_order)) == 0,
    )


def current_encounter_id(state: AdventuringDayState) -> str | None:
    if state.current_encounter_index >= len(state.encounter_order):
        return None
    return state.encounter_order[state.current_encounter_index]


def apply_short_rest_to_party(
    party: Mapping[str, AdventuringActorState],
    *,
    healing: int = 0,
) -> dict[str, AdventuringActorState]:
    healing_value = _required_int(healing, field_name="healing")
    if healing_value < 0:
        raise ValueError("healing must be >= 0")

    normalized_party = _normalize_party_input(party)
    rested: dict[str, AdventuringActorState] = {}
    for actor_id, actor in normalized_party.items():
        resources = dict(actor.resources)
        for resource_key in actor.short_rest_recovery:
            max_value = int(actor.max_resources.get(resource_key, resources.get(resource_key, 0)))
            resources[resource_key] = max_value

        rested[actor_id] = AdventuringActorState(
            actor_id=actor_id,
            hit_points=min(actor.max_hit_points, actor.hit_points + healing_value),
            max_hit_points=actor.max_hit_points,
            resources=resources,
            max_resources=dict(actor.max_resources),
            short_rest_recovery=actor.short_rest_recovery,
            conditions=actor.conditions,
        )
    return rested


def apply_long_rest_to_party(
    party: Mapping[str, AdventuringActorState],
) -> dict[str, AdventuringActorState]:
    normalized_party = _normalize_party_input(party)
    rested: dict[str, AdventuringActorState] = {}
    for actor_id, actor in normalized_party.items():
        resources = dict(actor.resources)
        for resource_key, max_value in actor.max_resources.items():
            resources[resource_key] = max_value

        rested[actor_id] = AdventuringActorState(
            actor_id=actor_id,
            hit_points=actor.max_hit_points,
            max_hit_points=actor.max_hit_points,
            resources=resources,
            max_resources=dict(actor.max_resources),
            short_rest_recovery=actor.short_rest_recovery,
            conditions=(),
        )
    return rested


def advance_adventuring_day(
    state: AdventuringDayState,
    *,
    encounter_id: str,
    outcome: str,
    party_after_encounter: Mapping[str, AdventuringActorState | Mapping[str, Any]],
    rest: str = REST_NONE,
    short_rest_healing: int = 0,
    exploration_activity: str | None = None,
    exploration_minutes: int = 0,
) -> AdventuringDayState:
    expected_encounter_id = current_encounter_id(state)
    if expected_encounter_id is None:
        raise ValueError("adventuring day is already complete")

    normalized_encounter_id = _required_text(encounter_id, field_name="encounter_id")
    if normalized_encounter_id != expected_encounter_id:
        raise ValueError("encounter_id does not match expected encounter")

    rest_mode = _required_text(rest, field_name="rest")
    if rest_mode not in REST_MODES:
        raise ValueError(f"rest must be one of {REST_MODES}")

    normalized_party = _normalize_party_input(party_after_encounter)
    if rest_mode == REST_SHORT:
        normalized_party = apply_short_rest_to_party(
            normalized_party,
            healing=short_rest_healing,
        )
    elif rest_mode == REST_LONG:
        normalized_party = apply_long_rest_to_party(normalized_party)

    minutes = _required_int(exploration_minutes, field_name="exploration_minutes")
    if minutes < 0:
        raise ValueError("exploration_minutes must be >= 0")

    world_state = state.world_state
    if minutes > 0:
        activity = exploration_activity if exploration_activity is not None else "travel"
        world_state = run_exploration_turn(
            world_state,
            activity=activity,
            elapsed_minutes=minutes,
        ).state

    history = list(state.encounter_history)
    history.append(
        EncounterCheckpoint(
            encounter_id=normalized_encounter_id,
            outcome=_required_text(outcome, field_name="outcome"),
            rest_applied=rest_mode,
            party=normalized_party,
            world_day=world_state.clock.day,
            world_minute_of_day=world_state.clock.minute_of_day,
        )
    )

    next_encounter_index = state.current_encounter_index + 1
    completed = next_encounter_index >= len(state.encounter_order)

    return AdventuringDayState(
        campaign_id=state.campaign_id,
        day_number=world_state.clock.day,
        encounter_order=state.encounter_order,
        current_encounter_index=next_encounter_index,
        party=normalized_party,
        world_state=world_state,
        encounter_history=tuple(history),
        completed=completed,
    )
