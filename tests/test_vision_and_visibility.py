from __future__ import annotations

from dnd_sim.spatial import AABB, query_visibility


def test_invisible_target_unseen_but_targetable_when_legal() -> None:
    result = query_visibility(
        attacker_pos=(0.0, 0.0, 0.0),
        target_pos=(10.0, 0.0, 0.0),
        attacker_traits={},
        target_traits={},
        attacker_conditions=set(),
        target_conditions={"invisible"},
        active_hazards=[],
        obstacles=[],
        light_level="bright",
        requires_sight=False,
        requires_line_of_effect=True,
    )

    assert result.attacker_can_see_target is False
    assert result.targeting_legal is True
    assert result.attack_disadvantage is True


def test_blindsight_ignores_visual_obscurement_in_range() -> None:
    result = query_visibility(
        attacker_pos=(0.0, 0.0, 0.0),
        target_pos=(10.0, 0.0, 0.0),
        attacker_traits={"blindsight": 15},
        target_traits={},
        attacker_conditions=set(),
        target_conditions={"invisible"},
        active_hazards=[],
        obstacles=[],
        light_level="darkness",
        target_obscurement="heavily_obscured",
    )

    assert result.attacker_can_see_target is True
    assert result.attack_disadvantage is False
    assert result.targeting_legal is True


def test_magical_darkness_blocks_normal_vision_but_not_truesight() -> None:
    hazards = [{"type": "magical_darkness", "position": (5.0, 0.0, 0.0), "radius": 20}]

    normal = query_visibility(
        attacker_pos=(0.0, 0.0, 0.0),
        target_pos=(10.0, 0.0, 0.0),
        attacker_traits={},
        target_traits={},
        attacker_conditions=set(),
        target_conditions=set(),
        active_hazards=hazards,
        obstacles=[],
        light_level="bright",
    )
    truesight = query_visibility(
        attacker_pos=(0.0, 0.0, 0.0),
        target_pos=(10.0, 0.0, 0.0),
        attacker_traits={"truesight": {"range_ft": 60}},
        target_traits={},
        attacker_conditions=set(),
        target_conditions=set(),
        active_hazards=hazards,
        obstacles=[],
        light_level="bright",
    )

    assert normal.attacker_can_see_target is False
    assert truesight.attacker_can_see_target is True


def test_line_of_effect_blocked_even_when_line_of_sight_exists() -> None:
    result = query_visibility(
        attacker_pos=(0.0, 0.0, 0.0),
        target_pos=(30.0, 0.0, 0.0),
        attacker_traits={},
        target_traits={},
        attacker_conditions=set(),
        target_conditions=set(),
        active_hazards=[],
        obstacles=[
            AABB(min_pos=(10.0, -1.0, -1.0), max_pos=(20.0, 1.0, 1.0), cover_level="TOTAL")
        ],
        light_level="bright",
        requires_sight=False,
        requires_line_of_effect=True,
    )

    assert result.line_of_sight is True
    assert result.line_of_effect is False
    assert result.targeting_legal is False
