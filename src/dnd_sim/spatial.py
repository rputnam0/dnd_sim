import math
from dataclasses import dataclass
from typing import Any, Tuple

Position = Tuple[float, float, float]


def distance_euclidean(pos1: Position, pos2: Position) -> float:
    """Standard straight-line distance in 3D space."""
    return math.sqrt((pos1[0] - pos2[0]) ** 2 + (pos1[1] - pos2[1]) ** 2 + (pos1[2] - pos2[2]) ** 2)


def distance_chebyshev(pos1: Position, pos2: Position) -> float:
    """
    Standard D&D 5e grid distance where diagonal and vertical movement
    cost the same as orthogonal movement (1 square/cube = 5ft).
    """
    return max(abs(pos1[0] - pos2[0]), abs(pos1[1] - pos2[1]), abs(pos1[2] - pos2[2]))


def move_towards(current: Position, target: Position, max_distance: float) -> Position:
    """Move 'current' towards 'target' using Euclidean geometry up to 'max_distance'."""
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
    """Returns all positions that fall within a Chebyshev radius of the center point."""
    return [p for p in positions if distance_chebyshev(center, p) <= radius]


@dataclass(slots=True)
class AABB:
    min_pos: Position
    max_pos: Position
    cover_level: str  # "HALF", "THREE_QUARTERS", "TOTAL"


def ray_intersects_aabb(start: Position, end: Position, aabb: AABB) -> bool:
    direction = (end[0] - start[0], end[1] - start[1], end[2] - start[2])
    dist = math.sqrt(direction[0] ** 2 + direction[1] ** 2 + direction[2] ** 2)
    if dist == 0:
        return False

    inv_dir = (
        1.0 / direction[0] if direction[0] != 0 else float("inf"),
        1.0 / direction[1] if direction[1] != 0 else float("inf"),
        1.0 / direction[2] if direction[2] != 0 else float("inf"),
    )

    tmin = (aabb.min_pos[0] - start[0]) * inv_dir[0]
    tmax = (aabb.max_pos[0] - start[0]) * inv_dir[0]
    if inv_dir[0] < 0:
        tmin, tmax = tmax, tmin

    tymin = (aabb.min_pos[1] - start[1]) * inv_dir[1]
    tymax = (aabb.max_pos[1] - start[1]) * inv_dir[1]
    if inv_dir[1] < 0:
        tymin, tymax = tymax, tymin

    if (tmin > tymax) or (tymin > tmax):
        return False

    if tymin > tmin:
        tmin = tymin
    if tymax < tmax:
        tmax = tymax

    tzmin = (aabb.min_pos[2] - start[2]) * inv_dir[2]
    tzmax = (aabb.max_pos[2] - start[2]) * inv_dir[2]
    if inv_dir[2] < 0:
        tzmin, tzmax = tzmax, tzmin

    if (tmin > tzmax) or (tzmin > tmax):
        return False

    if tzmin > tmin:
        tmin = tzmin
    if tzmax < tmax:
        tmax = tzmax

    return tmax >= 0 and tmin <= 1


def _coerce_position(value: Any, default: Position = (0.0, 0.0, 0.0)) -> Position:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError):
            return default
    return default


def _sense_range(observer_traits: dict[str, Any], sense: str, default: float) -> float | None:
    if sense not in observer_traits:
        return None
    value = observer_traits.get(sense)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("range_ft", "range", "distance", "value", "radius"):
            candidate = value.get(key)
            if isinstance(candidate, (int, float)):
                return float(candidate)
    # Presence without a numeric payload defaults to standard range.
    return float(default)


def can_see(
    observer_pos: Position,
    target_pos: Position,
    observer_traits: dict,
    target_conditions: set,
    active_hazards: list,
    light_level: str = "bright",
) -> bool:
    """
    Evaluates RAW 5e vision rules.
    Takes into account invisible targets, magical darkness hazards, and environmental lighting.
    observer_traits: Expects keys like 'truesight', 'blindsight', 'tremorsense', 'darkvision'.
    """
    distance = distance_chebyshev(observer_pos, target_pos)

    truesight = _sense_range(observer_traits, "truesight", 120)
    if truesight is not None and distance <= truesight:
        return True

    # Fighting Initiate (Blind Fighting): treat as 10ft blindsight.
    if "blind fighting" in observer_traits:
        if distance <= 10:
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
        if hazard_type == "magical_darkness":
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
        if darkvision is not None and distance <= darkvision:
            return True
        return False

    return True


def check_cover(pos1: Position, pos2: Position, obstacles: list[AABB] | None = None) -> str:
    """
    Rays cast between pos1 and pos2. Returns the highest level of cover intersected:
    NONE, HALF, THREE_QUARTERS, or TOTAL.
    """
    if not obstacles:
        return "NONE"

    highest_cover = "NONE"
    ranks = {"NONE": 0, "HALF": 1, "THREE_QUARTERS": 2, "TOTAL": 3}

    for obs in obstacles:
        if ray_intersects_aabb(pos1, pos2, obs):
            if ranks[obs.cover_level] > ranks[highest_cover]:
                highest_cover = obs.cover_level

    return highest_cover


def find_path(
    start: Position, target: Position, obstacles: list[AABB] | None = None
) -> list[Position]:
    """
    Finds a valid movement path avoiding obstacles using A*.
    Currently assumes an open battlefield and returns a direct vector.
    """
    return [start, target]
