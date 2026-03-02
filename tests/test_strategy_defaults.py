from __future__ import annotations

from dnd_sim.strategies.defaults import OptimalExpectedDamageStrategy, _expected_damage_against
from dnd_sim.strategy_api import ActionIntent, ActorView, BattleStateView


class _Target:
    def __init__(self, ac: int) -> None:
        self.ac = ac


def test_expected_damage_ignores_non_dict_effect_entries() -> None:
    target = _Target(ac=14)
    action = {
        "action_type": "save",
        "damage": "2d6",
        "save_dc": 14,
        "save_ability": "dex",
        "half_on_save": True,
        "effects": [
            "legacy_effect_entry",
            {"effect_type": "damage", "damage": "1d6", "apply_on": "save_fail", "target": "target"},
        ],
        "mechanics": ["legacy_mechanic_entry"],
    }

    score = _expected_damage_against(action, target, save_mod=2)

    assert score > 0.0


def _actor_view(
    *,
    actor_id: str,
    team: str,
    hp: int = 30,
    max_hp: int = 30,
    ac: int = 14,
    resources: dict[str, int] | None = None,
    save_mods: dict[str, int] | None = None,
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    concentrating: bool = False,
) -> ActorView:
    return ActorView(
        actor_id=actor_id,
        team=team,
        hp=hp,
        max_hp=max_hp,
        ac=ac,
        save_mods=save_mods or {"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        resources=resources or {},
        conditions=set(),
        position=position,
        speed_ft=30,
        movement_remaining=30.0,
        traits={},
        concentrating=concentrating,
    )


def test_optimal_strategy_prioritizes_high_threat_target_when_policy_enabled() -> None:
    strategy = OptimalExpectedDamageStrategy()
    actor = _actor_view(actor_id="hero", team="party")
    goblin = _actor_view(actor_id="goblin", team="enemy", position=(5.0, 0.0, 0.0))
    warlock = _actor_view(actor_id="warlock", team="enemy", position=(5.0, 5.0, 0.0))
    state = BattleStateView(
        round_number=1,
        actors={actor.actor_id: actor, goblin.actor_id: goblin, warlock.actor_id: warlock},
        actor_order=[actor.actor_id, goblin.actor_id, warlock.actor_id],
        metadata={
            "threat_scores": {goblin.actor_id: 1, warlock.actor_id: 30},
            "strategy_policy": {
                "threat_management": {
                    "enabled": True,
                    "target_weight": 0.6,
                }
            },
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "basic",
                        "action_type": "attack",
                        "to_hit": 7,
                        "damage": "1d8+4",
                        "attack_count": 1,
                        "resource_cost": {},
                        "action_cost": "action",
                        "recharge_ready": True,
                        "target_mode": "single_enemy",
                        "range_ft": 5,
                        "effects": [],
                        "mechanics": [],
                        "tags": [],
                    }
                ]
            },
        },
    )

    targets = strategy.choose_targets(actor, ActionIntent(action_name="basic"), state)

    assert [target.actor_id for target in targets] == ["warlock"]


def test_optimal_strategy_chooses_dodge_to_protect_concentration_when_low_hp() -> None:
    strategy = OptimalExpectedDamageStrategy()
    actor = _actor_view(
        actor_id="wizard",
        team="party",
        hp=8,
        max_hp=40,
        concentrating=True,
    )
    enemy = _actor_view(actor_id="orc", team="enemy", position=(10.0, 0.0, 0.0))
    state = BattleStateView(
        round_number=3,
        actors={actor.actor_id: actor, enemy.actor_id: enemy},
        actor_order=[actor.actor_id, enemy.actor_id],
        metadata={
            "strategy_policy": {
                "concentration_protection": {
                    "enabled": True,
                    "hp_ratio_threshold": 0.5,
                    "prefer_dodge": True,
                }
            },
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "fire_bolt",
                        "action_type": "attack",
                        "to_hit": 8,
                        "damage": "2d10",
                        "attack_count": 1,
                        "resource_cost": {},
                        "action_cost": "action",
                        "recharge_ready": True,
                        "target_mode": "single_enemy",
                        "range_ft": 120,
                        "effects": [],
                        "mechanics": [],
                        "tags": ["spell"],
                    },
                    {
                        "name": "dodge",
                        "action_type": "utility",
                        "resource_cost": {},
                        "action_cost": "action",
                        "recharge_ready": True,
                        "target_mode": "self",
                        "range_ft": None,
                        "effects": [],
                        "mechanics": [],
                        "tags": [],
                    },
                ]
            },
        },
    )

    intent = strategy.choose_action(actor, state)

    assert intent.action_name == "dodge"


