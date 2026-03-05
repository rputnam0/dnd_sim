import math
from heapq import heappop, heappush
from dataclasses import dataclass
from typing import Any, Tuple

Position = Tuple[float, float, float]
GridCell = tuple[int, int, int]
_CELL_SIZE_FT = 5.0


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


def grid_cell_for_position(pos: Position) -> GridCell:
    """Maps a world-space position to the nearest 5-foot grid cell."""
    return _position_to_cell(pos)


def grid_cell_center(cell: GridCell) -> Position:
    """Returns the world-space center point for a 5-foot grid cell."""
    return _cell_to_position(cell)


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


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_radius(hazard: dict[str, Any], default: float = 15.0) -> float:
    raw = hazard.get("radius", hazard.get("radius_ft", default))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _coerce_hazard_weight(hazard: dict[str, Any], default: float = 1.0) -> float:
    for key in ("severity", "weight", "risk", "damage_per_round", "damage"):
        raw = hazard.get(key)
        if raw is None:
            continue
        try:
            parsed = float(raw)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return float(default)


def _hazard_has_spatial_bounds(hazard: dict[str, Any]) -> bool:
    has_position = isinstance(hazard.get("position"), (list, tuple))
    has_box = isinstance(hazard.get("min_pos") or hazard.get("min"), (list, tuple)) and isinstance(
        hazard.get("max_pos") or hazard.get("max"), (list, tuple)
    )
    return has_position or has_box


def _hazard_contains_position(hazard: dict[str, Any], pos: Position) -> bool:
    min_pos = _coerce_position(hazard.get("min_pos") or hazard.get("min"), default=pos)
    max_pos = _coerce_position(hazard.get("max_pos") or hazard.get("max"), default=pos)
    has_box = bool(
        isinstance(hazard.get("min_pos") or hazard.get("min"), (list, tuple))
        and isinstance(hazard.get("max_pos") or hazard.get("max"), (list, tuple))
    )
    if has_box:
        lower = (
            min(min_pos[0], max_pos[0]),
            min(min_pos[1], max_pos[1]),
            min(min_pos[2], max_pos[2]),
        )
        upper = (
            max(min_pos[0], max_pos[0]),
            max(min_pos[1], max_pos[1]),
            max(min_pos[2], max_pos[2]),
        )
        return (
            lower[0] <= pos[0] <= upper[0]
            and lower[1] <= pos[1] <= upper[1]
            and lower[2] <= pos[2] <= upper[2]
        )

    center = _coerce_position(hazard.get("position"), default=(0.0, 0.0, 0.0))
    radius = _coerce_radius(hazard)
    return distance_chebyshev(pos, center) <= radius


def _hazard_obscures_vision(hazard: dict[str, Any]) -> bool:
    hazard_type = str(
        hazard.get("zone_type") or hazard.get("type") or hazard.get("hazard_type") or ""
    ).lower()
    if _coerce_bool(hazard.get("obscures_vision"), default=False):
        return True
    return hazard_type in {"magical_darkness", "cloud", "obscuring_zone", "obscuring"}


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

    for hazard in active_hazards_rows:
        if not isinstance(hazard, dict):
            continue
        if not _hazard_obscures_vision(hazard):
            continue
        if _hazard_contains_position(hazard, observer_pos) or _hazard_contains_position(
            hazard, target_pos
        ):
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


def has_clear_path(pos1: Position, pos2: Position, obstacles: list[AABB] | None = None) -> bool:
    """Returns True when a segment between two points is not blocked by TOTAL cover."""
    return check_cover(pos1, pos2, obstacles) != "TOTAL"


def point_in_total_cover(point: Position, obstacles: list[AABB] | None = None) -> bool:
    if not obstacles:
        return False
    for obstacle in obstacles:
        if obstacle.cover_level != "TOTAL":
            continue
        if (
            obstacle.min_pos[0] <= point[0] <= obstacle.max_pos[0]
            and obstacle.min_pos[1] <= point[1] <= obstacle.max_pos[1]
            and obstacle.min_pos[2] <= point[2] <= obstacle.max_pos[2]
        ):
            return True
    return False


def is_valid_template_origin(
    *,
    caster_position: Position,
    origin: Position,
    obstacles: list[AABB] | None = None,
) -> bool:
    """A point of origin is legal when it is not inside TOTAL cover and has a clear path."""
    if point_in_total_cover(origin, obstacles):
        return False
    return has_clear_path(caster_position, origin, obstacles)


