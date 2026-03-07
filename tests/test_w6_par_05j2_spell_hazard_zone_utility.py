from __future__ import annotations

import csv
import json
from pathlib import Path

from dnd_sim.capability_manifest import build_spell_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload
from dnd_sim.spells import canonicalize_spell_payload

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

SLICE_TWO_J2_SPELL_IDS = {
    "spell:augury",
    "spell:commune",
    "spell:commune_with_nature",
    "spell:contact_other_plane",
    "spell:divination",
    "spell:find_the_path",
    "spell:guidance_divination",
    "spell:locate_animals_or_plants",
}

SUPPORTED_SLICE_IDS = SLICE_ONE_J2_SPELL_IDS | SLICE_TWO_J2_SPELL_IDS
PURE_SENSE_SLICE_IDS = SUPPORTED_SLICE_IDS - {
    "spell:contact_other_plane",
    "spell:guidance_divination",
}
CONCENTRATION_SENSE_SLICE_IDS = {
    "spell:arcane_eye",
    "spell:clairvoyance",
    "spell:detect_evil_and_good",
    "spell:detect_magic",
    "spell:detect_poison_and_disease",
    "spell:detect_thoughts",
    "spell:find_the_path",
    "spell:locate_object",
}
RITUAL_SLICE_IDS = {
    "spell:augury",
    "spell:commune",
    "spell:commune_with_nature",
    "spell:contact_other_plane",
    "spell:detect_magic",
    "spell:detect_poison_and_disease",
    "spell:divination",
    "spell:locate_animals_or_plants",
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
    assert owned.issuperset(SUPPORTED_SLICE_IDS)
    return owned


def test_w6_par_05j2_supported_spells_are_supported() -> None:
    manifest = build_spell_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(SUPPORTED_SLICE_IDS - set(by_id))
    assert missing_ids == []

    blocked_missing_mechanics = {
        record.content_id
        for record in manifest.records
        if record.content_type == "spell"
        and record.states.unsupported_reason == "missing_runtime_mechanics"
    }
    assert blocked_missing_mechanics.isdisjoint(SUPPORTED_SLICE_IDS)

    for content_id in sorted(SUPPORTED_SLICE_IDS):
        record = by_id[content_id]
        assert record.content_type == "spell"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.runtime_hook_family == "effect"


def test_w6_par_05j2_owned_spell_blockers_shrink_after_supported_slices() -> None:
    owned_ids = _owned_j2_spell_ids()
    manifest = build_spell_capability_manifest()

    blocked_owned = {
        record.content_id
        for record in manifest.records
        if record.content_id in owned_ids and record.states.blocked
    }

    assert SUPPORTED_SLICE_IDS.isdisjoint(blocked_owned)
    assert blocked_owned == set()


def test_w6_par_05j2_supported_spell_files_use_canonical_rows() -> None:
    for content_id in sorted(SUPPORTED_SLICE_IDS):
        spell_id = content_id.split(":", 1)[1]
        path = SPELLS_DIR / f"{spell_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if content_id in RITUAL_SLICE_IDS:
            assert payload.get("ritual") is True, f"{content_id} should be ritual-castable"
        mechanics = payload.get("mechanics")
        assert isinstance(mechanics, list), f"{content_id} mechanics must be a list"
        assert mechanics, f"{content_id} mechanics must not be empty"
        if content_id == "spell:contact_other_plane":
            effect_rows = [row for row in mechanics if isinstance(row, dict)]
            effect_types = [str(row.get("effect_type")) for row in effect_rows]
            assert effect_types.count("save") == 1
            assert effect_types.count("sense") == 1
            assert effect_types.count("damage") == 1
            assert effect_types.count("apply_condition") == 1
            by_effect_type = {str(row.get("effect_type")): row for row in effect_rows}
            canonical_payload = canonicalize_spell_payload(payload, source_path=path)
            assert canonical_payload.get("action_type") == "save"
            assert canonical_payload.get("target_mode") == "self"
            assert canonical_payload.get("save_ability") == "int"
            assert canonical_payload.get("save_dc") == 15
            assert by_effect_type["save"].get("save_ability") == "int"
            assert by_effect_type["save"].get("save_dc") == 15
            assert by_effect_type["sense"].get("apply_on") == "save_success"
            assert by_effect_type["sense"].get("duration_rounds") == payload.get("duration_rounds")
            assert by_effect_type["damage"].get("target") == "source"
            assert by_effect_type["damage"].get("apply_on") == "save_fail"
            assert by_effect_type["damage"].get("damage") == "6d6"
            assert by_effect_type["damage"].get("damage_type") == "psychic"
            assert by_effect_type["apply_condition"].get("target") == "source"
            assert by_effect_type["apply_condition"].get("apply_on") == "save_fail"
            assert by_effect_type["apply_condition"].get("condition") == "incapacitated"
            assert by_effect_type["apply_condition"].get("duration_rounds") == 4800
        else:
            for idx, row in enumerate(mechanics):
                assert isinstance(row, dict), f"{content_id} mechanics[{idx}] must be object"
                if content_id in PURE_SENSE_SLICE_IDS:
                    assert row.get("effect_type") == "sense", (
                        f"{content_id} mechanics[{idx}] must use effect_type=sense"
                    )
                    assert "range_ft" in row, f"{content_id} mechanics[{idx}] missing range_ft"
                    assert row.get("range_ft") is not None, (
                        f"{content_id} mechanics[{idx}] range_ft must not be null"
                    )
                    assert row.get("sense"), f"{content_id} mechanics[{idx}] missing sense"
                    if content_id in CONCENTRATION_SENSE_SLICE_IDS:
                        assert row.get("duration_rounds") == payload.get("duration_rounds")
                else:
                    assert row.get("effect_type") == "apply_condition", (
                        f"{content_id} mechanics[{idx}] must use effect_type=apply_condition"
                    )
                    assert row.get("condition") == "guidance_bonus_d4"
                    assert row.get("bonus") == "1d4"
                    assert row.get("applies_to") == "ability_check"
                    assert payload.get("range_ft") == 0
        issues = validate_rule_mechanics_payload(kind="spell", payload=payload)
        assert issues == [], f"{content_id} has schema issues: {issues}"
