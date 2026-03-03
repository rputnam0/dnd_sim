import math
from heapq import heappop, heappush
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


@dataclass(slots=True)
class VisibilityQueryResult:
    attacker_can_see_target: bool
    target_can_see_attacker: bool
    line_of_sight: bool
    line_of_effect: bool
    cover_level: str
    targeting_legal: bool
    attack_advantage: bool
    attack_disadvantage: bool


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


def _trait_payload(observer_traits: dict[str, Any], trait_name: str) -> tuple[bool, Any]:
    target = trait_name.lower()
    for candidate, payload in observer_traits.items():
        if str(candidate).strip().lower() == target:
            return True, payload
    return False, None


def _sense_range(observer_traits: dict[str, Any], sense: str, default: float) -> float | None:
    found, value = _trait_payload(observer_traits, sense)
    if not found:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("range_ft", "range", "distance", "value", "radius"):
            candidate = value.get(key)
            if isinstance(candidate, (int, float)):
                return float(candidate)
    # Presence without a numeric payload defaults to standard range.
    return float(default)


def _normalize_light_level(light_level: str) -> str:
    key = str(light_level or "bright").strip().lower()
    if key in {"dark", "darkness", "unlit"}:
        return "darkness"
    if key in {"dim", "dim_light", "low"}:
        return "dim"
    return "bright"


def _normalize_obscurement(obscurement: str | None) -> str:
    key = str(obscurement or "").strip().lower().replace(" ", "_")
    if key in {
        "heavy",
        "heavily_obscured",
        "heavily-obscured",
        "opaque",
        "total",
        "total_obscurement",
    }:
        return "heavily_obscured"
    if key in {"light", "lightly_obscured", "lightly-obscured"}:
        return "lightly_obscured"
    return "none"


def _obscurement_rank(obscurement: str | None) -> int:
    normalized = _normalize_obscurement(obscurement)
    if normalized == "heavily_obscured":
        return 2
    if normalized == "lightly_obscured":
        return 1
    return 0


def _hazard_view_context(
    observer_pos: Position,
    target_pos: Position,
    active_hazards: list[dict[str, Any]],
) -> tuple[bool, int]:
    in_magical_darkness = False
    obscurement_rank = 0
    for hazard in active_hazards:
        if not isinstance(hazard, dict):
            continue
        hazard_type = str(hazard.get("type") or hazard.get("hazard_type") or "").lower().strip()
        hazard_pos = _coerce_position(hazard.get("position"), default=(0.0, 0.0, 0.0))
        try:
            hazard_radius = float(hazard.get("radius", hazard.get("radius_ft", 15)))
        except (TypeError, ValueError):
            hazard_radius = 15.0
        affects_view = (
            distance_chebyshev(observer_pos, hazard_pos) <= hazard_radius
            or distance_chebyshev(target_pos, hazard_pos) <= hazard_radius
        )
        if not affects_view:
            continue
        if hazard_type == "magical_darkness":
            in_magical_darkness = True
            obscurement_rank = max(obscurement_rank, 2)
            continue
        if hazard_type in {"heavily_obscured", "heavy_obscurement", "fog_cloud"}:
            obscurement_rank = max(obscurement_rank, 2)
            continue
        if hazard_type in {"lightly_obscured", "light_obscurement"}:
            obscurement_rank = max(obscurement_rank, 1)
            continue
        obscurement_rank = max(
            obscurement_rank,
            _obscurement_rank(
                str(hazard.get("obscurement") or hazard.get("obscurity") or "").strip()
            ),
        )
    return in_magical_darkness, obscurement_rank


