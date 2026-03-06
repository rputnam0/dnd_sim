from __future__ import annotations

import csv
import json
from pathlib import Path

from dnd_sim.capability_manifest import build_feature_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs" / "program" / "parity_leaf_registry.csv"
TRAITS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "traits"


def _owned_trait_families() -> dict[str, str]:
    owned: dict[str, str] = {}
    with REGISTRY_PATH.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("leaf_task_id") != "W6-PAR-05E2":
                continue
            content_id = str(row["content_id"])
            owned[content_id] = str(row["target_family"])
    return owned


OWNED_TRAIT_FAMILIES = _owned_trait_families()
OUT_OF_SCOPE_COMBAT_TRAIT_IDS = {
    "trait:ambush_master",
    "trait:destroy_undead_cr_1",
    "trait:destroy_undead_cr_1_2",
    "trait:destroy_undead_cr_2",
    "trait:destroy_undead_cr_3",
    "trait:destroy_undead_cr_4",
    "trait:flexible_casting",
    "trait:frenzy",
    "trait:hexblade_s_curse",
    "trait:lay_on_hands",
    "trait:second_wind",
}


def test_w6_par_05e2_registry_owned_trait_records_are_supported() -> None:
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(set(OWNED_TRAIT_FAMILIES) - set(by_id))
    assert missing_ids == []

    blocked_traits_missing_hook = {
        record.content_id
        for record in manifest.records
        if record.content_type == "trait"
        and record.states.unsupported_reason == "missing_runtime_hook_family"
    }
    assert blocked_traits_missing_hook.isdisjoint(OWNED_TRAIT_FAMILIES)

    for content_id in sorted(OWNED_TRAIT_FAMILIES):
        record = by_id[content_id]
        assert record.content_type == "trait"
        assert record.support_state == "supported"
        assert record.runtime_hook_family == "meta"
        assert record.states.blocked is False
        assert record.states.unsupported_reason is None


def test_w6_par_05e2_owned_trait_files_use_canonical_meta_rows() -> None:
    for content_id, expected_meta_type in OWNED_TRAIT_FAMILIES.items():
        trait_id = content_id.split(":", 1)[1]
        path = TRAITS_DIR / f"{trait_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))

        issues = validate_rule_mechanics_payload(kind="trait", payload=payload)
        assert issues == [], f"{content_id} has schema issues: {issues}"

        mechanics = payload.get("mechanics")
        assert isinstance(mechanics, list) and mechanics, f"{content_id} must define mechanics"

        for row in mechanics:
            assert isinstance(row, dict), f"{content_id} mechanics rows must be objects"
            assert row.get("meta_type") == expected_meta_type
            assert not str(row.get("effect_type", "")).strip()


def test_w6_par_05e2_leaves_combat_runtime_traits_out_of_scope() -> None:
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    assert OUT_OF_SCOPE_COMBAT_TRAIT_IDS.isdisjoint(OWNED_TRAIT_FAMILIES)

    for content_id in sorted(OUT_OF_SCOPE_COMBAT_TRAIT_IDS):
        record = by_id[content_id]
        assert record.content_type == "trait"
        assert record.states.blocked is True

        trait_id = content_id.split(":", 1)[1]
        path = TRAITS_DIR / f"{trait_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        mechanics = payload.get("mechanics")
        assert isinstance(mechanics, list)
        assert all(
            row.get("meta_type") != "trait_meta_social_support"
            for row in mechanics
            if isinstance(row, dict)
        )
