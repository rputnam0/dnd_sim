from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from dnd_sim.economy import CraftingProject, CraftingRecipe, apply_crafting_days
from dnd_sim.exploration_interaction import (
    ExplorationInteractionState,
    deserialize_interaction_state,
)
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

logger = logging.getLogger(__name__)

MINUTES_PER_DAY = 24 * 60
TURN_PHASES = (
    "declare_intent",
    "resolve_activity",
    "advance_time",
    "update_lights",
)
TRAVEL_PACE_MILES_PER_DAY: dict[str, float] = {"slow": 18.0, "normal": 24.0, "fast": 30.0}
TRAVEL_PACE_NAVIGATION_DC_MODIFIER: dict[str, int] = {"slow": -2, "normal": 0, "fast": 2}
TRAVEL_PACE_FORAGING_DC_MODIFIER: dict[str, int] = {"slow": -2, "normal": 0, "fast": 5}
REST_NONE = "none"
REST_SHORT = "short"
REST_LONG = "long"
REST_MODES = (REST_NONE, REST_SHORT, REST_LONG)
ENCUMBRANCE_UNENCUMBERED = "unencumbered"
ENCUMBRANCE_ENCUMBERED = "encumbered"
ENCUMBRANCE_HEAVILY_ENCUMBERED = "heavily_encumbered"
ENCUMBRANCE_OVER_CAPACITY = "over_capacity"
ENCUMBRANCE_STATES = (
    ENCUMBRANCE_UNENCUMBERED,
    ENCUMBRANCE_ENCUMBERED,
    ENCUMBRANCE_HEAVILY_ENCUMBERED,
    ENCUMBRANCE_OVER_CAPACITY,
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
    interaction_state: ExplorationInteractionState = field(
        default_factory=ExplorationInteractionState
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.turn_index, int)
            or isinstance(self.turn_index, bool)
            or self.turn_index < 0
        ):
            raise ValueError("turn_index must be an integer >= 0")
        if not isinstance(self.clock, WorldClock):
            raise ValueError("clock must be a WorldClock")
        if not isinstance(self.interaction_state, ExplorationInteractionState):
            raise ValueError("interaction_state must be an ExplorationInteractionState")

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


@dataclass(frozen=True, slots=True)
class TravelPaceOutcome:
    travel_pace: str
    distance_miles: float
    miles_per_day: float
    segments: int
    travel_minutes: int


@dataclass(frozen=True, slots=True)
class NavigationOutcome:
    success: bool
    check_total: int
    effective_dc: int
    margin: int
    lost_minutes: int
    encounter_check_required: bool


@dataclass(frozen=True, slots=True)
class ForagingOutcome:
    success: bool
    check_total: int
    effective_dc: int
    margin: int
    supplies_found: int
    encounter_check_required: bool


@dataclass(frozen=True, slots=True)
class TravelPartyMemberState:
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
class RestCycleOutcome:
    state: ExplorationState
    party: dict[str, TravelPartyMemberState]
    rest_mode: str
    elapsed_minutes: int
    day_cycle: str


@dataclass(frozen=True, slots=True)
class TravelAndRestCycleOutcome:
    state: ExplorationState
    party: dict[str, TravelPartyMemberState]
    travel: TravelPaceOutcome
    navigation: NavigationOutcome
    foraging: ForagingOutcome | None
    rest: RestCycleOutcome
    random_encounter_check: bool
    total_elapsed_minutes: int
    day_cycle_start: str
    day_cycle_end: str


@dataclass(frozen=True, slots=True)
class EncumbranceStatus:
    carried_weight_lb: float
    strength_score: int
    light_threshold_lb: float
    heavy_threshold_lb: float
    max_threshold_lb: float
    state: str
    speed_penalty_ft: int
    travel_allowed: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "carried_weight_lb",
            _required_non_negative_number(
                self.carried_weight_lb,
                field_name="carried_weight_lb",
            ),
        )
        strength_score = _required_int(self.strength_score, field_name="strength_score")
        if strength_score <= 0:
            raise ValueError("strength_score must be > 0")
        object.__setattr__(self, "strength_score", strength_score)
        object.__setattr__(
            self,
            "light_threshold_lb",
            _required_non_negative_number(
                self.light_threshold_lb,
                field_name="light_threshold_lb",
            ),
        )
        object.__setattr__(
            self,
            "heavy_threshold_lb",
            _required_non_negative_number(
                self.heavy_threshold_lb,
                field_name="heavy_threshold_lb",
            ),
        )
        object.__setattr__(
            self,
            "max_threshold_lb",
            _required_non_negative_number(
                self.max_threshold_lb,
                field_name="max_threshold_lb",
            ),
        )
        state = _required_text(self.state, field_name="state").lower()
        if state not in ENCUMBRANCE_STATES:
            raise ValueError(f"state must be one of {ENCUMBRANCE_STATES}")
        object.__setattr__(self, "state", state)
        speed_penalty_ft = _required_int(self.speed_penalty_ft, field_name="speed_penalty_ft")
        if speed_penalty_ft < 0:
            raise ValueError("speed_penalty_ft must be >= 0")
        object.__setattr__(self, "speed_penalty_ft", speed_penalty_ft)
        if not isinstance(self.travel_allowed, bool):
            raise ValueError("travel_allowed must be a bool")


