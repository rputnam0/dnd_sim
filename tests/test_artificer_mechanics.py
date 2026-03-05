from __future__ import annotations

import json
import random
from pathlib import Path

from dnd_sim.engine import run_simulation
from dnd_sim.engine_runtime import _build_actor_from_character
from dnd_sim.io import load_character_db, load_scenario, load_strategy_registry
from dnd_sim.rules_2014 import run_concentration_check
from tests.helpers import build_character, build_enemy, write_json


def _setup_env(
    tmp_path: Path,
    *,
    party: list[dict],
    enemies: list[dict],
) -> Path:
    db_dir = tmp_path / "db" / "characters"
    db_dir.mkdir(parents=True, exist_ok=True)

    index = {
        "characters": [
            {
                "character_id": character["character_id"],
                "name": character["name"],
                "class_levels": character["class_levels"],
                "source_pdf": "fixture.pdf",
            }
            for character in party
        ]
    }
    write_json(db_dir / "index.json", index)
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
        "scenario_id": "fixture_scenario",
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
            "max_rounds": 10,
        },
        "strategy_modules": [
            {
                "name": "focus_fire_lowest_hp",
                "source": "builtin",
                "class_name": "FocusFireLowestHPStrategy",
            },
            {
                "name": "boss_highest_threat_target",
                "source": "builtin",
                "class_name": "BossHighestThreatTargetStrategy",
            },
        ],
        "resource_policy": {
            "mode": "combat_and_utility",
            "burst_round_threshold": 3,
        },
        "assumption_overrides": {
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
    }

    scenario_path = scenario_dir / "scenario.json"
    scenario_path.write_text(json.dumps(scenario, indent=2), encoding="utf-8")
    return scenario_path


def _artificer_fixture(*, level: int, traits: list[str]) -> dict:
    character = build_character(
        character_id="arti",
        name="Arti",
        max_hp=38,
        ac=16,
        to_hit=7,
        damage="1d8+4",
    )
    character["class_levels"] = {"artificer": level}
    character["ability_scores"]["int"] = 18
    character["traits"] = list(character["traits"]) + traits
    return character


def test_enhanced_defense_infusion_increases_ac() -> None:
    actor = _build_actor_from_character(
        _artificer_fixture(level=10, traits=["Enhanced Defense"]), traits_db={}
    )
    assert actor.ac == 18


def test_enhanced_weapon_infusion_increases_attack_roll_and_damage() -> None:
    actor = _build_actor_from_character(
        _artificer_fixture(level=8, traits=["Enhanced Weapon"]), traits_db={}
    )
    basic = next(action for action in actor.actions if action.name == "basic")
    assert basic.to_hit == 8
    assert basic.damage == "1d8+5"


def test_mind_sharpener_converts_failed_concentration_to_success() -> None:
    actor = _build_actor_from_character(
        _artificer_fixture(level=8, traits=["Mind Sharpener"]), traits_db={}
    )
    actor.concentrating = True

    success = run_concentration_check(random.Random(1), actor, damage_taken=22)

    assert success is True
    assert actor.resources["mind_sharpener_charges"] == 3


def test_steel_defender_companion_is_added_to_party_actor_roster(tmp_path: Path) -> None:
    artificer = _artificer_fixture(level=6, traits=["Battle Smith", "Steel Defender"])
    artificer["character_id"] = "smith"
    artificer["name"] = "Smith"
    artificer["traits"] = ["Battle Smith", "Steel Defender"]

    enemies = [
        build_enemy(
            enemy_id="dummy",
            name="Training Dummy",
            hp=40,
            ac=8,
            to_hit=2,
            damage="1d4",
        )
    ]
    scenario_path = _setup_env(tmp_path, party=[artificer], enemies=enemies)
    loaded = load_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    db = load_character_db(Path(loaded.config.character_db_dir))

    summary = run_simulation(
        loaded,
        db,
        traits_db={},
        strategy_registry=registry,
        trials=1,
        seed=13,
        run_id="artificer_companion",
    ).summary.to_dict()

    assert "smith__steel_defender" in summary["per_actor_damage_dealt"]
