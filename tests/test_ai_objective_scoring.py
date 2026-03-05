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
    resources: dict[str, int] | None = None,
    concentrating: bool = False,
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


def test_retreat_threshold_scoring_prefers_retreat_when_below_survival_threshold() -> None:
    actor = _actor_view(actor_id="hero", team="party", hp=6, max_hp=30)
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(5.0, 0.0, 0.0))
    state = BattleStateView(
        round_number=4,
        actors={actor.actor_id: actor, enemy.actor_id: enemy},
        actor_order=[actor.actor_id, enemy.actor_id],
        metadata={
            "survival_threshold_ratio": 0.35,
            "available_actions": {actor.actor_id: ["withdraw", "strike"]},
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "withdraw",
                        "action_type": "utility",
                        "target_mode": "self",
                        "action_cost": "action",
                        "tags": ["retreat"],
                    },
                    {
                        "name": "strike",
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
    retreat = _snapshot_by_action_and_targets(snapshots, "withdraw", ["hero"])
    strike = _snapshot_by_action_and_targets(snapshots, "strike", ["enemy"])

    retreat_tradeoff = retreat["objective_tradeoff"]
    strike_tradeoff = strike["objective_tradeoff"]
    assert retreat_tradeoff["survival_pressure"] > 0.0
    assert retreat_tradeoff["retreat_score"] > strike_tradeoff["retreat_score"]


def test_objective_race_scoring_increases_when_clock_is_short() -> None:
    actor = _actor_view(actor_id="hero", team="party")
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(5.0, 0.0, 0.0))
    state = BattleStateView(
        round_number=8,
        actors={actor.actor_id: actor, enemy.actor_id: enemy},
        actor_order=[actor.actor_id, enemy.actor_id],
        metadata={
            "objective_rounds_remaining": 1,
            "objective_race_weight": 1.5,
            "objective_race_baseline": 100.0,
            "objective_scores": {"secure_relic": 4.0, "relic": 2.0},
            "available_actions": {actor.actor_id: ["secure_relic", "strike"]},
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "secure_relic",
                        "action_type": "utility",
                        "target_mode": "self",
                        "action_cost": "action",
                        "tags": ["objective:relic", "objective_race"],
                    },
                    {
                        "name": "strike",
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
    secure = _snapshot_by_action_and_targets(snapshots, "secure_relic", ["hero"])
    strike = _snapshot_by_action_and_targets(snapshots, "strike", ["enemy"])

    secure_tradeoff = secure["objective_tradeoff"]
    strike_tradeoff = strike["objective_tradeoff"]
    assert secure_tradeoff["objective_race_score"] > 0.0
    assert secure_tradeoff["objective_race_score"] > strike_tradeoff["objective_race_score"]
    assert secure_tradeoff["objective_race_score"] == 16.2


def test_objective_race_tag_without_explicit_score_uses_nonzero_baseline() -> None:
    actor = _actor_view(actor_id="hero", team="party")
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(5.0, 0.0, 0.0))
    state = BattleStateView(
        round_number=4,
        actors={actor.actor_id: actor, enemy.actor_id: enemy},
        actor_order=[actor.actor_id, enemy.actor_id],
        metadata={
            "objective_race_weight": 1.5,
            "objective_race_baseline": 2.0,
            "available_actions": {actor.actor_id: ["contest_point", "strike"]},
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "contest_point",
                        "action_type": "utility",
                        "target_mode": "self",
                        "action_cost": "action",
                        "tags": ["objective_race"],
                    },
                    {
                        "name": "strike",
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
    contest = _snapshot_by_action_and_targets(snapshots, "contest_point", ["hero"])
    strike = _snapshot_by_action_and_targets(snapshots, "strike", ["enemy"])

    contest_tradeoff = contest["objective_tradeoff"]
    strike_tradeoff = strike["objective_tradeoff"]
    assert contest_tradeoff["objective_race_score"] == 3.0
    assert contest_tradeoff["objective_race_score"] > strike_tradeoff["objective_race_score"]


def test_focus_fire_tradeoff_scores_focus_target_above_split_targeting() -> None:
    actor = _actor_view(actor_id="hero", team="party")
    enemy_a = _actor_view(
        actor_id="enemy_a", team="enemy", hp=8, max_hp=24, position=(5.0, 0.0, 0.0)
    )
    enemy_b = _actor_view(
        actor_id="enemy_b", team="enemy", hp=24, max_hp=24, position=(6.0, 0.0, 0.0)
    )
    state = BattleStateView(
        round_number=5,
        actors={actor.actor_id: actor, enemy_a.actor_id: enemy_a, enemy_b.actor_id: enemy_b},
        actor_order=[actor.actor_id, enemy_a.actor_id, enemy_b.actor_id],
        metadata={
            "focus_fire_target_id": "enemy_a",
            "available_actions": {actor.actor_id: ["strike"]},
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "strike",
                        "action_type": "attack",
                        "target_mode": "single_enemy",
                        "range_ft": 5,
                        "action_cost": "action",
                        "resource_cost": {},
                    }
                ]
            },
        },
    )

    snapshots = candidate_snapshots(enumerate_legal_action_candidates(actor, state))
    focus = _snapshot_by_action_and_targets(snapshots, "strike", ["enemy_a"])
    non_focus = _snapshot_by_action_and_targets(snapshots, "strike", ["enemy_b"])

    assert (
        focus["objective_tradeoff"]["focus_fire_score"]
        > non_focus["objective_tradeoff"]["focus_fire_score"]
    )


def test_ally_rescue_scoring_prioritizes_critical_ally_targets() -> None:
    actor = _actor_view(actor_id="hero", team="party")
    ally_critical = _actor_view(
        actor_id="ally_critical",
        team="party",
        hp=3,
        max_hp=20,
        position=(10.0, 0.0, 0.0),
    )
    ally_stable = _actor_view(
        actor_id="ally_stable",
        team="party",
        hp=16,
        max_hp=20,
        position=(8.0, 0.0, 0.0),
    )
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(5.0, 0.0, 0.0))
    state = BattleStateView(
        round_number=6,
        actors={
            actor.actor_id: actor,
            ally_critical.actor_id: ally_critical,
            ally_stable.actor_id: ally_stable,
            enemy.actor_id: enemy,
        },
        actor_order=[actor.actor_id, ally_critical.actor_id, ally_stable.actor_id, enemy.actor_id],
        metadata={
            "ally_rescue_threshold_ratio": 0.5,
            "available_actions": {actor.actor_id: ["heal_word", "strike"]},
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "heal_word",
                        "action_type": "heal",
                        "target_mode": "single_ally",
                        "range_ft": 60,
                        "action_cost": "action",
                        "resource_cost": {},
                        "tags": ["ally_rescue"],
                    },
                    {
                        "name": "strike",
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
    rescue_critical = _snapshot_by_action_and_targets(snapshots, "heal_word", ["ally_critical"])
    rescue_stable = _snapshot_by_action_and_targets(snapshots, "heal_word", ["ally_stable"])

    assert rescue_critical["objective_tradeoff"]["ally_rescue_score"] > 0.0
    assert (
        rescue_critical["objective_tradeoff"]["ally_rescue_score"]
        > rescue_stable["objective_tradeoff"]["ally_rescue_score"]
    )
