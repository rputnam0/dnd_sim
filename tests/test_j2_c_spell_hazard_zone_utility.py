from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from dnd_sim.capability_manifest import build_spell_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

SPELLS_DIR = Path("db/rules/2014/spells")
OWNED_SPELL_IDS = (
    "spell:fount_of_moonlight",
    "spell:freezing_sphere",
    "spell:galder_s_speedy_courier",
    "spell:galder_s_tower",
    "spell:gate",
    "spell:gate_seal",
    "spell:grease",
    "spell:gust_of_wind",
    "spell:incendiary_cloud",
    "spell:investiture_of_wind",
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


def test_j2_c_owned_spell_records_are_supported() -> None:
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


def test_j2_c_owned_spell_mechanics_are_schema_valid() -> None:
    for path in OWNED_SPELL_PATHS.values():
        payload = _load_payload(path)
        assert validate_rule_mechanics_payload(kind="spell", payload=payload) == []


def test_j2_c_owned_spell_paths_are_ascii_and_stable() -> None:
    for content_id in OWNED_SPELL_IDS:
        path = OWNED_SPELL_PATHS[content_id]
        assert path.name.isascii()
        assert path.exists()


def test_j2_c_reviewed_spell_rows_match_expected_canonical_shapes() -> None:
    fount_of_moonlight = _load_payload(OWNED_SPELL_PATHS["spell:fount_of_moonlight"])
    moonlight_condition = _find_effect(fount_of_moonlight, "apply_condition")
    assert moonlight_condition["condition"] == "fount_of_moonlight_active"
    assert moonlight_condition["duration_rounds"] == 100
    assert moonlight_condition["concentration_linked"] is True
    assert moonlight_condition["stack_policy"] == "refresh"
    assert moonlight_condition["bright_light_radius_ft"] == 20
    assert moonlight_condition["dim_light_radius_ft"] == 40
    assert moonlight_condition["grants_radiant_resistance"] is True
    assert moonlight_condition["melee_extra_damage"] == "2d6"
    assert moonlight_condition["melee_extra_damage_type"] == "radiant"
    assert moonlight_condition["retaliatory_blind_range_ft"] == 60
    assert moonlight_condition["retaliatory_blind_save_ability"] == "con"

    freezing_sphere = _load_payload(OWNED_SPELL_PATHS["spell:freezing_sphere"])
    freezing_damage = _find_effect(freezing_sphere, "damage")
    assert freezing_damage["damage"] == "10d6"
    assert freezing_damage["damage_type"] == "cold"
    assert freezing_damage["save"] == "con"
    assert freezing_damage["half_on_success"] is True
    assert freezing_damage["freeze_water_depth_in"] == 6
    assert freezing_damage["freeze_water_area_ft"] == 30
    assert freezing_damage["freeze_duration_rounds"] == 10
    assert freezing_damage["storable_globe"] is True
    assert freezing_damage["thrown_range_ft"] == 40
    assert freezing_damage["sling_delivery"] is True
    assert freezing_damage["delayed_explosion_rounds"] == 10

    galder_s_speedy_courier = _load_payload(OWNED_SPELL_PATHS["spell:galder_s_speedy_courier"])
    courier_transform = _find_effect(galder_s_speedy_courier, "transform")
    assert courier_transform["condition"] == "galders_speedy_courier_active"
    assert courier_transform["duration_rounds"] == 100
    assert courier_transform["courier_form"] == "small_air_elemental"
    assert courier_transform["courier_damage_immunity"] is True
    assert courier_transform["chest_size_ft"] == 3
    assert courier_transform["deliver_on_close"] is True
    assert courier_transform["target_must_be_known_or_have_body_part"] is True
    assert courier_transform["target_only_can_open_chest"] is True
    assert courier_transform["return_contents_if_blocked_or_expired"] is True
    assert courier_transform["cross_planar_at_slot_level"] == 8

    galder_s_tower = _load_payload(OWNED_SPELL_PATHS["spell:galder_s_tower"])
    tower_transform = _find_effect(galder_s_tower, "transform")
    assert tower_transform["condition"] == "galders_tower_active"
    assert tower_transform["duration_rounds"] == 14400
    assert tower_transform["story_count"] == 2
    assert tower_transform["story_height_ft"] == 10
    assert tower_transform["max_floor_area_sq_ft"] == 100
    assert tower_transform["shape_options"] == ["round", "square"]
    assert tower_transform["safe_eject_on_expire"] is True
    assert tower_transform["extend_with_recast"] is True
    assert tower_transform["permanent_after_year"] is True

    gate = _load_payload(OWNED_SPELL_PATHS["spell:gate"])
    gate_hazard = _find_effect(gate, "hazard")
    assert gate_hazard["hazard_type"] == "gate"
    assert gate_hazard["duration_rounds"] == 10
    assert gate_hazard["concentration_linked"] is True
    assert gate_hazard["diameter_min_ft"] == 5
    assert gate_hazard["diameter_max_ft"] == 20
    assert gate_hazard["links_other_plane"] is True
    assert gate_hazard["bidirectional_front_only_travel"] is True
    assert gate_hazard["named_creature_pull"] is True
    assert gate_hazard["named_creature_requires_other_plane"] is True
    assert gate_hazard["named_creature_not_controlled"] is True

    gate_seal = _load_payload(OWNED_SPELL_PATHS["spell:gate_seal"])
    gate_seal_hazard = _find_effect(gate_seal, "hazard")
    assert gate_seal_hazard["hazard_type"] == "gate_seal"
    assert gate_seal_hazard["cube_size_ft"] == 30
    assert gate_seal_hazard["duration_rounds"] == 14400
    assert gate_seal_hazard["closes_portals"] is True
    assert gate_seal_hazard["prevents_portals_opening"] is True
    assert gate_seal_hazard["blocks_planar_travel"] is True
    assert gate_seal_hazard["stationary"] is True
    assert gate_seal_hazard["upcast_permanent_slot_level"] == 6

    grease = _load_payload(OWNED_SPELL_PATHS["spell:grease"])
    grease_hazard = _find_effect(grease, "hazard")
    assert grease_hazard["hazard_type"] == "grease"
    assert grease_hazard["size_ft"] == 10
    assert grease_hazard["shape"] == "square"
    assert grease_hazard["duration_rounds"] == 10
    assert grease_hazard["difficult_terrain"] is True
    assert grease_hazard["prone_save_ability"] == "dex"
    assert grease_hazard["save_on_cast"] is True
    assert grease_hazard["save_on_enter"] is True
    assert grease_hazard["save_on_end_turn"] is True

    gust_of_wind = _load_payload(OWNED_SPELL_PATHS["spell:gust_of_wind"])
    gust_hazard = _find_effect(gust_of_wind, "hazard")
    assert gust_hazard["hazard_type"] == "gust_of_wind"
    assert gust_hazard["length_ft"] == 60
    assert gust_hazard["width_ft"] == 10
    assert gust_hazard["duration_rounds"] == 10
    assert gust_hazard["concentration_linked"] is True
    assert gust_hazard["push_save_ability"] == "str"
    assert gust_hazard["push_distance_ft"] == 15
    assert gust_hazard["extra_movement_cost_multiplier"] == 2
    assert gust_hazard["disperses_gas_or_vapor"] is True
    assert gust_hazard["extinguishes_unprotected_flames"] is True
    assert gust_hazard["protected_flame_extinguish_chance_percent"] == 50
    assert gust_hazard["redirect_bonus_action"] is True

    incendiary_cloud = _load_payload(OWNED_SPELL_PATHS["spell:incendiary_cloud"])
    incendiary_hazard = _find_effect(incendiary_cloud, "hazard")
    assert incendiary_hazard["hazard_type"] == "incendiary_cloud"
    assert incendiary_hazard["radius_ft"] == 20
    assert incendiary_hazard["duration_rounds"] == 10
    assert incendiary_hazard["concentration_linked"] is True
    assert incendiary_hazard["obscures_vision"] is True
    assert incendiary_hazard["spreads_around_corners"] is True
    assert incendiary_hazard["moves_away_from_source_ft"] == 10
    assert incendiary_hazard["dispersed_by"] == "moderate_wind"
    assert incendiary_hazard["on_enter"][0]["damage"] == "10d8"
    assert incendiary_hazard["on_enter"][0]["damage_type"] == "fire"
    assert incendiary_hazard["on_enter"][0]["save_ability"] == "dex"
    assert incendiary_hazard["on_end_turn"][0]["half_on_success"] is True

    investiture_of_wind = _load_payload(OWNED_SPELL_PATHS["spell:investiture_of_wind"])
    wind_condition = _find_effect(investiture_of_wind, "apply_condition")
    assert wind_condition["condition"] == "investiture_of_wind_active"
    assert wind_condition["duration_rounds"] == 100
    assert wind_condition["concentration_linked"] is True
    assert wind_condition["stack_policy"] == "refresh"
    assert wind_condition["fly_speed_ft"] == 60
    assert wind_condition["ranged_attacks_against_you_disadvantage"] is True
    assert wind_condition["fall_if_airborne_on_expire"] is True
    assert wind_condition["action_cube_size_ft"] == 15
    assert wind_condition["action_range_ft"] == 60
    assert wind_condition["action_damage"] == "2d10"
    assert wind_condition["action_damage_type"] == "bludgeoning"
    assert wind_condition["action_save_ability"] == "con"
    assert wind_condition["action_push_distance_ft"] == 10
    assert wind_condition["action_push_size_limit"] == "large"
