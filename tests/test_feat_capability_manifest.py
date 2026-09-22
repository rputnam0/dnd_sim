from __future__ import annotations

import pytest
from pydantic import ValidationError

from dnd_sim.capability_manifest import (
    build_feature_capability_manifest,
    load_feature_payloads,
)

SHARD_A_SPECIES_IDS = {
    "species:ambusher",
    "species:amorphous",
    "species:amphibious",
    "species:bestial_instincts",
    "species:black_blood_healing",
    "species:brave",
}
SHARD_B_SPECIES_IDS = {
    "species:cat_s_talents",
    "species:celestial_resistance",
    "species:climbing",
    "species:damage_resistance",
    "species:dwarven_combat_training",
    "species:emissary_of_the_sea",
}

SHARD_B_TRAIT_IDS = {
    "trait:acrobatic_movement",
    "trait:action_surge",
    "trait:action_surge_two_uses",
    "trait:additional_superiority_die",
    "trait:arcane_charge",
    "trait:arcane_ward",
    "trait:archdruid",
    "trait:aura_expansion",
    "trait:aura_improvements",
    "trait:aura_of_alacrity",
}


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


def test_feature_manifest_marks_runtime_effect_supported() -> None:
    manifest = build_feature_capability_manifest(
        feature_payloads=[
            {
                "name": "Battle Blessing",
                "source_type": "feat",
                "mechanics": [{"effect_type": "max_hp_increase", "calculation": "character_level"}],
            }
        ]
    )

    record = manifest.records[0]
    assert record.runtime_hook_family == "effect"
    assert record.support_state == "supported"
    assert record.states.schema_valid is True
    assert record.states.executable is True
    assert record.states.tested is False
    assert record.states.blocked is False
    assert record.states.unsupported_reason is None


def test_feature_manifest_uses_unsupported_effect_type_reason() -> None:
    manifest = build_feature_capability_manifest(
        feature_payloads=[
            {
                "name": "Alert",
                "source_type": "feat",
                "mechanics": [{"effect_type": "initiative_bonus", "amount": 5}],
            }
        ]
    )

    record = manifest.records[0]
    assert record.runtime_hook_family == "effect"
    assert record.support_state == "unsupported"
    assert record.states.schema_valid is False
    assert record.states.executable is False
    assert record.states.blocked is True
    assert record.states.unsupported_reason == "unsupported_effect_type"


def test_feature_manifest_uses_invalid_mechanics_schema_reason() -> None:
    manifest = build_feature_capability_manifest(
        feature_payloads=[
            {
                "name": "Incomplete Ward",
                "source_type": "class",
                "mechanics": [{"effect_type": "temp_hp"}],
            }
        ]
    )

    record = manifest.records[0]
    assert record.runtime_hook_family == "invalid"
    assert record.support_state == "unsupported"
    assert record.states.schema_valid is False
    assert record.states.executable is False
    assert record.states.blocked is True
    assert record.states.unsupported_reason == "invalid_mechanics_schema"


@pytest.mark.parametrize(
    "mechanics",
    [
        [{"meta_type": "skill_proficiency"}],
        [{"effect_type": "note", "text": "Narrative guidance only."}],
        [{"effect_type": "area", "radius_ft": 10}],
        [{"effect_type": "temp_hp", "amount": "1d6"}],
    ],
)
def test_feature_manifest_marks_metadata_and_no_op_mechanics_non_executable(
    mechanics: list[dict[str, object]],
) -> None:
    manifest = build_feature_capability_manifest(
        feature_payloads=[
            {
                "name": "Feature Marker",
                "source_type": "species",
                "mechanics": mechanics,
            }
        ]
    )

    record = manifest.records[0]
    assert record.support_state == "unsupported"
    assert record.states.schema_valid is True
    assert record.states.executable is False
    assert record.states.blocked is True
    assert record.states.unsupported_reason == "non_executable_mechanics"


def test_feature_manifest_accepts_metadata_when_paired_with_runtime_effect() -> None:
    manifest = build_feature_capability_manifest(
        feature_payloads=[
            {
                "name": "Ward Aura",
                "source_type": "species",
                "mechanics": [
                    {"meta_type": "aura_radius", "radius_ft": 10},
                    {"effect_type": "max_hp_increase", "calculation": "character_level"},
                ],
            }
        ]
    )

    record = manifest.records[0]
    assert record.runtime_hook_family == "effect_meta"
    assert record.support_state == "supported"
    assert record.states.schema_valid is True
    assert record.states.executable is True
    assert record.states.blocked is False
    assert record.states.unsupported_reason is None


