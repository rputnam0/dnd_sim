from __future__ import annotations

import json
from pathlib import Path

import pytest

from dnd_sim.engine import TurnDeclarationValidationError, run_simulation
from dnd_sim.engine_runtime import (
    _action_available,
    _build_actor_from_character,
    _execute_action,
    _spend_action_resource_cost,
    long_rest,
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


class WildShapeTurnStrategy(BaseStrategy):
    def declare_turn(self, actor, _state):
        return TurnDeclaration(
            action=DeclaredAction(action_name="wild_shape"),
            bonus_action=DeclaredAction(action_name="wild_shape_revert"),
        )


class IllegalWildShapeRevertStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()
        return TurnDeclaration(
            action=DeclaredAction(
                action_name="basic",
                targets=[TargetRef(actor_id=enemies[0].actor_id)],
            ),
            bonus_action=DeclaredAction(action_name="wild_shape_revert"),
        )


def _druid_character(
    *,
    level: int,
    traits: list[str] | None = None,
    class_level: str | None = None,
    class_levels: dict[str, int] | None = None,
    resources: dict | None = None,
    current_resources: dict | None = None,
) -> dict:
    payload: dict = {
        "character_id": f"druid_{level}",
        "name": f"Druid {level}",
        "class_level": class_level or f"Druid {level}",
        "max_hp": 42,
        "ac": 14,
        "speed_ft": 30,
        "ability_scores": {
            "str": 10,
            "dex": 14,
            "con": 14,
            "int": 10,
            "wis": 18,
            "cha": 12,
        },
        "save_mods": {"str": 0, "dex": 2, "con": 2, "int": 0, "wis": 7, "cha": 1},
        "skill_mods": {},
        "attacks": [
            {
                "name": "Quarterstaff",
                "to_hit": 6,
                "damage": "1d6+2",
                "damage_type": "bludgeoning",
            }
        ],
        "resources": resources or {},
        "traits": list(traits or []),
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }
    if class_levels is not None:
        payload["class_levels"] = dict(class_levels)
    if current_resources is not None:
        payload["current_resources"] = current_resources
    return with_class_levels(payload)


def _actor(actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=30,
        hp=30,
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


def test_build_actor_infers_druid_package_traits_resources_and_wild_shape_actions() -> None:
    character = _druid_character(level=18, class_level="Druid 2 / Wizard 16")

    actor = _build_actor_from_character(character, traits_db={})
    by_name = {action.name: action for action in actor.actions}

    assert actor.class_levels == {"druid": 2, "wizard": 16}
    assert {"druidic", "spellcasting", "wild shape"}.issubset(actor.traits)
    assert actor.max_resources["wild_shape"] == 2
    assert actor.resources["wild_shape"] == 2
    assert by_name["wild_shape"].action_cost == "action"
    assert by_name["wild_shape"].resource_cost == {"wild_shape": 1}
    assert by_name["wild_shape_revert"].action_cost == "bonus"


def test_wild_shape_actions_not_built_when_explicit_class_levels_exclude_druid() -> None:
    character = _druid_character(
        level=18,
        class_level="Druid 2 / Wizard 16",
        class_levels={"wizard": 18},
        traits=["wild shape"],
    )

    actor = _build_actor_from_character(character, traits_db={})
    action_names = {action.name for action in actor.actions}

    assert actor.class_levels == {"wizard": 18}
    assert "wild shape" in actor.traits
    assert "wild_shape" not in action_names
    assert "wild_shape_revert" not in action_names
    assert "wild_shape" not in actor.max_resources
    assert "wild_shape" not in actor.resources


def test_wild_shape_resource_lifecycle_and_revert_legality() -> None:
    druid = _build_actor_from_character(_druid_character(level=2), traits_db={})
    ally = _actor("ally", "party")
    actors = {druid.actor_id: druid, ally.actor_id: ally}
    resources_spent = {druid.actor_id: {}, ally.actor_id: {}}

    wild_shape = next(action for action in druid.actions if action.name == "wild_shape")
    revert = next(action for action in druid.actions if action.name == "wild_shape_revert")

    assert _action_available(druid, revert) is False

    assert _spend_action_resource_cost(druid, wild_shape, resources_spent)
    _execute_action(
        rng=FixedRng([]),
        actor=druid,
        action=wild_shape,
        targets=[druid],
        actors=actors,
        damage_dealt={druid.actor_id: 0, ally.actor_id: 0},
        damage_taken={druid.actor_id: 0, ally.actor_id: 0},
        threat_scores={druid.actor_id: 0, ally.actor_id: 0},
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert druid.resources["wild_shape"] == 1
    assert resources_spent[druid.actor_id]["wild_shape"] == 1
    assert "wild_shaped" in druid.conditions
    assert _action_available(druid, revert) is True

    _execute_action(
        rng=FixedRng([]),
        actor=druid,
        action=revert,
        targets=[druid],
        actors=actors,
        damage_dealt={druid.actor_id: 0, ally.actor_id: 0},
        damage_taken={druid.actor_id: 0, ally.actor_id: 0},
        threat_scores={druid.actor_id: 0, ally.actor_id: 0},
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert "wild_shaped" not in druid.conditions

    short_rest(druid)
    assert druid.resources["wild_shape"] == 2

    _spend_action_resource_cost(druid, wild_shape, resources_spent)
    assert druid.resources["wild_shape"] == 1

    long_rest(druid)
    assert druid.resources["wild_shape"] == 2


def test_chr07_integration_wild_shape_spend_is_deterministic_across_short_rest(
    tmp_path: Path,
) -> None:
    druid = _druid_character(level=2)
    skeleton_a = build_enemy(
        enemy_id="skeleton_a",
        name="Skeleton A",
        hp=25,
        ac=11,
        to_hit=2,
        damage="1",
    )
    skeleton_b = build_enemy(
        enemy_id="skeleton_b",
        name="Skeleton B",
        hp=25,
        ac=11,
        to_hit=2,
        damage="1",
    )

    scenario_path = _setup_env(
        tmp_path / "chr07_wild_shape",
        party=[druid],
        enemies=[skeleton_a, skeleton_b],
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
        max_rounds=1,
    )
    raw = json.loads(scenario_path.read_text(encoding="utf-8"))
    raw["encounters"] = [
        {"enemies": ["skeleton_a"], "short_rest_after": True},
        {"enemies": ["skeleton_b"], "short_rest_after": False},
    ]
    raw["enemies"] = []
    scenario_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = {
        "party_strategy": WildShapeTurnStrategy(),
        "enemy_strategy": BaseStrategy(),
    }

    run_a = run_simulation(loaded, db, {}, registry, trials=1, seed=73, run_id="chr07_a")
    run_b = run_simulation(loaded, db, {}, registry, trials=1, seed=73, run_id="chr07_b")

    trial = run_a.trial_results[0]
    assert trial.resources_spent["druid_2"].get("wild_shape", 0) == 2
    assert trial.state_snapshots[-1]["party"]["druid_2"]["resources"]["wild_shape"] == 1
    assert "wild_shaped" not in trial.state_snapshots[-1]["party"]["druid_2"]["conditions"]

    summary_a = run_a.summary.to_dict()
    summary_b = run_b.summary.to_dict()
    summary_a.pop("run_id", None)
    summary_b.pop("run_id", None)
    assert summary_a == summary_b


def test_declared_wild_shape_revert_before_transform_is_rejected(tmp_path: Path) -> None:
    druid = _druid_character(level=2)
    enemy = build_enemy(enemy_id="dummy", name="Dummy", hp=50, ac=8, to_hit=0, damage="1")

    scenario_path = _setup_env(
        tmp_path / "chr07_wild_shape_illegal",
        party=[druid],
        enemies=[enemy],
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
        max_rounds=1,
    )
    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = {
        "party_strategy": IllegalWildShapeRevertStrategy(),
        "enemy_strategy": BaseStrategy(),
    }

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        run_simulation(loaded, db, {}, registry, trials=1, seed=79, run_id="chr07_illegal")

    assert exc_info.value.code == "unavailable_action"
    assert exc_info.value.actor_id == "druid_2"
    assert exc_info.value.field == "bonus_action.action_name"
