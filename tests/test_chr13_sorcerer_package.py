from __future__ import annotations

from pathlib import Path

import pytest

from dnd_sim.engine import (
    TurnDeclarationValidationError,
    _build_actor_from_character,
    _spend_action_resource_cost,
    long_rest,
    run_simulation,
    short_rest,
)
from dnd_sim.io import load_character_db, load_scenario
from dnd_sim.strategy_api import BaseStrategy, DeclaredAction, TargetRef, TurnDeclaration
from tests.helpers import build_enemy
from tests.test_engine_integration import _setup_env


class QuickenedCantripStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        enemies = [
            entry for entry in state.actors.values() if entry.team != actor.team and entry.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()
        target = enemies[0]
        return TurnDeclaration(
            action=DeclaredAction(
                action_name="Fire Bolt",
                targets=[TargetRef(actor_id=target.actor_id)],
            ),
            bonus_action=DeclaredAction(
                action_name="Chromatic Orb [Quickened]",
                targets=[TargetRef(actor_id=target.actor_id)],
            ),
        )


class IllegalDoubleLeveledSpellSequenceStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        enemies = [
            entry for entry in state.actors.values() if entry.team != actor.team and entry.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()
        target = enemies[0]
        return TurnDeclaration(
            action=DeclaredAction(
                action_name="Chromatic Orb",
                targets=[TargetRef(actor_id=target.actor_id)],
            ),
            bonus_action=DeclaredAction(
                action_name="Fireball [Quickened]",
                targets=[TargetRef(actor_id=target.actor_id)],
            ),
        )


def _sorcerer_character(
    *,
    level: int,
    traits: list[str],
    spells: list[dict],
    resources: dict | None = None,
    class_level: str | None = None,
    class_levels: dict[str, int] | None = None,
) -> dict:
    payload: dict = {
        "character_id": f"sorcerer_{level}",
        "name": f"Sorcerer {level}",
        "class_level": class_level if class_level is not None else f"Sorcerer {level}",
        "max_hp": 34,
        "ac": 14,
        "speed_ft": 30,
        "ability_scores": {"str": 8, "dex": 14, "con": 14, "int": 10, "wis": 12, "cha": 18},
        "save_mods": {"str": -1, "dex": 2, "con": 2, "int": 0, "wis": 1, "cha": 7},
        "skill_mods": {},
        "attacks": [],
        "spells": spells,
        "resources": resources or {},
        "traits": traits,
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }
    if class_levels is not None:
        payload["class_levels"] = dict(class_levels)
    return payload


def test_build_actor_infers_sorcerer_package_traits_and_sorcery_points() -> None:
    actor = _build_actor_from_character(
        _sorcerer_character(
            level=12,
            class_level="",
            class_levels={"sorcerer": 7, "fighter": 5},
            traits=[],
            spells=[
                {
                    "name": "Fire Bolt",
                    "level": 0,
                    "action_type": "attack",
                    "to_hit": 7,
                    "damage": "1d10",
                    "damage_type": "fire",
                    "target_mode": "single_enemy",
                }
            ],
            resources={"spell_slots": {"1": 4, "2": 3, "3": 3, "4": 1}},
        ),
        traits_db={},
    )
    by_name = {action.name: action for action in actor.actions}

    assert actor.class_levels == {"sorcerer": 7, "fighter": 5}
    assert {"spellcasting", "font of magic", "metamagic"}.issubset(actor.traits)
    assert "sorcerous restoration" not in actor.traits
    assert actor.max_resources["sorcery_points"] == 7
    assert actor.resources["sorcery_points"] == 7
    assert "font_of_magic_create_slot_5" in by_name


def test_non_empty_class_levels_without_sorcerer_entry_blocks_text_fallback() -> None:
    actor = _build_actor_from_character(
        _sorcerer_character(
            level=9,
            class_level="Sorcerer 5 / Fighter 4",
            class_levels={"fighter": 9},
            traits=[],
            spells=[],
            resources={"spell_slots": {"2": 2}},
        ),
        traits_db={},
    )

    assert "spellcasting" not in actor.traits
    assert "font of magic" not in actor.traits
    assert "sorcery_points" not in actor.max_resources


def test_explicit_class_levels_override_conflicting_sorcerer_text() -> None:
    actor = _build_actor_from_character(
        _sorcerer_character(
            level=12,
            class_level="Sorcerer 20 / Fighter 1",
            class_levels={"sorcerer": 2, "fighter": 10},
            traits=[],
            spells=[],
            resources={"spell_slots": {"1": 4}},
        ),
        traits_db={},
    )

    assert "metamagic" not in actor.traits
    assert "sorcerous restoration" not in actor.traits
    assert actor.max_resources["sorcery_points"] == 2


def test_sorcery_points_lifecycle_spend_short_rest_and_long_rest() -> None:
    actor = _build_actor_from_character(
        _sorcerer_character(
            level=6,
            traits=[],
            spells=[],
            resources={"spell_slots": {"1": 4, "2": 3, "3": 3}},
        ),
        traits_db={},
    )
    resources_spent = {actor.actor_id: {}}
    conversion = next(
        action for action in actor.actions if action.name == "font_of_magic_create_slot_2"
    )

    assert actor.resources["sorcery_points"] == 6
    assert _spend_action_resource_cost(
        actor, conversion, resources_spent, turn_token="1:sorcerer_6"
    )
    assert actor.resources["sorcery_points"] == 3

    short_rest(actor)
    assert actor.resources["sorcery_points"] == 3

    long_rest(actor)
    assert actor.resources["sorcery_points"] == 6


def test_sorcerous_restoration_level_20_short_rest_recovers_four_and_caps() -> None:
    actor = _build_actor_from_character(
        _sorcerer_character(
            level=20,
            traits=[],
            spells=[],
            resources={"spell_slots": {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2}},
        ),
        traits_db={},
    )

    assert "sorcerous restoration" in actor.traits
    assert actor.max_resources["sorcery_points"] == 20

    actor.resources["sorcery_points"] = 12
    short_rest(actor)
    assert actor.resources["sorcery_points"] == 16

    actor.resources["sorcery_points"] = 19
    short_rest(actor)
    assert actor.resources["sorcery_points"] == 20


def test_chr13_integration_quickened_sequence_is_legal_and_deterministic(
    tmp_path: Path,
) -> None:
    sorcerer = _sorcerer_character(
        level=5,
        traits=["Quickened Spell"],
        spells=[
            {
                "name": "Fire Bolt",
                "level": 0,
                "action_type": "attack",
                "to_hit": 7,
                "damage": "1d10",
                "damage_type": "fire",
                "range_ft": 120,
                "target_mode": "single_enemy",
            },
            {
                "name": "Chromatic Orb",
                "level": 1,
                "action_type": "attack",
                "to_hit": 7,
                "damage": "3d8",
                "damage_type": "acid",
                "range_ft": 90,
                "target_mode": "single_enemy",
            },
        ],
        resources={"spell_slots": {"1": 4, "2": 3, "3": 2}},
    )
    enemies = [build_enemy(enemy_id="dummy", name="Dummy", hp=220, ac=8, to_hit=0, damage="1")]
    scenario_path = _setup_env(
        tmp_path / "chr13_sorcerer_quickened",
        party=[sorcerer],
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
        "party_strategy": QuickenedCantripStrategy(),
        "enemy_strategy": BaseStrategy(),
    }

    run_a = run_simulation(loaded, db, {}, registry, trials=1, seed=43, run_id="chr13_quickened_a")
    run_b = run_simulation(loaded, db, {}, registry, trials=1, seed=43, run_id="chr13_quickened_b")

    trial_a = run_a.trial_results[0]
    trial_b = run_b.trial_results[0]
    resources = trial_a.state_snapshots[-1]["party"]["sorcerer_5"]["resources"]

    assert trial_a.resources_spent["sorcerer_5"].get("sorcery_points", 0) == 2
    assert trial_a.resources_spent["sorcerer_5"].get("spell_slot_1", 0) == 1
    assert resources["sorcery_points"] == 3
    assert trial_a.rounds == trial_b.rounds
    assert trial_a.resources_spent == trial_b.resources_spent
    assert trial_a.state_snapshots == trial_b.state_snapshots

    summary_a = run_a.summary.to_dict()
    summary_b = run_b.summary.to_dict()
    summary_a.pop("run_id", None)
    summary_b.pop("run_id", None)
    assert summary_a == summary_b


def test_declared_quickened_spell_with_insufficient_sorcery_points_is_rejected(
    tmp_path: Path,
) -> None:
    sorcerer = _sorcerer_character(
        level=5,
        traits=["Quickened Spell"],
        spells=[
            {
                "name": "Fire Bolt",
                "level": 0,
                "action_type": "attack",
                "to_hit": 7,
                "damage": "1d10",
                "damage_type": "fire",
                "range_ft": 120,
                "target_mode": "single_enemy",
            },
            {
                "name": "Chromatic Orb",
                "level": 1,
                "action_type": "attack",
                "to_hit": 7,
                "damage": "3d8",
                "damage_type": "acid",
                "range_ft": 90,
                "target_mode": "single_enemy",
            },
        ],
        resources={"spell_slots": {"1": 4, "2": 3, "3": 2}},
    )
    sorcerer["current_resources"] = {"sorcery_points": 1}
    enemies = [build_enemy(enemy_id="dummy", name="Dummy", hp=220, ac=8, to_hit=0, damage="1")]
    scenario_path = _setup_env(
        tmp_path / "chr13_quickened_insufficient_points",
        party=[sorcerer],
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
        "party_strategy": QuickenedCantripStrategy(),
        "enemy_strategy": BaseStrategy(),
    }

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        run_simulation(
            loaded,
            db,
            {},
            registry,
            trials=1,
            seed=53,
            run_id="chr13_quickened_insufficient_points",
        )

    assert exc_info.value.code == "unavailable_action"
    assert exc_info.value.actor_id == "sorcerer_5"
    assert exc_info.value.field == "bonus_action.action_name"


def test_declared_double_leveled_spell_sequence_is_rejected(tmp_path: Path) -> None:
    sorcerer = _sorcerer_character(
        level=5,
        traits=["Quickened Spell"],
        spells=[
            {
                "name": "Chromatic Orb",
                "level": 1,
                "action_type": "attack",
                "to_hit": 7,
                "damage": "3d8",
                "damage_type": "acid",
                "range_ft": 90,
                "target_mode": "single_enemy",
            },
            {
                "name": "Fireball",
                "level": 3,
                "action_type": "save",
                "save_dc": 15,
                "save_ability": "dex",
                "damage": "8d6",
                "damage_type": "fire",
                "half_on_save": True,
                "target_mode": "single_enemy",
                "range_ft": 150,
            },
        ],
        resources={"spell_slots": {"1": 4, "2": 3, "3": 2}},
    )
    enemies = [build_enemy(enemy_id="dummy", name="Dummy", hp=220, ac=8, to_hit=0, damage="1")]
    scenario_path = _setup_env(
        tmp_path / "chr13_illegal_double_spell",
        party=[sorcerer],
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
        "party_strategy": IllegalDoubleLeveledSpellSequenceStrategy(),
        "enemy_strategy": BaseStrategy(),
    }

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        run_simulation(
            loaded,
            db,
            {},
            registry,
            trials=1,
            seed=47,
            run_id="chr13_illegal_double_spell",
        )

    assert exc_info.value.code == "unavailable_action"
    assert exc_info.value.actor_id == "sorcerer_5"
    assert exc_info.value.field == "bonus_action.action_name"
