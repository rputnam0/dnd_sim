from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dnd_sim.io import (
    EnemyConfig,
    build_run_dir,
    default_results_dir,
    load_custom_simulation_runner,
    load_scenario,
    load_strategy_registry,
)

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_PATH = (
    ROOT / "river_line" / "encounters" / "ley_heart" / "scenarios" / "ley_heart_phase_1.json"
)


def test_load_valid_scenario() -> None:
    loaded = load_scenario(SCENARIO_PATH)
    assert loaded.config.ruleset == "5e-2014"
    assert loaded.config.party
    assert set(loaded.enemies.keys()) == {"past_pylon", "present_pylon", "future_pylon"}


def test_invalid_scenario_schema_has_path_in_error(tmp_path: Path) -> None:
    payload = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    payload["party"] = "not-a-list"

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        load_scenario(invalid_path)

    message = str(exc.value)
    assert "Invalid scenario schema" in message
    assert str(invalid_path) in message


def test_missing_strategy_module_fails_before_simulation(tmp_path: Path) -> None:
    payload = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    payload["strategy_modules"].append(
        {
            "name": "bad_strategy",
            "source": "encounter",
            "module": "missing_module",
            "class_name": "MissingClass",
        }
    )

    base = tmp_path / "encounters" / "x"
    (base / "scenarios").mkdir(parents=True, exist_ok=True)
    (base / "enemies").mkdir(parents=True, exist_ok=True)

    for enemy_id in payload["enemies"]:
        src = ROOT / "river_line" / "encounters" / "ley_heart" / "enemies" / f"{enemy_id}.json"
        (base / "enemies" / f"{enemy_id}.json").write_text(src.read_text(encoding="utf-8"))

    scenario_path = base / "scenarios" / "broken.json"
    scenario_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_scenario(scenario_path)
    with pytest.raises(ValueError) as exc:
        load_strategy_registry(loaded)

    assert "Strategy module file not found" in str(exc.value)


def test_encounter_branch_target_index_must_be_within_encounter_bounds(tmp_path: Path) -> None:
    payload = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    payload["enemies"] = []
    payload["encounters"] = [
        {"enemies": ["past_pylon"]},
        {"enemies": ["present_pylon"], "branches": {"party": 99}},
    ]

    base = tmp_path / "encounters" / "x"
    (base / "scenarios").mkdir(parents=True, exist_ok=True)
    (base / "enemies").mkdir(parents=True, exist_ok=True)

    for enemy_id in ("past_pylon", "present_pylon"):
        src = ROOT / "river_line" / "encounters" / "ley_heart" / "enemies" / f"{enemy_id}.json"
        (base / "enemies" / f"{enemy_id}.json").write_text(src.read_text(encoding="utf-8"))

    scenario_path = base / "scenarios" / "invalid_branch_target.json"
    scenario_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        load_scenario(scenario_path)

    message = str(exc.value)
    assert "Invalid scenario schema" in message
    assert "Encounter branch target index out of bounds" in message


def test_long_rest_after_is_loaded_from_encounter_schema(tmp_path: Path) -> None:
    payload = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    payload["enemies"] = []
    payload["encounters"] = [{"enemies": ["past_pylon"], "long_rest_after": True}]

    base = tmp_path / "encounters" / "x"
    (base / "scenarios").mkdir(parents=True, exist_ok=True)
    (base / "enemies").mkdir(parents=True, exist_ok=True)

    src = ROOT / "river_line" / "encounters" / "ley_heart" / "enemies" / "past_pylon.json"
    (base / "enemies" / "past_pylon.json").write_text(src.read_text(encoding="utf-8"))

    scenario_path = base / "scenarios" / "long_rest_after.json"
    scenario_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_scenario(scenario_path)
    assert loaded.config.encounters[0].long_rest_after is True
    assert loaded.config.encounters[0].short_rest_after is False


def test_encounter_cannot_set_both_short_and_long_rest_after(tmp_path: Path) -> None:
    payload = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    payload["enemies"] = []
    payload["encounters"] = [
        {"enemies": ["past_pylon"], "short_rest_after": True, "long_rest_after": True}
    ]

    base = tmp_path / "encounters" / "x"
    (base / "scenarios").mkdir(parents=True, exist_ok=True)
    (base / "enemies").mkdir(parents=True, exist_ok=True)

    src = ROOT / "river_line" / "encounters" / "ley_heart" / "enemies" / "past_pylon.json"
    (base / "enemies" / "past_pylon.json").write_text(src.read_text(encoding="utf-8"))

    scenario_path = base / "scenarios" / "invalid_rest_flags.json"
    scenario_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        load_scenario(scenario_path)

    message = str(exc.value)
    assert "Invalid scenario schema" in message
    assert "short_rest_after and long_rest_after" in message


