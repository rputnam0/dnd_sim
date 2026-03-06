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
G1D_SURVIVAL_CLUSTER_IDS = {
    "trait:chalice",
    "trait:mastery_of_death",
    "trait:oketra_s_blessing",
    "trait:perfect_self",
    "trait:rallying_cry",
    "trait:reclaim_potential",
    "trait:relentless_rage",
    "trait:rhonas_s_blessing",
    "trait:searing_vengeance",
    "trait:slow_fall",
    "trait:spell_breaker",
    "trait:strength_before_death",
    "trait:strength_of_the_grave",
    "trait:tides_of_chaos",
    "trait:tireless_spirit",
    "trait:uncanny_metabolism",
    "trait:vitality_of_the_tree",
}
CONTINUATION_SLICE_IDS = {
    "trait:master_duelist",
    "trait:order_s_wrath",
    "trait:slayer_s_prey",
    "trait:slow_fall",
    "trait:tactical_shift",
    "trait:tides_of_chaos",
    "trait:tireless_spirit",
    "trait:wails_from_the_grave",
}
CONTINUATION_SLICE_REGISTRY_ASSIGNMENTS = {
    "trait:master_duelist": "W6-PAR-05G1",
    "trait:order_s_wrath": "W6-PAR-05G1",
    "trait:slayer_s_prey": "W6-PAR-05G1",
    "trait:slow_fall": "W6-PAR-05G1D",
    "trait:tactical_shift": "W6-PAR-05G1",
    "trait:tides_of_chaos": "W6-PAR-05G1D",
    "trait:tireless_spirit": "W6-PAR-05G1D",
    "trait:wails_from_the_grave": "W6-PAR-05G1",
}
CONTINUATION_SLICE_META_TYPES = {
    "master_duelist": {"reroll", "recharge"},
    "order_s_wrath": {"mark", "extra_damage"},
    "slayer_s_prey": {"mark", "extra_damage"},
    "slow_fall": {"fall_damage_reduction_support"},
    "tactical_shift": {"movement"},
    "tides_of_chaos": {
        "advantage_resource_support",
        "wild_magic_recharge_support",
    },
    "tireless_spirit": {"resource_recovery_support"},
    "wails_from_the_grave": {"extra_damage", "resource"},
}

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


def _owned_g1d_trait_ids() -> set[str]:
    owned: set[str] = set()
    with REGISTRY_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if (
                row.get("leaf_task_id") == "W6-PAR-05G1D"
                and row.get("target_family") == "trait_survival_recovery_support"
                and row.get("notes") == "survival, recovery, or resilience support family"
            ):
                content_id = str(row.get("content_id", "")).strip()
                if content_id:
                    owned.add(content_id)
    assert len(owned) == 17
    assert owned == G1D_SURVIVAL_CLUSTER_IDS
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
    assignments: dict[str, str] = {}
    with REGISTRY_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            content_id = str(row.get("content_id", "")).strip()
            if content_id in CONTINUATION_SLICE_IDS:
                assignments[content_id] = str(row.get("leaf_task_id", "")).strip()

    assert assignments == CONTINUATION_SLICE_REGISTRY_ASSIGNMENTS


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
            assert str(
                row.get("meta_type", "")
            ).strip(), f"{content_id} mechanics[{idx}] missing meta_type"
        issues = validate_rule_mechanics_payload(kind="trait", payload=payload)
        assert issues == [], f"{content_id} has schema issues: {issues}"


def test_w6_par_05g1d_owned_trait_records_are_supported() -> None:
    owned_ids = _owned_g1d_trait_ids()
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


def test_w6_par_05g1d_trait_files_use_canonical_mechanics_rows() -> None:
    owned_ids = _owned_g1d_trait_ids()

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
            assert (
                "effect_type" not in row
            ), f"{content_id} mechanics[{idx}] must not define effect_type"
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


def test_w6_par_05g1_tides_of_chaos_preserves_structured_single_use_limit() -> None:
    payload = json.loads((TRAITS_DIR / "tides_of_chaos.json").read_text(encoding="utf-8"))
    limited_rows = [
        row
        for row in payload.get("mechanics", [])
        if isinstance(row, dict) and row.get("uses") == 1
    ]

    assert len(limited_rows) == 1
    assert limited_rows[0].get("recharge") == "long_rest"
