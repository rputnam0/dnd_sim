from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from dnd_sim.capability_manifest import build_spell_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

SPELLS_DIR = Path("db/rules/2014/spells")
OWNED_SPELL_IDS = (
    "spell:daylight",
    "spell:demiplane",
    "spell:dream",
    "spell:dream_of_the_blue_veil",
    "spell:earthquake",
    "spell:elminster_s_effulgent_spheres",
    "spell:fabricate",
    "spell:fire_storm",
    "spell:floating_disk",
    "spell:fog_cloud",
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


def test_j2_b_owned_spell_records_are_supported() -> None:
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


def test_j2_b_owned_spell_mechanics_are_schema_valid() -> None:
    for path in OWNED_SPELL_PATHS.values():
        payload = _load_payload(path)
        assert validate_rule_mechanics_payload(kind="spell", payload=payload) == []


def test_j2_b_owned_spell_paths_are_ascii_and_stable() -> None:
    for content_id in OWNED_SPELL_IDS:
        path = OWNED_SPELL_PATHS[content_id]
        assert path.name.isascii()
        assert path.exists()


def test_j2_b_reviewed_spell_rows_match_expected_canonical_shapes() -> None:
    daylight = _load_payload(OWNED_SPELL_PATHS["spell:daylight"])
    daylight_hazard = _find_effect(daylight, "hazard")
    assert daylight_hazard["hazard_type"] == "light"
    assert daylight_hazard["radius_ft"] == 60
    assert daylight_hazard["dim_light_radius_ft"] == 120
    assert daylight_hazard["duration_rounds"] == 600
    assert daylight_hazard["spell_level"] == 3
    assert daylight_hazard["dispels_lower_level_darkness"] == 3

    demiplane = _load_payload(OWNED_SPELL_PATHS["spell:demiplane"])
    demiplane_transform = _find_effect(demiplane, "transform")
    assert demiplane_transform["condition"] == "demiplane_access_open"
    assert demiplane_transform["duration_rounds"] == 600
    assert demiplane_transform["door_width_ft"] == 5
    assert demiplane_transform["door_height_ft"] == 10
    assert demiplane_transform["room_size_ft"] == 30
    assert demiplane_transform["traps_contents_on_expire"] is True
    assert demiplane_transform["can_link_existing_demiplane"] is True

    dream = _load_payload(OWNED_SPELL_PATHS["spell:dream"])
    dream_transform = _find_effect(dream, "transform")
    assert dream_transform["condition"] == "dream_linked"
    assert dream_transform["duration_rounds"] == 4800
    assert dream_transform["requires_same_plane"] is True
    assert dream_transform["requires_sleeping_target"] is True
    assert dream_transform["nightmare_save_ability"] == "wis"
    assert dream_transform["nightmare_damage"] == "3d6"
    assert dream_transform["nightmare_damage_type"] == "psychic"
    assert dream_transform["blocks_rest_on_failed_nightmare_save"] is True

    dream_of_the_blue_veil = _load_payload(OWNED_SPELL_PATHS["spell:dream_of_the_blue_veil"])
    blue_veil_transform = _find_effect(dream_of_the_blue_veil, "transform")
    assert blue_veil_transform["condition"] == "dream_of_the_blue_veil_transit"
    assert blue_veil_transform["duration_rounds"] == 3600
    assert blue_veil_transform["max_willing_creatures"] == 8
    assert blue_veil_transform["applies_unconscious_trance"] is True
    assert blue_veil_transform["transports_on_full_duration"] is True
    assert blue_veil_transform["destination_safe_radius_miles"] == 1
    assert blue_veil_transform["ends_early_on_any_damage"] is True

    earthquake = _load_payload(OWNED_SPELL_PATHS["spell:earthquake"])
    earthquake_hazard = _find_effect(earthquake, "hazard")
    assert earthquake_hazard["hazard_type"] == "earthquake"
    assert earthquake_hazard["radius_ft"] == 100
    assert earthquake_hazard["duration_rounds"] == 10
    assert earthquake_hazard["concentration_linked"] is True
    assert earthquake_hazard["difficult_terrain"] is True
    assert earthquake_hazard["prone_save_ability"] == "dex"
    assert earthquake_hazard["concentration_break_save_ability"] == "con"
    assert earthquake_hazard["structure_damage"] == 50
    assert earthquake_hazard["collapse_damage"] == "5d6"
    assert earthquake_hazard["collapse_escape_dc"] == 20

    effulgent_spheres = _load_payload(OWNED_SPELL_PATHS["spell:elminster_s_effulgent_spheres"])
    spheres_condition = _find_effect(effulgent_spheres, "apply_condition")
    assert spheres_condition["condition"] == "elminster_s_effulgent_spheres_active"
    assert spheres_condition["duration_rounds"] == 600
    assert spheres_condition["stack_policy"] == "refresh"
    assert spheres_condition["sphere_count"] == 6
    assert spheres_condition["bonus_action_attack_damage"] == "3d6"
    assert spheres_condition["reaction_grants_resistance_until_turn_start"] is True
    assert spheres_condition["higher_slot_extra_spheres"] == 1

    fabricate = _load_payload(OWNED_SPELL_PATHS["spell:fabricate"])
    fabricate_transform = _find_effect(fabricate, "transform")
    assert fabricate_transform["condition"] == "fabricate_resolved"
    assert fabricate_transform["max_object_size"] == "large"
    assert fabricate_transform["mineral_max_object_size"] == "medium"
    assert fabricate_transform["default_cube_size_ft"] == 10
    assert fabricate_transform["connected_cube_count"] == 8
    assert fabricate_transform["requires_raw_materials"] is True
    assert fabricate_transform["requires_artisan_proficiency_for_fine_work"] is True

    fire_storm = _load_payload(OWNED_SPELL_PATHS["spell:fire_storm"])
    fire_storm_damage = _find_effect(fire_storm, "damage")
    assert fire_storm_damage["damage"] == "7d10"
    assert fire_storm_damage["damage_type"] == "fire"
    assert fire_storm_damage["save"] == "dex"
    assert fire_storm_damage["half_on_success"] is True
    assert fire_storm_damage["damages_objects"] is True
    assert fire_storm_damage["ignites_flammable_unworn_objects"] is True
    assert fire_storm_damage["can_spare_plants"] is True

    floating_disk = _load_payload(OWNED_SPELL_PATHS["spell:floating_disk"])
    floating_disk_hazard = _find_effect(floating_disk, "hazard")
    assert floating_disk_hazard["hazard_type"] == "floating_disk"
    assert floating_disk_hazard["duration_rounds"] == 600
    assert floating_disk_hazard["diameter_ft"] == 3
    assert floating_disk_hazard["thickness_in"] == 1
    assert floating_disk_hazard["capacity_lb"] == 500
    assert floating_disk_hazard["follow_distance_ft"] == 20
    assert floating_disk_hazard["ends_if_distance_exceeds_ft"] == 100
    assert floating_disk_hazard["max_elevation_change_ft"] == 10

    fog_cloud = _load_payload(OWNED_SPELL_PATHS["spell:fog_cloud"])
    fog_cloud_hazard = _find_effect(fog_cloud, "hazard")
    assert fog_cloud_hazard["hazard_type"] == "fog_cloud"
    assert fog_cloud_hazard["radius_ft"] == 20
    assert fog_cloud_hazard["duration_rounds"] == 600
    assert fog_cloud_hazard["concentration_linked"] is True
    assert fog_cloud_hazard["obscures_vision"] is True
    assert fog_cloud_hazard["spreads_around_corners"] is True
    assert fog_cloud_hazard["dispersed_by"] == "moderate_wind"
