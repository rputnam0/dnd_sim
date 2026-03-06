from __future__ import annotations

from dnd_sim import io
from dnd_sim.capability_manifest import build_feature_capability_manifest

SHARD_C_SPECIES_IDS = {
    "species:elf_weapon_training",
    "species:feat",
    "species:firearms_mastery",
    "species:hunter_s_instincts",
    "species:kenku_training",
    "species:martial_training",
    "species:natural_affinity",
    "species:nature_s_intuition",
    "species:primal_intuition",
    "species:tool_proficiency",
}


def test_species_hook_shard_c_records_are_supported_in_feature_manifest() -> None:
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(SHARD_C_SPECIES_IDS - set(by_id))
    assert missing_ids == []

    for content_id in sorted(SHARD_C_SPECIES_IDS):
        record = by_id[content_id]
        assert record.content_type == "species"
        assert record.runtime_hook_family == "meta"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.unsupported_reason is None


def test_species_hook_shard_c_records_are_supported_in_canonical_capability_records() -> None:
    io._canonical_capability_records.cache_clear()
    by_id = {record.content_id: record for record in io._canonical_capability_records()}

    missing_ids = sorted(SHARD_C_SPECIES_IDS - set(by_id))
    assert missing_ids == []

    for content_id in sorted(SHARD_C_SPECIES_IDS):
        record = by_id[content_id]
        assert record.content_type == "species"
        assert record.runtime_hook_family == "meta"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.unsupported_reason is None
