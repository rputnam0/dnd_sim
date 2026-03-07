from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from dnd_sim.capability_manifest import build_spell_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

SPELLS_DIR = Path("db/rules/2014/spells")
OWNED_SPELL_IDS = (
    "spell:wall_of_light",
    "spell:wall_of_sand",
    "spell:wall_of_stone",
    "spell:wall_of_thorns",
    "spell:wall_of_water",
    "spell:warding_wind",
    "spell:water_breathing",
    "spell:watery_sphere",
    "spell:whirlwind",
    "spell:wind_walk",
)


def _owned_spell_path(content_id: str) -> Path:
    slug = content_id.split(":", 1)[1]
    assert slug.isascii()
    return SPELLS_DIR / f"{slug}.json"


OWNED_SPELL_PATHS = {content_id: _owned_spell_path(content_id) for content_id in OWNED_SPELL_IDS}


def _load_payload(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _load_owned_payloads() -> list[dict[str, object]]:
    return [_load_payload(path) for path in OWNED_SPELL_PATHS.values()]


def _find_effect(
    payload: dict[str, object],
    effect_type: str,
    *,
    predicate: Callable[[dict[str, object]], bool] | None = None,
) -> dict[str, object]:
    mechanics = payload.get("mechanics", [])
    assert isinstance(mechanics, list)
    for row in mechanics:
        if not isinstance(row, dict):
            continue
        if row.get("effect_type") != effect_type:
            continue
        if predicate is None or predicate(row):
            return row
    raise AssertionError(f"missing {effect_type!r} mechanic in {payload.get('name')!r}")


def test_j2_f_owned_spell_records_are_supported() -> None:
    manifest = build_spell_capability_manifest(spell_payloads=_load_owned_payloads())
    by_id = {record.content_id: record for record in manifest.records}

    assert set(by_id) == set(OWNED_SPELL_IDS)
    for content_id in OWNED_SPELL_IDS:
        record = by_id[content_id]
        assert record.runtime_hook_family == "effect"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.schema_valid is True
        assert record.states.executable is True
        assert record.states.tested is True
        assert record.states.unsupported_reason is None


def test_j2_f_owned_spell_mechanics_are_schema_valid() -> None:
    for path in OWNED_SPELL_PATHS.values():
        payload = _load_payload(path)
        assert validate_rule_mechanics_payload(kind="spell", payload=payload) == []


def test_j2_f_owned_spell_paths_are_ascii_and_stable() -> None:
    for content_id in OWNED_SPELL_IDS:
        path = OWNED_SPELL_PATHS[content_id]
        assert path.name.isascii()
        assert path.exists()


def test_j2_f_reviewed_spell_rows_match_expected_canonical_shapes() -> None:
    wall_of_light = _load_payload(OWNED_SPELL_PATHS["spell:wall_of_light"])
    light_hazard = _find_effect(wall_of_light, "hazard")
    light_attack = _find_effect(wall_of_light, "ranged_spell_attack")
    light_aoe = _find_effect(wall_of_light, "aoe")
    assert light_hazard["hazard_type"] == "wall_of_light"
    assert light_hazard["bright_light_radius_ft"] == 120
    assert light_hazard["dim_light_radius_ft"] == 240
    assert light_hazard["beam_action_range_ft"] == 60
    assert light_hazard["on_cast"][0]["damage"] == "4d8"
    assert light_hazard["on_cast"][1]["condition"] == "blinded"
    assert light_attack["damage_type"] == "radiant"
    assert light_aoe["thickness_ft"] == 5

    wall_of_sand = _load_payload(OWNED_SPELL_PATHS["spell:wall_of_sand"])
    sand_hazard = _find_effect(wall_of_sand, "hazard")
    assert sand_hazard["hazard_type"] == "wall_of_sand"
    assert sand_hazard["extra_movement_cost_multiplier"] == 3
    assert sand_hazard["applies_conditions"] == ["blinded"]

    wall_of_stone = _load_payload(OWNED_SPELL_PATHS["spell:wall_of_stone"])
    stone_hazard = _find_effect(wall_of_stone, "hazard")
    stone_aoe = _find_effect(wall_of_stone, "aoe")
    assert stone_hazard["hazard_type"] == "wall_of_stone"
    assert stone_hazard["panel_ac"] == 15
    assert stone_hazard["panel_hp_per_inch"] == 30
    assert stone_hazard["permanent_on_full_duration"] is True
    assert stone_aoe["panel_count"] == 10

    wall_of_thorns = _load_payload(OWNED_SPELL_PATHS["spell:wall_of_thorns"])
    thorns_hazard = _find_effect(wall_of_thorns, "hazard")
    assert thorns_hazard["hazard_type"] == "wall_of_thorns"
    assert thorns_hazard["extra_movement_cost_multiplier"] == 4
    assert thorns_hazard["single_damage_trigger_per_turn"] is True
    assert thorns_hazard["on_cast"][0]["damage_type"] == "piercing"
    assert thorns_hazard["on_enter"][0]["damage_type"] == "slashing"

    wall_of_water = _load_payload(OWNED_SPELL_PATHS["spell:wall_of_water"])
    water_hazard = _find_effect(wall_of_water, "hazard")
    assert water_hazard["hazard_type"] == "wall_of_water"
    assert water_hazard["difficult_terrain"] is True
    assert water_hazard["fire_damage_through_multiplier"] == 0.5
    assert water_hazard["frozen_section_hp"] == 15

    warding_wind = _load_payload(OWNED_SPELL_PATHS["spell:warding_wind"])
    warding_hazard = _find_effect(warding_wind, "hazard")
    assert warding_hazard["hazard_type"] == "warding_wind"
    assert warding_hazard["moves_with_source"] is True
    assert warding_hazard["ranged_attacks_through_disadvantage"] is True
    assert warding_hazard["applies_conditions"] == ["deafened"]

    water_breathing = _load_payload(OWNED_SPELL_PATHS["spell:water_breathing"])
    breathing_condition = _find_effect(water_breathing, "apply_condition")
    assert breathing_condition["condition"] == "water_breathing"
    assert breathing_condition["max_targets"] == 10
    assert breathing_condition["retain_normal_respiration"] is True

    watery_sphere = _load_payload(OWNED_SPELL_PATHS["spell:watery_sphere"])
    sphere_hazard = _find_effect(watery_sphere, "hazard")
    sphere_move = _find_effect(watery_sphere, "forced_movement")
    assert sphere_hazard["hazard_type"] == "watery_sphere"
    assert sphere_hazard["hover_height_ft"] == 10
    assert sphere_hazard["capacity_medium_creatures"] == 4
    assert sphere_hazard["on_enter"][0]["condition"] == "restrained"
    assert sphere_move["distance_ft"] == 30

    whirlwind = _load_payload(OWNED_SPELL_PATHS["spell:whirlwind"])
    whirlwind_hazard = _find_effect(whirlwind, "hazard")
    whirlwind_aoe = _find_effect(whirlwind, "aoe")
    assert whirlwind_hazard["hazard_type"] == "whirlwind"
    assert whirlwind_hazard["move_action_distance_ft"] == 30
    assert whirlwind_hazard["on_enter"][0]["damage"] == "10d6"
    assert whirlwind_hazard["on_enter"][1]["condition"] == "restrained"
    assert whirlwind_aoe["shape"] == "cylinder"

    wind_walk = _load_payload(OWNED_SPELL_PATHS["spell:wind_walk"])
    walk_condition = _find_effect(wind_walk, "apply_condition")
    assert walk_condition["condition"] == "wind_walk_cloud_form"
    assert walk_condition["fly_speed_ft"] == 300
    assert walk_condition["max_targets"] == 10
    assert walk_condition["safe_descent_ft_per_round"] == 60
