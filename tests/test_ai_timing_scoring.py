from __future__ import annotations

import pytest

from dnd_sim.ai.scoring import candidate_snapshots, enumerate_legal_action_candidates
from dnd_sim.strategy_api import ActorView, BattleStateView


def _actor_view(
    *,
    actor_id: str,
    team: str,
    hp: int = 30,
    max_hp: int = 30,
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    resources: dict[str, int] | None = None,
) -> ActorView:
    return ActorView(
        actor_id=actor_id,
        team=team,
        hp=hp,
        max_hp=max_hp,
        ac=14,
        save_mods={"str": 0, "dex": 1, "con": 2, "int": 0, "wis": 0, "cha": 0},
        resources=resources or {},
        conditions=set(),
        position=position,
        speed_ft=30,
        movement_remaining=30.0,
        traits={},
        concentrating=False,
    )


def _snapshot(
    snapshots: list[dict[str, object]],
    *,
    action_name: str,
    target_ids: list[str],
) -> dict[str, object]:
    return next(
        row
        for row in snapshots
        if row["action_name"] == action_name and row["target_ids"] == target_ids
    )


def test_recharge_timing_scores_ready_recharge_actions_above_normal_actions() -> None:
    actor = _actor_view(actor_id="hero", team="party")
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(10.0, 0.0, 0.0))
    state = BattleStateView(
        round_number=3,
        actors={actor.actor_id: actor, enemy.actor_id: enemy},
        actor_order=[actor.actor_id, enemy.actor_id],
        metadata={
            "available_actions": {actor.actor_id: ["storm_breath", "slash"]},
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "storm_breath",
                        "action_type": "save",
                        "target_mode": "single_enemy",
                        "range_ft": 30,
                        "action_cost": "action",
                        "resource_cost": {},
                        "tags": ["recharge"],
                        "recharge_ready": True,
                    },
                    {
                        "name": "slash",
                        "action_type": "attack",
                        "target_mode": "single_enemy",
                        "range_ft": 5,
                        "action_cost": "action",
                        "resource_cost": {},
                    },
                ]
            },
        },
    )

    snapshots = candidate_snapshots(enumerate_legal_action_candidates(actor, state))
    breath = _snapshot(snapshots, action_name="storm_breath", target_ids=["enemy"])
    slash = _snapshot(snapshots, action_name="slash", target_ids=["enemy"])

    assert breath["timing"]["recharge_ready"] is True
    assert breath["timing"]["recharge_timing_score"] > 0.0
    assert breath["timing"]["recharge_timing_score"] > slash["timing"]["recharge_timing_score"]


def test_non_recharge_action_with_recharge_ready_flag_does_not_get_recharge_bonus() -> None:
    actor = _actor_view(actor_id="hero", team="party")
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(10.0, 0.0, 0.0))
    state = BattleStateView(
        round_number=3,
        actors={actor.actor_id: actor, enemy.actor_id: enemy},
        actor_order=[actor.actor_id, enemy.actor_id],
        metadata={
            "available_actions": {actor.actor_id: ["slash"]},
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "slash",
                        "action_type": "attack",
                        "target_mode": "single_enemy",
                        "range_ft": 5,
                        "action_cost": "action",
                        "resource_cost": {},
                        "recharge_ready": True,
                    },
                ]
            },
        },
    )

    snapshots = candidate_snapshots(enumerate_legal_action_candidates(actor, state))
    slash = _snapshot(snapshots, action_name="slash", target_ids=["enemy"])

    assert slash["timing"]["recharge_ready"] is False
    assert slash["timing"]["recharge_pending"] is False
    assert slash["timing"]["recharge_timing_score"] == 0.0


def test_legendary_window_timing_scores_setup_actions_when_legendary_pool_is_available() -> None:
    actor = _actor_view(actor_id="dragon", team="enemy")
    target = _actor_view(actor_id="hero", team="party", position=(10.0, 0.0, 0.0))
    state = BattleStateView(
        round_number=4,
        actors={actor.actor_id: actor, target.actor_id: target},
        actor_order=[actor.actor_id, target.actor_id],
        metadata={
            "legendary_actions_remaining_by_actor": {actor.actor_id: 2},
            "available_actions": {actor.actor_id: ["tail_fakeout", "claw"]},
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "tail_fakeout",
                        "action_type": "attack",
                        "target_mode": "single_enemy",
                        "range_ft": 10,
                        "action_cost": "action",
                        "resource_cost": {},
                        "tags": ["legendary_window"],
                    },
                    {
                        "name": "claw",
                        "action_type": "attack",
                        "target_mode": "single_enemy",
                        "range_ft": 5,
                        "action_cost": "action",
                        "resource_cost": {},
                    },
                ]
            },
        },
    )

    snapshots = candidate_snapshots(enumerate_legal_action_candidates(actor, state))
    setup = _snapshot(snapshots, action_name="tail_fakeout", target_ids=["hero"])
    claw = _snapshot(snapshots, action_name="claw", target_ids=["hero"])

    assert setup["timing"]["legendary_actions_remaining"] == 2
    assert setup["timing"]["legendary_action_window_score"] > 0.0
    assert (
        setup["timing"]["legendary_action_window_score"]
        > claw["timing"]["legendary_action_window_score"]
    )


