from __future__ import annotations

import pytest
from pydantic import ValidationError

from dnd_sim.capability_manifest import (
    build_feature_capability_manifest,
    load_feature_payloads,
)


def test_feature_manifest_emits_feat_trait_background_species_records() -> None:
    payloads = [
        {
            "name": "Alert",
            "source_type": "feat",
            "mechanics": [{"effect_type": "initiative_bonus"}],
        },
        {
            "name": "Dock Contact",
            "source_type": "background",
            "mechanics": [{"meta_type": "social_contact"}],
        },
        {
            "name": "Natural Athlete",
            "source_type": "species",
            "mechanics": [{"meta_type": "skill_proficiency"}],
        },
        {
            "name": "Arcane Recovery",
            "source_type": "class",
            "mechanics": [{"meta_type": "spell_slot_recovery"}],
        },
    ]

    manifest = build_feature_capability_manifest(feature_payloads=payloads)
    by_type = {record.content_type: record for record in manifest.records}

    assert set(by_type) == {"feat", "background", "species", "trait"}
    for record in manifest.records:
        assert record.runtime_hook_family is not None
        assert record.support_state in {"supported", "unsupported"}
        if record.support_state == "supported":
            assert record.states.blocked is False
            assert record.states.unsupported_reason is None


def test_feature_manifest_rejects_duplicate_content_ids() -> None:
    payloads = [
        {
            "name": "Alert",
            "source_type": "feat",
            "content_id": "feat:alert",
            "mechanics": [{"effect_type": "initiative_bonus"}],
        },
        {
            "name": "Alert Duplicate",
            "source_type": "feat",
            "content_id": "feat:alert",
            "mechanics": [{"effect_type": "initiative_bonus"}],
        },
    ]

    with pytest.raises(ValidationError) as exc_info:
        build_feature_capability_manifest(feature_payloads=payloads)

    assert "duplicate content_id" in str(exc_info)


def test_feature_manifest_sets_explicit_reason_for_unsupported_feature() -> None:
    payloads = [
        {
            "name": "Flavorful Feature",
            "source_type": "background",
            "mechanics": [],
        }
    ]

    manifest = build_feature_capability_manifest(feature_payloads=payloads)
    record = manifest.records[0]

    assert record.content_type == "background"
    assert record.runtime_hook_family == "narrative"
    assert record.support_state == "unsupported"
    assert record.states.blocked is True
    assert record.states.unsupported_reason == "missing_runtime_hook_family"


def test_background_shard_a_features_have_runtime_hook_family_support() -> None:
    manifest = build_feature_capability_manifest(feature_payloads=load_feature_payloads())
    by_content_id = {record.content_id: record for record in manifest.records}

    expected_ids = {
        "background:criminal_contact",
        "background:guild_membership",
        "background:military_rank",
        "background:position_of_privilege",
        "background:researcher",
        "background:rustic_hospitality",
        "background:shelter_of_the_faithful",
        "background:ship_s_passage",
    }

    for content_id in expected_ids:
        record = by_content_id[content_id]
        assert record.content_type == "background"
        assert record.runtime_hook_family == "meta"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.unsupported_reason is None