def test_feature_manifest_rejects_invalid_row_even_with_runtime_effect() -> None:
    manifest = build_feature_capability_manifest(
        feature_payloads=[
            {
                "name": "Mixed Mechanics",
                "source_type": "feat",
                "mechanics": [
                    {"effect_type": "temp_hp", "amount": 3},
                    {"effect_type": "initiative_bonus", "amount": 5},
                ],
            }
        ]
    )

    record = manifest.records[0]
    assert record.support_state == "unsupported"
    assert record.states.schema_valid is False
    assert record.states.executable is False
    assert record.states.blocked is True
    assert record.states.unsupported_reason == "unsupported_effect_type"


def test_trait_hook_shard_a_distinguishes_executable_effects_from_metadata() -> None:
    expected_states = {
        "trait:dark_one_s_blessing": (
            "effect",
            "unsupported",
            "non_executable_mechanics",
        ),
        "trait:ever_ready_shot": ("effect", "unsupported", "non_executable_mechanics"),
        "trait:expertise": ("meta", "unsupported", "non_executable_mechanics"),
        "trait:magical_ambush": ("meta", "unsupported", "non_executable_mechanics"),
        "trait:precise_hunter": ("meta", "unsupported", "non_executable_mechanics"),
        "trait:steady_eye": ("meta", "unsupported", "non_executable_mechanics"),
        "trait:tool_expertise": ("meta", "unsupported", "non_executable_mechanics"),
        "trait:uncanny_dodge": ("effect", "supported", None),
    }

    manifest = build_feature_capability_manifest()
    records = {record.content_id: record for record in manifest.records}

    assert expected_states.keys() <= records.keys()
    for trait_id, (expected_family, expected_support, expected_reason) in expected_states.items():
        record = records[trait_id]
        assert record.runtime_hook_family == expected_family
        assert record.support_state == expected_support
        assert record.states.executable is (expected_support == "supported")
        assert record.states.blocked is (expected_support == "unsupported")
        assert record.states.unsupported_reason == expected_reason


def test_background_shard_a_metadata_is_cataloged_but_non_executable() -> None:
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
        assert record.support_state == "unsupported"
        assert record.states.executable is False
        assert record.states.blocked is True
        assert record.states.unsupported_reason == "non_executable_mechanics"


def test_background_shard_b_metadata_is_cataloged_but_non_executable() -> None:
    manifest = build_feature_capability_manifest(feature_payloads=load_feature_payloads())
    by_content_id = {record.content_id: record for record in manifest.records}

    expected_ids = {
        "background:legal_authority",
        "background:library_access",
        "background:official_inquiry",
        "background:safe_haven",
        "background:secret_identity",
        "background:secret_passage",
        "background:secret_society",
        "background:voice_of_authority",
    }

    for content_id in expected_ids:
        record = by_content_id[content_id]
        assert record.content_type == "background"
        assert record.runtime_hook_family == "meta"
        assert record.support_state == "unsupported"
        assert record.states.executable is False
        assert record.states.blocked is True
        assert record.states.unsupported_reason == "non_executable_mechanics"


def test_species_hook_shard_a_unsupported_effects_are_not_executable() -> None:
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(SHARD_A_SPECIES_IDS - set(by_id))
    assert missing_ids == []

    for content_id in sorted(SHARD_A_SPECIES_IDS):
        record = by_id[content_id]
        assert record.content_type == "species"
        assert record.runtime_hook_family == "effect"
        assert record.support_state == "unsupported"
        assert record.states.schema_valid is False
        assert record.states.executable is False
        assert record.states.blocked is True
        assert record.states.unsupported_reason == "unsupported_effect_type"


def test_species_hook_shard_b_metadata_is_not_executable() -> None:
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(SHARD_B_SPECIES_IDS - set(by_id))
    assert missing_ids == []

    for content_id in sorted(SHARD_B_SPECIES_IDS):
        record = by_id[content_id]
        assert record.content_type == "species"
        assert record.runtime_hook_family == "meta"
        assert record.support_state == "unsupported"
        assert record.states.schema_valid is True
        assert record.states.executable is False
        assert record.states.blocked is True
        assert record.states.unsupported_reason == "non_executable_mechanics"


def test_trait_hook_shard_b_metadata_is_not_executable() -> None:
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(SHARD_B_TRAIT_IDS - set(by_id))
    assert missing_ids == []

    for content_id in sorted(SHARD_B_TRAIT_IDS):
        record = by_id[content_id]
        assert record.content_type == "trait"
        assert record.runtime_hook_family == "meta"
        assert record.support_state == "unsupported"
        assert record.states.schema_valid is True
        assert record.states.executable is False
        assert record.states.blocked is True
        assert record.states.unsupported_reason == "non_executable_mechanics"
