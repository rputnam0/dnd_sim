from __future__ import annotations

from dnd_sim.ai.scoring import candidate_snapshots, enumerate_legal_action_candidates
from dnd_sim.strategy_api import ActorView, BattleStateView


def _actor_view(
    *,
    actor_id: str,
    team: str,
    hp: int = 30,
    max_hp: int = 30,
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    concentrating: bool = False,
) -> ActorView:
    return ActorView(
        actor_id=actor_id,
        team=team,
        hp=hp,
        max_hp=max_hp,
        ac=14,
        save_mods={"str": 1, "dex": 2, "con": 2, "int": 0, "wis": 0, "cha": 0},
        resources={},
        conditions=set(),
        position=position,
        speed_ft=30,
        movement_remaining=30.0,
        traits={},
        concentrating=concentrating,
    )


def _snapshot_by_action_and_targets(
    snapshots: list[dict[str, object]], action_name: str, target_ids: list[str]
) -> dict[str, object]:
    return next(
        row
        for row in snapshots
        if row["action_name"] == action_name and row["target_ids"] == target_ids
    )


def test_concentration_break_scoring_prefers_concentrating_enemy_targets() -> None:
    actor = _actor_view(actor_id="hero", team="party")
    concentrating_enemy = _actor_view(
        actor_id="enemy_focus",
        team="enemy",
        position=(5.0, 0.0, 0.0),
        concentrating=True,
    )
    non_concentrating_enemy = _actor_view(
        actor_id="enemy_plain",
        team="enemy",
        position=(6.0, 0.0, 0.0),
        concentrating=False,
    )
    state = BattleStateView(
        round_number=4,
        actors={
            actor.actor_id: actor,
            concentrating_enemy.actor_id: concentrating_enemy,
            non_concentrating_enemy.actor_id: non_concentrating_enemy,
        },
        actor_order=[
            actor.actor_id,
            concentrating_enemy.actor_id,
            non_concentrating_enemy.actor_id,
        ],
        metadata={
            "available_actions": {actor.actor_id: ["arcane_jolt"]},
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "arcane_jolt",
                        "action_type": "attack",
                        "target_mode": "single_enemy",
                        "range_ft": 60,
                        "action_cost": "action",
                        "damage": "2d8",
                        "resource_cost": {},
                        "mechanics": [{"effect_type": "damage", "damage": "2d8"}],
                    }
                ]
            },
        },
    )

    snapshots = candidate_snapshots(enumerate_legal_action_candidates(actor, state))
    on_concentrator = _snapshot_by_action_and_targets(snapshots, "arcane_jolt", ["enemy_focus"])
    on_plain_target = _snapshot_by_action_and_targets(snapshots, "arcane_jolt", ["enemy_plain"])

    assert on_concentrator["control"]["concentration_break_score"] > 0.0
    assert (
        on_concentrator["control"]["concentration_break_score"]
        > on_plain_target["control"]["concentration_break_score"]
    )


def test_condition_application_value_rewards_stronger_control_conditions() -> None:
    actor = _actor_view(actor_id="hero", team="party")
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(5.0, 0.0, 0.0))
    state = BattleStateView(
        round_number=5,
        actors={actor.actor_id: actor, enemy.actor_id: enemy},
        actor_order=[actor.actor_id, enemy.actor_id],
        metadata={
            "available_actions": {actor.actor_id: ["stun_gaze", "trip_sweep"]},
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "stun_gaze",
                        "action_type": "save",
                        "target_mode": "single_enemy",
                        "range_ft": 30,
                        "action_cost": "action",
                        "resource_cost": {},
                        "mechanics": [{"effect_type": "apply_condition", "condition": "stunned"}],
                    },
                    {
                        "name": "trip_sweep",
                        "action_type": "attack",
                        "target_mode": "single_enemy",
                        "range_ft": 5,
                        "action_cost": "action",
                        "resource_cost": {},
                        "mechanics": [{"effect_type": "apply_condition", "condition": "prone"}],
                    },
                ]
            },
        },
    )

    snapshots = candidate_snapshots(enumerate_legal_action_candidates(actor, state))
    stun = _snapshot_by_action_and_targets(snapshots, "stun_gaze", ["enemy"])
    trip = _snapshot_by_action_and_targets(snapshots, "trip_sweep", ["enemy"])

    assert stun["control"]["condition_application_value"] > 0.0
    assert (
        stun["control"]["condition_application_value"]
        > trip["control"]["condition_application_value"]
    )


