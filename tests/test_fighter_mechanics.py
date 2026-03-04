from __future__ import annotations

import json
from pathlib import Path

import pytest

from dnd_sim.engine import (
    TurnDeclarationValidationError,
    _action_available,
    _build_actor_from_character,
    _execute_action,
    _spend_resources,
    run_simulation,
    short_rest,
)
from dnd_sim.io import load_character_db, load_scenario, load_strategy_registry
from dnd_sim.models import ActorRuntimeState
from dnd_sim.strategy_api import (
    ActionIntent,
    BaseStrategy,
    DeclaredAction,
    TargetRef,
    TurnDeclaration,
)
from tests.helpers import build_enemy
from tests.test_engine_integration import _setup_env


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self.values:
            raise AssertionError("RNG exhausted")
        return self.values.pop(0)


class ActionSurgePriorityStrategy(BaseStrategy):
    def choose_action(self, actor, state):
        if actor.resources.get("action_surge", 0) > 0:
            return ActionIntent(action_name="action_surge")
        return ActionIntent(action_name="basic")


class IllegalActionSurgeBonusStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        enemies = [
            entry for entry in state.actors.values() if entry.team != actor.team and entry.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()
        target = enemies[0]
        return TurnDeclaration(
            action=DeclaredAction(
                action_name="basic",
                targets=[TargetRef(actor_id=target.actor_id)],
            ),
            bonus_action=DeclaredAction(
                action_name="action_surge",
                targets=[TargetRef(actor_id=target.actor_id)],
            ),
        )


def _fighter_character(*, level: int, traits: list[str], resources: dict | None = None) -> dict:
    return {
        "character_id": f"fighter_{level}",
        "name": f"Fighter {level}",
        "class_level": f"Fighter {level}",
        "max_hp": 55,
        "ac": 16,
        "speed_ft": 30,
        "ability_scores": {
            "str": 18,
            "dex": 14,
            "con": 14,
            "int": 10,
            "wis": 10,
            "cha": 10,
        },
        "save_mods": {"str": 4, "dex": 2, "con": 2, "int": 0, "wis": 0, "cha": 0},
        "skill_mods": {},
        "attacks": [{"name": "Longsword", "to_hit": 7, "damage": "1d1", "damage_type": "slashing"}],
        "resources": resources or {},
        "traits": traits,
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }


def _enemy(actor_id: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team="enemy",
        name=actor_id,
        max_hp=40,
        hp=40,
        temp_hp=0,
        ac=10,
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


def test_build_actor_infers_action_surge_and_second_wind_resources() -> None:
    character = _fighter_character(level=8, traits=["Action Surge", "Second Wind"])

    actor = _build_actor_from_character(character, traits_db={})

    assert actor.max_resources["action_surge"] == 1
    assert actor.resources["action_surge"] == 1
    assert actor.max_resources["second_wind"] == 1
    assert actor.resources["second_wind"] == 1

    second_wind = next(action for action in actor.actions if action.name == "second_wind")
    assert second_wind.action_cost == "bonus"
    assert second_wind.resource_cost == {"second_wind": 1}


def test_build_actor_level_17_gets_two_action_surge_uses() -> None:
    character = _fighter_character(level=17, traits=["Action Surge"])

    actor = _build_actor_from_character(character, traits_db={})

    assert actor.max_resources["action_surge"] == 2
    assert actor.resources["action_surge"] == 2


def test_build_actor_adds_action_surge_attack_action_with_expected_attack_volume() -> None:
    character = _fighter_character(level=8, traits=["Extra Attack", "Action Surge"])

    actor = _build_actor_from_character(character, traits_db={})
    basic = next(action for action in actor.actions if action.name == "basic")
    surge = next(action for action in actor.actions if action.name == "action_surge")

    assert surge.action_type == "attack"
    assert surge.action_cost == "action"
    assert surge.resource_cost == {"action_surge": 1}
    assert surge.attack_count == basic.attack_count * 2


def test_action_surge_is_illegal_outside_fighters_turn_token() -> None:
    character = _fighter_character(level=8, traits=["Extra Attack", "Action Surge"])

    actor = _build_actor_from_character(character, traits_db={})
    surge = next(action for action in actor.actions if action.name == "action_surge")

    assert _action_available(actor, surge, turn_token=f"1:{actor.actor_id}") is True
    assert _action_available(actor, surge) is False
    assert _action_available(actor, surge, turn_token="1:enemy") is False


def test_short_rest_refreshes_fighter_short_rest_resources() -> None:
    character = _fighter_character(
        level=10,
        traits=["Action Surge", "Second Wind", "Combat Superiority", "Maneuvers", "Trip Attack"],
    )
    actor = _build_actor_from_character(character, traits_db={})
    actor.resources["action_surge"] = 0
    actor.resources["second_wind"] = 0
    actor.resources["superiority_dice"] = 0

    short_rest(actor)

    assert actor.resources["action_surge"] == 1
    assert actor.resources["second_wind"] == 1
    assert actor.resources["superiority_dice"] == 5


def test_trip_attack_maneuver_consumes_one_die_and_applies_once_per_action() -> None:
    character = _fighter_character(
        level=5,
        traits=["Extra Attack", "Combat Superiority", "Maneuvers", "Trip Attack"],
    )
    attacker = _build_actor_from_character(character, traits_db={})
    target = _enemy("ogre")
    action = next(action for action in attacker.actions if action.name == "maneuver_trip_attack")

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt = {attacker.actor_id: 0, target.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, target.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, target.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, target.actor_id: {}}

    spent = _spend_resources(attacker, action.resource_cost)
    assert spent == {"superiority_dice": 1}

    _execute_action(
        rng=FixedRng([15, 1, 8, 1, 15, 1, 1]),
        actor=attacker,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert attacker.resources["superiority_dice"] == attacker.max_resources["superiority_dice"] - 1
    assert damage_dealt[attacker.actor_id] == 10
    assert "prone" in target.conditions


def test_action_surge_is_not_auto_spent_between_encounters_with_short_rest(tmp_path: Path) -> None:
    fighter = _fighter_character(
        level=8,
        traits=["Extra Attack", "Action Surge", "Second Wind"],
        resources={"action_surge": {"max": 1}, "second_wind": {"max": 1}},
    )
    fighter["max_hp"] = 220
    fighter["ac"] = 18
    fighter["attacks"][0]["damage"] = "1d12+8"
    party = [fighter]
    enemies = [
        build_enemy(enemy_id="ogre_a", name="Ogre A", hp=120, ac=13, to_hit=5, damage="1d10+3"),
        build_enemy(enemy_id="ogre_b", name="Ogre B", hp=120, ac=13, to_hit=5, damage="1d10+3"),
    ]

    scenario_path = _setup_env(
        tmp_path,
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
    )
    raw = json.loads(scenario_path.read_text(encoding="utf-8"))
    raw["encounters"] = [
        {"enemies": ["ogre_a"], "short_rest_after": True},
        {"enemies": ["ogre_b"], "short_rest_after": False},
    ]
    raw["enemies"] = []
    scenario_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    loaded = load_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    db = load_character_db(Path(loaded.config.character_db_dir))

    artifacts = run_simulation(
        loaded, db, {}, registry, trials=1, seed=23, run_id="fighter_cadence"
    )
    spent = artifacts.trial_results[0].resources_spent["fighter_8"].get("action_surge", 0)
    assert spent == 0


def test_action_surge_spends_across_short_rest_encounters_deterministically(tmp_path: Path) -> None:
    fighter = _fighter_character(
        level=8,
        traits=["Extra Attack", "Action Surge"],
        resources={"action_surge": {"max": 1}},
    )
    fighter["max_hp"] = 220
    fighter["ac"] = 18
    fighter["attacks"][0]["damage"] = "1d12+8"
    party = [fighter]
    enemies = [
        build_enemy(enemy_id="ogre_a", name="Ogre A", hp=120, ac=13, to_hit=5, damage="1d10+3"),
        build_enemy(enemy_id="ogre_b", name="Ogre B", hp=120, ac=13, to_hit=5, damage="1d10+3"),
    ]

    scenario_path = _setup_env(
        tmp_path,
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
    )
    raw = json.loads(scenario_path.read_text(encoding="utf-8"))
    raw["encounters"] = [
        {"enemies": ["ogre_a"], "short_rest_after": True},
        {"enemies": ["ogre_b"], "short_rest_after": False},
    ]
    raw["enemies"] = []
    scenario_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = {
        "party_strategy": ActionSurgePriorityStrategy(),
        "enemy_strategy": BaseStrategy(),
    }

    run_a = run_simulation(loaded, db, {}, registry, trials=1, seed=37, run_id="fighter_as_a")
    run_b = run_simulation(loaded, db, {}, registry, trials=1, seed=37, run_id="fighter_as_b")

    spent = run_a.trial_results[0].resources_spent["fighter_8"].get("action_surge", 0)
    assert spent == 2

    summary_a = run_a.summary.to_dict()
    summary_b = run_b.summary.to_dict()
    summary_a.pop("run_id", None)
    summary_b.pop("run_id", None)
    assert summary_a == summary_b


def test_declared_bonus_action_cannot_use_action_surge(tmp_path: Path) -> None:
    fighter = _fighter_character(level=8, traits=["Extra Attack", "Action Surge"])
    enemies = [
        build_enemy(enemy_id="ogre", name="Ogre", hp=120, ac=13, to_hit=5, damage="1d10+3"),
    ]
    scenario_path = _setup_env(
        tmp_path,
        party=[fighter],
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
    )
    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = {
        "party_strategy": IllegalActionSurgeBonusStrategy(),
        "enemy_strategy": BaseStrategy(),
    }

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        run_simulation(loaded, db, {}, registry, trials=1, seed=43, run_id="illegal_bonus_as")

    assert exc_info.value.code == "illegal_bonus_action"
    assert exc_info.value.actor_id == "fighter_8"
    assert exc_info.value.field == "bonus_action.action_name"
