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
from dnd_sim.io import load_character_db, load_runtime_scenario
from dnd_sim.models import ActionDefinition, ActorRuntimeState
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


class TurnUndeadDeclarationStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()
        return TurnDeclaration(
            action=DeclaredAction(
                action_name="turn_undead",
                targets=[TargetRef(actor_id=enemies[0].actor_id)],
            )
        )


def _cleric_character(
    *,
    level: int,
    traits: list[str],
    class_level: str | None = None,
    resources: dict | None = None,
) -> dict:
    return with_class_levels(
        {
            "character_id": f"cleric_{level}",
            "name": f"Cleric {level}",
            "class_level": class_level or f"Cleric {level}",
            "max_hp": 40,
            "ac": 16,
            "speed_ft": 30,
            "ability_scores": {
                "str": 10,
                "dex": 12,
                "con": 14,
                "int": 10,
                "wis": 18,
                "cha": 12,
            },
            "save_mods": {"str": 0, "dex": 1, "con": 2, "int": 0, "wis": 7, "cha": 1},
            "skill_mods": {},
            "attacks": [
                {"name": "Mace", "to_hit": 6, "damage": "1d6+2", "damage_type": "bludgeoning"}
            ],
            "resources": resources or {},
            "traits": traits,
            "raw_fields": [],
            "source": {"pdf_name": "fixture.pdf"},
        }
    )


def _actor(actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=40,
        hp=40,
        temp_hp=0,
        ac=15,
        initiative_mod=0,
        str_mod=2,
        dex_mod=1,
        con_mod=2,
        int_mod=0,
        wis_mod=4,
        cha_mod=1,
        save_mods={"str": 2, "dex": 1, "con": 2, "int": 0, "wis": 4, "cha": 1},
        actions=[],
    )