def can_see(
    observer_pos: Position,
    target_pos: Position,
    observer_traits: dict,
    target_conditions: set,
    active_hazards: list,
    light_level: str = "bright",
    observer_conditions: set[str] | None = None,
    target_obscurement: str | None = None,
) -> bool:
    """
    Evaluates RAW 5e vision rules.
    Takes into account invisible targets, magical darkness hazards, and environmental lighting.
    observer_traits: Expects keys like 'truesight', 'blindsight', 'tremorsense', 'darkvision'.
    """
    distance = distance_chebyshev(observer_pos, target_pos)
    normalized_target_conditions = {
        str(condition).strip().lower() for condition in target_conditions if str(condition).strip()
    }
    normalized_observer_conditions = {
        str(condition).strip().lower()
        for condition in (observer_conditions or set())
        if str(condition).strip()
    }
    active_hazards_rows = active_hazards if isinstance(active_hazards, list) else []

    truesight = _sense_range(observer_traits, "truesight", 120)
    if truesight is not None and distance <= truesight:
        return True

    # Fighting Initiate (Blind Fighting): treat as 10ft blindsight.
    if _trait_payload(observer_traits, "blind fighting")[0]:
        if distance <= 10:
            return True

    blindsight = _sense_range(observer_traits, "blindsight", 60)
    if blindsight is not None and distance <= blindsight:
        return True

    tremorsense = _sense_range(observer_traits, "tremorsense", 60)
    if tremorsense is not None and distance <= tremorsense:
        return True

    if "blinded" in normalized_observer_conditions:
        return False

    in_magical_darkness, hazard_obscurement_rank = _hazard_view_context(
        observer_pos, target_pos, active_hazards_rows
    )
    effective_obscurement_rank = max(hazard_obscurement_rank, _obscurement_rank(target_obscurement))

    if in_magical_darkness:
        return False

    if effective_obscurement_rank >= 2:
        return False

    if "invisible" in normalized_target_conditions:
        return False

    if _normalize_light_level(light_level) == "darkness":
        darkvision = _sense_range(observer_traits, "darkvision", 60)
        if darkvision is not None and distance <= darkvision:
            return True
        return False

    return True


def query_visibility(
    *,
    attacker_pos: Position,
    target_pos: Position,
    attacker_traits: dict[str, Any],
    target_traits: dict[str, Any],
    attacker_conditions: set[str],
    target_conditions: set[str],
    active_hazards: list[dict[str, Any]] | None = None,
    obstacles: list[AABB] | None = None,
    light_level: str = "bright",
    attacker_obscurement: str | None = None,
    target_obscurement: str | None = None,
    requires_sight: bool = False,
    requires_line_of_effect: bool = False,
) -> VisibilityQueryResult:
    hazard_rows = active_hazards or []
    cover_level = check_cover(attacker_pos, target_pos, obstacles)
    line_of_effect = cover_level != "TOTAL"

    attacker_can_see_target = can_see(
        observer_pos=attacker_pos,
        target_pos=target_pos,
        observer_traits=attacker_traits,
        target_conditions=target_conditions,
        active_hazards=hazard_rows,
        light_level=light_level,
        observer_conditions=attacker_conditions,
        target_obscurement=target_obscurement,
    )
    target_can_see_attacker = can_see(
        observer_pos=target_pos,
        target_pos=attacker_pos,
        observer_traits=target_traits,
        target_conditions=attacker_conditions,
        active_hazards=hazard_rows,
        light_level=light_level,
        observer_conditions=target_conditions,
        target_obscurement=attacker_obscurement,
    )

    line_of_sight = attacker_can_see_target
    targeting_legal = (line_of_sight or not requires_sight) and (
        line_of_effect or not requires_line_of_effect
    )

    return VisibilityQueryResult(
        attacker_can_see_target=attacker_can_see_target,
        target_can_see_attacker=target_can_see_attacker,
        line_of_sight=line_of_sight,
        line_of_effect=line_of_effect,
        cover_level=cover_level,
        targeting_legal=targeting_legal,
        attack_advantage=not target_can_see_attacker,
        attack_disadvantage=not attacker_can_see_target,
    )


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


Cell = tuple[int, int, int]


