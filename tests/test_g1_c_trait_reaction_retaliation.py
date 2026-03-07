from __future__ import annotations

import csv
import json
from pathlib import Path

from dnd_sim.capability_manifest import build_feature_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_REGISTRY_PATH = REPO_ROOT / "docs" / "program" / "parity_batch_registry.csv"
TRAITS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "traits"
G1_C_IDS = {
    "trait:master_transmuter",
    "trait:misty_escape",
    "trait:opportunist",
    "trait:planar_warrior",
    "trait:psychic_blades",
    "trait:relentless_avenger",
    "trait:rend_mind",
    "trait:shadowy_dodge",
    "trait:spreading_spores",
    "trait:stalker_s_flurry",
}


def _owned_g1_c_trait_ids() -> set[str]:
    owned: set[str] = set()
    with BATCH_REGISTRY_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if (
                row.get("batch_id") == "G1-C"
                and row.get("leaf_task_id") == "W6-PAR-05G1"
                and row.get("content_type") == "trait"
                and row.get("prompt_family") == "trait_reaction_retaliation"
                and row.get("target_test_file")
                == "tests/test_g1_c_trait_reaction_retaliation.py"
                and row.get("branch_name")
                == "codex/feat/g1-c-trait-reaction-retaliation"
            ):
                content_id = str(row.get("content_id", "")).strip()
                if content_id:
                    owned.add(content_id)

    assert owned == G1_C_IDS
    return owned


def test_g1_c_owned_trait_records_are_supported() -> None:
    owned_ids = _owned_g1_c_trait_ids()
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


def test_g1_c_trait_files_use_canonical_mechanics_rows() -> None:
    owned_ids = _owned_g1_c_trait_ids()

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
