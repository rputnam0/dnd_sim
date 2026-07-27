from __future__ import annotations

from dnd_sim.capability_manifest import build_feature_capability_manifest

SHARD_C_TRAIT_IDS = {
    "trait:acolyte_of_strength",
    "trait:additional_fighting_style",
    "trait:additional_maneuvers",
    "trait:additional_rune_known",
    "trait:arcane_archer_lore",
    "trait:assassin_s_tools",
    "trait:druidic",
    "trait:eldritch_invocation_options",
    "trait:eldritch_invocations",
    "trait:implements_of_mercy",
    "trait:magic_item_adept",
    "trait:magic_item_master",
    "trait:maneuver_options",
    "trait:metamagic_options",
    "trait:optional_rule_firearm_proficiency",
    "trait:survivalist",
    "trait:tools_of_the_trade",
    "trait:wind_speaker",
}


def test_w6_par_05e_meta_only_trait_records_are_non_executable() -> None:
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(SHARD_C_TRAIT_IDS - set(by_id))
    assert missing_ids == []

    blocked_traits_missing_hook = {
        record.content_id
        for record in manifest.records
        if record.content_type == "trait"
        and record.states.unsupported_reason == "missing_runtime_hook_family"
    }
    assert blocked_traits_missing_hook.isdisjoint(SHARD_C_TRAIT_IDS)

    for content_id in sorted(SHARD_C_TRAIT_IDS):
        record = by_id[content_id]
        assert record.content_type == "trait"
        assert record.runtime_hook_family == "meta"
        assert record.support_state == "unsupported"
        assert record.states.cataloged is True
        assert record.states.schema_valid is True
        assert record.states.executable is False
        assert record.states.blocked is True
        assert record.states.unsupported_reason == "non_executable_mechanics"