def template_cells(
    *,
    template: str,
    origin: Position,
    size_ft: float,
    facing: Position | None = None,
) -> set[GridCell]:
    """
    Deterministically resolves grid cells intersected by an AoE template.

    `facing` is required for directional templates (`line`, `cone`).
    """
    try:
        size = float(size_ft)
    except (TypeError, ValueError):
        return set()
    if not math.isfinite(size) or size <= 0:
        return set()

    shape = str(template).strip().lower()
    if not shape:
        return set()

    fx, fy = 0.0, 0.0
    if facing is not None:
        fx, fy = float(facing[0]), float(facing[1])
    facing_len = math.hypot(fx, fy)
    if shape in {"line", "cone"} and facing_len <= 1e-9:
        return set()
    if facing_len > 0:
        fx, fy = fx / facing_len, fy / facing_len

    radius_cells = int(math.ceil(size / _CELL_SIZE_FT)) + 2
    origin_cell = _position_to_cell(origin)
    ox, oy, oz = origin

    out: set[GridCell] = set()
    for cx in range(origin_cell[0] - radius_cells, origin_cell[0] + radius_cells + 1):
        for cy in range(origin_cell[1] - radius_cells, origin_cell[1] + radius_cells + 1):
            for cz in range(origin_cell[2] - radius_cells, origin_cell[2] + radius_cells + 1):
                center = _cell_to_position((cx, cy, cz))
                half = _CELL_SIZE_FT / 2.0
                cell_min = (center[0] - half, center[1] - half, center[2] - half)
                cell_max = (center[0] + half, center[1] + half, center[2] + half)

                include = False
                if shape == "sphere":
                    include = _distance_point_to_box(origin, cell_min, cell_max) <= size + 1e-9
                elif shape == "cylinder":
                    radial = _distance_point_to_rect_2d((ox, oy), cell_min, cell_max)
                    z_gap = _distance_point_to_interval(oz, cell_min[2], cell_max[2])
                    include = radial <= size + 1e-9 and z_gap <= size + 1e-9
                elif shape == "cube":
                    half_side = size / 2.0
                    cube_min = (ox - half_side, oy - half_side, oz - half_side)
                    cube_max = (ox + half_side, oy + half_side, oz + half_side)
                    include = _boxes_overlap(cube_min, cube_max, cell_min, cell_max)
                elif shape == "line":
                    rel_x = center[0] - ox
                    rel_y = center[1] - oy
                    projection = rel_x * fx + rel_y * fy
                    if 0.0 <= projection <= size + 1e-9:
                        perp_sq = max(
                            0.0, (rel_x * rel_x + rel_y * rel_y) - (projection * projection)
                        )
                        include = math.sqrt(perp_sq) <= (_CELL_SIZE_FT / 2.0) + 1e-9
                elif shape == "cone":
                    rel_x = center[0] - ox
                    rel_y = center[1] - oy
                    distance = math.hypot(rel_x, rel_y)
                    if distance <= size + 1e-9:
                        projection = rel_x * fx + rel_y * fy
                        # 5e cone: width at endpoint equals length.
                        cone_cos = math.cos(math.atan(0.5))
                        include = projection >= (distance * cone_cos) - 1e-9

                if include:
                    out.add((cx, cy, cz))
    return out


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


def path_hazard_exposure(
    path: list[Position],
    hazards: list[dict[str, Any]] | None = None,
) -> float:
    """
    Returns a deterministic aggregate risk score for hazards intersecting `path`.
    Each intersected hazard contributes its configured severity/weight once.
    """
    if not path or not hazards:
        return 0.0

    total = 0.0
    for hazard in hazards:
        if not isinstance(hazard, dict):
            continue
        if not _hazard_has_spatial_bounds(hazard):
            continue
        weight = _coerce_hazard_weight(hazard)
        if weight <= 0:
            continue
        if _path_intersects_hazard(path, hazard):
            total += weight
    return total


def _path_intersects_hazard(path: list[Position], hazard: dict[str, Any]) -> bool:
    if len(path) == 1:
        return _hazard_contains_position(hazard, path[0])

    for start, end in zip(path, path[1:]):
        if _segment_intersects_hazard(start, end, hazard):
            return True
    return False


def _segment_intersects_hazard(start: Position, end: Position, hazard: dict[str, Any]) -> bool:
    segment_length = distance_euclidean(start, end)
    if segment_length <= 1e-9:
        return _hazard_contains_position(hazard, start)

    steps = max(1, int(math.ceil(segment_length / _CELL_SIZE_FT)))
    for step in range(steps + 1):
        ratio = float(step) / float(steps)
        sample = (
            start[0] + (end[0] - start[0]) * ratio,
            start[1] + (end[1] - start[1]) * ratio,
            start[2] + (end[2] - start[2]) * ratio,
        )
        if _hazard_contains_position(hazard, sample):
            return True
    return False


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
    return (
        int(round(pos[0] / _CELL_SIZE_FT)),
        int(round(pos[1] / _CELL_SIZE_FT)),
        int(round(pos[2] / _CELL_SIZE_FT)),
    )


def _cell_to_position(cell: Cell) -> Position:
    return (
        cell[0] * _CELL_SIZE_FT,
        cell[1] * _CELL_SIZE_FT,
        cell[2] * _CELL_SIZE_FT,
    )


def _distance_point_to_interval(value: float, low: float, high: float) -> float:
    if value < low:
        return low - value
    if value > high:
        return value - high
    return 0.0


def _distance_point_to_rect_2d(
    point: tuple[float, float],
    rect_min: Position,
    rect_max: Position,
) -> float:
    dx = _distance_point_to_interval(point[0], rect_min[0], rect_max[0])
    dy = _distance_point_to_interval(point[1], rect_min[1], rect_max[1])
    return math.hypot(dx, dy)


def _distance_point_to_box(point: Position, box_min: Position, box_max: Position) -> float:
    dx = _distance_point_to_interval(point[0], box_min[0], box_max[0])
    dy = _distance_point_to_interval(point[1], box_min[1], box_max[1])
    dz = _distance_point_to_interval(point[2], box_min[2], box_max[2])
    return math.sqrt((dx * dx) + (dy * dy) + (dz * dz))


def _boxes_overlap(
    min_a: Position,
    max_a: Position,
    min_b: Position,
    max_b: Position,
) -> bool:
    return not (
        max_a[0] < min_b[0]
        or min_a[0] > max_b[0]
        or max_a[1] < min_b[1]
        or min_a[1] > max_b[1]
        or max_a[2] < min_b[2]
        or min_a[2] > max_b[2]
    )
