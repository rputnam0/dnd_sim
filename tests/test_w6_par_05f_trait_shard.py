from __future__ import annotations

from dnd_sim.capability_manifest import build_feature_capability_manifest

SHARD_D_TRAIT_FAMILIES = {
    "trait:aura_of_warding": "meta",
    "trait:avatar_of_battle": "meta",
    "trait:danger_sense": "meta",
    "trait:fiendish_resilience": "meta",
    "trait:improved_critical": "meta",
    "trait:improved_divine_smite": "effect",
    "trait:land_s_stride": "meta",
    "trait:multiattack_defense": "effect",
    "trait:potent_spellcasting": "meta",
    "trait:primal_strike": "effect",
    "trait:second_story_work": "meta",
    "trait:shielding_storm": "meta",
    "trait:spell_resistance": "meta",
    "trait:supernatural_defense": "meta",
}


def test_trait_hook_shard_d_records_are_supported() -> None:
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(set(SHARD_D_TRAIT_FAMILIES) - set(by_id))
    assert missing_ids == []

    blocked_traits_missing_hook = {
        record.content_id
        for record in manifest.records
        if record.content_type == "trait"
        and record.states.unsupported_reason == "missing_runtime_hook_family"
    }
    assert blocked_traits_missing_hook.isdisjoint(SHARD_D_TRAIT_FAMILIES)

    for content_id, expected_family in SHARD_D_TRAIT_FAMILIES.items():
        record = by_id[content_id]
        assert record.content_type == "trait"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.runtime_hook_family == expected_family