def find_path(
    start: Position,
    target: Position,
    obstacles: list[AABB] | None = None,
    occupied_positions: list[Position] | None = None,
    difficult_terrain_positions: list[Position] | None = None,
) -> list[Position]:
    """
    Finds a deterministic, legal movement route on a 5 ft grid using weighted A*.
    TOTAL-cover obstacles and occupied squares are blocked.
    Difficult terrain is traversable but doubles movement cost.
    """
    if not obstacles and not occupied_positions and not difficult_terrain_positions:
        return [start, target]

    obstacle_list = obstacles or []
    total_obstacles = [obs for obs in obstacle_list if obs.cover_level == "TOTAL"]
    occupied_cells = {
        _position_to_cell(pos)
        for pos in (occupied_positions or [])
        if distance_chebyshev(pos, start) > 0
    }
    difficult_cells = {_position_to_cell(pos) for pos in (difficult_terrain_positions or [])}

    start_cell = _position_to_cell(start)
    target_cell = _position_to_cell(target)
    if start_cell == target_cell:
        return [start] if start == target else [start, target]

    points = [start_cell, target_cell, *occupied_cells, *difficult_cells]
    for obs in total_obstacles:
        points.append(_position_to_cell(obs.min_pos))
        points.append(_position_to_cell(obs.max_pos))

    margin = 4
    min_x = min(cell[0] for cell in points) - margin
    max_x = max(cell[0] for cell in points) + margin
    min_y = min(cell[1] for cell in points) - margin
    max_y = max(cell[1] for cell in points) + margin
    if start_cell[2] == target_cell[2]:
        min_z = max_z = start_cell[2]
    else:
        min_z = min(cell[2] for cell in points) - margin
        max_z = max(cell[2] for cell in points) + margin

    def in_bounds(cell: Cell) -> bool:
        return min_x <= cell[0] <= max_x and min_y <= cell[1] <= max_y and min_z <= cell[2] <= max_z

    def blocked(cell: Cell) -> bool:
        if cell in occupied_cells and cell not in {start_cell, target_cell}:
            return True
        pos = _cell_to_position(cell)
        for obs in total_obstacles:
            if (
                obs.min_pos[0] <= pos[0] <= obs.max_pos[0]
                and obs.min_pos[1] <= pos[1] <= obs.max_pos[1]
                and obs.min_pos[2] <= pos[2] <= obs.max_pos[2]
            ):
                return True
        return False

    if blocked(target_cell):
        return [start]

    dz_values = (0,) if start_cell[2] == target_cell[2] else (-1, 0, 1)
    neighbor_deltas = sorted(
        [
            (dx, dy, dz)
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for dz in dz_values
            if not (dx == 0 and dy == 0 and dz == 0)
        ],
        key=lambda delta: (
            abs(delta[0]) + abs(delta[1]) + abs(delta[2]),
            delta[0],
            delta[1],
            delta[2],
        ),
    )

    open_heap: list[tuple[float, float, int, int, int]] = []
    heappush(
        open_heap,
        (
            _cell_heuristic(start_cell, target_cell),
            0.0,
            start_cell[0],
            start_cell[1],
            start_cell[2],
        ),
    )
    came_from: dict[Cell, Cell] = {}
    g_score: dict[Cell, float] = {start_cell: 0.0}

    while open_heap:
        _, current_cost, x, y, z = heappop(open_heap)
        current = (x, y, z)
        if current == target_cell:
            break
        if current_cost > g_score.get(current, float("inf")):
            continue

        for dx, dy, dz in neighbor_deltas:
            neighbor = (current[0] + dx, current[1] + dy, current[2] + dz)
            if not in_bounds(neighbor) or blocked(neighbor):
                continue
            step_cost = 2.0 if neighbor in difficult_cells else 1.0
            candidate_cost = current_cost + step_cost
            if candidate_cost + 1e-9 >= g_score.get(neighbor, float("inf")):
                continue
            came_from[neighbor] = current
            g_score[neighbor] = candidate_cost
            heappush(
                open_heap,
                (
                    candidate_cost + _cell_heuristic(neighbor, target_cell),
                    candidate_cost,
                    neighbor[0],
                    neighbor[1],
                    neighbor[2],
                ),
            )

    if target_cell not in g_score:
        return [start]

    cell_path = [target_cell]
    cursor = target_cell
    while cursor != start_cell:
        cursor = came_from[cursor]
        cell_path.append(cursor)
    cell_path.reverse()

    path: list[Position] = [start]
    for cell in cell_path[1:-1]:
        path.append(_cell_to_position(cell))
    path.append(target)
    return path


