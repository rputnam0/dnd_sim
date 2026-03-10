from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from typing import Any

from dnd_sim.world_exploration_service import day_cycle_phase, run_exploration_turn
from dnd_sim.world_contracts import (
    REST_MODES,
    REST_LONG,
    REST_NONE,
    REST_SHORT,
    ExplorationState,
    ForagingOutcome,
    NavigationOutcome,
    RestCycleOutcome,
    TRAVEL_PACE_FORAGING_DC_MODIFIER,
    TRAVEL_PACE_MILES_PER_DAY,
    TRAVEL_PACE_NAVIGATION_DC_MODIFIER,
    TravelAndRestCycleOutcome,
    TravelPaceOutcome,
    TravelPartyMemberState,
    _normalize_text_tuple,
    _required_int,
    _required_text,
    _validate_resource_mapping,
)

logger = logging.getLogger(__name__)


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
