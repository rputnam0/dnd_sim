from __future__ import annotations

import pytest

from dnd_sim.models import ActorRuntimeState
from dnd_sim.movement_runtime import (
    MovementPathValidationError,
    difficult_terrain_positions_from_hazards,
    movement_reach_transitions,
    movement_triggers_opportunity_attacks,
    path_movement_cost_with_hazards,
    path_prefix_for_movement_budget,
    prepare_voluntary_movement,
    resolve_forced_movement_destination,
    validate_declared_movement_path,
)


def _actor() -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id="hero",
        team="party",
        name="Hero",
        max_hp=20,
        hp=20,
        temp_hp=0,
        ac=12,
        initiative_mod=0,
        str_mod=0,
        dex_mod=0,
        con_mod=0,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def _difficult_hazard() -> list[dict[str, object]]:
    return [
        {
            "hazard_type": "difficult_terrain",
            "position": (5.0, 0.0, 0.0),
            "radius_ft": 0,
        }
    ]


def test_path_movement_cost_respects_difficult_terrain_and_crawling() -> None:
    path = [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
    hazards = _difficult_hazard()

    assert path_movement_cost_with_hazards(path, active_hazards=hazards, crawling=False) == 15.0
    assert path_movement_cost_with_hazards(path, active_hazards=hazards, crawling=True) == 30.0


def test_path_prefix_for_budget_reports_spent_cost() -> None:
    path = [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
    hazards = _difficult_hazard()
    difficult_positions = set(difficult_terrain_positions_from_hazards(hazards))

    prefix, spent = path_prefix_for_movement_budget(
        path,
        movement_budget_ft=10.0,
        crawling=False,
        movement_multiplier_for_position=lambda point: 2.0 if point in difficult_positions else 1.0,
    )
    assert prefix == [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0)]
    assert spent == 10.0


def test_validate_declared_movement_path_requires_actor_start_position() -> None:
    with pytest.raises(MovementPathValidationError, match="movement_path_start_mismatch"):
        validate_declared_movement_path(
            movement_path=[(5.0, 0.0, 0.0)],
            actor_position=(0.0, 0.0, 0.0),
        )


def test_prepare_voluntary_movement_spends_prone_stand_cost() -> None:
    actor = _actor()
    actor.speed_ft = 30
    actor.movement_remaining = 30.0
    actor.conditions.add("prone")

    removed: list[str] = []
    available, crawling = prepare_voluntary_movement(
        actor,
        remove_condition=lambda _actor, condition: removed.append(condition),
    )

    assert available == 15.0
    assert crawling is False
    assert actor.movement_remaining == 15.0
    assert removed == ["prone"]


def test_forced_movement_and_opportunity_attack_gating() -> None:
    start = (0.0, 0.0, 0.0)
    end = (10.0, 0.0, 0.0)

    assert (
        movement_triggers_opportunity_attacks(
            movement_kind="forced",
            mover_conditions=set(),
            start_pos=start,
            end_pos=end,
        )
        is False
    )
    assert (
        movement_triggers_opportunity_attacks(
            movement_kind="voluntary",
            mover_conditions={"disengaging"},
            start_pos=start,
            end_pos=end,
        )
        is False
    )
    assert (
        movement_triggers_opportunity_attacks(
            movement_kind="voluntary",
            mover_conditions=set(),
            start_pos=start,
            end_pos=end,
        )
        is True
    )


def test_reach_transitions_emit_enter_then_exit() -> None:
    transitions = movement_reach_transitions(
        reactor_position=(0.0, 0.0, 0.0),
        path_points=[(10.0, 0.0, 0.0), (5.0, 0.0, 0.0), (10.0, 0.0, 0.0)],
        reach_ft=5.0,
    )

    assert [row[0] for row in transitions] == ["enter_reach", "exit_reach"]


def test_resolve_forced_movement_destination_supports_toward_and_away() -> None:
    source = (0.0, 0.0, 0.0)
    target = (10.0, 0.0, 0.0)

    toward = resolve_forced_movement_destination(
        source_pos=source,
        target_pos=target,
        direction="toward_source",
        distance_ft=5.0,
    )
    away = resolve_forced_movement_destination(
        source_pos=source,
        target_pos=target,
        direction="away_from_source",
        distance_ft=5.0,
    )

    assert toward == (5.0, 0.0, 0.0)
    assert away == (15.0, 0.0, 0.0)
