from __future__ import annotations

import pytest

from dnd_sim.ai.scoring import candidate_snapshots, enumerate_legal_action_candidates
from dnd_sim.spatial import AABB
from dnd_sim.strategy_api import ActorView, BattleStateView


def _actor_view(
    *,
    actor_id: str,
    team: str,
    hp: int = 30,
    max_hp: int = 30,
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    movement_remaining: float = 30.0,
) -> ActorView:
    return ActorView(
        actor_id=actor_id,
        team=team,
        hp=hp,
        max_hp=max_hp,
        ac=14,
        save_mods={"str": 0, "dex": 1, "con": 2, "int": 0, "wis": 0, "cha": 0},
        resources={},
        conditions=set(),
        position=position,
        speed_ft=30,
        movement_remaining=movement_remaining,
        traits={},
        concentrating=False,
    )


def _single_action_state(
    *,
    actor: ActorView,
    others: list[ActorView],
    action: dict[str, object],
    metadata: dict[str, object] | None = None,
) -> BattleStateView:
    actors = {actor.actor_id: actor, **{entry.actor_id: entry for entry in others}}
    return BattleStateView(
        round_number=1,
        actors=actors,
        actor_order=list(actors.keys()),
        metadata={
            "available_actions": {actor.actor_id: [str(action["name"])]},
            "action_catalog": {actor.actor_id: [action]},
            **(metadata or {}),
        },
    )


def test_hazard_exposure_counts_path_intersections() -> None:
    actor = _actor_view(actor_id="hero", team="party", position=(0.0, 0.0, 0.0))
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(30.0, 0.0, 0.0))
    action = {
        "name": "charge_strike",
        "action_type": "attack",
        "target_mode": "single_enemy",
        "action_cost": "action",
        "range_ft": 5,
        "resource_cost": {},
    }
    state = _single_action_state(
        actor=actor,
        others=[enemy],
        action=action,
        metadata={
            "active_hazards": [
                {"id": "lava_line", "position": (15.0, 0.0, 0.0), "radius_ft": 5, "severity": 2}
            ]
        },
    )

    snapshot = candidate_snapshots(enumerate_legal_action_candidates(actor, state))[0]
    assert snapshot["hazard"]["hazard_exposure_score"] == 2.0


def test_route_quality_penalizes_detours_and_difficult_terrain() -> None:
    actor = _actor_view(actor_id="hero", team="party", position=(0.0, 0.0, 0.0))
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(30.0, 0.0, 0.0))
    action = {
        "name": "close_gap",
        "action_type": "attack",
        "target_mode": "single_enemy",
        "action_cost": "action",
        "range_ft": 5,
        "resource_cost": {},
    }

    clear_state = _single_action_state(actor=actor, others=[enemy], action=action)
    clear_snapshot = candidate_snapshots(enumerate_legal_action_candidates(actor, clear_state))[0]
    assert clear_snapshot["spatial"]["route_quality_score"] == pytest.approx(1.0)

    detour_state = _single_action_state(
        actor=actor,
        others=[enemy],
        action=action,
        metadata={
            "obstacles": [
                AABB(min_pos=(10.0, -20.0, -1.0), max_pos=(20.0, 20.0, 1.0), cover_level="TOTAL")
            ],
        },
    )
    detour_snapshot = candidate_snapshots(enumerate_legal_action_candidates(actor, detour_state))[0]

    assert 0.0 < clear_snapshot["spatial"]["route_quality_score"] <= 1.0
    assert 0.0 < detour_snapshot["spatial"]["route_quality_score"] <= 1.0
    assert (
        detour_snapshot["spatial"]["route_quality_score"]
        < clear_snapshot["spatial"]["route_quality_score"]
    )


def test_route_quality_is_one_for_small_move_into_long_range() -> None:
    actor = _actor_view(actor_id="caster", team="party", position=(0.0, 0.0, 0.0))
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(65.0, 0.0, 0.0))
    action = {
        "name": "long_ray",
        "action_type": "save",
        "target_mode": "single_enemy",
        "action_cost": "action",
        "range_ft": 60,
        "resource_cost": {},
    }

    state = _single_action_state(actor=actor, others=[enemy], action=action)
    snapshot = candidate_snapshots(enumerate_legal_action_candidates(actor, state))[0]

    assert snapshot["range"]["requires_movement"] is True
    assert snapshot["spatial"]["route_quality_score"] == pytest.approx(1.0)


