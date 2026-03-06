from __future__ import annotations

from dnd_sim.capability_manifest import build_feature_capability_manifest

HOOKS_C_BACKGROUND_IDS = {
    "background:adept_linguist",
    "background:all_eyes_on_you",
    "background:at_home_in_the_wild",
    "background:black_market_breeder",
    "background:by_popular_demand",
    "background:carnival_fixture",
    "background:conclave_s_shelter",
    "background:conviction",
    "background:court_functionary",
    "background:divine_contact",
    "background:prismari_initiate",
    "background:quandrix_initiate",
    "background:silverquill_initiate",
    "background:wildspace_adaptation",
    "background:witherbloom_initiate",
}


def test_background_hooks_c_records_are_supported() -> None:
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(HOOKS_C_BACKGROUND_IDS - set(by_id))
    assert missing_ids == []

    blocked_backgrounds_missing_hook = {
        record.content_id
        for record in manifest.records
        if record.content_type == "background"
        and record.states.unsupported_reason == "missing_runtime_hook_family"
    }
    assert blocked_backgrounds_missing_hook.isdisjoint(HOOKS_C_BACKGROUND_IDS)

    for content_id in sorted(HOOKS_C_BACKGROUND_IDS):
        record = by_id[content_id]
        assert record.content_type == "background"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.runtime_hook_family == "meta"
