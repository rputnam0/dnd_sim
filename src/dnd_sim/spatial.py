from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

Position = tuple[float, float, float]
_TRAIT_NORMALIZE_RE = re.compile(r"[\s_-]+")


def _normalize_trait_name(name: str) -> str:
    return _TRAIT_NORMALIZE_RE.sub("", str(name).strip().lower())


def _has_trait(observer_traits: dict[str, Any], trait_name: str) -> bool:
    needle = _normalize_trait_name(trait_name)
    return any(_normalize_trait_name(key) == needle for key in observer_traits.keys())


def distance_euclidean(pos1: Position, pos2: Position) -> float:
    return math.sqrt((pos1[0] - pos2[0]) ** 2 + (pos1[1] - pos2[1]) ** 2 + (pos1[2] - pos2[2]) ** 2)


def distance_chebyshev(pos1: Position, pos2: Position) -> float:
    return max(abs(pos1[0] - pos2[0]), abs(pos1[1] - pos2[1]), abs(pos1[2] - pos2[2]))


def move_towards(current: Position, target: Position, max_distance: float) -> Position:
    dist = distance_euclidean(current, target)
    if dist <= max_distance or dist == 0:
        return target
    ratio = max_distance / dist
    dx = (target[0] - current[0]) * ratio
    dy = (target[1] - current[1]) * ratio
    dz = (target[2] - current[2]) * ratio
    return (current[0] + dx, current[1] + dy, current[2] + dz)


def get_positions_in_radius(
    center: Position, radius: float, positions: list[Position]
) -> list[Position]:
    return [p for p in positions if distance_chebyshev(center, p) <= radius]


@dataclass(slots=True)
class AABB:
    min_pos: Position
    max_pos: Position
    cover_level: str  # NONE/HALF/THREE_QUARTERS/TOTAL


def _axis_slab(
    start: float, direction: float, axis_min: float, axis_max: float
) -> tuple[float, float] | None:
    if direction == 0:
        if start < axis_min or start > axis_max:
            return None
        return (float("-inf"), float("inf"))
    inv = 1.0 / direction
    t0 = (axis_min - start) * inv
    t1 = (axis_max - start) * inv
    if inv < 0:
        t0, t1 = t1, t0
    return (t0, t1)


def ray_intersects_aabb(start: Position, end: Position, aabb: AABB) -> bool:
    direction = (end[0] - start[0], end[1] - start[1], end[2] - start[2])
    if direction == (0.0, 0.0, 0.0):
        return False

    x_slab = _axis_slab(start[0], direction[0], aabb.min_pos[0], aabb.max_pos[0])
    if x_slab is None:
        return False
    y_slab = _axis_slab(start[1], direction[1], aabb.min_pos[1], aabb.max_pos[1])
    if y_slab is None:
        return False
    z_slab = _axis_slab(start[2], direction[2], aabb.min_pos[2], aabb.max_pos[2])
    if z_slab is None:
        return False

    tmin = max(x_slab[0], y_slab[0], z_slab[0])
    tmax = min(x_slab[1], y_slab[1], z_slab[1])
    return tmax >= 0 and tmin <= tmax and tmin <= 1


def _coerce_position(value: Any, default: Position = (0.0, 0.0, 0.0)) -> Position:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError):
            return default
    return default


def _sense_range(observer_traits: dict[str, Any], sense: str, default: float) -> float | None:
    if not _has_trait(observer_traits, sense):
        return None
    for key, value in observer_traits.items():
        if _normalize_trait_name(key) != _normalize_trait_name(sense):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, dict):
            for range_key in ("range_ft", "range", "distance", "value", "radius"):
                candidate = value.get(range_key)
                if isinstance(candidate, (int, float)):
                    return float(candidate)
    return float(default)


def can_see(
    observer_pos: Position,
    target_pos: Position,
    observer_traits: dict[str, Any],
    target_conditions: set[str],
    active_hazards: list[dict[str, Any]],
    light_level: str = "bright",
) -> bool:
    distance = distance_chebyshev(observer_pos, target_pos)

    truesight = _sense_range(observer_traits, "truesight", 120)
    if truesight is not None and distance <= truesight:
        return True

    blindsight = _sense_range(observer_traits, "blindsight", 60)
    if blindsight is not None and distance <= blindsight:
        return True

    tremorsense = _sense_range(observer_traits, "tremorsense", 60)
    if tremorsense is not None and distance <= tremorsense:
        return True

    in_magical_darkness = False
    for hazard in active_hazards:
        hazard_type = str(hazard.get("type") or hazard.get("hazard_type") or "").lower()
        if hazard_type != "magical_darkness":
            continue
        hazard_pos = _coerce_position(hazard.get("position"), default=(0.0, 0.0, 0.0))
        hazard_radius = float(hazard.get("radius", hazard.get("radius_ft", 15)))
        if (
            distance_chebyshev(observer_pos, hazard_pos) <= hazard_radius
            or distance_chebyshev(target_pos, hazard_pos) <= hazard_radius
        ):
            in_magical_darkness = True
            break

    if in_magical_darkness:
        return False
    if "invisible" in target_conditions:
        return False
    if light_level.lower() == "darkness":
        darkvision = _sense_range(observer_traits, "darkvision", 60)
        return darkvision is not None and distance <= darkvision
    return True


def check_cover(pos1: Position, pos2: Position, obstacles: list[AABB] | None = None) -> str:
    if not obstacles:
        return "NONE"
    highest_cover = "NONE"
    ranks = {"NONE": 0, "HALF": 1, "THREE_QUARTERS": 2, "TOTAL": 3}
    for obs in obstacles:
        if ray_intersects_aabb(pos1, pos2, obs):
            if ranks.get(obs.cover_level, 0) > ranks[highest_cover]:
                highest_cover = obs.cover_level
    return highest_cover


def find_path(
    start: Position, target: Position, obstacles: list[AABB] | None = None
) -> list[Position]:
    return [start, target]
