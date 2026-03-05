from __future__ import annotations

import csv
from pathlib import Path

from dnd_sim.spatial import AABB
from dnd_sim.strategies.defaults import OptimalExpectedDamageStrategy, _evaluate_action_score
from dnd_sim.strategy_api import ActorView, BattleStateView


def _actor_view(
    *,
    actor_id: str,
    team: str,
    hp: int = 30,
    max_hp: int = 30,
    ac: int = 14,
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    movement_remaining: float = 30.0,
) -> ActorView:
    return ActorView(
        actor_id=actor_id,
        team=team,
        hp=hp,
        max_hp=max_hp,
        ac=ac,
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
    actions: list[dict[str, object]],
    metadata: dict[str, object] | None = None,
) -> BattleStateView:
    actors = {actor.actor_id: actor, **{entry.actor_id: entry for entry in others}}
    return BattleStateView(
        round_number=1,
        actors=actors,
        actor_order=list(actors.keys()),
        metadata={
            "action_catalog": {actor.actor_id: actions},
            **(metadata or {}),
        },
    )


def test_evaluate_action_score_penalizes_hazardous_pathing() -> None:
    actor = _actor_view(actor_id="hero", team="party", position=(0.0, 0.0, 0.0))
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(20.0, 0.0, 0.0))
    risky_strike = {
        "name": "risky_strike",
        "action_type": "attack",
        "target_mode": "single_enemy",
        "to_hit": 7,
        "damage": "2d10",
        "range_ft": 5,
        "resource_cost": {},
        "effects": [],
        "mechanics": [],
        "tags": [],
    }
    safe_shot = {
        "name": "safe_shot",
        "action_type": "attack",
        "target_mode": "single_enemy",
        "to_hit": 7,
        "damage": "1d8",
        "range_ft": 30,
        "resource_cost": {},
        "effects": [],
        "mechanics": [],
        "tags": [],
    }
    state = _single_action_state(
        actor=actor,
        others=[enemy],
        actions=[risky_strike, safe_shot],
        metadata={
            "active_hazards": [
                {"id": "lava_line", "position": (10.0, 0.0, 0.0), "radius_ft": 5, "severity": 8}
            ]
        },
    )

    risky_score = _evaluate_action_score(risky_strike, enemy, actor, state)
    safe_score = _evaluate_action_score(safe_shot, enemy, actor, state)

    assert safe_score > risky_score


def test_optimal_strategy_prefers_safe_action_over_hazardous_high_damage_option() -> None:
    strategy = OptimalExpectedDamageStrategy()
    actor = _actor_view(actor_id="hero", team="party", position=(0.0, 0.0, 0.0))
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(20.0, 0.0, 0.0))
    state = _single_action_state(
        actor=actor,
        others=[enemy],
        actions=[
            {
                "name": "risky_strike",
                "action_type": "attack",
                "target_mode": "single_enemy",
                "to_hit": 7,
                "damage": "2d10",
                "range_ft": 5,
                "resource_cost": {},
                "action_cost": "action",
                "recharge_ready": True,
                "effects": [],
                "mechanics": [],
                "tags": [],
            },
            {
                "name": "safe_shot",
                "action_type": "attack",
                "target_mode": "single_enemy",
                "to_hit": 7,
                "damage": "1d8",
                "range_ft": 30,
                "resource_cost": {},
                "action_cost": "action",
                "recharge_ready": True,
                "effects": [],
                "mechanics": [],
                "tags": [],
            },
        ],
        metadata={
            "active_hazards": [
                {"id": "lava_line", "position": (10.0, 0.0, 0.0), "radius_ft": 5, "severity": 8}
            ]
        },
    )

    declaration = strategy.declare_turn(actor, state)

    assert declaration is not None
    assert declaration.action is not None
    assert declaration.action.action_name == "safe_shot"


def test_evaluate_action_score_ignores_hazards_with_missing_or_invalid_position() -> None:
    actor = _actor_view(actor_id="hero", team="party", position=(0.0, 0.0, 0.0))
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(20.0, 0.0, 0.0))
    action = {
        "name": "risky_strike",
        "action_type": "attack",
        "target_mode": "single_enemy",
        "to_hit": 7,
        "damage": "2d10",
        "range_ft": 5,
        "resource_cost": {},
        "effects": [],
        "mechanics": [],
        "tags": [],
    }

    baseline_state = _single_action_state(actor=actor, others=[enemy], actions=[action])
    invalid_hazard_state = _single_action_state(
        actor=actor,
        others=[enemy],
        actions=[action],
        metadata={
            "active_hazards": [
                {"id": "missing_pos", "radius_ft": 5, "severity": 8},
                {"id": "bad_shape", "position": "not-a-position", "radius_ft": 5, "severity": 8},
                {"id": "bad_values", "position": ("x", 0.0, 0.0), "radius_ft": 5, "severity": 8},
            ]
        },
    )

    baseline_score = _evaluate_action_score(action, enemy, actor, baseline_state)
    invalid_hazard_score = _evaluate_action_score(action, enemy, actor, invalid_hazard_state)

    assert invalid_hazard_score == baseline_score


def test_optimal_strategy_prefers_line_of_effect_clear_target() -> None:
    strategy = OptimalExpectedDamageStrategy()
    actor = _actor_view(actor_id="archer", team="party", position=(0.0, 0.0, 0.0))
    blocked_enemy = _actor_view(actor_id="enemy_blocked", team="enemy", position=(30.0, 0.0, 0.0))
    clear_enemy = _actor_view(actor_id="enemy_clear", team="enemy", position=(0.0, 30.0, 0.0))
    state = _single_action_state(
        actor=actor,
        others=[blocked_enemy, clear_enemy],
        actions=[
            {
                "name": "longbow",
                "action_type": "attack",
                "target_mode": "single_enemy",
                "to_hit": 7,
                "damage": "1d8+3",
                "range_ft": 150,
                "resource_cost": {},
                "action_cost": "action",
                "recharge_ready": True,
                "effects": [],
                "mechanics": [],
                "tags": [],
            }
        ],
        metadata={
            "obstacles": [
                AABB(min_pos=(10.0, -1.0, -1.0), max_pos=(20.0, 1.0, 1.0), cover_level="TOTAL")
            ]
        },
    )

    declaration = strategy.declare_turn(actor, state)

    assert declaration is not None
    assert declaration.action is not None
    assert [target.actor_id for target in declaration.action.targets] == ["enemy_clear"]


def test_review_checklist_closes_fix07_only_after_fix_track_is_merged() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    backlog_path = repo_root / "docs/program/backlog.csv"
    checklist_path = repo_root / "docs/review_checklist.md"

    with backlog_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    fix_rows = [row for row in rows if row.get("track", "").strip() == "FIX"]
    all_fix_merged = bool(fix_rows) and all(
        row.get("status", "").strip() == "merged" for row in fix_rows
    )

    line = next(
        (
            row
            for row in checklist_path.read_text(encoding="utf-8").splitlines()
            if "FIX-07 Integrate hazard-aware strategy scoring and close the review checklist"
            in row
        ),
        "",
    )
    assert line
    fix07_checked = line.strip().startswith("- [x]")
    assert fix07_checked == all_fix_merged
