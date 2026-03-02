from dnd_sim.spatial import (
    AABB,
    can_see,
    check_cover,
    distance_chebyshev,
    distance_euclidean,
    find_path,
    move_towards,
)


def test_distance_metrics() -> None:
    pos1 = (0.0, 0.0, 0.0)
    pos2 = (15.0, 20.0, 0.0)
    assert distance_euclidean(pos1, pos2) == 25.0
    assert distance_chebyshev(pos1, pos2) == 20.0


def test_move_towards() -> None:
    start = (0.0, 0.0, 0.0)
    target = (30.0, 40.0, 0.0)
    assert move_towards(start, target, max_distance=25.0) == (15.0, 20.0, 0.0)
    assert move_towards(start, target, max_distance=100.0) == target
    assert move_towards(start, start, max_distance=30.0) == start


def test_can_see_darkvision_blocked_by_magical_darkness() -> None:
    observer_pos = (0.0, 0.0, 0.0)
    target_pos = (10.0, 0.0, 0.0)
    hazards = [{"type": "magical_darkness", "position": (5.0, 0.0, 0.0), "radius": 20}]
    assert (
        can_see(
            observer_pos,
            target_pos,
            observer_traits={"darkvision": 60},
            target_conditions=set(),
            active_hazards=hazards,
        )
        is False
    )


def test_can_see_truesight_with_dict_range_beats_magical_darkness_and_invisibility() -> None:
    observer_pos = (0.0, 0.0, 0.0)
    target_pos = (10.0, 0.0, 0.0)
    hazards = [{"type": "magical_darkness", "position": (5.0, 0.0, 0.0), "radius": 20}]
    assert (
        can_see(
            observer_pos,
            target_pos,
            observer_traits={"truesight": {"range_ft": 120}},
            target_conditions={"invisible"},
            active_hazards=hazards,
        )
        is True
    )


def test_check_cover_picks_highest_cover_level() -> None:
    pos1 = (0.0, 0.0, 0.0)
    pos2 = (30.0, 0.0, 0.0)
    obstacles = [
        AABB(min_pos=(5.0, -1.0, -1.0), max_pos=(10.0, 1.0, 1.0), cover_level="HALF"),
        AABB(min_pos=(15.0, -1.0, -1.0), max_pos=(20.0, 1.0, 1.0), cover_level="THREE_QUARTERS"),
    ]
    assert check_cover(pos1, pos2, obstacles) == "THREE_QUARTERS"


def test_find_path_routes_around_total_cover_obstacle() -> None:
    start = (0.0, 0.0, 0.0)
    target = (30.0, 0.0, 0.0)
    obstacles = [AABB(min_pos=(10.0, -2.0, -1.0), max_pos=(20.0, 2.0, 1.0), cover_level="TOTAL")]

    path = find_path(start, target, obstacles)

    assert path[0] == start
    assert path[-1] == target
    assert len(path) > 2


def test_find_path_avoids_occupied_space() -> None:
    start = (0.0, 0.0, 0.0)
    target = (30.0, 0.0, 0.0)
    occupied = [(15.0, 0.0, 0.0)]

    path = find_path(start, target, occupied_positions=occupied)

    assert path[0] == start
    assert path[-1] == target
    assert len(path) > 2
    assert (15.0, 0.0, 0.0) not in path
