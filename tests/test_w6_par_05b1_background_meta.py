from __future__ import annotations

import json
from pathlib import Path

from dnd_sim.capability_manifest import build_feature_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

REPO_ROOT = Path(__file__).resolve().parents[1]

W6_PAR_05B1_BACKGROUND_IDS = {
    "background:ballad_of_the_grinning_fool",
    "background:choose_a_feature",
    "background:discovery",
    "background:double_agent",
    "background:down_low",
    "background:dual_personalities",
    "background:ear_to_the_ground",
    "background:ex_convict",
    "background:factor",
    "background:false_identity",
    "background:fearsome_reputation",
    "background:feywild_connection",
    "background:guerrilla",
    "background:harborfolk",
    "background:heart_of_darkness",
    "background:highborn",
    "background:historical_knowledge",
    "background:house_connections",
    "background:i_ll_patch_it",
    "background:inheritance",
    "background:inside_informant",
    "background:investigative_services",
    "background:kept_in_style",
    "background:knightly_regard",
    "background:legalese",
    "background:legion_station",
    "background:leverage",
    "background:mercenary_life",
    "background:name_dropping",
    "background:never_tell_me_the_odds",
    "background:phlan_survivor",
    "background:red_plume_and_mage_guild_contacts",
    "background:respect_of_the_stout_folk",
    "background:shelter_of_the_elven_clergy",
    "background:steady",
    "background:still_standing",
    "background:supply_chain",
    "background:trade_contact",
    "background:trials_of_the_five_gods",
    "background:urban_infrastructure",
    "background:wagonmaster",
    "background:wanderer",
    "background:watcher_s_eye",
}


def test_w6_par_05b1_background_records_are_supported() -> None:
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(W6_PAR_05B1_BACKGROUND_IDS - set(by_id))
    assert missing_ids == []

    blocked_backgrounds_missing_hook = {
        record.content_id
        for record in manifest.records
        if record.content_type == "background"
        and record.states.unsupported_reason == "missing_runtime_hook_family"
    }
    assert blocked_backgrounds_missing_hook.isdisjoint(W6_PAR_05B1_BACKGROUND_IDS)

    for content_id in sorted(W6_PAR_05B1_BACKGROUND_IDS):
        record = by_id[content_id]
        assert record.content_type == "background"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.runtime_hook_family == "meta"


def test_w6_par_05b1_background_files_use_meta_rows_only() -> None:
    traits_dir = REPO_ROOT / "db" / "rules" / "2014" / "traits"

    for content_id in sorted(W6_PAR_05B1_BACKGROUND_IDS):
        slug = content_id.split(":", 1)[1]
        payload = json.loads((traits_dir / f"{slug}.json").read_text(encoding="utf-8"))
        mechanics = payload.get("mechanics")

        assert payload.get("source_type") == "background"
        assert isinstance(mechanics, list)
        assert mechanics != []
        assert all(isinstance(row, dict) for row in mechanics)
        assert all(str(row.get("meta_type", "")).strip() for row in mechanics)
        assert all("effect_type" not in row for row in mechanics)

        issues = validate_rule_mechanics_payload(kind="trait", payload=payload)
        assert issues == [], f"{content_id} has schema issues: {issues}"
