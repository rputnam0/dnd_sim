from __future__ import annotations

from pathlib import Path

import pytest

from dnd_sim.engine import TurnDeclarationValidationError, run_simulation
from dnd_sim.io import load_character_db, load_scenario, load_strategy_registry
from dnd_sim.strategy_api import BaseStrategy, DeclaredAction, TargetRef, TurnDeclaration
from tests.helpers import build_character, build_enemy
from tests.test_engine_integration import _setup_env


class LegalDeclaredAttackStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()
        target = enemies[0]
        return TurnDeclaration(
            action=DeclaredAction(
                action_name="basic",
                targets=[TargetRef(actor_id=target.actor_id)],
            )
        )


class InvalidDeclaredActionStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()
        target = enemies[0]
        return TurnDeclaration(
            action=DeclaredAction(
                action_name="does_not_exist",
                targets=[TargetRef(actor_id=target.actor_id)],
            )
        )


def _load_fixture(tmp_path: Path):
    scenario_path = _setup_env(
        tmp_path,
        party=[build_character("hero", "Hero", 28, 15, 7, "1d8+4")],
        enemies=[
            build_enemy(enemy_id="boss", name="Boss", hp=40, ac=13, to_hit=5, damage="1d10+3")
        ],
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
        max_rounds=2,
    )

    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    return loaded, db


def test_legal_turn_declaration_runs_through_engine_integration(tmp_path: Path) -> None:
    loaded, db = _load_fixture(tmp_path / "legal_turn")
    registry = load_strategy_registry(loaded)
    registry["party_strategy"] = LegalDeclaredAttackStrategy()
    registry["enemy_strategy"] = BaseStrategy()

    artifacts = run_simulation(
        loaded,
        db,
        {},
        registry,
        trials=1,
        seed=12,
        run_id="legal_turn_declaration",
    )

    assert len(artifacts.trial_results) == 1


def test_invalid_turn_declaration_surfaces_structured_legality_error(tmp_path: Path) -> None:
    loaded, db = _load_fixture(tmp_path / "invalid_turn")

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        run_simulation(
            loaded,
            db,
            {},
            {
                "party_strategy": InvalidDeclaredActionStrategy(),
                "enemy_strategy": BaseStrategy(),
            },
            trials=1,
            seed=13,
            run_id="invalid_turn_declaration",
        )

    assert exc_info.value.code == "unknown_action"
    assert exc_info.value.field == "action.action_name"
    assert exc_info.value.actor_id == "hero"
