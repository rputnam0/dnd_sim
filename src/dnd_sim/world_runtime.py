from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from dnd_sim.economy import CraftingProject, CraftingRecipe, apply_crafting_days
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


def create_downtime_state(
    *,
    day: int,
    hour: int,
    minute: int,
    downtime_days_remaining: int,
    wallet_cp: int,
    strength_score: int,
    carried_weight_lb: float = 0.0,
    inventory: Mapping[str, int] | None = None,
    crafting_projects: Mapping[str, CraftingProject | Mapping[str, Any]] | None = None,
    service_effects: Mapping[str, int] | None = None,
    location_id: str | None = None,
    turn_index: int = 0,
) -> DowntimeState:
    exploration_state = create_exploration_state(
        day=day,
        hour=hour,
        minute=minute,
        location_id=location_id,
        turn_index=turn_index,
    )

    normalized_projects = _normalize_crafting_project_mapping(crafting_projects or {})
    return DowntimeState(
        clock=exploration_state.clock,
        turn_index=exploration_state.turn_index,
        downtime_days_remaining=downtime_days_remaining,
        wallet_cp=wallet_cp,
        strength_score=strength_score,
        carried_weight_lb=carried_weight_lb,
        inventory=dict(inventory or {}),
        crafting_projects=normalized_projects,
        service_effects=dict(service_effects or {}),
        location_id=exploration_state.location_id,
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


def assess_encumbrance(
    *,
    carried_weight_lb: float,
    strength_score: int,
) -> EncumbranceStatus:
    weight = _required_non_negative_number(carried_weight_lb, field_name="carried_weight_lb")
    strength = _required_int(strength_score, field_name="strength_score")
    if strength <= 0:
        raise ValueError("strength_score must be > 0")

    light_threshold = strength * 5.0
    heavy_threshold = strength * 10.0
    max_threshold = strength * 15.0

    if weight <= light_threshold:
        state = ENCUMBRANCE_UNENCUMBERED
        speed_penalty = 0
        travel_allowed = True
    elif weight <= heavy_threshold:
        state = ENCUMBRANCE_ENCUMBERED
        speed_penalty = 10
        travel_allowed = True
    elif weight <= max_threshold:
        state = ENCUMBRANCE_HEAVILY_ENCUMBERED
        speed_penalty = 20
        travel_allowed = True
    else:
        state = ENCUMBRANCE_OVER_CAPACITY
        speed_penalty = 20
        travel_allowed = False

    return EncumbranceStatus(
        carried_weight_lb=weight,
        strength_score=strength,
        light_threshold_lb=light_threshold,
        heavy_threshold_lb=heavy_threshold,
        max_threshold_lb=max_threshold,
        state=state,
        speed_penalty_ft=speed_penalty,
        travel_allowed=travel_allowed,
    )


def run_crafting_downtime(
    state: DowntimeState,
    *,
    recipe: CraftingRecipe,
    days: int,
) -> DowntimeActionResult:
    if not isinstance(state, DowntimeState):
        raise ValueError("state must be DowntimeState")
    if not isinstance(recipe, CraftingRecipe):
        raise ValueError("recipe must be CraftingRecipe")

    downtime_days = _required_int(days, field_name="days")
    if downtime_days <= 0:
        raise ValueError("days must be > 0")
    if downtime_days > state.downtime_days_remaining:
        raise ValueError("downtime_days exceeds available downtime")

    existing_project = state.crafting_projects.get(
        recipe.recipe_id,
        CraftingProject(recipe_id=recipe.recipe_id, accrued_days=0),
    )
    resolution = apply_crafting_days(
        recipe=recipe,
        project=existing_project,
        days=downtime_days,
        available_cp=state.wallet_cp,
    )

    next_inventory = dict(state.inventory)
    for item_id, quantity in resolution.inventory_delta.items():
        next_inventory[item_id] = next_inventory.get(item_id, 0) + quantity

    next_projects = dict(state.crafting_projects)
    next_projects[recipe.recipe_id] = resolution.project

    elapsed_minutes = downtime_days * MINUTES_PER_DAY
    next_clock = advance_world_clock(state.clock, elapsed_minutes=elapsed_minutes)
    next_turn_index = state.turn_index + 1
    next_weight = state.carried_weight_lb + (
        resolution.completed_batches * recipe.output_quantity * recipe.output_weight_lb
    )

    encumbrance = assess_encumbrance(
        carried_weight_lb=next_weight,
        strength_score=state.strength_score,
    )

    next_state = DowntimeState(
        clock=next_clock,
        turn_index=next_turn_index,
        downtime_days_remaining=state.downtime_days_remaining - downtime_days,
        wallet_cp=state.wallet_cp - resolution.cost_paid_cp,
        strength_score=state.strength_score,
        carried_weight_lb=next_weight,
        inventory=next_inventory,
        crafting_projects=next_projects,
        service_effects=state.service_effects,
        location_id=state.location_id,
    )

    return DowntimeActionResult(
        state=next_state,
        action=f"craft:{recipe.recipe_id}",
        downtime_days_spent=downtime_days,
        elapsed_minutes=elapsed_minutes,
        completed_batches=resolution.completed_batches,
        cost_paid_cp=resolution.cost_paid_cp,
        encumbrance=encumbrance,
    )


def run_service_action(
    state: DowntimeState,
    *,
    service_id: str,
    downtime_days: int,
    cost_cp: int,
    effect_id: str | None = None,
    effect_stacks: int = 1,
) -> DowntimeActionResult:
    if not isinstance(state, DowntimeState):
        raise ValueError("state must be DowntimeState")

    normalized_service_id = _required_text(service_id, field_name="service_id")
    days = _required_int(downtime_days, field_name="downtime_days")
    if days <= 0:
        raise ValueError("downtime_days must be > 0")
    if days > state.downtime_days_remaining:
        raise ValueError("downtime_days exceeds available downtime")

    service_cost_cp = _required_int(cost_cp, field_name="cost_cp")
    if service_cost_cp < 0:
        raise ValueError("cost_cp must be >= 0")
    if service_cost_cp > state.wallet_cp:
        raise ValueError("Insufficient currency")

    stacks = _required_int(effect_stacks, field_name="effect_stacks")
    if stacks <= 0:
        raise ValueError("effect_stacks must be > 0")
    normalized_effect_id = _required_text(
        effect_id if effect_id is not None else normalized_service_id,
        field_name="effect_id",
    )

    elapsed_minutes = days * MINUTES_PER_DAY
    next_clock = advance_world_clock(state.clock, elapsed_minutes=elapsed_minutes)
    next_effects = dict(state.service_effects)
    next_effects[normalized_effect_id] = next_effects.get(normalized_effect_id, 0) + stacks

    next_state = DowntimeState(
        clock=next_clock,
        turn_index=state.turn_index + 1,
        downtime_days_remaining=state.downtime_days_remaining - days,
        wallet_cp=state.wallet_cp - service_cost_cp,
        strength_score=state.strength_score,
        carried_weight_lb=state.carried_weight_lb,
        inventory=state.inventory,
        crafting_projects=state.crafting_projects,
        service_effects=next_effects,
        location_id=state.location_id,
    )

    return DowntimeActionResult(
        state=next_state,
        action=f"service:{normalized_service_id}",
        downtime_days_spent=days,
        elapsed_minutes=elapsed_minutes,
        cost_paid_cp=service_cost_cp,
        encumbrance=assess_encumbrance(
            carried_weight_lb=next_state.carried_weight_lb,
            strength_score=next_state.strength_score,
        ),
    )


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


def normalize_travel_pace(value: Any) -> str:
    pace = str(value or "normal").lower().strip()
    if pace not in TRAVEL_PACE_MILES_PER_DAY:
        return "normal"
    return pace


def plan_travel_pace(
    *,
    distance_miles: float,
    travel_pace: str = "normal",
    segments: int | None = None,
) -> TravelPaceOutcome:
    if isinstance(distance_miles, bool) or not isinstance(distance_miles, int | float):
        raise ValueError("distance_miles must be a number >= 0")

    miles = float(distance_miles)
    if math.isnan(miles) or math.isinf(miles) or miles < 0:
        raise ValueError("distance_miles must be a number >= 0")

    pace = normalize_travel_pace(travel_pace)
    miles_per_day = TRAVEL_PACE_MILES_PER_DAY[pace]

    explicit_segments = 0
    if segments is not None:
        explicit_segments = _required_int(segments, field_name="segments")
        if explicit_segments < 0:
            raise ValueError("segments must be >= 0")

    if explicit_segments > 0:
        planned_segments = explicit_segments
    elif miles > 0:
        planned_segments = max(1, int(math.ceil(miles / miles_per_day)))
    else:
        planned_segments = 0

    if miles <= 0:
        travel_minutes = 0
    else:
        miles_per_hour = miles_per_day / 8.0
        travel_minutes = int(math.ceil((miles / miles_per_hour) * 60.0))

    return TravelPaceOutcome(
        travel_pace=pace,
        distance_miles=miles,
        miles_per_day=miles_per_day,
        segments=planned_segments,
        travel_minutes=travel_minutes,
    )


def resolve_navigation(
    *,
    check_total: int,
    dc: int = 10,
    travel_pace: str = "normal",
) -> NavigationOutcome:
    total = _required_int(check_total, field_name="check_total")
    base_dc = _required_int(dc, field_name="dc")
    if base_dc < 0:
        raise ValueError("dc must be >= 0")

    pace = normalize_travel_pace(travel_pace)
    effective_dc = base_dc + TRAVEL_PACE_NAVIGATION_DC_MODIFIER[pace]
    margin = total - effective_dc
    success = margin >= 0
    lost_minutes = 0 if success else 60 if margin > -8 else 120
    encounter_check_required = margin <= -3

    return NavigationOutcome(
        success=success,
        check_total=total,
        effective_dc=effective_dc,
        margin=margin,
        lost_minutes=lost_minutes,
        encounter_check_required=encounter_check_required,
    )


def resolve_foraging(
    *,
    check_total: int,
    dc: int = 15,
    travel_pace: str = "normal",
) -> ForagingOutcome:
    total = _required_int(check_total, field_name="check_total")
    base_dc = _required_int(dc, field_name="dc")
    if base_dc < 0:
        raise ValueError("dc must be >= 0")

    pace = normalize_travel_pace(travel_pace)
    effective_dc = base_dc + TRAVEL_PACE_FORAGING_DC_MODIFIER[pace]
    margin = total - effective_dc
    success = margin >= 0
    supplies_found = 0
    if success:
        supplies_found = 1 + max(0, margin // 5)
    encounter_check_required = pace == "fast" or margin <= -5

    return ForagingOutcome(
        success=success,
        check_total=total,
        effective_dc=effective_dc,
        margin=margin,
        supplies_found=supplies_found,
        encounter_check_required=encounter_check_required,
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


def _party_state_from_mapping(actor_id: str, payload: Mapping[str, Any]) -> TravelPartyMemberState:
    return TravelPartyMemberState(
        actor_id=_required_text(payload.get("actor_id", actor_id), field_name="actor_id"),
        hit_points=_required_int(payload.get("hit_points"), field_name="hit_points"),
        max_hit_points=_required_int(payload.get("max_hit_points"), field_name="max_hit_points"),
        resources=dict(payload.get("resources", {})),
        max_resources=dict(payload.get("max_resources", {})),
        short_rest_recovery=tuple(payload.get("short_rest_recovery", ())),
        conditions=tuple(payload.get("conditions", ())),
    )


def _normalize_party_input(
    party: Mapping[str, TravelPartyMemberState | Mapping[str, Any]],
) -> dict[str, TravelPartyMemberState]:
    if not isinstance(party, Mapping):
        raise ValueError("party must be a mapping")

    normalized: dict[str, TravelPartyMemberState] = {}
    for actor_id, actor_payload in sorted(dict(party).items()):
        key = _required_text(actor_id, field_name="party actor_id")
        if isinstance(actor_payload, TravelPartyMemberState):
            actor = actor_payload
        elif isinstance(actor_payload, Mapping):
            actor = _party_state_from_mapping(key, actor_payload)
        else:
            raise ValueError("party values must be TravelPartyMemberState or mappings")
        if actor.actor_id != key:
            raise ValueError("party actor key must match actor_id")
        normalized[key] = actor
    return normalized


def _apply_short_rest(
    party: Mapping[str, TravelPartyMemberState],
    *,
    short_rest_healing: int,
) -> dict[str, TravelPartyMemberState]:
    rested: dict[str, TravelPartyMemberState] = {}
    for actor_id, actor in party.items():
        resources = dict(actor.resources)
        for resource_key in actor.short_rest_recovery:
            max_value = int(actor.max_resources.get(resource_key, resources.get(resource_key, 0)))
            resources[resource_key] = max_value

        rested[actor_id] = TravelPartyMemberState(
            actor_id=actor_id,
            hit_points=min(actor.max_hit_points, actor.hit_points + short_rest_healing),
            max_hit_points=actor.max_hit_points,
            resources=resources,
            max_resources=dict(actor.max_resources),
            short_rest_recovery=actor.short_rest_recovery,
            conditions=actor.conditions,
        )
    return rested


def _apply_long_rest(
    party: Mapping[str, TravelPartyMemberState],
) -> dict[str, TravelPartyMemberState]:
    rested: dict[str, TravelPartyMemberState] = {}
    for actor_id, actor in party.items():
        resources = dict(actor.resources)
        for resource_key, max_value in actor.max_resources.items():
            resources[resource_key] = max_value

        rested[actor_id] = TravelPartyMemberState(
            actor_id=actor_id,
            hit_points=actor.max_hit_points,
            max_hit_points=actor.max_hit_points,
            resources=resources,
            max_resources=dict(actor.max_resources),
            short_rest_recovery=actor.short_rest_recovery,
            conditions=(),
        )
    return rested


def apply_rest_cycle(
    state: ExplorationState,
    *,
    party: Mapping[str, TravelPartyMemberState | Mapping[str, Any]],
    rest_mode: str = REST_NONE,
    short_rest_healing: int = 0,
) -> RestCycleOutcome:
    mode = _required_text(rest_mode, field_name="rest_mode").lower()
    if mode not in REST_MODES:
        raise ValueError(f"rest_mode must be one of {REST_MODES}")

    healing = _required_int(short_rest_healing, field_name="short_rest_healing")
    if healing < 0:
        raise ValueError("short_rest_healing must be >= 0")

    normalized_party = _normalize_party_input(party)
    elapsed_minutes = 0

    if mode == REST_SHORT:
        normalized_party = _apply_short_rest(normalized_party, short_rest_healing=healing)
        elapsed_minutes = 60
    elif mode == REST_LONG:
        normalized_party = _apply_long_rest(normalized_party)
        elapsed_minutes = 8 * 60

    next_state = state
    if elapsed_minutes > 0:
        next_state = run_exploration_turn(
            state,
            activity=f"{mode}_rest",
            elapsed_minutes=elapsed_minutes,
        ).state

    return RestCycleOutcome(
        state=next_state,
        party=normalized_party,
        rest_mode=mode,
        elapsed_minutes=elapsed_minutes,
        day_cycle=day_cycle_phase(next_state.clock),
    )


def run_travel_and_rest_cycle(
    state: ExplorationState,
    *,
    distance_miles: float,
    travel_pace: str = "normal",
    navigation_check_total: int,
    navigation_dc: int = 10,
    foraging_check_total: int | None = None,
    foraging_dc: int = 15,
    rest_mode: str = REST_NONE,
    short_rest_healing: int = 0,
    party: Mapping[str, TravelPartyMemberState | Mapping[str, Any]] | None = None,
) -> TravelAndRestCycleOutcome:
    planned_travel = plan_travel_pace(distance_miles=distance_miles, travel_pace=travel_pace)
    navigation = resolve_navigation(
        check_total=navigation_check_total,
        dc=navigation_dc,
        travel_pace=planned_travel.travel_pace,
    )

    foraging: ForagingOutcome | None = None
    if foraging_check_total is not None:
        foraging = resolve_foraging(
            check_total=foraging_check_total,
            dc=foraging_dc,
            travel_pace=planned_travel.travel_pace,
        )

    random_encounter_check = navigation.encounter_check_required
    if foraging is not None:
        random_encounter_check = random_encounter_check or foraging.encounter_check_required

    day_cycle_start = day_cycle_phase(state.clock)

    travel_minutes = planned_travel.travel_minutes + navigation.lost_minutes
    traveled_state = state
    if travel_minutes > 0:
        traveled_state = run_exploration_turn(
            state,
            activity=f"travel_{planned_travel.travel_pace}",
            elapsed_minutes=travel_minutes,
        ).state

    rest = apply_rest_cycle(
        traveled_state,
        party=party or {},
        rest_mode=rest_mode,
        short_rest_healing=short_rest_healing,
    )

    return TravelAndRestCycleOutcome(
        state=rest.state,
        party=rest.party,
        travel=planned_travel,
        navigation=navigation,
        foraging=foraging,
        rest=rest,
        random_encounter_check=random_encounter_check,
        total_elapsed_minutes=travel_minutes + rest.elapsed_minutes,
        day_cycle_start=day_cycle_start,
        day_cycle_end=rest.day_cycle,
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
