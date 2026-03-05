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


def test_candidate_completeness_for_legal_target_modes() -> None:
    actor = _actor_view(actor_id="hero", team="party")
    ally = _actor_view(actor_id="ally", team="party", position=(5.0, 0.0, 0.0))
    enemy_a = _actor_view(actor_id="enemy_a", team="enemy", position=(5.0, 0.0, 0.0))
    enemy_b = _actor_view(actor_id="enemy_b", team="enemy", position=(8.0, 0.0, 0.0))

    state = BattleStateView(
        round_number=1,
        actors={
            actor.actor_id: actor,
            ally.actor_id: ally,
            enemy_a.actor_id: enemy_a,
            enemy_b.actor_id: enemy_b,
        },
        actor_order=[actor.actor_id, ally.actor_id, enemy_a.actor_id, enemy_b.actor_id],
        metadata={
            "available_actions": {actor.actor_id: ["slash", "guard", "chain_blast"]},
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "slash",
                        "action_type": "attack",
                        "target_mode": "single_enemy",
                        "range_ft": 5,
                        "resource_cost": {},
                        "action_cost": "action",
                    },
                    {
                        "name": "guard",
                        "action_type": "utility",
                        "target_mode": "self",
                        "resource_cost": {},
                        "action_cost": "action",
                    },
                    {
                        "name": "chain_blast",
                        "action_type": "save",
                        "target_mode": "n_enemies",
                        "max_targets": 2,
                        "range_ft": 60,
                        "resource_cost": {"spell_slot_3": 1},
                        "action_cost": "action",
                    },
                ]
            },
        },
    )

    actor.resources = {"spell_slot_3": 1}
    candidates = enumerate_legal_action_candidates(actor, state)
    signatures = {(row.action_name, row.target_ids) for row in candidates}

    assert signatures == {
        ("slash", ("enemy_a",)),
        ("slash", ("enemy_b",)),
        ("guard", ("hero",)),
        ("chain_blast", ("enemy_a", "enemy_b")),
    }


def test_illegal_candidates_are_excluded_from_enumeration() -> None:
    actor = _actor_view(actor_id="hero", team="party", resources={"ki": 1})
    enemy = _actor_view(actor_id="enemy", team="enemy", position=(5.0, 0.0, 0.0))

    state = BattleStateView(
        round_number=2,
        actors={actor.actor_id: actor, enemy.actor_id: enemy},
        actor_order=[actor.actor_id, enemy.actor_id],
        metadata={
            "available_actions": {
                actor.actor_id: [
                    "jab",
                    "reaction_bite",
                    "expensive_strike",
                    "spent_once",
                    "needs_recharge",
                    "weird_mode",
                ]
            },
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "jab",
                        "action_type": "attack",
                        "target_mode": "single_enemy",
                        "range_ft": 5,
                        "resource_cost": {},
                        "action_cost": "action",
                    },
                    {
                        "name": "reaction_bite",
                        "action_type": "attack",
                        "target_mode": "single_enemy",
                        "range_ft": 5,
                        "resource_cost": {},
                        "action_cost": "reaction",
                    },
                    {
                        "name": "expensive_strike",
                        "action_type": "attack",
                        "target_mode": "single_enemy",
                        "range_ft": 5,
                        "resource_cost": {"ki": 2},
                        "action_cost": "action",
                    },
                    {
                        "name": "spent_once",
                        "action_type": "attack",
                        "target_mode": "single_enemy",
                        "range_ft": 5,
                        "resource_cost": {},
                        "action_cost": "action",
                        "max_uses": 1,
                        "used_count": 1,
                    },
                    {
                        "name": "needs_recharge",
                        "action_type": "attack",
                        "target_mode": "single_enemy",
                        "range_ft": 5,
                        "resource_cost": {},
                        "action_cost": "action",
                        "recharge_ready": False,
                    },
                    {
                        "name": "weird_mode",
                        "action_type": "utility",
                        "target_mode": "teleport_enemy_swarm",
                        "resource_cost": {},
                        "action_cost": "action",
                    },
                ]
            },
        },
    )

    candidates = enumerate_legal_action_candidates(actor, state)

    assert [(row.action_name, row.target_ids) for row in candidates] == [
        ("jab", ("enemy",)),
    ]


def test_scoring_input_snapshot_includes_normalized_dimensions() -> None:
    actor = _actor_view(
        actor_id="caster",
        team="party",
        hp=18,
        max_hp=36,
        concentrating=True,
        resources={"spell_slot_3": 1, "sorcery_points": 2},
    )
    ally = _actor_view(actor_id="ally", team="party", position=(12.0, 0.0, 0.0))
    enemy_a = _actor_view(actor_id="enemy_a", team="enemy", position=(10.0, 0.0, 0.0))
    enemy_b = _actor_view(actor_id="enemy_b", team="enemy", position=(16.0, 0.0, 0.0))

    state = BattleStateView(
        round_number=3,
        actors={
            actor.actor_id: actor,
            ally.actor_id: ally,
            enemy_a.actor_id: enemy_a,
            enemy_b.actor_id: enemy_b,
        },
        actor_order=[actor.actor_id, ally.actor_id, enemy_a.actor_id, enemy_b.actor_id],
        metadata={
            "available_actions": {actor.actor_id: ["control_burst"]},
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "control_burst",
                        "action_type": "save",
                        "target_mode": "single_enemy",
                        "range_ft": 60,
                        "aoe_type": "sphere",
                        "aoe_size_ft": 10,
                        "concentration": True,
                        "resource_cost": {"spell_slot_3": 1, "sorcery_points": 2},
                        "action_cost": "action",
                        "save_ability": "dex",
                        "tags": ["spell", "objective:altar"],
                        "effects": [
                            {
                                "effect_type": "apply_condition",
                                "condition": "restrained",
                            }
                        ],
                        "mechanics": [
                            {
                                "effect_type": "forced_movement",
                                "distance_ft": 10,
                            }
                        ],
                    }
                ]
            },
            "active_hazards": [{"id": "hz_1"}, {"id": "hz_2"}],
            "hazard_exposure_by_actor": {"enemy_a": 2, "enemy_b": 1, "ally": 1},
            "objective_scores": {"control_burst": 4.0, "altar": 1.0},
        },
    )

    candidates = enumerate_legal_action_candidates(actor, state)
    snapshot = candidate_snapshots(candidates)

    control_primary = next(row for row in snapshot if row["target_ids"] == ["enemy_a"])
    assert control_primary["range"] == {
        "distance_to_primary_ft": 10.0,
        "action_range_ft": 60.0,
        "movement_budget_ft": 30.0,
        "requires_movement": False,
        "reachable": True,
    }
    assert control_primary["hazard"] == {
        "active_hazard_count": 2,
        "hazard_exposure_score": 2.0,
        "estimated_affected_count": 3,
        "friendly_fire_risk": True,
    }
    assert control_primary["concentration"] == {
        "actor_concentrating": True,
        "action_requires_concentration": True,
        "recast_penalty_applies": True,
        "actor_hp_ratio": 0.5,
    }
    assert control_primary["control"] == {
        "applied_condition_count": 1,
        "forced_movement_count": 1,
        "control_intensity": 2.0,
    }
    assert control_primary["objective"] == {
        "objective_tags": ["objective:altar"],
        "objective_score": 5.0,
    }
    assert control_primary["resource"] == {
        "resource_cost": {"sorcery_points": 2, "spell_slot_3": 1},
        "total_cost": 3,
        "resource_keys": ["sorcery_points", "spell_slot_3"],
    }
