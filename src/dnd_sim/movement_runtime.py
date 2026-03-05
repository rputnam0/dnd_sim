from __future__ import annotations

import logging
import math
from dataclasses import replace
from typing import Any, Callable

from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.spatial import distance_chebyshev, distance_euclidean, move_towards

logger = logging.getLogger(__name__)


class MovementPathValidationError(ValueError):
    def __init__(
        self,
        *,
        code: str,
        field: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.field = field
        self.message = message
        self.details = dict(details or {})
        super().__init__(f"{code} [{field}] {message}")


def _to_position3(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        return None
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError):
        return None


def difficult_terrain_positions_from_hazards(
    active_hazards: list[dict[str, Any]],
) -> list[tuple[float, float, float]]:
    difficult_positions: set[tuple[float, float, float]] = set()
    for hazard in active_hazards:
        if not isinstance(hazard, dict):
            continue
        hazard_type = str(hazard.get("type") or hazard.get("hazard_type") or "").strip().lower()
        normalized_type = hazard_type.replace("-", "_").replace(" ", "_")
        if normalized_type != "difficult_terrain":
            continue

        explicit_positions = (
            hazard.get("difficult_positions") or hazard.get("positions") or hazard.get("cells")
        )
        if isinstance(explicit_positions, list):
            for row in explicit_positions:
                pos = _to_position3(row)
                if pos is not None:
                    difficult_positions.add(pos)

        center = _to_position3(hazard.get("position"))
        if center is None:
            continue
        raw_radius = hazard.get("radius", hazard.get("radius_ft", 0))
        try:
            radius_ft = float(raw_radius)
        except (TypeError, ValueError):
            radius_ft = 0.0
        if radius_ft <= 0:
            difficult_positions.add(center)
            continue

        center_cell = (
            int(round(center[0] / 5.0)),
            int(round(center[1] / 5.0)),
            int(round(center[2] / 5.0)),
        )
        radius_cells = int(math.ceil(radius_ft / 5.0))
        for dx in range(-radius_cells, radius_cells + 1):
            for dy in range(-radius_cells, radius_cells + 1):
                for dz in range(-radius_cells, radius_cells + 1):
                    candidate = (
                        (center_cell[0] + dx) * 5.0,
                        (center_cell[1] + dy) * 5.0,
                        (center_cell[2] + dz) * 5.0,
                    )
                    if distance_chebyshev(center, candidate) <= radius_ft + 1e-9:
                        difficult_positions.add(candidate)

    return sorted(difficult_positions)


def path_distance(path: list[tuple[float, float, float]]) -> float:
    if len(path) < 2:
        return 0.0
    total = 0.0
    for idx in range(1, len(path)):
        total += distance_chebyshev(path[idx - 1], path[idx])
    return total


def expand_path_points(
    path: list[tuple[float, float, float]],
    *,
    step_ft: float = 5.0,
) -> list[tuple[float, float, float]]:
    if len(path) < 2:
        return path
    expanded: list[tuple[float, float, float]] = [path[0]]
    for idx in range(1, len(path)):
        start = path[idx - 1]
        end = path[idx]
        segment = distance_chebyshev(start, end)
        if segment <= 0:
            continue
        steps = max(1, int(segment / step_ft))
        if (steps * step_ft) < segment:
            steps += 1
        for step in range(1, steps + 1):
            ratio = step / steps
            expanded.append(
                (
                    start[0] + (end[0] - start[0]) * ratio,
                    start[1] + (end[1] - start[1]) * ratio,
                    start[2] + (end[2] - start[2]) * ratio,
                )
            )
    return expanded


def prepare_voluntary_movement(
    actor: ActorRuntimeState,
    *,
    remove_condition: Callable[[ActorRuntimeState, str], None],
) -> tuple[float, bool]:
    if actor.movement_remaining <= 0:
        return 0.0, False
    if actor.conditions.intersection({"grappled", "restrained"}):
        return 0.0, False
    if "prone" not in actor.conditions:
        return actor.movement_remaining, False

    stand_cost = float(actor.speed_ft) / 2.0
    if actor.movement_remaining >= stand_cost:
        actor.movement_remaining -= stand_cost
        remove_condition(actor, "prone")
        return actor.movement_remaining, False

    # RAW crawl when prone: each moved foot costs 2 feet.
    return actor.movement_remaining / 2.0, True


def path_movement_cost(
    path: list[tuple[float, float, float]],
    *,
    crawling: bool,
    movement_multiplier_for_position: Callable[[tuple[float, float, float]], float],
) -> float:
    if len(path) < 2:
        return 0.0
    expanded = expand_path_points(path)
    total = 0.0
    for idx in range(1, len(expanded)):
        segment = distance_chebyshev(expanded[idx - 1], expanded[idx])
        if segment <= 0:
            continue
        multiplier = movement_multiplier_for_position(expanded[idx])
        if crawling:
            multiplier *= 2.0
        total += segment * multiplier
    return total


def path_prefix_for_movement_budget(
    path: list[tuple[float, float, float]],
    *,
    movement_budget_ft: float,
    crawling: bool,
    movement_multiplier_for_position: Callable[[tuple[float, float, float]], float],
    max_travel_ft: float | None = None,
) -> tuple[list[tuple[float, float, float]], float]:
    if not path:
        return [], 0.0
    if len(path) == 1 or movement_budget_ft <= 0:
        return [path[0]], 0.0

    traveled_path: list[tuple[float, float, float]] = [path[0]]
    spent = 0.0
    traveled_ft = 0.0
    current = path[0]
    for waypoint in path[1:]:
        segment = distance_chebyshev(current, waypoint)
        if segment <= 0:
            current = waypoint
            continue

        remaining_budget = movement_budget_ft - spent
        if remaining_budget <= 1e-9:
            break
        remaining_travel = float("inf")
        if max_travel_ft is not None:
            remaining_travel = max(0.0, max_travel_ft - traveled_ft)
            if remaining_travel <= 1e-9:
                break

        multiplier = movement_multiplier_for_position(waypoint)
        if crawling:
            multiplier *= 2.0
        affordable = remaining_budget / multiplier
        move_ft = min(segment, affordable, remaining_travel)
        if move_ft <= 1e-9:
            break

        if move_ft + 1e-9 >= segment:
            next_point = waypoint
        else:
            ratio = move_ft / segment
            next_point = (
                current[0] + (waypoint[0] - current[0]) * ratio,
                current[1] + (waypoint[1] - current[1]) * ratio,
                current[2] + (waypoint[2] - current[2]) * ratio,
            )

        if distance_chebyshev(traveled_path[-1], next_point) > 1e-9:
            traveled_path.append(next_point)
        spent += move_ft * multiplier
        traveled_ft += move_ft
        current = next_point
        if distance_chebyshev(current, waypoint) > 1e-6:
            break

    return traveled_path, spent


def path_movement_cost_with_hazards(
    path: list[tuple[float, float, float]],
    *,
    active_hazards: list[dict[str, Any]],
    crawling: bool,
) -> float:
    difficult_positions = difficult_terrain_positions_from_hazards(active_hazards)
    difficult_lookup = set(difficult_positions)
    return path_movement_cost(
        path,
        crawling=crawling,
        movement_multiplier_for_position=lambda point: 2.0 if point in difficult_lookup else 1.0,
    )


def validate_declared_movement_path(
    *,
    movement_path: Any,
    actor_position: tuple[float, float, float],
) -> list[tuple[float, float, float]]:
    if not isinstance(movement_path, list):
        raise MovementPathValidationError(
            code="invalid_movement_path",
            field="movement_path",
            message="movement_path must be a list of 3D waypoints.",
        )
    if not movement_path:
        return []

    normalized: list[tuple[float, float, float]] = []
    for idx, waypoint in enumerate(movement_path):
        if not isinstance(waypoint, (tuple, list)) or len(waypoint) != 3:
            raise MovementPathValidationError(
                code="invalid_waypoint",
                field=f"movement_path[{idx}]",
                message="Each movement waypoint must be a 3-value coordinate.",
            )
        try:
            normalized.append((float(waypoint[0]), float(waypoint[1]), float(waypoint[2])))
        except (TypeError, ValueError) as exc:
            raise MovementPathValidationError(
                code="invalid_waypoint",
                field=f"movement_path[{idx}]",
                message="Each movement waypoint value must be numeric.",
            ) from exc

    if distance_chebyshev(actor_position, normalized[0]) > 1e-6:
        raise MovementPathValidationError(
            code="movement_path_start_mismatch",
            field="movement_path[0]",
            message="movement_path must start at the actor's current position.",
            details={"current_position": actor_position},
        )
    return normalized


def movement_triggers_opportunity_attacks(
    *,
    movement_kind: str,
    mover_conditions: set[str],
    start_pos: tuple[float, float, float],
    end_pos: tuple[float, float, float],
) -> bool:
    if movement_kind != "voluntary":
        return False
    if "disengaging" in mover_conditions:
        return False
    if start_pos == end_pos:
        return False
    return True


def movement_reach_transitions(
    *,
    reactor_position: tuple[float, float, float],
    path_points: list[tuple[float, float, float]],
    reach_ft: float,
) -> list[tuple[str, tuple[float, float, float], float]]:
    if len(path_points) < 2 or reach_ft <= 0:
        return []

    transitions: list[tuple[str, tuple[float, float, float], float]] = []
    previous = path_points[0]
    was_in_reach = distance_chebyshev(reactor_position, previous) <= reach_ft
    for point in path_points[1:]:
        is_in_reach = distance_chebyshev(reactor_position, point) <= reach_ft
        if not was_in_reach and is_in_reach:
            distance_ft = distance_chebyshev(reactor_position, point)
            transitions.append(("enter_reach", point, distance_ft))
        elif was_in_reach and not is_in_reach:
            distance_ft = distance_chebyshev(reactor_position, previous)
            transitions.append(("exit_reach", previous, distance_ft))
        was_in_reach = is_in_reach
        previous = point
    return transitions


def opportunity_attack_reach_ft(
    action: ActionDefinition,
    *,
    is_ranged_weapon_action: Callable[[ActionDefinition], bool],
    action_has_weapon_property: Callable[[ActionDefinition, str], bool],
    action_range_ft: Callable[[ActionDefinition], float | None],
) -> float | None:
    if action.action_type != "attack":
        return None
    if is_ranged_weapon_action(action):
        return None
    if action.reach_ft is not None:
        return max(0.0, float(action.reach_ft))
    if action_has_weapon_property(action, "reach"):
        if action.range_ft is not None and action.range_ft > 0:
            return float(action.range_ft)
        if action.range_normal_ft is not None and action.range_normal_ft > 0:
            return float(action.range_normal_ft)
        return 10.0
    inferred_range = action_range_ft(action)
    if inferred_range is None:
        return 5.0
    return min(5.0, max(0.0, float(inferred_range)))


def opportunity_attack_candidates(
    actor: ActorRuntimeState,
    *,
    can_pay_resource_cost: Callable[[ActorRuntimeState, ActionDefinition], bool],
    reach_resolver: Callable[[ActionDefinition], float | None],
) -> list[tuple[ActionDefinition, float]]:
    candidates: list[tuple[ActionDefinition, float]] = []
    for action in actor.actions:
        if action.action_type != "attack":
            continue
        if action.action_cost in {"legendary", "lair"}:
            continue
        if not can_pay_resource_cost(actor, action):
            continue
        reach_ft = reach_resolver(action)
        if reach_ft is None or reach_ft <= 0:
            continue
        candidates.append((action, reach_ft))
    return candidates


def find_opportunity_attack_action(
    actor: ActorRuntimeState,
    *,
    required_reach_ft: float,
    can_pay_resource_cost: Callable[[ActorRuntimeState, ActionDefinition], bool],
    reach_resolver: Callable[[ActionDefinition], float | None],
) -> tuple[ActionDefinition, float] | None:
    best: tuple[ActionDefinition, float] | None = None
    for action, reach_ft in opportunity_attack_candidates(
        actor,
        can_pay_resource_cost=can_pay_resource_cost,
        reach_resolver=reach_resolver,
    ):
        if reach_ft + 1e-9 < required_reach_ft:
            continue
        if best is None:
            best = (action, reach_ft)
            continue
        best_action, best_reach = best
        current_to_hit = action.to_hit if action.to_hit is not None else -999
        best_to_hit = best_action.to_hit if best_action.to_hit is not None else -999
        if (current_to_hit, reach_ft) > (best_to_hit, best_reach):
            best = (action, reach_ft)
    if best is None:
        return None
    best_action, best_reach = best
    return replace(best_action, attack_count=1, action_cost="reaction"), best_reach


def resolve_forced_movement_destination(
    *,
    source_pos: tuple[float, float, float],
    target_pos: tuple[float, float, float],
    direction: str,
    distance_ft: float,
) -> tuple[float, float, float]:
    if distance_ft <= 0:
        return target_pos

    if direction == "toward_source":
        return move_towards(target_pos, source_pos, distance_ft)

    if direction != "away_from_source":
        return target_pos

    distance_from_source = distance_euclidean(source_pos, target_pos)
    if distance_from_source <= 0:
        return (target_pos[0] + distance_ft, target_pos[1], target_pos[2])

    unit = (
        (target_pos[0] - source_pos[0]) / distance_from_source,
        (target_pos[1] - source_pos[1]) / distance_from_source,
        (target_pos[2] - source_pos[2]) / distance_from_source,
    )
    return (
        target_pos[0] + unit[0] * distance_ft,
        target_pos[1] + unit[1] * distance_ft,
        target_pos[2] + unit[2] * distance_ft,
    )
