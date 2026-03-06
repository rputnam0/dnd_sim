from __future__ import annotations

import csv
import json
from pathlib import Path

from dnd_sim.capability_manifest import build_feature_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs" / "program" / "parity_leaf_registry.csv"
TRAITS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "traits"

SLICE_ONE_F1_TRAIT_IDS = {
    "trait:aura_of_conquest",
    "trait:aura_of_hate",
    "trait:aura_of_malevolence",
    "trait:blazing_revival",
    "trait:blessed_healer",
    "trait:blessed_strikes",
    "trait:bulwark",
    "trait:bulwark_of_force",
}

SLICE_TWO_F1_TRAIT_IDS = {
    "trait:aquatic_affinity",
    "trait:armor_modifications",
    "trait:divine_intervention_improvement",
    "trait:greater_portent",
    "trait:persistent_rage",
    "trait:purity_of_body",
    "trait:sculpt_spells",
    "trait:song_of_rest_d12",
    "trait:unyielding_spirit",
    "trait:words_of_creation",
}

COVERED_F1_TRAIT_IDS = SLICE_ONE_F1_TRAIT_IDS | SLICE_TWO_F1_TRAIT_IDS


def _owned_f1_trait_ids() -> set[str]:
    owned: set[str] = set()
    with REGISTRY_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("leaf_task_id") == "W6-PAR-05F1":
                content_id = str(row.get("content_id", "")).strip()
                if content_id:
                    owned.add(content_id)
    assert owned.issuperset(COVERED_F1_TRAIT_IDS)
    assert len(owned) >= len(COVERED_F1_TRAIT_IDS)
    return owned


def test_w6_par_05f1_registry_still_covers_this_slice() -> None:
    owned_ids = _owned_f1_trait_ids()
    assert COVERED_F1_TRAIT_IDS <= owned_ids


def test_trait_defense_support_covered_records_are_supported() -> None:
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(COVERED_F1_TRAIT_IDS - set(by_id))
    assert missing_ids == []

    blocked_traits_missing_hook = {
        record.content_id
        for record in manifest.records
        if record.content_type == "trait"
        and record.states.unsupported_reason == "missing_runtime_hook_family"
    }
    assert blocked_traits_missing_hook.isdisjoint(COVERED_F1_TRAIT_IDS)

    for content_id in COVERED_F1_TRAIT_IDS:
        record = by_id[content_id]
        assert record.content_type == "trait"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.runtime_hook_family == "meta"


def test_w6_par_05f1_trait_files_use_meta_rows_only() -> None:
    owned_ids = COVERED_F1_TRAIT_IDS

    for content_id in sorted(owned_ids):
        trait_id = content_id.split(":", 1)[1]
        path = TRAITS_DIR / f"{trait_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        mechanics = payload.get("mechanics")
        assert isinstance(mechanics, list), f"{content_id} mechanics must be a list"
        assert mechanics, f"{content_id} mechanics must not be empty"
        for idx, row in enumerate(mechanics):
            assert isinstance(row, dict), f"{content_id} mechanics[{idx}] must be object"
            meta_type = str(row.get("meta_type", "")).strip()
            assert meta_type, f"{content_id} mechanics[{idx}] missing meta_type"
            assert "effect_type" not in row, (
                f"{content_id} mechanics[{idx}] must not define effect_type for F1 meta scope"
            )
        issues = validate_rule_mechanics_payload(kind="trait", payload=payload)
        assert issues == [], f"{content_id} has schema issues: {issues}"
