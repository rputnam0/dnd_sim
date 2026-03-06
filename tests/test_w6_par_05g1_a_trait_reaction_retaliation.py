from __future__ import annotations

import csv
import json
from pathlib import Path

from dnd_sim.capability_manifest import build_feature_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs" / "program" / "parity_leaf_registry.csv"
TRAITS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "traits"
G1_A_IDS = {
    "trait:ambush_master",
    "trait:armor_of_hexes",
    "trait:blaze_of_glory",
    "trait:defy_death",
    "trait:elemental_attunement",
    "trait:emboldening_bond",
    "trait:emissary_of_redemption",
    "trait:eventide_s_splendor",
    "trait:favored_by_the_gods",
    "trait:gathered_swarm",
}


def _owned_g1_a_trait_ids() -> set[str]:
    owned: set[str] = set()
    with REGISTRY_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if (
                row.get("leaf_task_id") == "W6-PAR-05G1-A"
                and row.get("target_family") == "trait_reaction_retaliation"
                and row.get("notes") == "g1-a reaction-retaliation batch"
            ):
                content_id = str(row.get("content_id", "")).strip()
                if content_id:
                    owned.add(content_id)

    assert owned == G1_A_IDS
    return owned


def test_w6_par_05g1_a_owned_trait_records_are_supported() -> None:
    owned_ids = _owned_g1_a_trait_ids()
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(owned_ids - set(by_id))
    assert missing_ids == []

    blocked_traits_missing_hook = {
        record.content_id
        for record in manifest.records
        if record.content_type == "trait"
        and record.states.unsupported_reason == "missing_runtime_hook_family"
    }
    assert blocked_traits_missing_hook.isdisjoint(owned_ids)

    for content_id in sorted(owned_ids):
        record = by_id[content_id]
        assert record.content_type == "trait"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.unsupported_reason is None
        assert record.runtime_hook_family == "meta"


def test_w6_par_05g1_a_trait_files_use_canonical_meta_rows() -> None:
    owned_ids = _owned_g1_a_trait_ids()

    for content_id in sorted(owned_ids):
        trait_id = content_id.split(":", 1)[1]
        path = TRAITS_DIR / f"{trait_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))

        mechanics = payload.get("mechanics")
        assert isinstance(mechanics, list), f"{content_id} mechanics must be a list"
        assert mechanics, f"{content_id} mechanics must not be empty"

        for idx, row in enumerate(mechanics):
            assert isinstance(row, dict), f"{content_id} mechanics[{idx}] must be object"
            assert str(
                row.get("meta_type", "")
            ).strip(), f"{content_id} mechanics[{idx}] missing meta_type"

        issues = validate_rule_mechanics_payload(kind="trait", payload=payload)
        assert issues == [], f"{content_id} has schema issues: {issues}"
