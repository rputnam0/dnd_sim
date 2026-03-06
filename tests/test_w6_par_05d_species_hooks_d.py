from __future__ import annotations

from dnd_sim import io
from dnd_sim.capability_manifest import build_feature_capability_manifest

W6_PAR_05D_SPECIES_IDS = {
    "species:breath_weapon",
    "species:built_for_success",
    "species:celestial_revelation",
    "species:charge",
    "species:chromatic_warding",
    "species:control_air_and_water",
    "species:cunning_artisan",
    "species:daunting_roar",
    "species:dexterous_feet",
    "species:dive_attack",
    "species:draconic_cry",
    "species:draconic_flight",
    "species:fairy_magic",
    "species:fey_step",
    "species:gem_flight",
    "species:gift_of_the_svirfneblin",
    "species:githyanki_psionics",
    "species:githzerai_psionics",
    "species:glide",
    "species:goring_rush",
    "species:grovel_cower_and_beg",
    "species:healing_hands",
    "species:hooves",
    "species:horns",
    "species:hungry_jaws",
    "species:infernal_legacy",
    "species:knowledge_from_a_past_life",
    "species:large_form",
    "species:light_bearer",
    "species:long_limbed",
    "species:lucky_footwork",
    "species:mind_link",
    "species:natural_weapon",
    "species:nimble_escape",
    "species:otherworldly_presence",
    "species:partially_amphibious",
    "species:rabbit_hop",
    "species:rampage",
    "species:relentless_endurance",
    "species:savage_attacks",
    "species:saving_face",
    "species:shape_self",
    "species:shifting",
    "species:starlight_step",
    "species:surprise_attack",
    "species:taunt",
    "species:undead_fortitude",
    "species:wind_caller",
}


def test_w6_par_05d_species_records_are_supported_in_feature_manifest() -> None:
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(W6_PAR_05D_SPECIES_IDS - set(by_id))
    assert missing_ids == []

    for content_id in sorted(W6_PAR_05D_SPECIES_IDS):
        record = by_id[content_id]
        assert record.content_type == "species"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.runtime_hook_family in {"effect", "effect_meta", "meta"}


def test_w6_par_05d_species_ids_are_supported_in_canonical_capability_records() -> None:
    io._canonical_capability_records.cache_clear()
    by_id = {record.content_id: record for record in io._canonical_capability_records()}

    missing_ids = sorted(W6_PAR_05D_SPECIES_IDS - set(by_id))
    assert missing_ids == []

    for content_id in sorted(W6_PAR_05D_SPECIES_IDS):
        record = by_id[content_id]
        assert record.content_type == "species"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.runtime_hook_family in {"effect", "effect_meta", "meta"}