def path_movement_cost(
    path: list[Position],
    difficult_terrain_positions: list[Position] | None = None,
) -> float:
    """Returns movement cost in feet for a path, doubling cost in difficult terrain cells."""
    if len(path) < 2:
        return 0.0
    difficult_cells = {_position_to_cell(pos) for pos in (difficult_terrain_positions or [])}
    total_cost = 0.0
    current_cell = _position_to_cell(path[0])
    for waypoint in path[1:]:
        next_cell = _position_to_cell(waypoint)
        total_cost += _cell_traversal_cost(current_cell, next_cell, difficult_cells)
        current_cell = next_cell
    return total_cost * 5.0


def path_prefix_for_movement(
    path: list[Position],
    movement_budget_ft: float,
    difficult_terrain_positions: list[Position] | None = None,
) -> list[Position]:
    """
    Returns the furthest legal prefix of path reachable within movement_budget_ft.
    Movement is quantized to 5 ft cell entries.
    """
    if not path:
        return []
    if len(path) == 1 or movement_budget_ft <= 0:
        return [path[0]]

    difficult_cells = {_position_to_cell(pos) for pos in (difficult_terrain_positions or [])}
    remaining_cost_units = movement_budget_ft / 5.0
    prefix: list[Position] = [path[0]]
    current_cell = _position_to_cell(path[0])

    for waypoint in path[1:]:
        target_cell = _position_to_cell(waypoint)
        if current_cell == target_cell:
            if prefix[-1] != waypoint:
                prefix.append(waypoint)
            continue

        for next_cell in _iter_cells_between(current_cell, target_cell):
            step_cost = 2.0 if next_cell in difficult_cells else 1.0
            if step_cost > (remaining_cost_units + 1e-9):
                return prefix
            remaining_cost_units -= step_cost
            current_cell = next_cell
            cell_pos = _cell_to_position(current_cell)
            if prefix[-1] != cell_pos:
                prefix.append(cell_pos)

        if prefix[-1] != waypoint:
            prefix.append(waypoint)

    return prefix


def _cell_heuristic(cell: Cell, target_cell: Cell) -> float:
    return float(
        max(
            abs(cell[0] - target_cell[0]),
            abs(cell[1] - target_cell[1]),
            abs(cell[2] - target_cell[2]),
        )
    )


def _cell_traversal_cost(start_cell: Cell, end_cell: Cell, difficult_cells: set[Cell]) -> float:
    total_cost = 0.0
    for cell in _iter_cells_between(start_cell, end_cell):
        total_cost += 2.0 if cell in difficult_cells else 1.0
    return total_cost


def _iter_cells_between(start_cell: Cell, end_cell: Cell) -> list[Cell]:
    cells: list[Cell] = []
    current = start_cell
    while current != end_cell:
        current = (
            current[0] + _step_toward_axis(end_cell[0] - current[0]),
            current[1] + _step_toward_axis(end_cell[1] - current[1]),
            current[2] + _step_toward_axis(end_cell[2] - current[2]),
        )
        cells.append(current)
    return cells


def _step_toward_axis(delta: int) -> int:
    if delta > 0:
        return 1
    if delta < 0:
        return -1
    return 0


def _position_to_cell(pos: Position) -> Cell:
    return (int(round(pos[0] / 5.0)), int(round(pos[1] / 5.0)), int(round(pos[2] / 5.0)))


def _cell_to_position(cell: Cell) -> Position:
    return (cell[0] * 5.0, cell[1] * 5.0, cell[2] * 5.0)