def test_optimal_strategy_prioritizes_objective_action_when_policy_enabled() -> None:
    strategy = OptimalExpectedDamageStrategy()
    actor = _actor_view(actor_id="rogue", team="party")
    enemy = _actor_view(actor_id="bandit", team="enemy", position=(5.0, 0.0, 0.0))
    state = BattleStateView(
        round_number=2,
        actors={actor.actor_id: actor, enemy.actor_id: enemy},
        actor_order=[actor.actor_id, enemy.actor_id],
        metadata={
            "strategy_policy": {
                "objective_play": {
                    "enabled": True,
                    "objective_action_bonus": 25.0,
                }
            },
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "shortsword",
                        "action_type": "attack",
                        "to_hit": 7,
                        "damage": "1d6+4",
                        "attack_count": 1,
                        "resource_cost": {},
                        "action_cost": "action",
                        "recharge_ready": True,
                        "target_mode": "single_enemy",
                        "range_ft": 5,
                        "effects": [],
                        "mechanics": [],
                        "tags": [],
                    },
                    {
                        "name": "secure_objective",
                        "action_type": "utility",
                        "resource_cost": {},
                        "action_cost": "action",
                        "recharge_ready": True,
                        "target_mode": "self",
                        "range_ft": None,
                        "effects": [],
                        "mechanics": [],
                        "tags": ["objective:control_point"],
                    },
                ]
            },
        },
    )

    intent = strategy.choose_action(actor, state)

    assert intent.action_name == "secure_objective"


def test_optimal_strategy_lookahead_mode_prefers_tactical_branch_setup_action() -> None:
    strategy = OptimalExpectedDamageStrategy()
    actor = _actor_view(
        actor_id="monk",
        team="party",
        resources={"ki": 1},
    )
    enemy = _actor_view(actor_id="ogre", team="enemy", position=(5.0, 0.0, 0.0), ac=13)
    state = BattleStateView(
        round_number=1,
        actors={actor.actor_id: actor, enemy.actor_id: enemy},
        actor_order=[actor.actor_id, enemy.actor_id],
        metadata={
            "evaluation_mode": "lookahead",
            "lookahead_discount": 1.0,
            "tactical_branches": {
                "set_up": [
                    {
                        "next_action": "finisher",
                        "weight": 2.0,
                    }
                ]
            },
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "finisher",
                        "action_type": "attack",
                        "to_hit": 7,
                        "damage": "2d8+4",
                        "attack_count": 1,
                        "resource_cost": {"ki": 1},
                        "action_cost": "action",
                        "recharge_ready": True,
                        "target_mode": "single_enemy",
                        "range_ft": 5,
                        "effects": [],
                        "mechanics": [],
                        "tags": [],
                    },
                    {
                        "name": "set_up",
                        "action_type": "utility",
                        "resource_cost": {},
                        "action_cost": "action",
                        "recharge_ready": True,
                        "target_mode": "self",
                        "range_ft": None,
                        "effects": [],
                        "mechanics": [],
                        "tags": ["objective:open_window"],
                    },
                ]
            },
        },
    )

    intent = strategy.choose_action(actor, state)

    assert intent.action_name == "set_up"
