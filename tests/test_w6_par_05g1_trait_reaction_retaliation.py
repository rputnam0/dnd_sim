from __future__ import annotations

import csv
import json
from pathlib import Path

from dnd_sim.capability_manifest import build_feature_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs" / "program" / "parity_leaf_registry.csv"
TRAITS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "traits"
RETARGETED_ACTION_IDS = {
    "trait:abjure_enemy",
    "trait:champion_challenge",
    "trait:conquering_presence",
    "trait:control_undead",
    "trait:countercharm",
    "trait:dreadful_aspect",
}
CONTINUATION_SLICE_IDS = {
    "trait:ambush_master",
    "trait:blaze_of_glory",
    "trait:elemental_attunement",
    "trait:emboldening_bond",
    "trait:emissary_of_redemption",
    "trait:eventide_s_splendor",
    "trait:gathered_swarm",
    "trait:genie_s_wrath",
}
CONTINUATION_SLICE_META_TYPES = {
    "ambush_master": {"initiative", "grant_advantage"},
    "blaze_of_glory": {"reaction_movement", "retaliation_attack", "death"},
    "elemental_attunement": {
        "resource_spend",
        "duration",
        "reach_increase",
        "damage_type_choice",
        "push",
    },
    "emboldening_bond": {"action", "roll_bonus", "resource"},
    "emissary_of_redemption": {"damage_resistance", "damage_reflection", "restriction"},
    "eventide_s_splendor": {"invisibility", "teleport", "resource_substitution"},
    "gathered_swarm": {"extra_damage", "push", "movement"},
    "genie_s_wrath": {"extra_damage"},
}


def _all_g1_trait_ids() -> set[str]:
    owned: set[str] = set()
    with REGISTRY_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("leaf_task_id") == "W6-PAR-05G1":
                content_id = str(row.get("content_id", "")).strip()
                if content_id:
                    owned.add(content_id)
    assert len(owned) == 73
    return owned


def _owned_g1_trait_ids() -> set[str]:
    owned: set[str] = set()
    with REGISTRY_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if (
                row.get("leaf_task_id") == "W6-PAR-05G1"
                and row.get("target_family") == "trait_reaction_retaliation"
                and row.get("notes") == "reaction or retaliation family"
            ):
                content_id = str(row.get("content_id", "")).strip()
                if content_id:
                    owned.add(content_id)
    assert len(owned) == 13
    assert owned.isdisjoint(RETARGETED_ACTION_IDS)
    return owned


def test_w6_par_05g1_registry_retargets_action_traits_to_g2() -> None:
    by_id: dict[str, tuple[str, str]] = {}
    with REGISTRY_PATH.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            content_id = str(row.get("content_id", "")).strip()
            if content_id:
                by_id[content_id] = (
                    str(row.get("leaf_task_id", "")).strip(),
                    str(row.get("target_family", "")).strip(),
                )

    for content_id in sorted(RETARGETED_ACTION_IDS):
        leaf_task_id, target_family = by_id[content_id]
        assert leaf_task_id == "W6-PAR-05G2"
        assert target_family == "trait_resource_turn_gated"


def test_w6_par_05g1_continuation_slice_belongs_to_registry() -> None:
    assert CONTINUATION_SLICE_IDS <= _all_g1_trait_ids()


def test_w6_par_05g1_owned_trait_records_are_supported() -> None:
    owned_ids = _owned_g1_trait_ids()
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


def test_w6_par_05g1_continuation_slice_records_are_supported() -> None:
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(CONTINUATION_SLICE_IDS - set(by_id))
    assert missing_ids == []

    for content_id in sorted(CONTINUATION_SLICE_IDS):
        record = by_id[content_id]
        assert record.content_type == "trait"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.runtime_hook_family == "meta"


def test_w6_par_05g1_trait_files_use_canonical_mechanics_rows() -> None:
    owned_ids = _owned_g1_trait_ids()

    for content_id in sorted(owned_ids):
        trait_id = content_id.split(":", 1)[1]
        path = TRAITS_DIR / f"{trait_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        mechanics = payload.get("mechanics")
        assert isinstance(mechanics, list), f"{content_id} mechanics must be a list"
        assert mechanics, f"{content_id} mechanics must not be empty"
        for idx, row in enumerate(mechanics):
            assert isinstance(row, dict), f"{content_id} mechanics[{idx}] must be object"
            assert str(row.get("meta_type", "")).strip(), (
                f"{content_id} mechanics[{idx}] missing meta_type"
            )
        issues = validate_rule_mechanics_payload(kind="trait", payload=payload)
        assert issues == [], f"{content_id} has schema issues: {issues}"


def test_w6_par_05g1_continuation_slice_uses_expected_meta_types() -> None:
    for trait_id, expected_meta_types in sorted(CONTINUATION_SLICE_META_TYPES.items()):
        payload = json.loads((TRAITS_DIR / f"{trait_id}.json").read_text(encoding="utf-8"))
        mechanics = payload.get("mechanics")
        assert isinstance(mechanics, list), f"trait:{trait_id} mechanics must be a list"
        assert mechanics, f"trait:{trait_id} mechanics must not be empty"

        seen_meta_types = {
            str(row.get("meta_type", "")).strip()
            for row in mechanics
            if isinstance(row, dict)
        }
        assert expected_meta_types <= seen_meta_types

        issues = validate_rule_mechanics_payload(kind="trait", payload=payload)
        assert issues == [], f"trait:{trait_id} has schema issues: {issues}"
