from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any, Iterable

from dnd_sim.spatial import (
    AABB,
    check_cover,
    distance_chebyshev,
    find_path,
    path_hazard_exposure,
    path_movement_cost,
    path_prefix_for_movement,
)
from dnd_sim.strategy_api import ActorView, BattleStateView

_EXPLICIT_TARGET_MODES = {
    "single_enemy",
    "single_ally",
    "n_enemies",
    "n_allies",
    "random_enemy",
    "random_ally",
}

_AUTO_TARGET_MODES = {"all_enemies", "all_allies", "all_creatures"}
_SUPPORTED_TARGET_MODES = _EXPLICIT_TARGET_MODES | _AUTO_TARGET_MODES | {"self"}


@dataclass(frozen=True, slots=True)
class RangeScoringInputs:
    distance_to_primary_ft: float
    action_range_ft: float
    movement_budget_ft: float
    requires_movement: bool
    reachable: bool


@dataclass(frozen=True, slots=True)
class HazardScoringInputs:
    active_hazard_count: int
    hazard_exposure_score: float
    estimated_affected_count: int
    friendly_fire_risk: bool


@dataclass(frozen=True, slots=True)
class ConcentrationScoringInputs:
    actor_concentrating: bool
    action_requires_concentration: bool
    recast_penalty_applies: bool
    actor_hp_ratio: float


@dataclass(frozen=True, slots=True)
class ControlScoringInputs:
    applied_condition_count: int
    forced_movement_count: int
    control_intensity: float


@dataclass(frozen=True, slots=True)
class ObjectiveScoringInputs:
    objective_tags: tuple[str, ...]
    objective_score: float


@dataclass(frozen=True, slots=True)
class ObjectiveTradeoffScoringInputs:
    survival_threshold_ratio: float
    actor_hp_ratio: float
    survival_pressure: float
    retreat_score: float
    objective_race_score: float
    ally_rescue_score: float
    focus_fire_score: float
    focus_fire_target_id: str | None


@dataclass(frozen=True, slots=True)
class ResourceScoringInputs:
    resource_cost: tuple[tuple[str, int], ...]
    total_cost: int
    resource_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SpatialScoringInputs:
    route_quality_score: float
    geometry_score: float
    cover_level: str
    cover_penalty: float
    line_of_effect_clear: bool
    line_of_effect_penalty: float
    friendly_fire_penalty: float


@dataclass(frozen=True, slots=True)
class CandidateScoringInputs:
    range: RangeScoringInputs
    hazard: HazardScoringInputs
    spatial: SpatialScoringInputs
    concentration: ConcentrationScoringInputs
    control: ControlScoringInputs
    objective: ObjectiveScoringInputs
    objective_tradeoff: ObjectiveTradeoffScoringInputs
    resource: ResourceScoringInputs


@dataclass(frozen=True, slots=True)
class ActionCandidate:
    action_name: str
    action_type: str
    target_mode: str
    target_ids: tuple[str, ...]
    scoring_inputs: CandidateScoringInputs


@dataclass(frozen=True, slots=True)
class _AreaProfile:
    affected_count: int
    enemy_count: int
    ally_count: int


_COVER_PENALTIES = {
    "NONE": 0.0,
    "HALF": 0.5,
    "THREE_QUARTERS": 1.0,
    "TOTAL": 2.0,
}


def _action_catalog_for_actor(actor: ActorView, state: BattleStateView) -> list[dict[str, Any]]:
    raw = state.metadata.get("action_catalog", {}).get(actor.actor_id, [])
    return [entry for entry in raw if isinstance(entry, dict)]


def _available_action_names(actor: ActorView, state: BattleStateView) -> set[str] | None:
    raw = state.metadata.get("available_actions", {}).get(actor.actor_id)
    if raw is None:
        return None
    names = {str(action_name).strip() for action_name in raw if str(action_name).strip()}
    return names if names else set()


def _coerce_positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0.0:
        return None
    return parsed


def _action_range_ft(action: dict[str, Any]) -> float:
    if isinstance(action.get("range_ft"), (int, float)):
        return float(action["range_ft"])
    if isinstance(action.get("range_normal_ft"), (int, float)):
        return float(action["range_normal_ft"])
    if isinstance(action.get("reach_ft"), (int, float)):
        return float(action["reach_ft"])

    action_type = str(action.get("action_type", "")).strip().lower()
    if action_type == "attack":
        return 5.0
    if action_type == "utility":
        return 30.0
    return 60.0