def _trackers(
    *actors: ActorRuntimeState,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    damage_dealt = {actor.actor_id: 0 for actor in actors}
    damage_taken = {actor.actor_id: 0 for actor in actors}
    threat_scores = {actor.actor_id: 0 for actor in actors}
    resources_spent = {actor.actor_id: {} for actor in actors}
    return damage_dealt, damage_taken, threat_scores, resources_spent


def test_build_actor_infers_channel_divinity_and_preserve_life_scaling_from_cleric_level() -> None:
    character = _cleric_character(
        level=18,
        class_level="Cleric 2 / Wizard 16",
        traits=["Turn Undead", "Preserve Life"],
    )

    actor = _build_actor_from_character(character, traits_db={})

    assert actor.class_levels == {"cleric": 2, "wizard": 16}
    assert actor.max_resources["channel_divinity"] == 1
    assert actor.resources["channel_divinity"] == 1
    preserve_life = next(action for action in actor.actions if action.name == "preserve_life")
    assert preserve_life.effects[0]["amount"] == "10"


def test_channel_divinity_lifecycle_spend_short_rest_and_long_rest_recovery() -> None:
    cleric = _build_actor_from_character(
        _cleric_character(level=2, traits=["Turn Undead"]),
        traits_db={},
    )
    undead = _actor("undead", "enemy")
    undead.traits = {"undead": {}}
    turn_undead = next(action for action in cleric.actions if action.name == "turn_undead")

    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(cleric, undead)
    actors = {cleric.actor_id: cleric, undead.actor_id: undead}

    assert _action_available(cleric, turn_undead) is True
    assert _spend_action_resource_cost(cleric, turn_undead, resources_spent)
    _execute_action(
        rng=FixedRng([3]),
        actor=cleric,
        action=turn_undead,
        targets=[undead],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert cleric.resources["channel_divinity"] == 0
    assert resources_spent[cleric.actor_id]["channel_divinity"] == 1
    assert _action_available(cleric, turn_undead) is False

    short_rest(cleric)
    assert cleric.resources["channel_divinity"] == 1
    assert _action_available(cleric, turn_undead) is True

    _spend_action_resource_cost(cleric, turn_undead, resources_spent)
    assert cleric.resources["channel_divinity"] == 0

    long_rest(cleric)
    assert cleric.resources["channel_divinity"] == 1


def test_war_gods_blessing_spends_reaction_and_channel_divinity_once() -> None:
    attacker = _actor("attacker", "party")
    ally_cleric = _actor("ally_cleric", "party")
    target = _actor("target", "enemy")
    target.ac = 15
    ally_cleric.position = (0.0, 0.0, 0.0)
    attacker.position = (0.0, 10.0, 0.0)
    target.position = (0.0, 15.0, 0.0)
    ally_cleric.traits = {"war god's blessing": {}}
    ally_cleric.resources = {"channel_divinity": 1}
    ally_cleric.max_resources = {"channel_divinity": 1}

    action = ActionDefinition(
        name="longsword",
        action_type="attack",
        to_hit=4,
        damage="1",
        damage_type="slashing",
    )
    actors = {
        attacker.actor_id: attacker,
        ally_cleric.actor_id: ally_cleric,
        target.actor_id: target,
    }
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(
        attacker, ally_cleric, target
    )

    _execute_action(
        rng=FixedRng([10, 1]),
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

    assert target.hp == 39
    assert ally_cleric.resources["channel_divinity"] == 0
    assert ally_cleric.reaction_available is False
    assert resources_spent[ally_cleric.actor_id]["channel_divinity"] == 1

    _execute_action(
        rng=FixedRng([10]),
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

    assert target.hp == 39
    assert resources_spent[ally_cleric.actor_id]["channel_divinity"] == 1


def test_chr06_integration_turn_undead_spends_across_short_rest_encounters_deterministically(
    tmp_path: Path,
) -> None:
    cleric = _cleric_character(level=2, traits=["Turn Undead"])
    skeleton_a = build_enemy(
        enemy_id="skeleton_a",
        name="Skeleton A",
        hp=30,
        ac=11,
        to_hit=2,
        damage="1",
    )
    skeleton_b = build_enemy(
        enemy_id="skeleton_b",
        name="Skeleton B",
        hp=30,
        ac=11,
        to_hit=2,
        damage="1",
    )
    skeleton_a["traits"] = ["undead"]
    skeleton_b["traits"] = ["undead"]

    scenario_path = _setup_env(
        tmp_path / "chr06_short_rest",
        party=[cleric],
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

    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = {"party_strategy": TurnUndeadDeclarationStrategy(), "enemy_strategy": BaseStrategy()}

    run_a = run_simulation(loaded, db, {}, registry, trials=1, seed=29, run_id="chr06_turn_a")
    run_b = run_simulation(loaded, db, {}, registry, trials=1, seed=29, run_id="chr06_turn_b")

    spent = run_a.trial_results[0].resources_spent["cleric_2"].get("channel_divinity", 0)
    assert spent == 2
    assert (
        run_a.trial_results[0].state_snapshots[-1]["party"]["cleric_2"]["resources"][
            "channel_divinity"
        ]
        == 0
    )

    summary_a = run_a.summary.to_dict()
    summary_b = run_b.summary.to_dict()
    summary_a.pop("run_id", None)
    summary_b.pop("run_id", None)
    assert summary_a == summary_b


def test_declared_turn_undead_rejected_when_target_is_not_undead(tmp_path: Path) -> None:
    cleric = _cleric_character(
        level=2,
        traits=["Turn Undead"],
        resources={"channel_divinity": {"max": 1}},
    )
    ogre = build_enemy(enemy_id="ogre", name="Ogre", hp=30, ac=11, to_hit=2, damage="1")

    scenario_path = _setup_env(
        tmp_path / "chr06_illegal_target",
        party=[cleric],
        enemies=[ogre],
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
        max_rounds=1,
    )
    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    registry = {"party_strategy": TurnUndeadDeclarationStrategy(), "enemy_strategy": BaseStrategy()}

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        run_simulation(loaded, db, {}, registry, trials=1, seed=41, run_id="chr06_illegal_target")

    assert exc_info.value.code == "no_legal_targets"
    assert exc_info.value.actor_id == "cleric_2"
    assert exc_info.value.field == "action.targets"