def test_cover_and_loe_use_post_movement_origin() -> None:
    actor = _actor_view(actor_id="fighter", team="party", position=(0.0, 0.0, 0.0))
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(30.0, 0.0, 0.0))
    action = {
        "name": "lunge",
        "action_type": "attack",
        "target_mode": "single_enemy",
        "action_cost": "action",
        "range_ft": 5,
        "resource_cost": {},
    }
    state = _single_action_state(
        actor=actor,
        others=[enemy],
        action=action,
        metadata={
            "obstacles": [
                AABB(min_pos=(10.0, -5.0, -1.0), max_pos=(20.0, 5.0, 1.0), cover_level="TOTAL")
            ]
        },
    )

    snapshot = candidate_snapshots(enumerate_legal_action_candidates(actor, state))[0]
    assert snapshot["range"]["requires_movement"] is True
    assert snapshot["spatial"]["line_of_effect_clear"] is True
    assert snapshot["spatial"]["line_of_effect_penalty"] == 0.0
    assert snapshot["spatial"]["cover_penalty"] == 0.0


def test_cover_and_line_of_effect_penalties_are_scored() -> None:
    actor = _actor_view(actor_id="archer", team="party", position=(0.0, 0.0, 0.0))
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(30.0, 0.0, 0.0))
    action = {
        "name": "longbow",
        "action_type": "attack",
        "target_mode": "single_enemy",
        "action_cost": "action",
        "range_ft": 150,
        "resource_cost": {},
    }

    partial_cover_state = _single_action_state(
        actor=actor,
        others=[enemy],
        action=action,
        metadata={
            "obstacles": [
                AABB(
                    min_pos=(10.0, -1.0, -1.0),
                    max_pos=(20.0, 1.0, 1.0),
                    cover_level="THREE_QUARTERS",
                )
            ]
        },
    )
    partial_snapshot = candidate_snapshots(
        enumerate_legal_action_candidates(actor, partial_cover_state)
    )[0]
    assert partial_snapshot["spatial"]["cover_level"] == "THREE_QUARTERS"
    assert partial_snapshot["spatial"]["cover_penalty"] > 0.0
    assert partial_snapshot["spatial"]["line_of_effect_clear"] is True
    assert partial_snapshot["spatial"]["line_of_effect_penalty"] == 0.0

    total_cover_state = _single_action_state(
        actor=actor,
        others=[enemy],
        action=action,
        metadata={
            "obstacles": [
                AABB(min_pos=(10.0, -1.0, -1.0), max_pos=(20.0, 1.0, 1.0), cover_level="TOTAL")
            ]
        },
    )
    total_snapshot = candidate_snapshots(
        enumerate_legal_action_candidates(actor, total_cover_state)
    )[0]
    assert total_snapshot["spatial"]["cover_level"] == "TOTAL"
    assert total_snapshot["spatial"]["line_of_effect_clear"] is False
    assert total_snapshot["spatial"]["line_of_effect_penalty"] > 0.0


def test_aoe_friendly_fire_penalty_and_geometry_score() -> None:
    actor = _actor_view(actor_id="caster", team="party", position=(0.0, 0.0, 0.0))
    ally = _actor_view(actor_id="ally", team="party", position=(22.0, 0.0, 0.0))
    enemy_a = _actor_view(actor_id="enemy_a", team="enemy", position=(20.0, 0.0, 0.0))
    enemy_b = _actor_view(actor_id="enemy_b", team="enemy", position=(25.0, 0.0, 0.0))
    action = {
        "name": "fireburst",
        "action_type": "save",
        "target_mode": "single_enemy",
        "action_cost": "action",
        "range_ft": 60,
        "aoe_type": "sphere",
        "aoe_size_ft": 10,
        "resource_cost": {},
    }
    state = _single_action_state(actor=actor, others=[ally, enemy_a, enemy_b], action=action)

    snapshots = candidate_snapshots(enumerate_legal_action_candidates(actor, state))
    primary_enemy = next(row for row in snapshots if row["target_ids"] == ["enemy_a"])
    assert primary_enemy["hazard"]["friendly_fire_risk"] is True
    assert primary_enemy["hazard"]["estimated_affected_count"] == 3
    assert primary_enemy["spatial"]["friendly_fire_penalty"] == 2.0
    assert primary_enemy["spatial"]["geometry_score"] == 1.0
