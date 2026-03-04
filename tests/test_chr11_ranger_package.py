from __future__ import annotations

import random
from dataclasses import replace
from pathlib import Path

import pytest

from dnd_sim.engine import (
    TurnDeclarationValidationError,
    _build_actor_from_character,
    _execute_action,
    _tick_conditions_for_actor,
    long_rest,
    run_simulation,
    short_rest,
)
from dnd_sim.io import load_character_db, load_scenario
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


class IllegalVanishAsMainActionStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        enemies = [
            entry for entry in state.actors.values() if entry.team != actor.team and entry.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()
        return TurnDeclaration(
            action=DeclaredAction(
                action_name="vanish_hide",
                targets=[TargetRef(actor_id=actor.actor_id)],
            )
        )


def _ranger_character(
    *,
    level: int,
    traits: list[str] | None = None,
    resources: dict | None = None,
    current_resources: dict | None = None,
) -> dict:
    payload: dict = {
        "character_id": f"ranger_{level}",
        "name": f"Ranger {level}",
        "class_level": f"Ranger {level}",
        "max_hp": 52,
        "ac": 16,
        "speed_ft": 30,
        "ability_scores": {"str": 12, "dex": 18, "con": 14, "int": 10, "wis": 16, "cha": 10},
        "save_mods": {"str": 1, "dex": 7, "con": 2, "int": 0, "wis": 6, "cha": 0},
        "skill_mods": {},
        "attacks": [{"name": "Longbow", "to_hit": 9, "damage": "1d1", "damage_type": "piercing"}],
        "resources": resources or {},
        "traits": list(traits or []),
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }
    if current_resources is not None:
        payload["current_resources"] = current_resources
    return with_class_levels(payload)


def _enemy(actor_id: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team="enemy",
        name=actor_id,
        max_hp=50,
        hp=50,
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


def test_build_actor_infers_ranger_core_traits_and_vanish_bonus_action() -> None:
    actor = _build_actor_from_character(_ranger_character(level=14), traits_db={})
    by_name = {action.name: action for action in actor.actions}

    assert {
        "favored enemy",
        "natural explorer",
        "spellcasting",
        "extra attack",
        "vanish",
    }.issubset(actor.traits.keys())
    assert by_name["vanish_hide"].action_cost == "bonus"
    assert "vanish" in by_name["vanish_hide"].tags


def test_ranger_spell_slot_lifecycle_short_rest_then_long_rest() -> None:
    actor = _build_actor_from_character(
        _ranger_character(
            level=5,
            traits=["Spellcasting"],
            resources={"spell_slots": {"1": 4, "2": 2}},
            current_resources={"spell_slot_1": 0, "spell_slot_2": 1},
        ),
        traits_db={},
    )

    short_rest(actor)
    assert actor.resources["spell_slot_1"] == 0
    assert actor.resources["spell_slot_2"] == 1

    long_rest(actor)
    assert actor.resources["spell_slot_1"] == 4
    assert actor.resources["spell_slot_2"] == 2


def test_colossus_slayer_applies_once_per_turn_and_resets_next_turn() -> None:
    ranger = _build_actor_from_character(
        _ranger_character(level=5, traits=["Extra Attack", "Colossus Slayer"]),
        traits_db={},
    )
    target = _enemy("ogre")
    target.hp = 40
    basic = next(action for action in ranger.actions if action.name == "basic")
    single_attack = replace(basic, attack_count=1)

    actors = {ranger.actor_id: ranger, target.actor_id: target}
    damage_dealt = {ranger.actor_id: 0, target.actor_id: 0}
    damage_taken = {ranger.actor_id: 0, target.actor_id: 0}
    threat_scores = {ranger.actor_id: 0, target.actor_id: 0}
    resources_spent = {ranger.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=FixedRng([15, 1, 4, 4, 1]),
        actor=ranger,
        action=basic,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token=f"1:{ranger.actor_id}",
    )

    assert damage_dealt[ranger.actor_id] == 6
    assert ranger.colossus_slayer_used_this_turn is True

    _tick_conditions_for_actor(random.Random(7), ranger)
    assert ranger.colossus_slayer_used_this_turn is False

    _execute_action(
        rng=FixedRng([15, 1, 6]),
        actor=ranger,
        action=single_attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=2,
        turn_token=f"2:{ranger.actor_id}",
    )

    assert damage_dealt[ranger.actor_id] == 13


def test_colossus_slayer_does_not_proc_off_turn_attack() -> None:
    ranger = _build_actor_from_character(
        _ranger_character(level=5, traits=["Extra Attack", "Colossus Slayer"]),
        traits_db={},
    )
    target = _enemy("ogre")
    target.hp = 40
    basic = next(action for action in ranger.actions if action.name == "basic")
    reaction_attack = replace(basic, attack_count=1, action_cost="reaction")

    actors = {ranger.actor_id: ranger, target.actor_id: target}
    damage_dealt = {ranger.actor_id: 0, target.actor_id: 0}
    damage_taken = {ranger.actor_id: 0, target.actor_id: 0}
    threat_scores = {ranger.actor_id: 0, target.actor_id: 0}
    resources_spent = {ranger.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=FixedRng([15, 1]),
        actor=ranger,
        action=reaction_attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:enemy",
    )

    assert damage_dealt[ranger.actor_id] == 1
    assert ranger.colossus_slayer_used_this_turn is False


def test_colossus_slayer_does_not_proc_against_full_hp_target() -> None:
    ranger = _build_actor_from_character(
        _ranger_character(level=5, traits=["Extra Attack", "Colossus Slayer"]),
        traits_db={},
    )
    target = _enemy("ogre")
    basic = next(action for action in ranger.actions if action.name == "basic")
    single_attack = replace(basic, attack_count=1)

    actors = {ranger.actor_id: ranger, target.actor_id: target}
    damage_dealt = {ranger.actor_id: 0, target.actor_id: 0}
    damage_taken = {ranger.actor_id: 0, target.actor_id: 0}
    threat_scores = {ranger.actor_id: 0, target.actor_id: 0}
    resources_spent = {ranger.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=FixedRng([15, 1]),
        actor=ranger,
        action=single_attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token=f"1:{ranger.actor_id}",
    )

    assert damage_dealt[ranger.actor_id] == 1
    assert ranger.colossus_slayer_used_this_turn is False


def test_colossus_slayer_does_not_proc_for_spell_tagged_attack() -> None:
    ranger = _build_actor_from_character(
        _ranger_character(level=5, traits=["Extra Attack", "Colossus Slayer"]),
        traits_db={},
    )
    target = _enemy("ogre")
    target.hp = 40
    basic = next(action for action in ranger.actions if action.name == "basic")
    single_attack = replace(basic, attack_count=1)
    spell_tagged_attack = replace(
        single_attack,
        tags=[*single_attack.tags, "spell"],
        range_ft=5,
        range_normal_ft=None,
        range_long_ft=None,
    )

    actors = {ranger.actor_id: ranger, target.actor_id: target}
    damage_dealt = {ranger.actor_id: 0, target.actor_id: 0}
    damage_taken = {ranger.actor_id: 0, target.actor_id: 0}
    threat_scores = {ranger.actor_id: 0, target.actor_id: 0}
    resources_spent = {ranger.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=FixedRng([15, 1]),
        actor=ranger,
        action=spell_tagged_attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token=f"1:{ranger.actor_id}",
    )

    assert damage_dealt[ranger.actor_id] == 1
    assert ranger.colossus_slayer_used_this_turn is False


def test_declared_main_action_rejects_vanish_hide_bonus_timing(tmp_path: Path) -> None:
    ranger = _ranger_character(level=14)
    enemies = [
        build_enemy(enemy_id="dummy", name="Dummy", hp=200, ac=8, to_hit=0, damage="1"),
    ]
    scenario_path = _setup_env(
        tmp_path / "chr11_illegal_vanish",
        party=[ranger],
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
    )

    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = {
        "party_strategy": IllegalVanishAsMainActionStrategy(),
        "enemy_strategy": BaseStrategy(),
    }

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        run_simulation(
            loaded,
            db,
            {},
            registry,
            trials=1,
            seed=31,
            run_id="chr11_illegal_vanish",
        )

    assert exc_info.value.code == "illegal_action"
    assert exc_info.value.field == "action.action_name"
    assert exc_info.value.actor_id == "ranger_14"