def test_default_results_dir_and_descriptive_folder_name(tmp_path: Path) -> None:
    results_root = default_results_dir()
    assert results_root.as_posix().endswith("/river_line/results")

    run_dir = build_run_dir(tmp_path, "Ley Heart Phase 1 Focus Fire")
    assert run_dir.parent == tmp_path
    assert "ley_heart_phase_1_focus_fire" in run_dir.name
    assert (run_dir / "plots").exists()


def test_load_custom_simulation_runner() -> None:
    loaded = load_scenario(SCENARIO_PATH)
    runner = load_custom_simulation_runner(loaded)
    assert callable(runner)


def _minimal_enemy_payload() -> dict[str, object]:
    return {
        "identity": {"enemy_id": "validator_enemy", "name": "Validator Enemy", "team": "enemy"},
        "stat_block": {
            "max_hp": 30,
            "ac": 13,
            "initiative_mod": 1,
            "save_mods": {"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        },
        "actions": [{"name": "basic", "action_type": "attack", "to_hit": 4, "damage": "1d8+2"}],
        "bonus_actions": [],
        "reactions": [],
        "legendary_actions": [],
        "lair_actions": [],
        "resources": {},
        "damage_resistances": [],
        "damage_immunities": [],
        "damage_vulnerabilities": [],
        "condition_immunities": [],
        "script_hooks": {},
        "traits": [],
    }


def test_enemy_schema_rejects_invalid_recharge_format() -> None:
    payload = _minimal_enemy_payload()
    actions = list(payload["actions"])  # type: ignore[index]
    actions[0] = dict(actions[0], recharge="Recharge seven")
    payload["actions"] = actions

    with pytest.raises(ValidationError):
        EnemyConfig.model_validate(payload)


def test_enemy_schema_rejects_unknown_innate_spell_reference() -> None:
    payload = _minimal_enemy_payload()
    payload["innate_spellcasting"] = [{"spell": "Not A Real Spell", "max_uses": 1}]

    with pytest.raises(ValidationError):
        EnemyConfig.model_validate(payload)


def test_scenario_schema_accepts_first_class_stealth_and_interactable_payloads(
    tmp_path: Path,
) -> None:
    payload = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    payload["stealth_actors"] = [
        {
            "actor_id": "hero_rogue",
            "team": "party",
            "hidden": True,
            "stealth_total": 16,
            "detected_by": [],
            "surprised": False,
        }
    ]
    payload["interactables"] = [
        {
            "object_id": "locked_chest_a",
            "kind": "container",
            "discovered": True,
            "locked": True,
            "unlock_dc": 14,
            "contents": ["potion_healing"],
        }
    ]
    payload["interaction_actions"] = [
        {
            "action": "unlock",
            "actor_id": "hero_rogue",
            "object_id": "locked_chest_a",
            "check_total": 17,
        }
    ]

    base = tmp_path / "encounters" / "x"
    (base / "scenarios").mkdir(parents=True, exist_ok=True)
    (base / "enemies").mkdir(parents=True, exist_ok=True)

    for enemy_id in payload["enemies"]:
        src = ROOT / "river_line" / "encounters" / "ley_heart" / "enemies" / f"{enemy_id}.json"
        (base / "enemies" / f"{enemy_id}.json").write_text(src.read_text(encoding="utf-8"))

    scenario_path = base / "scenarios" / "stealth_interactable_schema.json"
    scenario_path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_scenario(scenario_path)

    assert loaded.config.stealth_actors[0].actor_id == "hero_rogue"
    assert loaded.config.interactables[0].object_id == "locked_chest_a"
    assert loaded.config.interaction_actions[0].action == "unlock"


def test_scenario_schema_rejects_interactable_with_open_and_locked_state(tmp_path: Path) -> None:
    payload = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    payload["interactables"] = [
        {
            "object_id": "bad_chest",
            "kind": "container",
            "open": True,
            "locked": True,
        }
    ]

    base = tmp_path / "encounters" / "x"
    (base / "scenarios").mkdir(parents=True, exist_ok=True)
    (base / "enemies").mkdir(parents=True, exist_ok=True)

    for enemy_id in payload["enemies"]:
        src = ROOT / "river_line" / "encounters" / "ley_heart" / "enemies" / f"{enemy_id}.json"
        (base / "enemies" / f"{enemy_id}.json").write_text(src.read_text(encoding="utf-8"))

    scenario_path = base / "scenarios" / "invalid_interactable_state.json"
    scenario_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        load_scenario(scenario_path)

    assert "Invalid scenario schema" in str(exc.value)
    assert "open and locked" in str(exc.value)