def test_reaction_bait_scores_only_actions_that_pressure_enemy_reactions() -> None:
    actor = _actor_view(actor_id="hero", team="party")
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(5.0, 0.0, 0.0))
    state = BattleStateView(
        round_number=2,
        actors={actor.actor_id: actor, enemy.actor_id: enemy},
        actor_order=[actor.actor_id, enemy.actor_id],
        metadata={
            "enemy_reactions_available_by_actor": {enemy.actor_id: 1},
            "available_actions": {actor.actor_id: ["bait_step", "basic_strike"]},
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "bait_step",
                        "action_type": "attack",
                        "target_mode": "single_enemy",
                        "range_ft": 5,
                        "action_cost": "action",
                        "resource_cost": {},
                        "tags": ["reaction_bait"],
                    },
                    {
                        "name": "basic_strike",
                        "action_type": "attack",
                        "target_mode": "single_enemy",
                        "range_ft": 5,
                        "action_cost": "action",
                        "resource_cost": {},
                    },
                ]
            },
        },
    )

    snapshots = candidate_snapshots(enumerate_legal_action_candidates(actor, state))
    bait = _snapshot(snapshots, action_name="bait_step", target_ids=["enemy"])
    basic = _snapshot(snapshots, action_name="basic_strike", target_ids=["enemy"])

    assert bait["timing"]["reaction_bait_score"] == pytest.approx(0.75)
    assert basic["timing"]["reaction_bait_score"] == 0.0


def test_reaction_bait_uses_fallback_reaction_availability_keys() -> None:
    actor = _actor_view(actor_id="hero", team="party")
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(5.0, 0.0, 0.0))
    state = BattleStateView(
        round_number=2,
        actors={actor.actor_id: actor, enemy.actor_id: enemy},
        actor_order=[actor.actor_id, enemy.actor_id],
        metadata={
            "enemy_reactions_available_by_actor": {},
            "reactions_available_by_actor": {enemy.actor_id: 1},
            "available_actions": {actor.actor_id: ["bait_step"]},
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "bait_step",
                        "action_type": "attack",
                        "target_mode": "single_enemy",
                        "range_ft": 5,
                        "action_cost": "action",
                        "resource_cost": {},
                        "tags": ["reaction_bait"],
                    },
                ]
            },
        },
    )

    snapshots = candidate_snapshots(enumerate_legal_action_candidates(actor, state))
    bait = _snapshot(snapshots, action_name="bait_step", target_ids=["enemy"])

    assert bait["timing"]["reaction_bait_score"] == pytest.approx(0.75)


def test_limited_resource_timing_increases_in_late_encounter_rounds() -> None:
    actor_early = _actor_view(actor_id="hero", team="party", resources={"ki": 1})
    actor_late = _actor_view(actor_id="hero", team="party", resources={"ki": 1})
    enemy_early = _actor_view(actor_id="enemy", team="enemy", position=(5.0, 0.0, 0.0))
    enemy_late = _actor_view(actor_id="enemy", team="enemy", position=(5.0, 0.0, 0.0))
    action = {
        "name": "flurry",
        "action_type": "attack",
        "target_mode": "single_enemy",
        "range_ft": 5,
        "action_cost": "action",
        "resource_cost": {"ki": 1},
        "max_uses": 2,
        "used_count": 1,
    }

    early_state = BattleStateView(
        round_number=1,
        actors={actor_early.actor_id: actor_early, enemy_early.actor_id: enemy_early},
        actor_order=[actor_early.actor_id, enemy_early.actor_id],
        metadata={
            "encounter_expected_rounds": 6,
            "available_actions": {actor_early.actor_id: ["flurry"]},
            "action_catalog": {actor_early.actor_id: [action]},
        },
    )
    late_state = BattleStateView(
        round_number=6,
        actors={actor_late.actor_id: actor_late, enemy_late.actor_id: enemy_late},
        actor_order=[actor_late.actor_id, enemy_late.actor_id],
        metadata={
            "encounter_expected_rounds": 6,
            "available_actions": {actor_late.actor_id: ["flurry"]},
            "action_catalog": {actor_late.actor_id: [action]},
        },
    )

    early_snapshot = candidate_snapshots(
        enumerate_legal_action_candidates(actor_early, early_state)
    )[0]
    late_snapshot = candidate_snapshots(enumerate_legal_action_candidates(actor_late, late_state))[
        0
    ]

    assert early_snapshot["timing"]["limited_use_remaining_ratio"] == pytest.approx(0.5)
    assert early_snapshot["timing"]["limited_resource_timing_score"] < 0.0
    assert late_snapshot["timing"]["limited_resource_timing_score"] > 0.0
    assert (
        late_snapshot["timing"]["limited_resource_timing_score"]
        > early_snapshot["timing"]["limited_resource_timing_score"]
    )