def _can_reach_target(actor: ActorView, action: dict[str, Any], target: ActorView) -> bool:
    if str(action.get("target_mode", "single_enemy")) == "self":
        return True
    action_range = _action_range_ft(action)
    distance = distance_chebyshev(actor.position, target.position)
    return distance <= action_range + float(actor.movement_remaining)


def _can_pay_resource_cost(actor: ActorView, action: dict[str, Any]) -> bool:
    resource_cost = action.get("resource_cost") or {}
    if not isinstance(resource_cost, dict):
        return False
    for key, amount in resource_cost.items():
        if int(actor.resources.get(str(key), 0)) < int(amount):
            return False
    return True


def _is_action_legal(actor: ActorView, action: dict[str, Any]) -> bool:
    target_mode = str(action.get("target_mode", "single_enemy")).strip().lower()
    if target_mode not in _SUPPORTED_TARGET_MODES:
        return False
    action_cost = str(action.get("action_cost", "action")).strip().lower()
    if action_cost in {"reaction", "legendary", "lair"}:
        return False
    max_uses = action.get("max_uses")
    if max_uses is not None and int(action.get("used_count", 0)) >= int(max_uses):
        return False
    if not bool(action.get("recharge_ready", True)):
        return False
    return _can_pay_resource_cost(actor, action)


def _living_pool_for_mode(
    actor: ActorView,
    state: BattleStateView,
    *,
    target_mode: str,
) -> list[ActorView]:
    living = [view for view in state.actors.values() if view.hp > 0]
    enemies = [view for view in living if view.team != actor.team]
    allies = [view for view in living if view.team == actor.team]

    if target_mode in {"single_enemy", "n_enemies", "random_enemy", "all_enemies"}:
        return sorted(enemies, key=lambda entry: entry.actor_id)
    if target_mode in {"single_ally", "n_allies", "random_ally", "all_allies"}:
        return sorted(allies, key=lambda entry: entry.actor_id)
    if target_mode == "all_creatures":
        return sorted(living, key=lambda entry: entry.actor_id)
    return []


def _enumerate_target_sets(
    actor: ActorView,
    state: BattleStateView,
    *,
    action: dict[str, Any],
    target_mode: str,
) -> list[tuple[str, ...]]:
    if target_mode == "self":
        return [(actor.actor_id,)]

    pool = _living_pool_for_mode(actor, state, target_mode=target_mode)
    reachable = [target for target in pool if _can_reach_target(actor, action, target)]
    if not reachable:
        return []

    if target_mode in {"single_enemy", "single_ally", "random_enemy", "random_ally"}:
        return [(target.actor_id,) for target in reachable]

    if target_mode in {"n_enemies", "n_allies"}:
        max_targets = max(1, int(action.get("max_targets") or 1))
        choose_n = min(max_targets, len(reachable))
        return [
            tuple(target.actor_id for target in group)
            for group in combinations(reachable, choose_n)
        ]

    if target_mode in _AUTO_TARGET_MODES:
        return [tuple(target.actor_id for target in reachable)]

    return []


def _objective_tags(action: dict[str, Any]) -> tuple[str, ...]:
    tags = [str(tag).strip() for tag in action.get("tags", []) if str(tag).strip()]
    return tuple(tag for tag in tags if tag.startswith("objective"))


def _objective_score(action: dict[str, Any], state: BattleStateView) -> float:
    objective_scores = state.metadata.get("objective_scores", {})
    if not isinstance(objective_scores, dict):
        return 0.0

    total = float(objective_scores.get(str(action.get("name", "")), 0.0))
    for tag in _objective_tags(action):
        if ":" not in tag:
            continue
        _, objective_id = tag.split(":", 1)
        total += float(objective_scores.get(objective_id, 0.0))
    return total


def _coerce_ratio(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, parsed))


def _survival_threshold_ratio(actor: ActorView, state: BattleStateView) -> float:
    per_actor = state.metadata.get("survival_threshold_ratio_by_actor", {})
    if isinstance(per_actor, dict):
        actor_value = per_actor.get(actor.actor_id)
        if actor_value is not None:
            return _coerce_ratio(actor_value, default=0.35)
    return _coerce_ratio(state.metadata.get("survival_threshold_ratio", 0.35), default=0.35)


