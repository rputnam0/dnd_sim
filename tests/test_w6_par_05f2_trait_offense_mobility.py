from __future__ import annotations

import json
from pathlib import Path

from dnd_sim.capability_manifest import build_feature_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

REPO_ROOT = Path(__file__).resolve().parents[1]

W6_PAR_05F2_TRAIT_FAMILIES = {
    "trait:additional_arcane_shot_option": "meta",
    "trait:agile_strikes": "meta",
    "trait:aspect_of_the_beast": "meta",
    "trait:aspect_of_the_wilds": "meta",
    "trait:aspect_of_the_wyrm": "effect_meta",
    "trait:bardic_damage": "effect_meta",
    "trait:battlerager_charge": "meta",
    "trait:bonus_unarmed_strike": "meta",
    "trait:born_to_the_saddle": "meta",
    "trait:brutal_critical_1_die": "meta",
    "trait:brutal_critical_2_dice": "meta",
    "trait:brutal_critical_3_dice": "meta",
    "trait:cunning_strike": "meta",
    "trait:curving_shot": "meta",
    "trait:death_strike": "effect_meta",
    "trait:devious_strikes": "meta",
    "trait:dexterous_attacks": "meta",
    "trait:distant_strike": "meta",
    "trait:divine_fury": "effect",
    "trait:divine_smite": "effect",
    "trait:divine_soul": "meta",
    "trait:divine_strike": "effect",
    "trait:dread_ambusher": "effect_meta",
    "trait:drunken_technique": "effect_meta",
    "trait:eldritch_strike": "effect",
    "trait:elemental_cleaver": "effect_meta",
    "trait:extra_attack_2": "meta",
    "trait:guided_strike": "meta",
    "trait:homing_strikes": "meta",
    "trait:improved_brutal_strike": "meta",
    "trait:improved_cunning_strike": "meta",
    "trait:infectious_fury": "effect_meta",
    "trait:inspiring_movement": "meta",
    "trait:inspiring_smite": "effect_meta",
    "trait:keeper_of_souls": "effect",
    "trait:kensei_s_shot": "effect",
    "trait:master_s_flourish": "meta",
    "trait:multiattack": "meta",
    "trait:paladin_s_smite": "meta",
    "trait:psionic_strike": "effect",
    "trait:pyromancer_s_fury": "effect",
    "trait:reckless_attack": "meta",
    "trait:redirect_attack": "meta",
    "trait:searing_arc_strike": "meta",
    "trait:slashing_flourish": "effect_meta",
    "trait:soul_blades": "meta",
    "trait:soul_of_artifice": "effect_meta",
    "trait:soul_of_vengeance": "effect",
    "trait:soulknife": "meta",
    "trait:storm_s_fury": "effect_meta",
    "trait:storm_soul": "meta",
    "trait:three_extra_attacks": "meta",
    "trait:thunderbolt_strike": "effect",
    "trait:two_extra_attacks": "meta",
    "trait:way_of_the_sun_soul": "meta",
    "trait:weapon_mastery": "meta",
    "trait:whirlwind_attack": "meta",
}


def _load_trait_payload(content_id: str) -> dict[str, object]:
    trait_id = content_id.split(":", 1)[1]
    path = REPO_ROOT / "db" / "rules" / "2014" / "traits" / f"{trait_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_w6_par_05f2_trait_records_are_supported() -> None:
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(set(W6_PAR_05F2_TRAIT_FAMILIES) - set(by_id))
    assert missing_ids == []

    blocked_traits_missing_hook = {
        record.content_id
        for record in manifest.records
        if record.content_type == "trait"
        and record.states.unsupported_reason == "missing_runtime_hook_family"
    }
    assert blocked_traits_missing_hook.isdisjoint(W6_PAR_05F2_TRAIT_FAMILIES)

    for content_id, expected_family in W6_PAR_05F2_TRAIT_FAMILIES.items():
        record = by_id[content_id]
        assert record.content_type == "trait"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.unsupported_reason is None
        assert record.runtime_hook_family == expected_family


def test_w6_par_05f2_trait_mechanics_are_schema_valid() -> None:
    for content_id in W6_PAR_05F2_TRAIT_FAMILIES:
        payload = _load_trait_payload(content_id)
        issues = validate_rule_mechanics_payload(kind="trait", payload=payload)
        assert issues == [], f"{content_id} has schema issues: {issues}"


def test_w6_par_05f2_representative_offense_and_mobility_rows_use_canonical_types() -> None:
    dread_ambusher = _load_trait_payload("trait:dread_ambusher")
    dread_types = {
        (row.get("effect_type"), row.get("meta_type"))
        for row in dread_ambusher["mechanics"]
        if isinstance(row, dict)
    }
    assert (None, "initiative_bonus") in dread_types
    assert ("speed_increase", None) in dread_types
    assert (None, "extra_attack") in dread_types
    assert ("extra_damage", None) in dread_types

    storm_s_fury = _load_trait_payload("trait:storm_s_fury")
    storm_types = {
        (row.get("effect_type"), row.get("meta_type"))
        for row in storm_s_fury["mechanics"]
        if isinstance(row, dict)
    }
    assert (None, "reaction") in storm_types
    assert ("damage", None) in storm_types
    assert ("forced_movement", None) in storm_types

    thunderbolt_strike = _load_trait_payload("trait:thunderbolt_strike")
    assert thunderbolt_strike["mechanics"] == [
        {
            "effect_type": "forced_movement",
            "trigger": "deal_lightning_damage_to_large_or_smaller_creature",
            "target": "damaged_creature",
            "distance_ft": 10,
            "direction": "away_from_source",
            "size_limit": "large",
        }
    ]

    brutal_critical = _load_trait_payload("trait:brutal_critical_1_die")
    assert brutal_critical["mechanics"][0]["meta_type"] == "critical_damage"
    assert brutal_critical["mechanics"][0]["dice_by_level"] == [
        {"level": 9, "additional_dice": 1},
        {"level": 13, "additional_dice": 2},
        {"level": 17, "additional_dice": 3},
    ]

    weapon_mastery = _load_trait_payload("trait:weapon_mastery")
    assert weapon_mastery["mechanics"] == [
        {
            "meta_type": "choice",
            "choice_key": "weapon_mastery_weapons",
            "count": 2,
            "grants": "weapon_mastery_property_use",
            "reset": "long_rest",
            "scales_with": "barbarian_weapon_mastery_progression",
            "weapon_categories": ["simple", "martial_melee"],
        }
    ]

    subclass_identity_traits = {
        "trait:divine_soul",
        "trait:soulknife",
        "trait:way_of_the_sun_soul",
    }
    for content_id in subclass_identity_traits:
        payload = _load_trait_payload(content_id)
        assert payload["mechanics"] == [{"meta_type": "subclass_identity"}]
