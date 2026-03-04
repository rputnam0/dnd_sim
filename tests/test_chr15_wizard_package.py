from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dnd_sim.engine import (
    TurnDeclarationValidationError,
    _action_available,
    _build_actor_from_character,
    _execute_action,
    _spend_action_resource_cost,
    _tick_conditions_for_actor,
    long_rest,
    run_simulation,
    short_rest,
)
from dnd_sim.io import load_character_db, load_scenario
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


class WizardMagicMissilePlanStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        enemies = [
            entry for entry in state.actors.values() if entry.team != actor.team and entry.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()
        return TurnDeclaration(
            action=DeclaredAction(
                action_name="Magic Missile",
                targets=[TargetRef(actor_id=enemies[0].actor_id)],
            )
        )


class IllegalShieldAsMainActionStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        enemies = [
            entry for entry in state.actors.values() if entry.team != actor.team and entry.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()
        return TurnDeclaration(
            action=DeclaredAction(
                action_name="Shield",
                targets=[TargetRef(actor_id=actor.actor_id)],
            )
        )


def _wizard_character(
    *,
    level: int,
    class_level: str | None = None,
    class_levels: dict[str, int] | None = None,
    traits: list[str] | None = None,
    spells: list[dict[str, Any]] | None = None,
    resources: dict[str, Any] | None = None,
    current_resources: dict[str, int] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "character_id": f"wizard_{level}",
        "name": f"Wizard {level}",
        "class_level": f"Wizard {level}" if class_level is None else class_level,
        "max_hp": 30,
        "ac": 13,
        "speed_ft": 30,
        "ability_scores": {
            "str": 8,
            "dex": 14,
            "con": 12,
            "int": 18,
            "wis": 12,
            "cha": 10,
        },
        "save_mods": {"str": -1, "dex": 2, "con": 1, "int": 7, "wis": 1, "cha": 0},
        "skill_mods": {},
        "attacks": [],
        "spells": list(spells or []),
        "resources": dict(resources or {}),
        "traits": list(traits or []),
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }
    if class_levels is not None:
        payload["class_levels"] = dict(class_levels)
    if current_resources is not None:
        payload["current_resources"] = dict(current_resources)
    return with_class_levels(payload)


def _enemy(actor_id: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team="enemy",
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


def test_build_actor_infers_wizard_package_and_arcane_recovery_lifecycle() -> None:
    actor = _build_actor_from_character(
        _wizard_character(
            level=5,
            class_level="",
            class_levels={"wizard": 5},
            traits=[],
            resources={"spell_slots": {"1": 4, "2": 3, "3": 2}},
            current_resources={"spell_slot_3": 0, "arcane_recovery": 1},
        ),
        traits_db={},
    )

    assert actor.class_levels == {"wizard": 5}
    assert {"spellcasting", "arcane recovery", "arcane tradition"}.issubset(actor.traits)
    assert actor.max_resources["arcane_recovery"] == 1
    assert actor.resources["arcane_recovery"] == 1

    short_rest(actor)
    assert actor.resources["spell_slot_3"] == 1
    assert actor.resources["arcane_recovery"] == 0

    actor.resources["spell_slot_3"] = 0
    short_rest(actor)
    assert actor.resources["spell_slot_3"] == 0

    long_rest(actor)
    assert actor.resources["spell_slot_3"] == 2
    assert actor.resources["arcane_recovery"] == 1


def test_wizard_reaction_spell_obeys_timing_and_resource_legality() -> None:
    wizard = _build_actor_from_character(
        _wizard_character(
            level=5,
            traits=[],
            resources={"spell_slots": {"1": 4, "2": 3, "3": 2}},
            spells=[
                {
                    "name": "Misty Step",
                    "level": 2,
                    "action_type": "utility",
                    "action_cost": "bonus",
                    "target_mode": "self",
                },
                {
                    "name": "Shield",
                    "level": 1,
                    "action_type": "utility",
                    "action_cost": "reaction",
                    "target_mode": "self",
                },
            ],
        ),
        traits_db={},
    )
    enemy = _enemy("orc")
    actors = {wizard.actor_id: wizard, enemy.actor_id: enemy}
    resources_spent = {wizard.actor_id: {}, enemy.actor_id: {}}
    misty_step = next(action for action in wizard.actions if action.name == "Misty Step")
    shield = next(action for action in wizard.actions if action.name == "Shield")

    assert _spend_action_resource_cost(
        wizard, misty_step, resources_spent, turn_token=f"1:{wizard.actor_id}"
    )
    _execute_action(
        rng=SequenceRng([]),
        actor=wizard,
        action=misty_step,
        targets=[wizard],
        actors=actors,
        damage_dealt={wizard.actor_id: 0, enemy.actor_id: 0},
        damage_taken={wizard.actor_id: 0, enemy.actor_id: 0},
        threat_scores={wizard.actor_id: 0, enemy.actor_id: 0},
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token=f"1:{wizard.actor_id}",
    )

    assert _action_available(wizard, shield, turn_token=f"1:{wizard.actor_id}") is False
    assert _action_available(wizard, shield, turn_token="1:orc") is True

    wizard.resources["spell_slot_1"] = 0
    wizard.resources["spell_slot_2"] = 0
    wizard.resources["spell_slot_3"] = 0
    assert _action_available(wizard, shield, turn_token="1:orc") is False


def test_non_empty_class_levels_without_wizard_entry_blocks_text_fallback() -> None:
    actor = _build_actor_from_character(
        _wizard_character(
            level=12,
            class_level="Wizard 18 / Fighter 2",
            class_levels={"fighter": 12},
            traits=[],
            resources={"spell_slots": {"1": 4, "2": 3, "3": 2}},
        ),
        traits_db={},
    )

    assert "spellcasting" not in actor.traits
    assert "arcane recovery" not in actor.traits
    assert "arcane tradition" not in actor.traits
    assert "spell mastery" not in actor.traits
    assert "signature spells" not in actor.traits
    assert "arcane_recovery" not in actor.max_resources


def test_explicit_class_levels_override_conflicting_wizard_text() -> None:
    actor = _build_actor_from_character(
        _wizard_character(
            level=12,
            class_level="Wizard 20 / Fighter 1",
            class_levels={"wizard": 2, "fighter": 10},
            traits=[],
            resources={"spell_slots": {"1": 4, "2": 2}},
        ),
        traits_db={},
    )

    assert "spellcasting" in actor.traits
    assert "arcane recovery" in actor.traits
    assert "arcane tradition" in actor.traits
    assert "spell mastery" not in actor.traits
    assert "signature spells" not in actor.traits


def test_wizard_package_feature_threshold_edges() -> None:
    level_17_actor = _build_actor_from_character(
        _wizard_character(
            level=17,
            class_level="",
            class_levels={"wizard": 17},
            traits=[],
            resources={"spell_slots": {"1": 4, "2": 3, "3": 3, "4": 3, "5": 1}},
        ),
        traits_db={},
    )
    level_18_actor = _build_actor_from_character(
        _wizard_character(
            level=18,
            class_level="",
            class_levels={"wizard": 18},
            traits=[],
            resources={"spell_slots": {"1": 4, "2": 3, "3": 3, "4": 3, "5": 1}},
        ),
        traits_db={},
    )
    level_20_actor = _build_actor_from_character(
        _wizard_character(
            level=20,
            class_level="",
            class_levels={"wizard": 20},
            traits=[],
            resources={"spell_slots": {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2}},
        ),
        traits_db={},
    )

    assert "spell mastery" not in level_17_actor.traits
    assert "signature spells" not in level_17_actor.traits
    assert "spell mastery" in level_18_actor.traits
    assert "signature spells" not in level_18_actor.traits
    assert "spell mastery" in level_20_actor.traits
    assert "signature spells" in level_20_actor.traits


def test_wizard_shield_reaction_lifecycle_requires_turn_refresh() -> None:
    wizard = _build_actor_from_character(
        _wizard_character(
            level=5,
            traits=[],
            spells=[
                {
                    "name": "Shield",
                    "level": 1,
                    "action_type": "utility",
                    "action_cost": "reaction",
                    "target_mode": "self",
                }
            ],
            resources={"spell_slots": {"1": 4, "2": 3, "3": 2}},
        ),
        traits_db={},
    )
    enemy = _enemy("orc")
    attack = ActionDefinition(
        name="longsword",
        action_type="attack",
        action_cost="action",
        target_mode="single_enemy",
        to_hit=2,
        damage="4",
        damage_type="slashing",
    )
    actors = {wizard.actor_id: wizard, enemy.actor_id: enemy}
    damage_dealt = {wizard.actor_id: 0, enemy.actor_id: 0}
    damage_taken = {wizard.actor_id: 0, enemy.actor_id: 0}
    threat_scores = {wizard.actor_id: 0, enemy.actor_id: 0}
    resources_spent = {wizard.actor_id: {}, enemy.actor_id: {}}
    shield = next(action for action in wizard.actions if action.name == "Shield")

    _execute_action(
        rng=SequenceRng([11]),
        actor=enemy,
        action=attack,
        targets=[wizard],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:orc",
    )

    assert wizard.resources["spell_slot_1"] == 3
    assert wizard.reaction_available is False
    assert _action_available(wizard, shield, turn_token="1:orc") is False
    assert _action_available(wizard, shield, turn_token="2:orc") is False

    _tick_conditions_for_actor(SequenceRng([1]), wizard, boundary="turn_start")
    wizard.reaction_available = True
    assert _action_available(wizard, shield, turn_token="2:orc") is True


def test_chr15_integration_wizard_package_is_deterministic(tmp_path: Path) -> None:
    wizard = _wizard_character(
        level=5,
        class_level="",
        class_levels={"wizard": 5},
        traits=[],
        spells=[
            {
                "name": "Magic Missile",
                "level": 1,
                "action_type": "attack",
                "to_hit": 8,
                "damage": "1d4+1",
                "damage_type": "force",
                "target_mode": "single_enemy",
            }
        ],
        resources={"spell_slots": {"1": 4, "2": 3, "3": 2}},
    )
    enemies = [build_enemy(enemy_id="dummy", name="Dummy", hp=250, ac=8, to_hit=0, damage="1")]
    scenario_path = _setup_env(
        tmp_path / "chr15_wizard_integration",
        party=[wizard],
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
        "party_strategy": WizardMagicMissilePlanStrategy(),
        "enemy_strategy": BaseStrategy(),
    }

    run_a = run_simulation(loaded, db, {}, registry, trials=1, seed=95, run_id="chr15_wizard_a")
    run_b = run_simulation(loaded, db, {}, registry, trials=1, seed=95, run_id="chr15_wizard_b")

    trial = run_a.trial_results[0]
    snapshot = trial.state_snapshots[-1]["party"]["wizard_5"]["resources"]

    assert trial.rounds == 1
    assert trial.resources_spent["wizard_5"].get("spell_slot_1", 0) == 1
    assert snapshot["spell_slot_1"] == 3
    assert snapshot["arcane_recovery"] == 1

    first_trial = run_a.trial_results[0]
    second_trial = run_b.trial_results[0]
    assert first_trial.rounds == second_trial.rounds
    assert first_trial.winner == second_trial.winner
    assert first_trial.damage_taken == second_trial.damage_taken
    assert first_trial.damage_dealt == second_trial.damage_dealt
    assert first_trial.resources_spent == second_trial.resources_spent
    assert first_trial.state_snapshots == second_trial.state_snapshots
    assert run_a.trial_rows == run_b.trial_rows

    summary_a = run_a.summary.to_dict()
    summary_b = run_b.summary.to_dict()
    summary_a.pop("run_id", None)
    summary_b.pop("run_id", None)
    assert summary_a == summary_b


def test_declared_main_action_rejects_wizard_reaction_spell(tmp_path: Path) -> None:
    wizard = _wizard_character(
        level=5,
        traits=[],
        spells=[
            {
                "name": "Shield",
                "level": 1,
                "action_type": "utility",
                "action_cost": "reaction",
                "target_mode": "self",
            }
        ],
        resources={"spell_slots": {"1": 4, "2": 3, "3": 2}},
    )
    enemies = [build_enemy(enemy_id="dummy", name="Dummy", hp=200, ac=8, to_hit=0, damage="1")]
    scenario_path = _setup_env(
        tmp_path / "chr15_illegal_shield_action",
        party=[wizard],
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
        "party_strategy": IllegalShieldAsMainActionStrategy(),
        "enemy_strategy": BaseStrategy(),
    }

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        run_simulation(loaded, db, {}, registry, trials=1, seed=43, run_id="chr15_illegal_shield")

    assert exc_info.value.code == "illegal_action"
    assert exc_info.value.actor_id == "wizard_5"
    assert exc_info.value.field == "action.action_name"
