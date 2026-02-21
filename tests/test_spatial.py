from __future__ import annotations

from dnd_sim.spatial import AABB, can_see, check_cover


def test_ray_intersects_axis_aligned_boundary_without_nan_false_negative() -> None:
    cover = AABB(min_pos=(0.0, 5.0, -1.0), max_pos=(3.0, 10.0, 1.0), cover_level="TOTAL")
    # Axis-aligned ray with x=0 touching the AABB boundary.
    result = check_cover((0.0, 0.0, 0.0), (0.0, 30.0, 0.0), [cover])
    assert result == "TOTAL"


def test_can_see_matches_normalized_trait_keys() -> None:
    observer_traits = {"dark_vision": 60}
    visible = can_see(
        observer_pos=(0.0, 0.0, 0.0),
        target_pos=(30.0, 0.0, 0.0),
        observer_traits=observer_traits,
        target_conditions=set(),
        active_hazards=[],
        light_level="darkness",
    )
    assert visible is True
