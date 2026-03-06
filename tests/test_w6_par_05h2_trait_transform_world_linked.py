from __future__ import annotations

import csv
import json
from pathlib import Path

from dnd_sim.capability_manifest import build_feature_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs/program/parity_leaf_registry.csv"

INITIAL_CHECKPOINT_IDS: set[str] = {
    "trait:beast_spells",
    "trait:elemental_wild_shape",
    "trait:forms_of_your_astral_self",
    "trait:path_of_wild_magic",
    "trait:thousand_forms",
    "trait:wild_magic",
    "trait:wild_magic_sorcery",
    "trait:wild_shape_improvement",
}


def _w6_par_05h2_trait_ids() -> set[str]:
    with REGISTRY_PATH.open(newline="", encoding="utf-8") as handle:
        ids = {
            str(row["content_id"])
            for row in csv.DictReader(handle)
            if str(row.get("leaf_task_id", "")).strip() == "W6-PAR-05H2"
        }
    assert len(ids) == 22
    return ids


def test_w6_par_05h2_initial_checkpoint_records_are_supported() -> None:
    owned_ids = _w6_par_05h2_trait_ids()
    assert INITIAL_CHECKPOINT_IDS <= owned_ids

    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(INITIAL_CHECKPOINT_IDS - set(by_id))
    assert missing_ids == []

    for content_id in sorted(INITIAL_CHECKPOINT_IDS):
        record = by_id[content_id]
        assert record.content_type == "trait"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.runtime_hook_family in {"meta", "effect", "effect_meta"}


def test_w6_par_05h2_initial_checkpoint_traits_use_canonical_mechanics() -> None:
    traits_dir = REPO_ROOT / "db" / "rules" / "2014" / "traits"

    for content_id in sorted(INITIAL_CHECKPOINT_IDS):
        slug = content_id.split(":", 1)[1]
        payload = json.loads((traits_dir / f"{slug}.json").read_text(encoding="utf-8"))
        mechanics = payload.get("mechanics")

        assert isinstance(mechanics, list)
        assert mechanics != []
        assert all(isinstance(row, dict) for row in mechanics)
        assert all(
            str(row.get("meta_type", "")).strip() or str(row.get("effect_type", "")).strip()
            for row in mechanics
        )

        issues = validate_rule_mechanics_payload(kind="trait", payload=payload)
        assert issues == [], f"{content_id} has schema issues: {issues}"
