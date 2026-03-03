from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from dnd_sim.engine import (
    _action_available,
    _build_actor_from_character,
    _execute_action,
    _spend_action_resource_cost,
    run_simulation,
    short_rest,
)
from dnd_sim.io import load_character_db, load_scenario, load_strategy_registry
from dnd_sim.models import ActorRuntimeState
from tests.helpers import build_enemy
from tests.test_engine_integration import _setup_env


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self.values:
            raise AssertionError("RNG exhausted")
        return self.values.pop(0)


def _warlock_character(
    *,
    level: int,
    traits: list[str],
    spells: list[dict[str, Any]],
    resources: dict[str, Any],
    class_level: str | None = None,
    class_levels: dict[str, int] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "character_id": f"warlock_{level}",
        "name": f"Warlock {level}",
        "class_level": f"Warlock {level}" if class_level is None else class_level,
        "max_hp": 38,
        "ac": 14,
        "speed_ft": 30,
        "ability_scores": {
            "str": 8,
            "dex": 14,
            "con": 14,
            "int": 12,
            "wis": 10,
            "cha": 18,
        },
        "save_mods": {"str": -1, "dex": 2, "con": 2, "int": 1, "wis": 0, "cha": 4},
        "skill_mods": {},
        "attacks": [],
        "spells": spells,
        "resources": resources,
        "traits": traits,
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }
    if class_levels is not None:
        payload["class_levels"] = dict(class_levels)
    return payload


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


def test_build_actor_infers_warlock_package_from_class_levels_payload() -> None:
    character = _warlock_character(
        level=13,
        class_level="",
        class_levels={"warlock": 13},
        traits=[],
        spells=[
            {
                "name": "Hunger of Hadar",
                "level": 3,
                "action_type": "save",
                "save_dc": 14,
                "damage": "2d6",
            },
            {
                "name": "Forcecage",
                "level": 7,
                "action_type": "utility",
                "target_mode": "single_enemy",
            },
        ],
        resources={"spell_slots": {"5": 3}},
    )

    actor = _build_actor_from_character(character, traits_db={})
    hunger = next(action for action in actor.actions if action.name == "Hunger of Hadar")
    forcecage = next(action for action in actor.actions if action.name == "Forcecage")

    assert {"pact magic", "eldritch invocations", "mystic arcanum"}.issubset(actor.traits)
    assert actor.max_resources["warlock_spell_slot_5"] == 3
    assert "spell_slot_5" not in actor.max_resources
    assert hunger.resource_cost == {"warlock_spell_slot_5": 1}
    assert "mystic_arcanum" in forcecage.tags
    assert forcecage.max_uses == 1


def test_pact_slot_short_rest_recovery_uses_warlock_level_from_class_levels_payload() -> None:
    character = _warlock_character(
        level=11,
        class_level="",
        class_levels={"warlock": 5, "fighter": 6},
        traits=[],
        spells=[
            {
                "name": "Hex",
                "level": 1,
                "action_type": "utility",
                "action_cost": "bonus",
                "target_mode": "self",
                "effects": [
                    {"effect_type": "apply_condition", "condition": "hexed", "target": "source"}
                ],
            }
        ],
        resources={"spell_slots": {"3": 2}},
    )

    actor = _build_actor_from_character(character, traits_db={})
    hex_action = next(action for action in actor.actions if action.name == "Hex")
    resources_spent = {actor.actor_id: {}}

    assert _spend_action_resource_cost(
        actor, hex_action, resources_spent, turn_token="1:warlock_11"
    )
    assert actor.resources["warlock_spell_slot_3"] == 1

    short_rest(actor)

    assert actor.resources["warlock_spell_slot_3"] == 2


def test_warlock_reaction_spell_rejected_for_invalid_timing_or_resource_sequence() -> None:
    character = _warlock_character(
        level=5,
        traits=[],
        spells=[
            {
                "name": "Hex",
                "level": 1,
                "action_type": "utility",
                "action_cost": "bonus",
                "target_mode": "self",
                "effects": [
                    {"effect_type": "apply_condition", "condition": "hexed", "target": "source"}
                ],
            },
            {
                "name": "Hellish Rebuke",
                "level": 1,
                "action_type": "attack",
                "action_cost": "reaction",
                "target_mode": "single_enemy",
                "to_hit": 8,
                "damage": "2d10",
                "damage_type": "fire",
            },
        ],
        resources={"spell_slots": {"3": 2}},
    )

    warlock = _build_actor_from_character(character, traits_db={})
    enemy = _enemy("orc")
    actors = {warlock.actor_id: warlock, enemy.actor_id: enemy}
    damage_dealt = {warlock.actor_id: 0, enemy.actor_id: 0}
    damage_taken = {warlock.actor_id: 0, enemy.actor_id: 0}
    threat_scores = {warlock.actor_id: 0, enemy.actor_id: 0}
    resources_spent = {warlock.actor_id: {}, enemy.actor_id: {}}

    hex_action = next(action for action in warlock.actions if action.name == "Hex")
    rebuke = next(action for action in warlock.actions if action.name == "Hellish Rebuke")

    assert _spend_action_resource_cost(
        warlock, hex_action, resources_spent, turn_token="1:warlock_5"
    )
    _execute_action(
        rng=FixedRng([5]),
        actor=warlock,
        action=hex_action,
        targets=[warlock],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:warlock_5",
    )

    assert _action_available(warlock, rebuke, turn_token="1:warlock_5") is False
    assert _action_available(warlock, rebuke, turn_token="1:orc") is True

    warlock.reaction_available = False
    assert _action_available(warlock, rebuke, turn_token="1:orc") is False

    warlock.reaction_available = True
    warlock.resources["warlock_spell_slot_3"] = 0
    assert _action_available(warlock, rebuke, turn_token="1:orc") is False


def test_chr14_integration_multiclass_warlock_slots_survive_scenario_build(
    tmp_path: Path,
) -> None:
    warlock = _warlock_character(
        level=11,
        class_level="",
        class_levels={"warlock": 5, "fighter": 6},
        traits=[],
        spells=[
            {
                "name": "Eldritch Blast",
                "level": 0,
                "action_type": "attack",
                "to_hit": 8,
                "damage": "1d10",
                "damage_type": "force",
            }
        ],
        resources={"spell_slots": {"3": 2}},
    )
    enemies = [build_enemy(enemy_id="dummy", name="Dummy", hp=250, ac=8, to_hit=0, damage="1")]
    scenario_path = _setup_env(
        tmp_path / "chr14_warlock_integration",
        party=[warlock],
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
    artifacts = run_simulation(
        loaded,
        db,
        {},
        registry,
        trials=1,
        seed=41,
        run_id="chr14_warlock_integration",
    )

    trial = artifacts.trial_results[0]
    snapshot = trial.state_snapshots[-1]["party"]["warlock_11"]["resources"]

    assert trial.rounds == 1
    assert trial.resources_spent["warlock_11"].get("warlock_spell_slot_3", 0) == 0
    assert snapshot["warlock_spell_slot_3"] == 2
    assert "spell_slot_3" not in snapshot
