from __future__ import annotations

import csv
import json
from pathlib import Path

from dnd_sim.capability_manifest import build_feature_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs/program/parity_leaf_registry.csv"


def _w6_par_05e1_trait_ids() -> set[str]:
    with REGISTRY_PATH.open(newline="", encoding="utf-8") as handle:
        ids = {
            str(row["content_id"])
            for row in csv.DictReader(handle)
            if str(row.get("leaf_task_id", "")).strip() == "W6-PAR-05E1"
        }
    assert len(ids) == 88
    return ids


def test_w6_par_05e1_trait_records_are_supported() -> None:
    owned_ids = _w6_par_05e1_trait_ids()

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
        assert record.runtime_hook_family == "meta"


def test_w6_par_05e1_trait_files_use_meta_rows_only() -> None:
    owned_ids = _w6_par_05e1_trait_ids()
    traits_dir = REPO_ROOT / "db" / "rules" / "2014" / "traits"

    for content_id in sorted(owned_ids):
        slug = content_id.split(":", 1)[1]
        payload = json.loads((traits_dir / f"{slug}.json").read_text(encoding="utf-8"))
        mechanics = payload.get("mechanics")

        assert payload.get("source_type") == "class" or payload.get("source_type") == "subclass"
        assert isinstance(mechanics, list)
        assert mechanics != []
        assert all(isinstance(row, dict) for row in mechanics)
        assert all(str(row.get("meta_type", "")).strip() for row in mechanics)
        assert all("effect_type" not in row for row in mechanics)

        issues = validate_rule_mechanics_payload(kind="trait", payload=payload)
        assert issues == [], f"{content_id} has schema issues: {issues}"
