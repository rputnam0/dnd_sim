from __future__ import annotations

import random
from pathlib import Path

import pytest

import dnd_sim.engine as engine_module
from dnd_sim.engine import _execute_action, run_simulation
from dnd_sim.io import load_character_db, load_scenario, load_strategy_registry
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.action_resolution import (
    ActionResolutionHandlers,
    ActionResolutionResult,
    execute_action_pipeline,
)
from tests.helpers import build_character, build_enemy
from tests.test_engine_integration import _setup_env


class _FixedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self.values:
            raise AssertionError("RNG exhausted")
        return self.values.pop(0)


def _base_actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=30,
        hp=30,
        temp_hp=0,
        ac=12,
        initiative_mod=0,
        str_mod=2,
        dex_mod=2,
        con_mod=2,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 2, "dex": 2, "con": 2, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def test_execute_action_pipeline_dispatches_handlers_by_action_type() -> None:
    actor = _base_actor(actor_id="actor", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    actors = {actor.actor_id: actor, target.actor_id: target}
    seen: list[str] = []

    handlers = ActionResolutionHandlers(
        attack=lambda _action, _targets: seen.append("attack"),
        save=lambda _action, _targets: seen.append("save"),
        utility=lambda _action, _targets: seen.append("utility"),
        grapple_shove=lambda _action, _targets: seen.append("grapple_shove"),
        item=lambda _action, _targets: seen.append("item"),
    )

    attack = ActionDefinition(name="strike", action_type="attack")
    save = ActionDefinition(name="burning_hands", action_type="save")
    utility = ActionDefinition(name="dash", action_type="utility")
    grapple = ActionDefinition(name="grapple", action_type="grapple")
    item = ActionDefinition(name="potion_of_fire", action_type="item")

    attack_result = execute_action_pipeline(
        action=attack,
        targets=[target],
        actors=actors,
        handlers=handlers,
    )
    save_result = execute_action_pipeline(
        action=save,
        targets=[target],
        actors=actors,
        handlers=handlers,
    )
    utility_result = execute_action_pipeline(
        action=utility,
        targets=[target],
        actors=actors,
        handlers=handlers,
    )
    grapple_result = execute_action_pipeline(
        action=grapple,
        targets=[target],
        actors=actors,
        handlers=handlers,
    )
    item_result = execute_action_pipeline(
        action=item,
        targets=[target],
        actors=actors,
        handlers=handlers,
    )

    assert seen == ["attack", "save", "utility", "grapple_shove", "item"]
    assert attack_result.dispatch_path == "attack"
    assert save_result.dispatch_path == "save"
    assert utility_result.dispatch_path == "utility"
    assert grapple_result.dispatch_path == "grapple_shove"
    assert item_result.dispatch_path == "item"
    assert all(
        result.executed
        for result in (
            attack_result,
            save_result,
            utility_result,
            grapple_result,
            item_result,
        )
    )


def test_execute_action_pipeline_skips_unknown_targets_without_dispatch() -> None:
    actor = _base_actor(actor_id="actor", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    ghost = _base_actor(actor_id="ghost", team="enemy")
    actors = {actor.actor_id: actor, target.actor_id: target}
    seen: list[str] = []

    handlers = ActionResolutionHandlers(
        attack=lambda _action, _targets: seen.append("attack"),
        save=lambda _action, _targets: seen.append("save"),
        utility=lambda _action, _targets: seen.append("utility"),
        grapple_shove=lambda _action, _targets: seen.append("grapple_shove"),
    )

    result = execute_action_pipeline(
        action=ActionDefinition(name="strike", action_type="attack", to_hit=6, damage="4"),
        targets=[ghost],
        actors=actors,
        handlers=handlers,
    )

    assert seen == []
    assert result.executed is False
    assert result.skipped_reason == "no_valid_targets"
    assert result.invalid_target_ids == ["ghost"]


def test_engine_routes_execute_action_through_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    actor = _base_actor(actor_id="actor", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    action = ActionDefinition(
        name="strike",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="3",
    )
    actors = {actor.actor_id: actor, target.actor_id: target}
    damage_dealt = {actor.actor_id: 0, target.actor_id: 0}
    damage_taken = {actor.actor_id: 0, target.actor_id: 0}
    threat_scores = {actor.actor_id: 0, target.actor_id: 0}
    resources_spent = {actor.actor_id: {}, target.actor_id: {}}

    calls: list[str] = []

    def _fake_pipeline(*, action, targets, actors, handlers):
        calls.append(action.action_type)
        handlers.attack(action, targets)
        return ActionResolutionResult(
            action_name=action.name,
            action_type=action.action_type,
            attempted_target_ids=[target.actor_id for target in targets],
            resolved_target_ids=[target.actor_id for target in targets],
            invalid_target_ids=[],
            executed=True,
            dispatch_path="attack",
        )

    monkeypatch.setattr(engine_module, "_action_resolution_execute_action_pipeline", _fake_pipeline)

    _execute_action(
        rng=_FixedRng([15]),
        actor=actor,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert calls == ["attack"]
    assert target.hp == 27


def test_attack_spell_and_item_actions_execute_integration() -> None:
    actor = _base_actor(actor_id="actor", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    actors = {actor.actor_id: actor, target.actor_id: target}
    damage_dealt = {actor.actor_id: 0, target.actor_id: 0}
    damage_taken = {actor.actor_id: 0, target.actor_id: 0}
    threat_scores = {actor.actor_id: 0, target.actor_id: 0}
    resources_spent = {actor.actor_id: {}, target.actor_id: {}}

    attack = ActionDefinition(
        name="weapon_strike",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="2",
        item_id="item_longsword",
    )
    spell = ActionDefinition(
        name="burning_hands",
        action_type="save",
        action_cost="action",
        save_dc=25,
        save_ability="dex",
        half_on_save=True,
        damage="4",
        damage_type="fire",
        tags=["spell"],
    )
    item = ActionDefinition(
        name="alchemist_fire",
        action_type="item",
        action_cost="action",
        target_mode="single_enemy",
        effects=[
            {
                "effect_type": "damage",
                "target": "target",
                "damage": "3",
                "damage_type": "fire",
            }
        ],
    )

    _execute_action(
        rng=_FixedRng([15]),
        actor=actor,
        action=attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    _execute_action(
        rng=_FixedRng([1]),
        actor=actor,
        action=spell,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    _execute_action(
        rng=random.Random(1),
        actor=actor,
        action=item,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.hp == 21
    assert damage_dealt[actor.actor_id] == 9
    assert damage_taken[target.actor_id] == 9
    assert threat_scores[actor.actor_id] == 9


def test_invalid_target_is_a_noop_for_execute_action() -> None:
    actor = _base_actor(actor_id="actor", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    ghost = _base_actor(actor_id="ghost", team="enemy")
    actors = {actor.actor_id: actor, target.actor_id: target}
    damage_dealt = {actor.actor_id: 0, target.actor_id: 0}
    damage_taken = {actor.actor_id: 0, target.actor_id: 0}
    threat_scores = {actor.actor_id: 0, target.actor_id: 0}
    resources_spent = {actor.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=_FixedRng([15]),
        actor=actor,
        action=ActionDefinition(
            name="strike",
            action_type="attack",
            action_cost="action",
            to_hit=20,
            damage="4",
        ),
        targets=[ghost],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.hp == target.max_hp
    assert damage_dealt[actor.actor_id] == 0
    assert damage_taken[target.actor_id] == 0


def test_action_resolution_fixed_seed_combat_regression(tmp_path: Path) -> None:
    scenario_path = _setup_env(
        tmp_path,
        party=[build_character("hero", "Hero", 28, 15, 7, "1d8+4")],
        enemies=[
            build_enemy(enemy_id="boss", name="Boss", hp=40, ac=13, to_hit=5, damage="1d10+3")
        ],
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
    )
    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = load_strategy_registry(loaded)

    run_a = run_simulation(
        loaded,
        db,
        {},
        registry,
        trials=5,
        seed=11,
        run_id="arc04_action_resolution_regression_a",
    ).summary.to_dict()
    run_b = run_simulation(
        loaded,
        db,
        {},
        registry,
        trials=5,
        seed=11,
        run_id="arc04_action_resolution_regression_b",
    ).summary.to_dict()

    run_a.pop("run_id", None)
    run_b.pop("run_id", None)
    assert run_a == run_b