@dataclass(frozen=True, slots=True)
class DowntimeState:
    clock: WorldClock
    turn_index: int
    downtime_days_remaining: int
    wallet_cp: int
    strength_score: int
    carried_weight_lb: float = 0.0
    inventory: dict[str, int] = field(default_factory=dict)
    crafting_projects: dict[str, CraftingProject] = field(default_factory=dict)
    service_effects: dict[str, int] = field(default_factory=dict)
    location_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.clock, WorldClock):
            raise ValueError("clock must be a WorldClock")
        turn_index = _required_int(self.turn_index, field_name="turn_index")
        if turn_index < 0:
            raise ValueError("turn_index must be >= 0")
        object.__setattr__(self, "turn_index", turn_index)
        object.__setattr__(
            self,
            "downtime_days_remaining",
            _required_int(
                self.downtime_days_remaining,
                field_name="downtime_days_remaining",
            ),
        )
        if self.downtime_days_remaining < 0:
            raise ValueError("downtime_days_remaining must be >= 0")
        object.__setattr__(self, "wallet_cp", _required_int(self.wallet_cp, field_name="wallet_cp"))
        if self.wallet_cp < 0:
            raise ValueError("wallet_cp must be >= 0")
        strength_score = _required_int(self.strength_score, field_name="strength_score")
        if strength_score <= 0:
            raise ValueError("strength_score must be > 0")
        object.__setattr__(self, "strength_score", strength_score)
        object.__setattr__(
            self,
            "carried_weight_lb",
            _required_non_negative_number(
                self.carried_weight_lb,
                field_name="carried_weight_lb",
            ),
        )

        location = self.location_id
        if location is not None:
            if not isinstance(location, str):
                raise ValueError("location_id must be a string when provided")
            location = location.strip() or None
        object.__setattr__(self, "location_id", location)
        object.__setattr__(
            self,
            "inventory",
            _normalize_non_negative_int_mapping(self.inventory, field_name="inventory"),
        )
        object.__setattr__(
            self,
            "crafting_projects",
            _normalize_crafting_project_mapping(self.crafting_projects),
        )
        object.__setattr__(
            self,
            "service_effects",
            _normalize_non_negative_int_mapping(self.service_effects, field_name="service_effects"),
        )


@dataclass(frozen=True, slots=True)
class DowntimeActionResult:
    state: DowntimeState
    action: str
    downtime_days_spent: int
    elapsed_minutes: int
    completed_batches: int = 0
    cost_paid_cp: int = 0
    encumbrance: EncumbranceStatus | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, DowntimeState):
            raise ValueError("state must be DowntimeState")
        object.__setattr__(self, "action", _required_text(self.action, field_name="action"))
        days_spent = _required_int(self.downtime_days_spent, field_name="downtime_days_spent")
        if days_spent < 0:
            raise ValueError("downtime_days_spent must be >= 0")
        object.__setattr__(self, "downtime_days_spent", days_spent)
        elapsed_minutes = _required_int(self.elapsed_minutes, field_name="elapsed_minutes")
        if elapsed_minutes < 0:
            raise ValueError("elapsed_minutes must be >= 0")
        object.__setattr__(self, "elapsed_minutes", elapsed_minutes)
        completed_batches = _required_int(self.completed_batches, field_name="completed_batches")
        if completed_batches < 0:
            raise ValueError("completed_batches must be >= 0")
        object.__setattr__(self, "completed_batches", completed_batches)
        cost_paid_cp = _required_int(self.cost_paid_cp, field_name="cost_paid_cp")
        if cost_paid_cp < 0:
            raise ValueError("cost_paid_cp must be >= 0")
        object.__setattr__(self, "cost_paid_cp", cost_paid_cp)
        if self.encumbrance is not None and not isinstance(self.encumbrance, EncumbranceStatus):
            raise ValueError("encumbrance must be EncumbranceStatus or None")


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


def _required_non_negative_number(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be a number")
    normalized = float(value)
    if math.isnan(normalized) or math.isinf(normalized) or normalized < 0:
        raise ValueError(f"{field_name} must be a finite number >= 0")
    return normalized


def _normalize_non_negative_int_mapping(
    value: Mapping[str, Any],
    *,
    field_name: str,
) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")

    normalized: dict[str, int] = {}
    for key, raw_amount in sorted(dict(value).items()):
        normalized_key = _required_text(key, field_name=f"{field_name} key")
        amount = _required_int(raw_amount, field_name=f"{field_name}[{normalized_key}]")
        if amount < 0:
            raise ValueError(f"{field_name}[{normalized_key}] must be >= 0")
        if amount > 0:
            normalized[normalized_key] = amount
    return normalized


def _coerce_crafting_project(
    value: CraftingProject | Mapping[str, Any], *, recipe_id: str
) -> CraftingProject:
    if isinstance(value, CraftingProject):
        if value.recipe_id == recipe_id:
            return value
        return CraftingProject(recipe_id=recipe_id, accrued_days=value.accrued_days)
    if not isinstance(value, Mapping):
        raise ValueError("crafting_projects values must be CraftingProject or mappings")
    return CraftingProject(
        recipe_id=_required_text(value.get("recipe_id", recipe_id), field_name="recipe_id"),
        accrued_days=_required_int(value.get("accrued_days", 0), field_name="accrued_days"),
    )


def _normalize_crafting_project_mapping(value: Mapping[str, Any]) -> dict[str, CraftingProject]:
    if not isinstance(value, Mapping):
        raise ValueError("crafting_projects must be a mapping")
    normalized: dict[str, CraftingProject] = {}
    for recipe_id, project in sorted(dict(value).items()):
        normalized_recipe_id = _required_text(recipe_id, field_name="recipe_id")
        normalized[normalized_recipe_id] = _coerce_crafting_project(
            project,
            recipe_id=normalized_recipe_id,
        )
    return normalized


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

