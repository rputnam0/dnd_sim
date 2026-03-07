from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from dnd_sim.capability_manifest import build_spell_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

SPELLS_DIR = Path("db/rules/2014/spells")
OWNED_SPELL_IDS = (
    "spell:jallarzi_s_storm_of_radiance",
    "spell:linked_glyphs",
    "spell:maddening_darkness",
    "spell:nystul_s_magic_aura",
    "spell:otiluke_s_resilient_sphere",
    "spell:prismatic_wall",
    "spell:resilient_sphere",
    "spell:shape_water",
    "spell:spellfire_storm",
    "spell:steel_wind_strike",
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


def test_j2_d_owned_spell_records_are_supported() -> None:
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


def test_j2_d_owned_spell_mechanics_are_schema_valid() -> None:
    for path in OWNED_SPELL_PATHS.values():
        payload = _load_payload(path)
        assert validate_rule_mechanics_payload(kind="spell", payload=payload) == []


def test_j2_d_owned_spell_paths_are_ascii_and_stable() -> None:
    for content_id in OWNED_SPELL_IDS:
        path = OWNED_SPELL_PATHS[content_id]
        assert path.name.isascii()
        assert path.exists()


def test_j2_d_reviewed_spell_rows_match_expected_canonical_shapes() -> None:
    jallarzi = _load_payload(OWNED_SPELL_PATHS["spell:jallarzi_s_storm_of_radiance"])
    jallarzi_hazard = _find_effect(jallarzi, "hazard")
    assert jallarzi_hazard["hazard_type"] == "storm_of_radiance"
    assert jallarzi_hazard["radius_ft"] == 10
    assert jallarzi_hazard["height_ft"] == 40
    assert jallarzi_hazard["duration_rounds"] == 10
    assert jallarzi_hazard["concentration_linked"] is True
    assert jallarzi_hazard["bright_light"] is True
    assert jallarzi_hazard["applies_conditions"] == ["blinded", "deafened"]
    assert jallarzi_hazard["blocks_verbal_components"] is True
    assert jallarzi_hazard["on_enter"][0]["damage"] == "2d10"
    assert jallarzi_hazard["on_enter"][1]["damage"] == "2d10"
    assert jallarzi_hazard["on_end_turn"][0]["half_on_success"] is True

    linked_glyphs = _load_payload(OWNED_SPELL_PATHS["spell:linked_glyphs"])
    linked_glyphs_hazard = _find_effect(linked_glyphs, "hazard")
    assert linked_glyphs_hazard["hazard_type"] == "linked_glyphs"
    assert linked_glyphs_hazard["detection_radius_ft"] == 5
    assert linked_glyphs_hazard["breaks_if_moved_over_ft"] == 10
    assert linked_glyphs_hazard["alarm_link_range_miles"] == 100
    assert linked_glyphs_hazard["spell_glyph_link_range_ft"] == 100
    assert linked_glyphs_hazard["stored_spell_max_level"] == 4
    assert linked_glyphs_hazard["can_store_higher_level_spell_with_slot_match"] is True

    maddening_darkness = _load_payload(OWNED_SPELL_PATHS["spell:maddening_darkness"])
    maddening_darkness_hazard = _find_effect(maddening_darkness, "hazard")
    assert maddening_darkness_hazard["hazard_type"] == "maddening_darkness"
    assert maddening_darkness_hazard["radius_ft"] == 60
    assert maddening_darkness_hazard["duration_rounds"] == 100
    assert maddening_darkness_hazard["concentration_linked"] is True
    assert maddening_darkness_hazard["obscures_vision"] is True
    assert maddening_darkness_hazard["blocks_nonmagical_light"] is True
    assert maddening_darkness_hazard["blocks_lower_level_spell_light_at_or_below"] == 8
    assert maddening_darkness_hazard["on_start_turn"][0]["damage"] == "8d8"
    assert maddening_darkness_hazard["on_start_turn"][0]["save_ability"] == "wis"

    nystul = _load_payload(OWNED_SPELL_PATHS["spell:nystul_s_magic_aura"])
    nystul_transform = _find_effect(nystul, "transform")
    assert nystul_transform["condition"] == "nystul_s_magic_aura"
    assert nystul_transform["duration_rounds"] == 14400
    assert nystul_transform["false_aura"] is True
    assert nystul_transform["mask"] is True
    assert nystul_transform["permanent_after_recasting_days"] == 30

    otiluke = _load_payload(OWNED_SPELL_PATHS["spell:otiluke_s_resilient_sphere"])
    otiluke_transform = _find_effect(otiluke, "transform")
    assert otiluke_transform["condition"] == "resilient_sphere_enclosed"
    assert otiluke_transform["apply_on"] == "save_fail"
    assert otiluke_transform["save_ability"] == "dex"
    assert otiluke_transform["size_max"] == "large"
    assert otiluke_transform["blocks_incoming_outgoing_effects"] is True
    assert otiluke_transform["movable_by_creatures"] is True
    assert otiluke_transform["self_roll_speed"] == "half_speed"

    prismatic_wall = _load_payload(OWNED_SPELL_PATHS["spell:prismatic_wall"])
    prismatic_wall_hazard = _find_effect(prismatic_wall, "hazard")
    assert prismatic_wall_hazard["hazard_type"] == "prismatic_wall"
    assert prismatic_wall_hazard["duration_rounds"] == 100
    assert prismatic_wall_hazard["bright_light_radius_ft"] == 100
    assert prismatic_wall_hazard["dim_light_radius_ft"] == 200
    assert prismatic_wall_hazard["layers"] == 7
    assert prismatic_wall_hazard["allows_designated_creatures_to_pass"] is True
    assert prismatic_wall_hazard["on_start_turn"][0]["condition"] == "blinded"
    assert prismatic_wall_hazard["on_enter"][0]["damage_type"] == "fire"
    assert prismatic_wall_hazard["on_enter"][4]["damage_type"] == "cold"

    resilient_sphere = _load_payload(OWNED_SPELL_PATHS["spell:resilient_sphere"])
    resilient_transform = _find_effect(resilient_sphere, "transform")
    assert resilient_transform["condition"] == "resilient_sphere_enclosed"
    assert resilient_transform["apply_on"] == "save_fail"
    assert resilient_transform["save_ability"] == "dex"
    assert resilient_transform["duration_rounds"] == 10
    assert resilient_transform["blocks_incoming_outgoing_effects"] is True

    shape_water = _load_payload(OWNED_SPELL_PATHS["spell:shape_water"])
    shape_water_transform = _find_effect(shape_water, "transform")
    assert shape_water_transform["condition"] == "shape_water_effect"
    assert shape_water_transform["cube_size_ft"] == 5
    assert shape_water_transform["move_water_ft"] == 5
    assert shape_water_transform["reshape_water"] is True
    assert shape_water_transform["recolor_or_opacify"] is True
    assert shape_water_transform["freeze_without_creatures"] is True
    assert shape_water_transform["noninstant_duration_rounds"] == 600
    assert shape_water_transform["simultaneous_noninstant_effect_limit"] == 2

    spellfire_storm = _load_payload(OWNED_SPELL_PATHS["spell:spellfire_storm"])
    spellfire_storm_hazard = _find_effect(spellfire_storm, "hazard")
    assert spellfire_storm_hazard["hazard_type"] == "spellfire_storm"
    assert spellfire_storm_hazard["radius_ft"] == 20
    assert spellfire_storm_hazard["height_ft"] == 20
    assert spellfire_storm_hazard["duration_rounds"] == 10
    assert spellfire_storm_hazard["concentration_linked"] is True
    assert spellfire_storm_hazard["bright_light"] is True
    assert spellfire_storm_hazard["on_enter"][0]["damage"] == "4d10"
    assert spellfire_storm_hazard["on_end_turn"][0]["half_on_success"] is True
    assert spellfire_storm_hazard["spellcast_save_ability"] == "con"
    assert spellfire_storm_hazard["suppresses_spell_on_failed_save"] is True

    steel_wind_strike = _load_payload(OWNED_SPELL_PATHS["spell:steel_wind_strike"])
    steel_wind_strike_damage = _find_effect(steel_wind_strike, "damage")
    assert steel_wind_strike_damage["damage"] == "6d10"
    assert steel_wind_strike_damage["damage_type"] == "force"
    assert steel_wind_strike_damage["attack_type"] == "melee_spell_attack"
    assert steel_wind_strike_damage["max_targets"] == 5
    assert steel_wind_strike_damage["range_ft"] == 30
    steel_wind_strike_transform = _find_effect(steel_wind_strike, "transform")
    assert steel_wind_strike_transform["condition"] == "steel_wind_strike_reposition"
    assert steel_wind_strike_transform["distance_from_target_ft"] == 5
    assert steel_wind_strike_transform["requires_visible_unoccupied_space"] is True