def _ally_rescue_threshold_ratio(actor: ActorView, state: BattleStateView) -> float:
    per_actor = state.metadata.get("ally_rescue_threshold_ratio_by_actor", {})
    if isinstance(per_actor, dict):
        actor_value = per_actor.get(actor.actor_id)
        if actor_value is not None:
            return _coerce_ratio(actor_value, default=0.4)
    fallback = _survival_threshold_ratio(actor, state)
    return _coerce_ratio(
        state.metadata.get("ally_rescue_threshold_ratio", fallback), default=fallback
    )


def _normalized_action_tags(action: dict[str, Any]) -> set[str]:
    raw_tags = action.get("tags", [])
    if not isinstance(raw_tags, list):
        return set()
    return {str(tag).strip().lower() for tag in raw_tags if str(tag).strip()}


def _is_retreat_action(action: dict[str, Any]) -> bool:
    action_name = str(action.get("name", "")).strip().lower()
    action_type = str(action.get("action_type", "")).strip().lower()
    tags = _normalized_action_tags(action)
    if action_name in {"dash", "disengage", "dodge", "withdraw", "retreat"}:
        return True
    if action_type in {"dash", "disengage", "dodge"}:
        return True
    if any(tag in {"retreat", "disengage", "dash", "dodge"} for tag in tags):
        return True
    return any(tag.startswith("retreat:") for tag in tags)


def _is_supportive_action(action: dict[str, Any]) -> bool:
    action_type = str(action.get("action_type", "")).strip().lower()
    action_name = str(action.get("name", "")).strip().lower()
    tags = _normalized_action_tags(action)
    if action_type in {"heal", "buff"}:
        return True
    if any(tag in {"ally_rescue", "rescue", "support"} for tag in tags):
        return True
    return any(token in action_name for token in ("heal", "aid", "rescue", "stabilize"))


def _enemy_target_ids(
    actor: ActorView, state: BattleStateView, *, target_ids: tuple[str, ...]
) -> list[str]:
    target_list: list[str] = []
    for target_id in target_ids:
        target = state.actors.get(target_id)
        if target is None or target.hp <= 0:
            continue
        if target.team == actor.team:
            continue
        target_list.append(target_id)
    return target_list


def _focus_fire_target_id(actor: ActorView, state: BattleStateView) -> str | None:
    per_actor = state.metadata.get("focus_fire_target_by_actor", {})
    if isinstance(per_actor, dict):
        candidate = str(per_actor.get(actor.actor_id, "")).strip()
        if candidate:
            target = state.actors.get(candidate)
            if target is not None and target.team != actor.team and target.hp > 0:
                return candidate

    candidate = str(state.metadata.get("focus_fire_target_id", "")).strip()
    if candidate:
        target = state.actors.get(candidate)
        if target is not None and target.team != actor.team and target.hp > 0:
            return candidate

    enemies = [
        target for target in state.actors.values() if target.team != actor.team and target.hp > 0
    ]
    if not enemies:
        return None
    focus = min(
        enemies,
        key=lambda target: (
            float(target.hp) / float(max(target.max_hp, 1)),
            target.hp,
            target.actor_id,
        ),
    )
    return focus.actor_id


def _objective_race_score(
    action: dict[str, Any],
    state: BattleStateView,
    *,
    objective_score: float,
) -> float:
    tags = _normalized_action_tags(action)
    race_tagged = "objective_race" in tags
    if objective_score <= 0.0 and not race_tagged:
        return 0.0

    try:
        race_weight = float(state.metadata.get("objective_race_weight", 1.0))
    except (TypeError, ValueError):
        race_weight = 1.0
    race_weight = max(0.0, race_weight)
    if race_weight == 0.0:
        return 0.0

    urgency = 1.0
    rounds_remaining = state.metadata.get("objective_rounds_remaining")
    if rounds_remaining is not None:
        try:
            rounds = float(rounds_remaining)
        except (TypeError, ValueError):
            rounds = 5.0
        if rounds <= 0:
            urgency = 2.0
        else:
            urgency = 1.0 + max(0.0, (5.0 - rounds) / 5.0)

    effective_objective_score = float(objective_score)
    if effective_objective_score <= 0.0 and race_tagged:
        try:
            baseline = float(state.metadata.get("objective_race_baseline", 1.0))
        except (TypeError, ValueError):
            baseline = 1.0
        effective_objective_score = max(0.0, baseline)
    return effective_objective_score * race_weight * urgency


