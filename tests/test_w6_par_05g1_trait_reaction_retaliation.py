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
