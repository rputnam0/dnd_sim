from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from dnd_sim.capability_manifest import build_spell_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

SPELLS_DIR = Path("db/rules/2014/spells")
OWNED_SPELL_IDS = (
    "spell:storm_of_vengeance",
    "spell:storm_sphere",
    "spell:teleport",
    "spell:teleportation_circle",
    "spell:tiny_hut",
    "spell:true_strike_divination",
    "spell:vitriolic_sphere",
    "spell:wall_of_fire",
    "spell:wall_of_force",
    "spell:wall_of_ice",
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


def test_j2_e_owned_spell_records_are_supported() -> None:
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


def test_j2_e_owned_spell_mechanics_are_schema_valid() -> None:
    for path in OWNED_SPELL_PATHS.values():
        payload = _load_payload(path)
        assert validate_rule_mechanics_payload(kind="spell", payload=payload) == []


def test_j2_e_owned_spell_paths_are_ascii_and_stable() -> None:
    for content_id in OWNED_SPELL_IDS:
        path = OWNED_SPELL_PATHS[content_id]
        assert path.name.isascii()
        assert path.exists()


def test_j2_e_reviewed_spell_rows_match_expected_canonical_shapes() -> None:
    storm_of_vengeance = _load_payload(OWNED_SPELL_PATHS["spell:storm_of_vengeance"])
    vengeance_hazard = _find_effect(storm_of_vengeance, "hazard")
    vengeance_thunder = _find_effect(
        storm_of_vengeance,
        "damage",
        predicate=lambda row: row.get("damage_type") == "thunder",
    )
    vengeance_deafened = _find_effect(storm_of_vengeance, "apply_condition")
    vengeance_lightning = _find_effect(
        storm_of_vengeance,
        "damage",
        predicate=lambda row: row.get("damage_type") == "lightning",
    )
    vengeance_cold = _find_effect(
        storm_of_vengeance,
        "damage",
        predicate=lambda row: row.get("damage_type") == "cold",
    )
    assert vengeance_hazard["hazard_type"] == "storm_of_vengeance"
    assert vengeance_hazard["radius_ft"] == 360
    assert vengeance_hazard["duration_rounds"] == 10
    assert vengeance_hazard["concentration_linked"] is True
    assert vengeance_hazard["vertical_limit_ft"] == 5000
    assert vengeance_hazard["difficult_terrain_from_round"] == 5
    assert vengeance_hazard["obscures_vision_from_round"] == 5
    assert vengeance_hazard["ranged_weapon_attacks_impossible_from_round"] == 5
    assert vengeance_hazard["disperses_fog_from_round"] == 5
    assert vengeance_thunder["damage"] == "2d6"
    assert vengeance_thunder["save_ability"] == "con"
    assert vengeance_thunder["timing_round"] == 1
    assert vengeance_deafened["condition"] == "deafened"
    assert vengeance_deafened["apply_on"] == "save_fail"
    assert vengeance_deafened["duration_rounds"] == 50
    assert vengeance_lightning["damage"] == "10d6"
    assert vengeance_lightning["save_ability"] == "dex"
    assert vengeance_lightning["half_on_success"] is True
    assert vengeance_lightning["timing_round"] == 3
    assert vengeance_lightning["target_count"] == 6
    assert vengeance_cold["damage"] == "1d6"
    assert vengeance_cold["timing_round_start"] == 5
    assert vengeance_cold["timing_round_end"] == 10

    storm_sphere = _load_payload(OWNED_SPELL_PATHS["spell:storm_sphere"])
    sphere_hazard = _find_effect(storm_sphere, "hazard")
    sphere_attack = _find_effect(storm_sphere, "ranged_spell_attack")
    assert sphere_hazard["hazard_type"] == "storm_sphere"
    assert sphere_hazard["radius_ft"] == 20
    assert sphere_hazard["duration_rounds"] == 10
    assert sphere_hazard["concentration_linked"] is True
    assert sphere_hazard["difficult_terrain"] is True
    assert sphere_hazard["listening_perception_disadvantage_radius_ft"] == 30
    assert sphere_hazard["on_cast"][0]["damage"] == "2d6"
    assert sphere_hazard["on_cast"][0]["damage_type"] == "bludgeoning"
    assert sphere_hazard["on_cast"][0]["save_ability"] == "str"
    assert sphere_hazard["on_end_turn"][0]["damage"] == "2d6"
    assert sphere_hazard["on_end_turn"][0]["save_ability"] == "str"
    assert sphere_attack["range_ft"] == 60
    assert sphere_attack["damage"] == "4d6"
    assert sphere_attack["damage_type"] == "lightning"
    assert sphere_attack["action_cost"] == "bonus_action"
    assert sphere_attack["advantage_if_target_in_hazard"] == "storm_sphere"

    teleport = _load_payload(OWNED_SPELL_PATHS["spell:teleport"])
    teleport_transform = _find_effect(teleport, "transform")
    assert teleport_transform["condition"] == "teleport_transit"
    assert teleport_transform["target"] == "source"
    assert teleport_transform["max_willing_creatures"] == 8
    assert teleport_transform["object_cube_size_ft"] == 10
    assert teleport_transform["same_plane_only"] is True
    assert teleport_transform["familiarity_table"] is True
    assert teleport_transform["off_target_distance_percent"] == "1d10x1d10"
    assert teleport_transform["mishap_damage"] == "3d10"
    assert teleport_transform["mishap_damage_type"] == "force"

    teleportation_circle = _load_payload(OWNED_SPELL_PATHS["spell:teleportation_circle"])
    circle_hazard = _find_effect(teleportation_circle, "hazard")
    circle_aoe = _find_effect(teleportation_circle, "aoe")
    assert circle_hazard["hazard_type"] == "teleportation_circle"
    assert circle_hazard["diameter_ft"] == 10
    assert circle_hazard["duration_rounds"] == 1
    assert circle_hazard["same_plane_only"] is True
    assert circle_hazard["requires_known_sigils"] is True
    assert circle_hazard["arrival_distance_ft"] == 5
    assert circle_hazard["permanent_circle_castings"] == 365
    assert circle_aoe["shape"] == "circle"
    assert circle_aoe["radius_ft"] == 5

    tiny_hut = _load_payload(OWNED_SPELL_PATHS["spell:tiny_hut"])
    tiny_hut_aoe = _find_effect(tiny_hut, "aoe")
    tiny_hut_hazard = _find_effect(tiny_hut, "hazard")
    assert tiny_hut_aoe["shape"] == "hemisphere"
    assert tiny_hut_aoe["radius_ft"] == 10
    assert tiny_hut_hazard["hazard_type"] == "tiny_hut"
    assert tiny_hut_hazard["duration_rounds"] == 4800
    assert tiny_hut_hazard["capacity_limit"] == 9
    assert tiny_hut_hazard["size_limit"] == "Medium"
    assert tiny_hut_hazard["climate_control"] is True
    assert tiny_hut_hazard["blocks_weather"] is True
    assert tiny_hut_hazard["blocks_spells"] is True
    assert tiny_hut_hazard["opaque_from_outside"] is True
    assert tiny_hut_hazard["transparent_from_inside"] is True

    true_strike = _load_payload(OWNED_SPELL_PATHS["spell:true_strike_divination"])
    true_strike_effect = _find_effect(true_strike, "next_attack_advantage")
    assert true_strike_effect["target"] == "source"

    vitriolic_sphere = _load_payload(OWNED_SPELL_PATHS["spell:vitriolic_sphere"])
    vitriolic_aoe = _find_effect(vitriolic_sphere, "aoe")
    vitriolic_initial = _find_effect(
        vitriolic_sphere,
        "damage",
        predicate=lambda row: row.get("timing") == "on_cast",
    )
    vitriolic_delayed = _find_effect(
        vitriolic_sphere,
        "damage",
        predicate=lambda row: row.get("timing") == "end_of_next_turn",
    )
    assert vitriolic_aoe["shape"] == "sphere"
    assert vitriolic_aoe["radius_ft"] == 20
    assert vitriolic_initial["damage"] == "10d4"
    assert vitriolic_initial["damage_type"] == "acid"
    assert vitriolic_initial["save_ability"] == "dex"
    assert vitriolic_initial["half_on_success"] is True
    assert vitriolic_delayed["damage"] == "5d4"
    assert vitriolic_delayed["damage_type"] == "acid"
    assert vitriolic_delayed["apply_on"] == "save_fail"

    wall_of_fire = _load_payload(OWNED_SPELL_PATHS["spell:wall_of_fire"])
    fire_wall_hazard = _find_effect(wall_of_fire, "hazard")
    fire_wall_aoe = _find_effect(wall_of_fire, "aoe")
    assert fire_wall_hazard["hazard_type"] == "wall_of_fire"
    assert fire_wall_hazard["duration_rounds"] == 10
    assert fire_wall_hazard["concentration_linked"] is True
    assert fire_wall_hazard["opaque"] is True
    assert fire_wall_hazard["damaging_side_only"] is True
    assert fire_wall_hazard["damaging_side_reach_ft"] == 10
    assert fire_wall_hazard["on_cast"][0]["damage"] == "5d8"
    assert fire_wall_hazard["on_cast"][0]["save_ability"] == "dex"
    assert fire_wall_hazard["on_cast"][0]["half_on_success"] is True
    assert fire_wall_hazard["on_enter"][0]["damage_type"] == "fire"
    assert fire_wall_hazard["on_end_turn"][0]["damage"] == "5d8"
    assert fire_wall_aoe["shape"] == "wall"
    assert fire_wall_aoe["length_ft"] == 60
    assert fire_wall_aoe["height_ft"] == 20
    assert fire_wall_aoe["thickness_ft"] == 1

    wall_of_force = _load_payload(OWNED_SPELL_PATHS["spell:wall_of_force"])
    force_wall_hazard = _find_effect(wall_of_force, "hazard")
    force_wall_aoe = _find_effect(wall_of_force, "aoe")
    assert force_wall_hazard["hazard_type"] == "wall_of_force"
    assert force_wall_hazard["duration_rounds"] == 100
    assert force_wall_hazard["concentration_linked"] is True
    assert force_wall_hazard["invisible"] is True
    assert force_wall_hazard["blocks_physical_passage"] is True
    assert force_wall_hazard["immune_to_damage"] is True
    assert force_wall_hazard["dispel_magic_immune"] is True
    assert force_wall_hazard["disintegrate_destroys"] is True
    assert force_wall_hazard["extends_to_ethereal"] is True
    assert force_wall_hazard["pushes_creatures_on_creation"] is True
    assert force_wall_aoe["shape"] == "wall"
    assert force_wall_aoe["panel_count"] == 10
    assert force_wall_aoe["panel_size_ft"] == 10
    assert force_wall_aoe["sphere_radius_ft"] == 10

    wall_of_ice = _load_payload(OWNED_SPELL_PATHS["spell:wall_of_ice"])
    ice_wall_hazard = _find_effect(wall_of_ice, "hazard")
    ice_wall_aoe = _find_effect(wall_of_ice, "aoe")
    assert ice_wall_hazard["hazard_type"] == "wall_of_ice"
    assert ice_wall_hazard["duration_rounds"] == 100
    assert ice_wall_hazard["concentration_linked"] is True
    assert ice_wall_hazard["thickness_ft"] == 1
    assert ice_wall_hazard["section_ac"] == 12
    assert ice_wall_hazard["section_hp"] == 30
    assert ice_wall_hazard["vulnerable_to_damage_type"] == "fire"
    assert ice_wall_hazard["on_cast"][0]["damage"] == "10d6"
    assert ice_wall_hazard["on_cast"][0]["save_ability"] == "dex"
    assert ice_wall_hazard["on_cast"][0]["half_on_success"] is True
    assert ice_wall_hazard["on_enter"][0]["damage"] == "5d6"
    assert ice_wall_hazard["on_enter"][0]["save_ability"] == "con"
    assert ice_wall_aoe["shape"] == "wall"
    assert ice_wall_aoe["panel_count"] == 10
    assert ice_wall_aoe["panel_size_ft"] == 10
    assert ice_wall_aoe["thickness_ft"] == 1