def test_enemy_action_denial_scoring_prioritizes_hard_cc_over_reaction_lock() -> None:
    actor = _actor_view(actor_id="hero", team="party")
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(5.0, 0.0, 0.0))
    state = BattleStateView(
        round_number=6,
        actors={actor.actor_id: actor, enemy.actor_id: enemy},
        actor_order=[actor.actor_id, enemy.actor_id],
        metadata={
            "available_actions": {actor.actor_id: ["lock_down", "cut_off"]},
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "lock_down",
                        "action_type": "save",
                        "target_mode": "single_enemy",
                        "range_ft": 30,
                        "action_cost": "action",
                        "resource_cost": {},
                        "mechanics": [
                            {"effect_type": "apply_condition", "condition": "incapacitated"}
                        ],
                    },
                    {
                        "name": "cut_off",
                        "action_type": "save",
                        "target_mode": "single_enemy",
                        "range_ft": 30,
                        "action_cost": "action",
                        "resource_cost": {},
                        "mechanics": [
                            {"effect_type": "apply_condition", "condition": "no_reactions"}
                        ],
                    },
                ]
            },
        },
    )

    snapshots = candidate_snapshots(enumerate_legal_action_candidates(actor, state))
    hard_cc = _snapshot_by_action_and_targets(snapshots, "lock_down", ["enemy"])
    reaction_lock = _snapshot_by_action_and_targets(snapshots, "cut_off", ["enemy"])

    assert (
        hard_cc["control"]["enemy_action_denial_score"]
        > reaction_lock["control"]["enemy_action_denial_score"]
    )
    assert reaction_lock["control"]["enemy_action_denial_score"] > 0.0


def test_control_value_score_combines_break_and_denial_components() -> None:
    actor = _actor_view(actor_id="hero", team="party")
    enemy = _actor_view(
        actor_id="enemy",
        team="enemy",
        position=(5.0, 0.0, 0.0),
        concentrating=True,
    )
    state = BattleStateView(
        round_number=7,
        actors={actor.actor_id: actor, enemy.actor_id: enemy},
        actor_order=[actor.actor_id, enemy.actor_id],
        metadata={
            "available_actions": {actor.actor_id: ["shatter_focus", "basic_shot"]},
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "shatter_focus",
                        "action_type": "save",
                        "target_mode": "single_enemy",
                        "range_ft": 30,
                        "action_cost": "action",
                        "damage": "2d8",
                        "resource_cost": {},
                        "mechanics": [
                            {"effect_type": "damage", "damage": "2d8"},
                            {"effect_type": "apply_condition", "condition": "stunned"},
                            {"effect_type": "forced_movement", "distance_ft": 10},
                        ],
                    },
                    {
                        "name": "basic_shot",
                        "action_type": "attack",
                        "target_mode": "single_enemy",
                        "range_ft": 30,
                        "action_cost": "action",
                        "damage": "1d8",
                        "resource_cost": {},
                        "mechanics": [{"effect_type": "damage", "damage": "1d8"}],
                    },
                ]
            },
        },
    )

    snapshots = candidate_snapshots(enumerate_legal_action_candidates(actor, state))
    shatter = _snapshot_by_action_and_targets(snapshots, "shatter_focus", ["enemy"])
    basic = _snapshot_by_action_and_targets(snapshots, "basic_shot", ["enemy"])

    shatter_control = shatter["control"]
    assert shatter_control["control_value_score"] == (
        shatter_control["control_intensity"]
        + shatter_control["concentration_break_score"]
        + shatter_control["condition_application_value"]
        + shatter_control["enemy_action_denial_score"]
    )
    assert shatter_control["control_value_score"] > basic["control"]["control_value_score"]


def test_control_scoring_ignores_non_hostile_targets_for_denial() -> None:
    actor = _actor_view(actor_id="hero", team="party")
    ally = _actor_view(actor_id="ally", team="party", position=(5.0, 0.0, 0.0))
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(5.0, 5.0, 0.0))
    state = BattleStateView(
        round_number=8,
        actors={actor.actor_id: actor, ally.actor_id: ally, enemy.actor_id: enemy},
        actor_order=[actor.actor_id, ally.actor_id, enemy.actor_id],
        metadata={
            "available_actions": {actor.actor_id: ["rally"]},
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "rally",
                        "action_type": "buff",
                        "target_mode": "single_ally",
                        "range_ft": 30,
                        "action_cost": "action",
                        "resource_cost": {},
                        "mechanics": [{"effect_type": "apply_condition", "condition": "stunned"}],
                    }
                ]
            },
        },
    )

    snapshots = candidate_snapshots(enumerate_legal_action_candidates(actor, state))
    ally_target = _snapshot_by_action_and_targets(snapshots, "rally", ["ally"])

    assert ally_target["control"]["concentration_break_score"] == 0.0
    assert ally_target["control"]["condition_application_value"] == 0.0
    assert ally_target["control"]["enemy_action_denial_score"] == 0.0