def _ally_rescue_score(
    actor: ActorView,
    state: BattleStateView,
    *,
    action: dict[str, Any],
    target_ids: tuple[str, ...],
) -> float:
    if not _is_supportive_action(action):
        return 0.0

    threshold = _ally_rescue_threshold_ratio(actor, state)
    total = 0.0
    for target_id in target_ids:
        if target_id == actor.actor_id:
            continue
        target = state.actors.get(target_id)
        if target is None or target.team != actor.team or target.hp <= 0:
            continue
        hp_ratio = float(target.hp) / float(max(target.max_hp, 1))
        pressure = max(0.0, threshold - hp_ratio)
        if pressure <= 0.0:
            continue
        total += 0.25 + (pressure * 2.0)
    return total


def _focus_fire_score(
    actor: ActorView,
    state: BattleStateView,
    *,
    target_ids: tuple[str, ...],
) -> tuple[float, str | None]:
    enemy_targets = _enemy_target_ids(actor, state, target_ids=target_ids)
    if not enemy_targets:
        return 0.0, None

    focus_target_id = _focus_fire_target_id(actor, state)
    if focus_target_id is None:
        return 0.0, None

    enemy_target_count = len(enemy_targets)
    if focus_target_id in enemy_targets:
        bonus = 0.5 if enemy_target_count == 1 else 0.0
        spread_penalty = max(0, enemy_target_count - 1) * 0.15
        return 1.0 + bonus - spread_penalty, focus_target_id

    return -0.25 * float(max(1, enemy_target_count)), focus_target_id


def _objective_tradeoff_inputs(
    actor: ActorView,
    state: BattleStateView,
    *,
    action: dict[str, Any],
    target_ids: tuple[str, ...],
    objective_score: float,
) -> ObjectiveTradeoffScoringInputs:
    actor_hp_ratio = float(actor.hp) / float(max(actor.max_hp, 1))
    survival_threshold_ratio = _survival_threshold_ratio(actor, state)
    survival_pressure = max(0.0, survival_threshold_ratio - actor_hp_ratio)
    retreat_action = _is_retreat_action(action)
    enemy_targets = _enemy_target_ids(actor, state, target_ids=target_ids)

    retreat_score = 0.0
    if survival_pressure > 0.0:
        if retreat_action:
            retreat_score = survival_pressure * 3.0
        elif enemy_targets:
            retreat_score = -survival_pressure
    elif retreat_action:
        retreat_score = -0.2

    objective_race_score = _objective_race_score(
        action,
        state,
        objective_score=objective_score,
    )
    ally_rescue_score = _ally_rescue_score(
        actor,
        state,
        action=action,
        target_ids=target_ids,
    )
    focus_fire_score, focus_fire_target_id = _focus_fire_score(
        actor,
        state,
        target_ids=target_ids,
    )

    return ObjectiveTradeoffScoringInputs(
        survival_threshold_ratio=survival_threshold_ratio,
        actor_hp_ratio=actor_hp_ratio,
        survival_pressure=survival_pressure,
        retreat_score=retreat_score,
        objective_race_score=objective_race_score,
        ally_rescue_score=ally_rescue_score,
        focus_fire_score=focus_fire_score,
        focus_fire_target_id=focus_fire_target_id,
    )


def _resource_inputs(action: dict[str, Any]) -> ResourceScoringInputs:
    raw_cost = action.get("resource_cost") or {}
    if not isinstance(raw_cost, dict):
        raw_cost = {}

    normalized = {str(key): int(value) for key, value in raw_cost.items() if int(value) > 0}
    ordered_keys = tuple(sorted(normalized.keys()))
    ordered_cost = tuple((key, normalized[key]) for key in ordered_keys)
    total_cost = sum(value for _, value in ordered_cost)
    return ResourceScoringInputs(
        resource_cost=ordered_cost,
        total_cost=total_cost,
        resource_keys=ordered_keys,
    )


def _control_inputs(action: dict[str, Any]) -> ControlScoringInputs:
    applied_condition_count = 0
    forced_movement_count = 0
    for payload in _iter_effect_payloads(action):
        effect_type = str(payload.get("effect_type", "")).strip().lower()
        if effect_type == "apply_condition":
            applied_condition_count += 1
        if effect_type == "forced_movement":
            forced_movement_count += 1
    control_intensity = float(applied_condition_count + forced_movement_count)
    return ControlScoringInputs(
        applied_condition_count=applied_condition_count,
        forced_movement_count=forced_movement_count,
        control_intensity=control_intensity,
    )


