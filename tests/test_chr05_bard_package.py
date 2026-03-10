from __future__ import annotations

from pathlib import Path

import pytest

from dnd_sim.engine import TurnDeclarationValidationError, run_simulation
from dnd_sim.engine_runtime import (
    _build_actor_from_character,
    _execute_action,
    _spend_action_resource_cost,
    long_rest,
    short_rest,
)
from dnd_sim.io import load_character_db, load_runtime_scenario
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.strategy_api import BaseStrategy, DeclaredAction, TargetRef, TurnDeclaration
from tests.helpers import build_enemy, with_class_levels
from tests.test_engine_integration import _setup_env


class SequenceRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self.values:
            raise AssertionError("RNG exhausted")
        return self.values.pop(0)


class BardInspirationPlanStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        enemies = [
            entry for entry in state.actors.values() if entry.team != actor.team and entry.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()

        target = enemies[0]
        move_to = (
            float(target.position[0]),
            float(target.position[1] - 5.0),
            float(target.position[2]),
        )
        action = DeclaredAction(
            action_name="basic",
            targets=[TargetRef(actor_id=target.actor_id)],
        )
        bonus_action = None
        available = set(state.metadata.get("available_actions", {}).get(actor.actor_id, []))
        if "bardic_inspiration" in available:
            allies = [
                entry
                for entry in state.actors.values()
                if entry.team == actor.team and entry.actor_id != actor.actor_id and entry.hp > 0
            ]
            if allies:
                bonus_action = DeclaredAction(
                    action_name="bardic_inspiration",
                    targets=[TargetRef(actor_id=allies[0].actor_id)],
                )

        return TurnDeclaration(
            movement_path=[actor.position, move_to],
            action=action,
            bonus_action=bonus_action,
        )


class IllegalBardNoResourcePlanStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        enemies = [
            entry for entry in state.actors.values() if entry.team != actor.team and entry.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()

        target = enemies[0]
        move_to = (
            float(target.position[0]),
            float(target.position[1] - 5.0),
            float(target.position[2]),
        )
        action = DeclaredAction(
            action_name="basic",
            targets=[TargetRef(actor_id=target.actor_id)],
        )
        if actor.actor_id != "bard_5":
            return TurnDeclaration(
                movement_path=[actor.position, move_to],
                action=action,
            )

        allies = [
            entry
            for entry in state.actors.values()
            if entry.team == actor.team and entry.actor_id != actor.actor_id and entry.hp > 0
        ]
        if not allies:
            return TurnDeclaration(
                movement_path=[actor.position, move_to],
                action=action,
            )

        return TurnDeclaration(
            movement_path=[actor.position, move_to],
            action=action,
            bonus_action=DeclaredAction(
                action_name="bardic_inspiration",
                targets=[TargetRef(actor_id=allies[0].actor_id)],
            ),
        )


def _base_actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=40,
        hp=40,
        temp_hp=0,
        ac=12,
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


def _bard_character(*, level: int, current_resources: dict[str, int] | None = None) -> dict:
    payload = {
        "character_id": f"bard_{level}",
        "name": f"Bard {level}",
        "class_level": f"Bard {level}",
        "max_hp": 36,
        "ac": 14,
        "speed_ft": 30,
        "ability_scores": {
            "str": 8,
            "dex": 14,
            "con": 14,
            "int": 10,
            "wis": 12,
            "cha": 18,
        },
        "save_mods": {"str": -1, "dex": 2, "con": 2, "int": 0, "wis": 1, "cha": 4},
        "skill_mods": {},
        "attacks": [{"name": "Rapier", "to_hit": 8, "damage": "1d8+4", "damage_type": "piercing"}],
        "resources": {},
        "traits": [],
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }
    if current_resources is not None:
        payload["current_resources"] = current_resources
    return with_class_levels(payload)


def _ally_character() -> dict:
    return with_class_levels(
        {
            "character_id": "ally_support",
            "name": "Support Ally",
            "class_level": "Fighter 5",
            "max_hp": 50,
            "ac": 15,
            "speed_ft": 30,
            "ability_scores": {
                "str": 16,
                "dex": 14,
                "con": 14,
                "int": 10,
                "wis": 10,
                "cha": 10,
            },
            "save_mods": {"str": 3, "dex": 2, "con": 2, "int": 0, "wis": 0, "cha": 0},
            "skill_mods": {},
            "attacks": [
                {"name": "Longsword", "to_hit": 9, "damage": "1d8+3", "damage_type": "slashing"}
            ],
            "resources": {},
            "traits": ["Extra Attack"],
            "raw_fields": [],
            "source": {"pdf_name": "fixture.pdf"},
        }
    )


def test_build_actor_infers_bard_package_traits_resources_and_action() -> None:
    actor = _build_actor_from_character(_bard_character(level=7), traits_db={})
    by_name = {action.name: action for action in actor.actions}

    assert {
        "bardic inspiration",
        "jack of all trades",
        "song of rest",
        "font of inspiration",
        "countercharm",
        "bardic inspiration (d8)",
    }.issubset(actor.traits)
    assert "bardic inspiration (d10)" not in actor.traits
    assert actor.max_resources["bardic_inspiration"] == 4
    assert actor.resources["bardic_inspiration"] == 4
    assert by_name["bardic_inspiration"].resource_cost == {"bardic_inspiration": 1}


def test_build_actor_infers_bard_package_from_class_levels_only_payload() -> None:
    character = _bard_character(level=5)
    character["class_levels"] = {"bard": 5}

    actor = _build_actor_from_character(character, traits_db={})
    by_name = {action.name: action for action in actor.actions}

    assert actor.class_levels == {"bard": 5}
    assert "bardic inspiration" in actor.traits
    assert actor.max_resources["bardic_inspiration"] == 4
    assert actor.resources["bardic_inspiration"] == 4
    assert by_name["bardic_inspiration"].resource_cost == {"bardic_inspiration": 1}


def test_build_actor_prefers_class_levels_when_class_level_text_mismatches_for_bard() -> None:
    character = _bard_character(level=5)
    character["class_levels"] = {"bard": 5}

    actor = _build_actor_from_character(character, traits_db={})
    by_name = {action.name: action for action in actor.actions}

    assert actor.class_levels == {"bard": 5}
    assert "bardic inspiration" in actor.traits
    assert actor.max_resources["bardic_inspiration"] == 4
    assert actor.resources["bardic_inspiration"] == 4
    assert by_name["bardic_inspiration"].resource_cost == {"bardic_inspiration": 1}


def test_bardic_inspiration_resource_lifecycle_short_and_long_rest_recovery() -> None:
    pre_font_bard = _build_actor_from_character(_bard_character(level=4), traits_db={})
    pre_font_action = next(
        action for action in pre_font_bard.actions if action.name == "bardic_inspiration"
    )
    pre_font_ally = _base_actor(actor_id="ally_pre", team="party")
    resources_spent = {pre_font_bard.actor_id: {}, pre_font_ally.actor_id: {}}
    actors = {pre_font_bard.actor_id: pre_font_bard, pre_font_ally.actor_id: pre_font_ally}

    assert _spend_action_resource_cost(pre_font_bard, pre_font_action, resources_spent)
    _execute_action(
        rng=SequenceRng([]),
        actor=pre_font_bard,
        action=pre_font_action,
        targets=[pre_font_ally],
        actors=actors,
        damage_dealt={pre_font_bard.actor_id: 0, pre_font_ally.actor_id: 0},
        damage_taken={pre_font_bard.actor_id: 0, pre_font_ally.actor_id: 0},
        threat_scores={pre_font_bard.actor_id: 0, pre_font_ally.actor_id: 0},
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert pre_font_bard.resources["bardic_inspiration"] == 3

    short_rest(pre_font_bard)
    assert pre_font_bard.resources["bardic_inspiration"] == 3

    long_rest(pre_font_bard)
    assert pre_font_bard.resources["bardic_inspiration"] == 4

    post_font_bard = _build_actor_from_character(_bard_character(level=5), traits_db={})
    post_font_action = next(
        action for action in post_font_bard.actions if action.name == "bardic_inspiration"
    )
    post_font_ally = _base_actor(actor_id="ally_post", team="party")
    post_resources_spent = {post_font_bard.actor_id: {}, post_font_ally.actor_id: {}}
    post_actors = {post_font_bard.actor_id: post_font_bard, post_font_ally.actor_id: post_font_ally}

    assert _spend_action_resource_cost(post_font_bard, post_font_action, post_resources_spent)
    _execute_action(
        rng=SequenceRng([]),
        actor=post_font_bard,
        action=post_font_action,
        targets=[post_font_ally],
        actors=post_actors,
        damage_dealt={post_font_bard.actor_id: 0, post_font_ally.actor_id: 0},
        damage_taken={post_font_bard.actor_id: 0, post_font_ally.actor_id: 0},
        threat_scores={post_font_bard.actor_id: 0, post_font_ally.actor_id: 0},
        resources_spent=post_resources_spent,
        active_hazards=[],
    )

    assert post_font_bard.resources["bardic_inspiration"] == 3
    short_rest(post_font_bard)
    assert post_font_bard.resources["bardic_inspiration"] == 4


def test_cutting_words_consumes_reaction_once_per_attack_sequence() -> None:
    rng = SequenceRng([10, 4, 10, 3])  # attack1 d20, cut words d6, attack2 d20, damage d4

    attacker = _base_actor(actor_id="attacker", team="enemy")
    attacker.position = (20.0, 0.0, 0.0)

    target = _base_actor(actor_id="target", team="party")
    target.ac = 15

    bard = _base_actor(actor_id="bard", team="party")
    bard.position = (0.0, 0.0, 0.0)
    bard.traits = {"cutting words": {}}
    bard.resources = {"bardic_inspiration": 1}

    action = ActionDefinition(
        name="claw",
        action_type="attack",
        to_hit=8,
        damage="1d4+2",
        damage_type="slashing",
        attack_count=2,
    )

    actors = {attacker.actor_id: attacker, target.actor_id: target, bard.actor_id: bard}
    damage_dealt = {attacker.actor_id: 0, target.actor_id: 0, bard.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, target.actor_id: 0, bard.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, target.actor_id: 0, bard.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, target.actor_id: {}, bard.actor_id: {}}

    _execute_action(
        rng=rng,
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

    assert target.hp == 35
    assert bard.resources["bardic_inspiration"] == 0
    assert bard.reaction_available is False
    assert resources_spent[bard.actor_id]["bardic_inspiration"] == 1


def test_chr05_integration_declared_bardic_inspiration_is_deterministic(tmp_path: Path) -> None:
    party = [_bard_character(level=7), _ally_character()]
    enemies = [build_enemy(enemy_id="dummy", name="Dummy", hp=250, ac=8, to_hit=0, damage="1")]

    scenario_path = _setup_env(
        tmp_path / "chr05_bard_integration",
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
        max_rounds=1,
    )
    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = {
        "party_strategy": BardInspirationPlanStrategy(),
        "enemy_strategy": BaseStrategy(),
    }

    run_a = run_simulation(loaded, db, {}, registry, trials=1, seed=61, run_id="chr05_bard_a")
    run_b = run_simulation(loaded, db, {}, registry, trials=1, seed=61, run_id="chr05_bard_b")

    trial = run_a.trial_results[0]
    assert trial.resources_spent["bard_7"].get("bardic_inspiration", 0) == 1
    assert (
        trial.state_snapshots[-1]["party"]["ally_support"]["resources"]["bardic_inspiration_die"]
        == 8
    )

    summary_a = run_a.summary.to_dict()
    summary_b = run_b.summary.to_dict()
    summary_a.pop("run_id", None)
    summary_b.pop("run_id", None)
    assert summary_a == summary_b


def test_declared_bardic_inspiration_without_resource_is_rejected(tmp_path: Path) -> None:
    bard = _bard_character(level=5, current_resources={"bardic_inspiration": 0})
    party = [bard, _ally_character()]
    enemies = [build_enemy(enemy_id="dummy", name="Dummy", hp=250, ac=8, to_hit=0, damage="1")]

    scenario_path = _setup_env(
        tmp_path / "chr05_bard_invalid",
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
        max_rounds=1,
    )
    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = {
        "party_strategy": IllegalBardNoResourcePlanStrategy(),
        "enemy_strategy": BaseStrategy(),
    }

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        run_simulation(loaded, db, {}, registry, trials=1, seed=67, run_id="chr05_bard_illegal")

    assert exc_info.value.code == "unavailable_action"
    assert exc_info.value.actor_id == "bard_5"
    assert exc_info.value.field == "bonus_action.action_name"
