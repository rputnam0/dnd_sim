from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from pydantic import ValidationError

from dnd_sim.engine import (
    _execute_action,
    _reorder_initiative_for_construct_companions,
    run_simulation,
)
from dnd_sim.io import ActionConfig, load_character_db, load_scenario, load_strategy_registry
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.strategy_api import BaseStrategy, DeclaredAction, TargetRef, TurnDeclaration
from tests.helpers import build_character, build_enemy, write_json


def _actor(actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=30,
        hp=30,
        temp_hp=0,
        ac=12,
        initiative_mod=1,
        str_mod=0,
        dex_mod=1,
        con_mod=0,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 0, "dex": 1, "con": 0, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def _trackers(
    *actors: ActorRuntimeState,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    return (
        {actor.actor_id: 0 for actor in actors},
        {actor.actor_id: 0 for actor in actors},
        {actor.actor_id: 0 for actor in actors},
        {actor.actor_id: {} for actor in actors},
    )


class _ControlledSummonStrategy(BaseStrategy):
    def __init__(self, *, use_command: bool) -> None:
        self._use_command = use_command

    def declare_turn(self, actor, state):
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()
        enemy_id = enemies[0].actor_id

        if actor.actor_id == "hero":
            bonus = DeclaredAction(action_name="command_allies") if self._use_command else None
            if "hero_wolf" not in state.actors:
                return TurnDeclaration(
                    action=DeclaredAction(action_name="summon_wolf"),
                    bonus_action=bonus,
                )
            return TurnDeclaration(
                action=DeclaredAction(
                    action_name="basic",
                    targets=[TargetRef(actor_id=enemy_id)],
                ),
                bonus_action=bonus,
            )

        if actor.actor_id == "hero_wolf":
            return TurnDeclaration(
                action=DeclaredAction(
                    action_name="hero_wolf_attack",
                    targets=[TargetRef(actor_id=enemy_id)],
                )
            )
        return None


def _setup_env(
    tmp_path: Path,
    *,
    party: list[dict],
    enemies: list[dict],
) -> Path:
    db_dir = tmp_path / "db" / "characters"
    db_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        db_dir / "index.json",
        {
            "characters": [
                {
                    "character_id": row["character_id"],
                    "name": row["name"],
                    "class_level": row["class_level"],
                    "source_pdf": "fixture.pdf",
                }
                for row in party
            ]
        },
    )
    for character in party:
        write_json(db_dir / f"{character['character_id']}.json", character)

    encounter_dir = tmp_path / "encounters" / "fixture"
    enemy_dir = encounter_dir / "enemies"
    scenario_dir = encounter_dir / "scenarios"
    enemy_dir.mkdir(parents=True, exist_ok=True)
    scenario_dir.mkdir(parents=True, exist_ok=True)
    for enemy in enemies:
        write_json(enemy_dir / f"{enemy['identity']['enemy_id']}.json", enemy)

    scenario = {
        "scenario_id": "com10_fixture",
        "encounter_id": "fixture",
        "ruleset": "5e-2014",
        "character_db_dir": str(db_dir),
        "party": [character["character_id"] for character in party],
        "enemies": [enemy["identity"]["enemy_id"] for enemy in enemies],
        "initiative_mode": "individual",
        "battlefield": {},
        "termination_rules": {
            "party_defeat": "all_unconscious_or_dead",
            "enemy_defeat": "all_dead",
            "max_rounds": 5,
        },
        "strategy_modules": [
            {
                "name": "boss_highest_threat_target",
                "source": "builtin",
                "class_name": "BossHighestThreatTargetStrategy",
            }
        ],
        "resource_policy": {
            "mode": "combat_and_utility",
            "burst_round_threshold": 3,
        },
        "assumption_overrides": {
            "party_strategy": "party_no_command",
            "enemy_strategy": "boss_highest_threat_target",
        },
    }
    scenario_path = scenario_dir / "scenario.json"
    scenario_path.write_text(json.dumps(scenario, indent=2), encoding="utf-8")
    return scenario_path


def test_com10_reorders_controlled_allies_after_owner() -> None:
    owner = _actor("owner", "party")
    controlled = _actor("controlled", "party")
    enemy = _actor("enemy", "enemy")

    controlled.companion_owner_id = owner.actor_id
    controlled.requires_command = True

    actors = {
        owner.actor_id: owner,
        controlled.actor_id: controlled,
        enemy.actor_id: enemy,
    }
    order = [controlled.actor_id, enemy.actor_id, owner.actor_id]

    assert _reorder_initiative_for_construct_companions(order, actors) == [
        enemy.actor_id,
        owner.actor_id,
        controlled.actor_id,
    ]


def test_com10_command_effect_only_applies_to_owned_allies() -> None:
    controller = _actor("controller", "party")
    owned = _actor("owned", "party")
    foreign = _actor("foreign", "party")

    owned.companion_owner_id = controller.actor_id
    owned.requires_command = True
    foreign.companion_owner_id = "someone_else"
    foreign.requires_command = True

    action = ActionDefinition(
        name="command_allies",
        action_type="utility",
        action_cost="bonus",
        target_mode="all_allies",
        effects=[{"effect_type": "command_allied", "target": "target"}],
    )

    actors = {
        controller.actor_id: controller,
        owned.actor_id: owned,
        foreign.actor_id: foreign,
    }
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(
        controller, owned, foreign
    )

    _execute_action(
        rng=random.Random(3),
        actor=controller,
        action=action,
        targets=[owned, foreign],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert owned.commanded_this_round is True
    assert foreign.commanded_this_round is False


def test_com10_controlled_summon_command_flow_and_determinism(tmp_path: Path) -> None:
    hero = build_character(
        character_id="hero",
        name="Hero",
        max_hp=36,
        ac=15,
        to_hit=5,
        damage="1d6+2",
    )
    hero["ability_scores"]["dex"] = 10
    hero["save_mods"]["dex"] = 0
    hero["spells"] = [
        {
            "name": "summon_wolf",
            "level": 0,
            "action_type": "utility",
            "action_cost": "action",
            "target_mode": "self",
            "mechanics": [
                {
                    "effect_type": "summon",
                    "actor_id": "hero_wolf",
                    "name": "Hero Wolf",
                    "max_hp": 18,
                    "ac": 13,
                    "to_hit": 7,
                    "damage": "1d8+3",
                    "damage_type": "piercing",
                    "requires_command": True,
                    "controller": "source",
                }
            ],
        },
        {
            "name": "command_allies",
            "level": 0,
            "action_type": "utility",
            "action_cost": "bonus",
            "target_mode": "all_allies",
            "mechanics": [{"effect_type": "command_allied", "target": "target"}],
        },
    ]
    enemy = build_enemy(
        enemy_id="ogre",
        name="Ogre",
        hp=140,
        ac=12,
        to_hit=2,
        damage="1d4",
    )

    scenario_path = _setup_env(tmp_path, party=[hero], enemies=[enemy])
    loaded = load_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    registry["party_no_command"] = _ControlledSummonStrategy(use_command=False)
    registry["party_with_command"] = _ControlledSummonStrategy(use_command=True)
    db = load_character_db(Path(loaded.config.character_db_dir))

    no_command = run_simulation(
        loaded,
        db,
        traits_db={},
        strategy_registry=registry,
        trials=1,
        seed=31,
        run_id="no_command",
    ).summary.to_dict()

    loaded.config.assumption_overrides["party_strategy"] = "party_with_command"
    with_command = run_simulation(
        loaded,
        db,
        traits_db={},
        strategy_registry=registry,
        trials=1,
        seed=31,
        run_id="with_command",
    ).summary.to_dict()
    with_command_repeat = run_simulation(
        loaded,
        db,
        traits_db={},
        strategy_registry=registry,
        trials=1,
        seed=31,
        run_id="with_command_repeat",
    ).summary.to_dict()

    assert no_command["per_actor_damage_dealt"]["hero_wolf"]["mean"] == 0.0
    assert with_command["per_actor_damage_dealt"]["hero_wolf"]["mean"] > 0.0

    with_command.pop("run_id", None)
    with_command_repeat.pop("run_id", None)
    assert with_command == with_command_repeat


def test_com10_action_schema_accepts_summon_command_and_mount_effects() -> None:
    action = ActionConfig.model_validate(
        {
            "name": "coordinated_call",
            "action_type": "utility",
            "action_cost": "action",
            "target_mode": "self",
            "effects": [
                {
                    "effect_type": "summon",
                    "target": "source",
                    "actor_id": "spirit_wolf",
                    "name": "Spirit Wolf",
                    "max_hp": 20,
                    "ac": 13,
                },
                {"effect_type": "command_allied", "target": "target"},
                {"effect_type": "mount", "target": "target"},
            ],
        }
    )

    assert [effect.effect_type for effect in action.effects] == [
        "summon",
        "command_allied",
        "mount",
    ]


def test_com10_summon_effect_schema_requires_actor_id_or_name() -> None:
    with pytest.raises(ValidationError, match="actor_id or name"):
        ActionConfig.model_validate(
            {
                "name": "bad_summon",
                "action_type": "utility",
                "action_cost": "action",
                "target_mode": "self",
                "effects": [{"effect_type": "summon", "target": "source"}],
            }
        )