def _iter_effect_payloads(action: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for key in ("effects", "mechanics"):
        raw = action.get(key, [])
        if not isinstance(raw, list):
            continue
        for entry in raw:
            if isinstance(entry, dict):
                yield entry


def _coerce_position(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError):
        return None


def _obstacles_from_state(state: BattleStateView) -> list[AABB]:
    raw = state.metadata.get("obstacles", [])
    if not isinstance(raw, list):
        return []

    rows: list[AABB] = []
    for entry in raw:
        if isinstance(entry, AABB):
            rows.append(entry)
            continue
        if not isinstance(entry, dict):
            continue
        min_pos = _coerce_position(entry.get("min_pos") or entry.get("min"))
        max_pos = _coerce_position(entry.get("max_pos") or entry.get("max"))
        if min_pos is None or max_pos is None:
            continue
        cover_level = str(entry.get("cover_level", "TOTAL")).strip().upper()
        if cover_level not in _COVER_PENALTIES:
            cover_level = "TOTAL"
        rows.append(AABB(min_pos=min_pos, max_pos=max_pos, cover_level=cover_level))
    return rows


def _difficult_terrain_positions(state: BattleStateView) -> list[tuple[float, float, float]]:
    raw = state.metadata.get("difficult_terrain_positions", [])
    if not isinstance(raw, list):
        return []
    rows: list[tuple[float, float, float]] = []
    for entry in raw:
        pos = _coerce_position(entry)
        if pos is not None:
            rows.append(pos)
    return rows


def _movement_path_to_primary(
    actor: ActorView,
    *,
    primary_target: ActorView | None,
    obstacles: list[AABB],
    difficult_terrain_positions: list[tuple[float, float, float]],
) -> list[tuple[float, float, float]]:
    if primary_target is None:
        return []
    return find_path(
        actor.position,
        primary_target.position,
        obstacles=obstacles,
        difficult_terrain_positions=difficult_terrain_positions,
    )


def _area_profile(
    actor: ActorView,
    state: BattleStateView,
    *,
    action: dict[str, Any],
    primary_target: ActorView | None,
    target_ids: tuple[str, ...],
) -> _AreaProfile:
    aoe_radius = _coerce_positive_float(action.get("aoe_size_ft"))
    aoe_type = str(action.get("aoe_type", "")).strip().lower()
    include_self = bool(action.get("include_self", False))

    affected: list[ActorView] = []
    if aoe_type and aoe_radius is not None and primary_target is not None:
        for candidate in state.actors.values():
            if candidate.hp <= 0:
                continue
            if candidate.actor_id == actor.actor_id and not include_self:
                continue
            if distance_chebyshev(primary_target.position, candidate.position) > aoe_radius:
                continue
            affected.append(candidate)
    else:
        for target_id in target_ids:
            candidate = state.actors.get(target_id)
            if candidate is None or candidate.hp <= 0:
                continue
            affected.append(candidate)

    enemy_count = sum(1 for candidate in affected if candidate.team != actor.team)
    ally_count = sum(
        1
        for candidate in affected
        if candidate.team == actor.team and candidate.actor_id != actor.actor_id
    )
    return _AreaProfile(
        affected_count=len(affected),
        enemy_count=enemy_count,
        ally_count=ally_count,
    )


def _action_requires_line_of_effect(action: dict[str, Any]) -> bool:
    if str(action.get("target_mode", "single_enemy")) == "self":
        return False
    tags = {str(tag).strip().lower() for tag in action.get("tags", [])}
    if "ignore_line_of_effect" in tags or "ignore_total_cover" in tags:
        return False
    if "ignores_line_of_effect" in tags:
        return False
    if "requires_line_of_effect" in tags:
        return True
    action_type = str(action.get("action_type", "")).strip().lower()
    if action_type in {"attack", "save", "grapple", "shove"}:
        return True
    if "spell" in tags:
        return True
    for payload in _iter_effect_payloads(action):
        effect_type = str(payload.get("effect_type", "")).strip().lower()
        if effect_type in {"damage", "apply_condition", "forced_movement"}:
            return True
    return False


def _route_quality_score(
    actor: ActorView,
    *,
    action: dict[str, Any],
    primary_target: ActorView | None,
    movement_path: list[tuple[float, float, float]],
    difficult_terrain_positions: list[tuple[float, float, float]],
) -> float:
    if primary_target is None:
        return 1.0

    action_range_ft = _action_range_ft(action)
    distance_to_primary = float(distance_chebyshev(actor.position, primary_target.position))
    if distance_to_primary <= action_range_ft:
        return 1.0
    if len(movement_path) < 2:
        return 0.0

    movement_needed = max(0.0, distance_to_primary - action_range_ft)
    movement_budget = max(0.0, float(actor.movement_remaining))
    effective_movement_cost = _movement_cost_to_get_within_range(
        movement_path,
        target_position=primary_target.position,
        action_range_ft=action_range_ft,
        difficult_terrain_positions=difficult_terrain_positions,
    )
    if effective_movement_cost <= 0.0:
        return 0.0

    budget_factor = min(1.0, movement_budget / max(movement_needed, 1.0))
    detour_factor = min(1.0, movement_needed / max(effective_movement_cost, movement_needed))
    return max(0.0, min(1.0, budget_factor * detour_factor))


def _cover_penalty(cover_level: str) -> float:
    return _COVER_PENALTIES.get(cover_level, _COVER_PENALTIES["TOTAL"])


def _movement_cost_to_get_within_range(
    movement_path: list[tuple[float, float, float]],
    *,
    target_position: tuple[float, float, float],
    action_range_ft: float,
    difficult_terrain_positions: list[tuple[float, float, float]],
) -> float:
    if len(movement_path) < 2:
        return 0.0

    if distance_chebyshev(movement_path[0], target_position) <= action_range_ft:
        return 0.0

    full_path_cost = path_movement_cost(
        movement_path,
        difficult_terrain_positions=difficult_terrain_positions,
    )
    expanded_path = path_prefix_for_movement(
        movement_path,
        movement_budget_ft=full_path_cost,
        difficult_terrain_positions=difficult_terrain_positions,
    )

    spent = 0.0
    previous = expanded_path[0]
    for current in expanded_path[1:]:
        spent += path_movement_cost(
            [previous, current],
            difficult_terrain_positions=difficult_terrain_positions,
        )
        if distance_chebyshev(current, target_position) <= action_range_ft:
            return spent
        previous = current

    return full_path_cost


def _hazard_inputs(
    actor: ActorView,
    state: BattleStateView,
    *,
    action: dict[str, Any],
    primary_target: ActorView | None,
    target_ids: tuple[str, ...],
    area_profile: _AreaProfile,
    movement_path: list[tuple[float, float, float]],
) -> HazardScoringInputs:
    active_hazards_raw = state.metadata.get("active_hazards", [])
    active_hazards = (
        [entry for entry in active_hazards_raw if isinstance(entry, dict)]
        if isinstance(active_hazards_raw, list)
        else []
    )
    active_hazard_count = len(active_hazards)

    exposure_map = state.metadata.get("hazard_exposure_by_actor", {})
    if not isinstance(exposure_map, dict):
        exposure_map = {}
    target_exposure = float(
        sum(float(exposure_map.get(target_id, 0.0)) for target_id in target_ids)
    )
    route_exposure = path_hazard_exposure(movement_path, active_hazards)
    hazard_exposure_score = target_exposure + route_exposure

    return HazardScoringInputs(
        active_hazard_count=active_hazard_count,
        hazard_exposure_score=hazard_exposure_score,
        estimated_affected_count=area_profile.affected_count,
        friendly_fire_risk=area_profile.ally_count > 0,
    )


def _range_inputs(
    actor: ActorView,
    *,
    action: dict[str, Any],
    primary_target: ActorView | None,
) -> RangeScoringInputs:
    action_range_ft = _action_range_ft(action)
    movement_budget_ft = float(actor.movement_remaining)
    if primary_target is None:
        return RangeScoringInputs(
            distance_to_primary_ft=0.0,
            action_range_ft=action_range_ft,
            movement_budget_ft=movement_budget_ft,
            requires_movement=False,
            reachable=True,
        )

    distance_to_primary = float(distance_chebyshev(actor.position, primary_target.position))
    reachable = distance_to_primary <= action_range_ft + movement_budget_ft
    requires_movement = distance_to_primary > action_range_ft
    return RangeScoringInputs(
        distance_to_primary_ft=distance_to_primary,
        action_range_ft=action_range_ft,
        movement_budget_ft=movement_budget_ft,
        requires_movement=requires_movement,
        reachable=reachable,
    )


def _concentration_inputs(
    actor: ActorView, *, action: dict[str, Any]
) -> ConcentrationScoringInputs:
    actor_hp_ratio = float(actor.hp) / float(max(actor.max_hp, 1))
    action_requires_concentration = bool(action.get("concentration", False))
    actor_concentrating = bool(actor.concentrating)
    return ConcentrationScoringInputs(
        actor_concentrating=actor_concentrating,
        action_requires_concentration=action_requires_concentration,
        recast_penalty_applies=actor_concentrating and action_requires_concentration,
        actor_hp_ratio=actor_hp_ratio,
    )


def _spatial_inputs(
    actor: ActorView,
    *,
    action: dict[str, Any],
    primary_target: ActorView | None,
    area_profile: _AreaProfile,
    movement_path: list[tuple[float, float, float]],
    obstacles: list[AABB],
    difficult_terrain_positions: list[tuple[float, float, float]],
) -> SpatialScoringInputs:
    route_quality_score = _route_quality_score(
        actor,
        action=action,
        primary_target=primary_target,
        movement_path=movement_path,
        difficult_terrain_positions=difficult_terrain_positions,
    )
    geometry_score = float(area_profile.enemy_count - area_profile.ally_count)
    friendly_fire_penalty = float(area_profile.ally_count * 2)

    cover_level = "NONE"
    cover_penalty = 0.0
    line_of_effect_clear = True
    line_of_effect_penalty = 0.0
    if primary_target is not None and obstacles:
        cover_level = check_cover(actor.position, primary_target.position, obstacles)
        cover_penalty = _cover_penalty(cover_level)
        if _action_requires_line_of_effect(action) and cover_level == "TOTAL":
            line_of_effect_clear = False
            line_of_effect_penalty = 5.0

    return SpatialScoringInputs(
        route_quality_score=route_quality_score,
        geometry_score=geometry_score,
        cover_level=cover_level,
        cover_penalty=cover_penalty,
        line_of_effect_clear=line_of_effect_clear,
        line_of_effect_penalty=line_of_effect_penalty,
        friendly_fire_penalty=friendly_fire_penalty,
    )


def _build_scoring_inputs(
    actor: ActorView,
    state: BattleStateView,
    *,
    action: dict[str, Any],
    target_ids: tuple[str, ...],
) -> CandidateScoringInputs:
    primary_target = state.actors.get(target_ids[0]) if target_ids else None
    objective_score = _objective_score(action, state)
    obstacles = _obstacles_from_state(state)
    difficult_terrain_positions = _difficult_terrain_positions(state)
    movement_path = _movement_path_to_primary(
        actor,
        primary_target=primary_target,
        obstacles=obstacles,
        difficult_terrain_positions=difficult_terrain_positions,
    )
    area_profile = _area_profile(
        actor,
        state,
        action=action,
        primary_target=primary_target,
        target_ids=target_ids,
    )
    return CandidateScoringInputs(
        range=_range_inputs(actor, action=action, primary_target=primary_target),
        hazard=_hazard_inputs(
            actor,
            state,
            action=action,
            primary_target=primary_target,
            target_ids=target_ids,
            area_profile=area_profile,
            movement_path=movement_path,
        ),
        spatial=_spatial_inputs(
            actor,
            action=action,
            primary_target=primary_target,
            area_profile=area_profile,
            movement_path=movement_path,
            obstacles=obstacles,
            difficult_terrain_positions=difficult_terrain_positions,
        ),
        concentration=_concentration_inputs(actor, action=action),
        control=_control_inputs(action),
        objective=ObjectiveScoringInputs(
            objective_tags=_objective_tags(action),
            objective_score=objective_score,
        ),
        objective_tradeoff=_objective_tradeoff_inputs(
            actor,
            state,
            action=action,
            target_ids=target_ids,
            objective_score=objective_score,
        ),
        resource=_resource_inputs(action),
    )


def enumerate_legal_action_candidates(
    actor: ActorView, state: BattleStateView
) -> list[ActionCandidate]:
    catalog = _action_catalog_for_actor(actor, state)
    available_names = _available_action_names(actor, state)

    candidates: list[ActionCandidate] = []
    for action in catalog:
        action_name = str(action.get("name", "")).strip()
        if not action_name:
            continue
        if available_names is not None and action_name not in available_names:
            continue
        if not _is_action_legal(actor, action):
            continue

        target_mode = str(action.get("target_mode", "single_enemy")).strip().lower()
        for target_ids in _enumerate_target_sets(
            actor,
            state,
            action=action,
            target_mode=target_mode,
        ):
            candidates.append(
                ActionCandidate(
                    action_name=action_name,
                    action_type=str(action.get("action_type", "")).strip().lower(),
                    target_mode=target_mode,
                    target_ids=target_ids,
                    scoring_inputs=_build_scoring_inputs(
                        actor,
                        state,
                        action=action,
                        target_ids=target_ids,
                    ),
                )
            )

    return sorted(candidates, key=lambda row: (row.action_name, row.target_ids))


def _resource_snapshot(resource: ResourceScoringInputs) -> dict[str, Any]:
    return {
        "resource_cost": {key: value for key, value in resource.resource_cost},
        "total_cost": resource.total_cost,
        "resource_keys": list(resource.resource_keys),
    }


def candidate_snapshots(candidates: list[ActionCandidate]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for row in candidates:
        snapshots.append(
            {
                "action_name": row.action_name,
                "action_type": row.action_type,
                "target_mode": row.target_mode,
                "target_ids": list(row.target_ids),
                "range": {
                    "distance_to_primary_ft": row.scoring_inputs.range.distance_to_primary_ft,
                    "action_range_ft": row.scoring_inputs.range.action_range_ft,
                    "movement_budget_ft": row.scoring_inputs.range.movement_budget_ft,
                    "requires_movement": row.scoring_inputs.range.requires_movement,
                    "reachable": row.scoring_inputs.range.reachable,
                },
                "hazard": {
                    "active_hazard_count": row.scoring_inputs.hazard.active_hazard_count,
                    "hazard_exposure_score": row.scoring_inputs.hazard.hazard_exposure_score,
                    "estimated_affected_count": row.scoring_inputs.hazard.estimated_affected_count,
                    "friendly_fire_risk": row.scoring_inputs.hazard.friendly_fire_risk,
                },
                "spatial": {
                    "route_quality_score": row.scoring_inputs.spatial.route_quality_score,
                    "geometry_score": row.scoring_inputs.spatial.geometry_score,
                    "cover_level": row.scoring_inputs.spatial.cover_level,
                    "cover_penalty": row.scoring_inputs.spatial.cover_penalty,
                    "line_of_effect_clear": row.scoring_inputs.spatial.line_of_effect_clear,
                    "line_of_effect_penalty": row.scoring_inputs.spatial.line_of_effect_penalty,
                    "friendly_fire_penalty": row.scoring_inputs.spatial.friendly_fire_penalty,
                },
                "concentration": {
                    "actor_concentrating": row.scoring_inputs.concentration.actor_concentrating,
                    "action_requires_concentration": row.scoring_inputs.concentration.action_requires_concentration,
                    "recast_penalty_applies": row.scoring_inputs.concentration.recast_penalty_applies,
                    "actor_hp_ratio": row.scoring_inputs.concentration.actor_hp_ratio,
                },
                "control": {
                    "applied_condition_count": row.scoring_inputs.control.applied_condition_count,
                    "forced_movement_count": row.scoring_inputs.control.forced_movement_count,
                    "control_intensity": row.scoring_inputs.control.control_intensity,
                },
                "objective": {
                    "objective_tags": list(row.scoring_inputs.objective.objective_tags),
                    "objective_score": row.scoring_inputs.objective.objective_score,
                },
                "objective_tradeoff": {
                    "survival_threshold_ratio": row.scoring_inputs.objective_tradeoff.survival_threshold_ratio,
                    "actor_hp_ratio": row.scoring_inputs.objective_tradeoff.actor_hp_ratio,
                    "survival_pressure": row.scoring_inputs.objective_tradeoff.survival_pressure,
                    "retreat_score": row.scoring_inputs.objective_tradeoff.retreat_score,
                    "objective_race_score": row.scoring_inputs.objective_tradeoff.objective_race_score,
                    "ally_rescue_score": row.scoring_inputs.objective_tradeoff.ally_rescue_score,
                    "focus_fire_score": row.scoring_inputs.objective_tradeoff.focus_fire_score,
                    "focus_fire_target_id": row.scoring_inputs.objective_tradeoff.focus_fire_target_id,
                },
                "resource": _resource_snapshot(row.scoring_inputs.resource),
            }
        )
    return snapshots
