from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dnd_sim.engine import (
    TurnDeclarationValidationError,
    _action_available,
    _build_actor_from_character,
    _execute_declared_turn_or_error,
    _execute_action,
    _spend_action_resource_cost,
    long_rest,
    run_simulation,
    short_rest,
)
from dnd_sim.io import load_character_db, load_scenario, load_strategy_registry
from dnd_sim.models import ActorRuntimeState
from dnd_sim.strategy_api import BaseStrategy, DeclaredAction, TargetRef, TurnDeclaration
from tests.helpers import build_enemy, with_class_levels
from tests.test_engine_integration import _setup_env


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self.values:
            raise AssertionError("RNG exhausted")
        return self.values.pop(0)


class IllegalSmiteAsMainActionStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        enemies = [
            entry for entry in state.actors.values() if entry.team != actor.team and entry.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()
        return TurnDeclaration(
            action=DeclaredAction(
                action_name="Searing Smite",
                targets=[TargetRef(actor_id=actor.actor_id)],
            )
        )


def _paladin_character(
    *,
    level: int,
    class_level: str | None = None,
    class_levels: dict[str, int] | None = None,
    traits: list[str] | None = None,
    resources: dict[str, Any] | None = None,
    spells: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "character_id": f"paladin_{level}",
        "name": f"Paladin {level}",
        "class_level": class_level or f"Paladin {level}",
        "max_hp": 52,
        "ac": 17,
        "speed_ft": 30,
        "ability_scores": {"str": 18, "dex": 10, "con": 14, "int": 10, "wis": 12, "cha": 16},
        "save_mods": {"str": 7, "dex": 0, "con": 2, "int": 0, "wis": 1, "cha": 6},
        "skill_mods": {},
        "attacks": [{"name": "Longsword", "to_hit": 9, "damage": "1", "damage_type": "slashing"}],
        "spells": spells or [],
        "resources": resources or {},
        "traits": traits or [],
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }
    if class_levels is not None:
        payload["class_levels"] = dict(class_levels)
    return with_class_levels(payload)


def _actor(actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
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


def test_build_actor_infers_paladin_package_traits_resources_and_action_from_multiclass_levels() -> (
    None
):
    character = _paladin_character(level=11, class_level="Paladin 3 / Fighter 8")

    actor = _build_actor_from_character(character, traits_db={})

    assert actor.class_levels == {"paladin": 3, "fighter": 8}
    assert {"lay on hands", "divine smite", "spellcasting"}.issubset(actor.traits)
    assert "improved divine smite" not in actor.traits
    assert actor.max_resources["lay_on_hands_pool"] == 15
    assert actor.resources["lay_on_hands_pool"] == 15
    assert any(action.name == "lay_on_hands" for action in actor.actions)


def test_explicit_lay_on_hands_trait_does_not_infer_pool_without_paladin_levels() -> None:
    character = _paladin_character(
        level=5,
        class_level="Fighter 5",
        class_levels={"fighter": 5},
        traits=["Lay on Hands"],
    )

    actor = _build_actor_from_character(character, traits_db={})

    assert "lay_on_hands_pool" not in actor.max_resources
    assert "lay_on_hands_pool" not in actor.resources


def test_lay_on_hands_pool_spend_short_rest_and_long_rest_recovery() -> None:
    paladin = _build_actor_from_character(_paladin_character(level=5), traits_db={})
    ally = _actor("ally", "party")
    ally.max_hp = 30
    ally.hp = 18
    lay_on_hands = next(action for action in paladin.actions if action.name == "lay_on_hands")

    actors = {paladin.actor_id: paladin, ally.actor_id: ally}
    damage_dealt = {paladin.actor_id: 0, ally.actor_id: 0}
    damage_taken = {paladin.actor_id: 0, ally.actor_id: 0}
    threat_scores = {paladin.actor_id: 0, ally.actor_id: 0}
    resources_spent = {paladin.actor_id: {}, ally.actor_id: {}}

    assert _action_available(paladin, lay_on_hands, turn_token=f"1:{paladin.actor_id}") is True
    _execute_action(
        rng=FixedRng([]),
        actor=paladin,
        action=lay_on_hands,
        targets=[ally],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token=f"1:{paladin.actor_id}",
    )

    assert ally.hp == 30
    assert paladin.resources["lay_on_hands_pool"] == 13
    assert resources_spent[paladin.actor_id]["lay_on_hands_pool"] == 12

    short_rest(paladin)
    assert paladin.resources["lay_on_hands_pool"] == 13

    long_rest(paladin)
    assert paladin.resources["lay_on_hands_pool"] == 25


def test_smite_setup_arms_then_consumes_on_next_turn_hit() -> None:
    paladin = _build_actor_from_character(
        _paladin_character(
            level=2,
            resources={"spell_slots": {"1": 1}},
            spells=[
                {
                    "name": "Searing Smite",
                    "level": 1,
                    "concentration": True,
                    "mechanics": [
                        {"effect_type": "extra_damage", "damage": "1d6", "damage_type": "fire"}
                    ],
                }
            ],
        ),
        traits_db={},
    )
    smite_action = next(action for action in paladin.actions if action.name == "Searing Smite")
    basic_attack = next(action for action in paladin.actions if action.name == "basic")
    target = _actor("ogre", "enemy")

    assert smite_action.action_cost == "bonus"

    actors = {paladin.actor_id: paladin, target.actor_id: target}
    damage_dealt = {paladin.actor_id: 0, target.actor_id: 0}
    damage_taken = {paladin.actor_id: 0, target.actor_id: 0}
    threat_scores = {paladin.actor_id: 0, target.actor_id: 0}
    resources_spent = {paladin.actor_id: {}, target.actor_id: {}}

    assert _spend_action_resource_cost(
        paladin,
        smite_action,
        resources_spent,
        turn_token=f"1:{paladin.actor_id}",
    )
    _execute_action(
        rng=FixedRng([]),
        actor=paladin,
        action=smite_action,
        targets=[paladin],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token=f"1:{paladin.actor_id}",
    )
    assert paladin.pending_smite is not None

    _execute_action(
        rng=FixedRng([15, 4]),
        actor=paladin,
        action=basic_attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=2,
        turn_token=f"2:{paladin.actor_id}",
    )

    assert paladin.pending_smite is None
    assert paladin.resources["spell_slot_1"] == 0
    assert resources_spent[paladin.actor_id]["spell_slot_1"] == 1
    assert damage_dealt[paladin.actor_id] == 5


def test_chr10_integration_paladin_package_inference_is_deterministic(tmp_path: Path) -> None:
    paladin = _paladin_character(
        level=11,
        class_level="Paladin 3 / Fighter 8",
        class_levels={"paladin": 3, "fighter": 8},
    )
    enemies = [build_enemy(enemy_id="dummy", name="Dummy", hp=250, ac=8, to_hit=0, damage="1")]
    scenario_path = _setup_env(
        tmp_path / "chr10_paladin_integration",
        party=[paladin],
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
        max_rounds=1,
    )

    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = load_strategy_registry(loaded)

    run_a = run_simulation(loaded, db, {}, registry, trials=1, seed=53, run_id="chr10_paladin_a")
    run_b = run_simulation(loaded, db, {}, registry, trials=1, seed=53, run_id="chr10_paladin_b")

    trial = run_a.trial_results[0]
    assert trial.rounds == 1
    assert trial.resources_spent["paladin_11"].get("lay_on_hands_pool", 0) == 0
    assert trial.state_snapshots[-1]["party"]["paladin_11"]["resources"]["lay_on_hands_pool"] == 15

    summary_a = run_a.summary.to_dict()
    summary_b = run_b.summary.to_dict()
    summary_a.pop("run_id", None)
    summary_b.pop("run_id", None)
    assert summary_a == summary_b


def test_declared_main_action_rejects_smite_setup_bonus_timing(tmp_path: Path) -> None:
    paladin = _paladin_character(
        level=2,
        resources={"spell_slots": {"1": 1}},
        spells=[
            {
                "name": "Searing Smite",
                "level": 1,
                "concentration": True,
                "mechanics": [
                    {"effect_type": "extra_damage", "damage": "1d6", "damage_type": "fire"}
                ],
            }
        ],
    )
    enemies = [build_enemy(enemy_id="dummy", name="Dummy", hp=200, ac=8, to_hit=0, damage="1")]
    scenario_path = _setup_env(
        tmp_path / "chr10_illegal_smite_timing",
        party=[paladin],
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
        max_rounds=1,
    )

    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = {
        "party_strategy": IllegalSmiteAsMainActionStrategy(),
        "enemy_strategy": BaseStrategy(),
    }

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        run_simulation(
            loaded,
            db,
            {},
            registry,
            trials=1,
            seed=59,
            run_id="chr10_illegal_smite_timing",
        )

    assert exc_info.value.code == "illegal_action"
    assert exc_info.value.field == "action.action_name"
    assert exc_info.value.actor_id == "paladin_2"


def test_declared_basic_then_bonus_searing_smite_remains_legal_with_one_slot() -> None:
    paladin = _build_actor_from_character(
        _paladin_character(
            level=2,
            resources={"spell_slots": {"1": 1}},
            spells=[
                {
                    "name": "Searing Smite",
                    "level": 1,
                    "concentration": True,
                    "mechanics": [
                        {"effect_type": "extra_damage", "damage": "1d6", "damage_type": "fire"}
                    ],
                }
            ],
        ),
        traits_db={},
    )
    target = _actor("ogre", "enemy")
    actors = {paladin.actor_id: paladin, target.actor_id: target}
    damage_dealt = {paladin.actor_id: 0, target.actor_id: 0}
    damage_taken = {paladin.actor_id: 0, target.actor_id: 0}
    threat_scores = {paladin.actor_id: 0, target.actor_id: 0}
    resources_spent = {paladin.actor_id: {}, target.actor_id: {}}

    declaration = TurnDeclaration(
        action=DeclaredAction(
            action_name="basic",
            targets=[TargetRef(actor_id=target.actor_id)],
        ),
        bonus_action=DeclaredAction(
            action_name="Searing Smite",
            targets=[TargetRef(actor_id=paladin.actor_id)],
        ),
    )

    _execute_declared_turn_or_error(
        rng=FixedRng([15, 4, 4, 4]),
        actor=paladin,
        declaration=declaration,
        strategy_name="declared_basic_then_bonus_searing_smite",
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token=f"1:{paladin.actor_id}",
    )

    assert resources_spent[paladin.actor_id].get("spell_slot_1", 0) == 1
    assert paladin.pending_smite is not None
    assert str(paladin.pending_smite.get("name", "")).lower() == "searing smite"
