from __future__ import annotations

import csv
import json
from pathlib import Path

from dnd_sim.capability_manifest import build_spell_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs" / "program" / "parity_leaf_registry.csv"
SPELLS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "spells"

SLICE_ONE_J2_SPELL_IDS = {
    "spell:arcane_eye",
    "spell:clairvoyance",
    "spell:detect_evil_and_good",
    "spell:detect_magic",
    "spell:detect_poison_and_disease",
    "spell:detect_thoughts",
    "spell:find_traps",
    "spell:locate_object",
}


def _owned_j2_spell_ids() -> set[str]:
    owned: set[str] = set()
    with REGISTRY_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("leaf_task_id") == "W6-PAR-05J2":
                content_id = str(row.get("content_id", "")).strip()
                if content_id:
                    owned.add(content_id)
    assert owned.issuperset(SLICE_ONE_J2_SPELL_IDS)
    return owned


def test_w6_par_05j2_slice_one_spells_are_supported() -> None:
    manifest = build_spell_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(SLICE_ONE_J2_SPELL_IDS - set(by_id))
    assert missing_ids == []

    blocked_missing_mechanics = {
        record.content_id
        for record in manifest.records
        if record.content_type == "spell"
        and record.states.unsupported_reason == "missing_runtime_mechanics"
    }
    assert blocked_missing_mechanics.isdisjoint(SLICE_ONE_J2_SPELL_IDS)

    for content_id in sorted(SLICE_ONE_J2_SPELL_IDS):
        record = by_id[content_id]
        assert record.content_type == "spell"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.runtime_hook_family == "effect"


def test_w6_par_05j2_owned_spell_blockers_shrink_after_slice_one() -> None:
    owned_ids = _owned_j2_spell_ids()
    manifest = build_spell_capability_manifest()

    blocked_owned = {
        record.content_id
        for record in manifest.records
        if record.content_id in owned_ids and record.states.blocked
    }

    assert SLICE_ONE_J2_SPELL_IDS.isdisjoint(blocked_owned)
    assert 0 < len(blocked_owned) < len(owned_ids)


def test_w6_par_05j2_slice_one_spell_files_use_canonical_sense_rows() -> None:
    for content_id in sorted(SLICE_ONE_J2_SPELL_IDS):
        spell_id = content_id.split(":", 1)[1]
        path = SPELLS_DIR / f"{spell_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        mechanics = payload.get("mechanics")
        assert isinstance(mechanics, list), f"{content_id} mechanics must be a list"
        assert mechanics, f"{content_id} mechanics must not be empty"
        for idx, row in enumerate(mechanics):
            assert isinstance(row, dict), f"{content_id} mechanics[{idx}] must be object"
            assert row.get("effect_type") == "sense", (
                f"{content_id} mechanics[{idx}] must use effect_type=sense"
            )
            assert row.get("range_ft"), f"{content_id} mechanics[{idx}] missing range_ft"
            assert row.get("sense"), f"{content_id} mechanics[{idx}] missing sense"
        issues = validate_rule_mechanics_payload(kind="spell", payload=payload)
        assert issues == [], f"{content_id} has schema issues: {issues}"
