from __future__ import annotations

import csv
import json
from pathlib import Path

from dnd_sim import io
from dnd_sim.capability_manifest import build_spell_capability_manifest
from dnd_sim.mechanics_schema import KNOWN_EFFECT_TYPES, validate_rule_mechanics_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs" / "program" / "parity_leaf_registry.csv"
SPELLS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "spells"
FIRST_SLICE_IDS = {
    "spell:animate_dead",
    "spell:arcane_gate",
    "spell:arcane_lock",
    "spell:armor_of_agathys",
    "spell:aura_of_life",
    "spell:aura_of_purity",
    "spell:bigbys_hand",
    "spell:blade_ward",
    "spell:chromatic_orb",
    "spell:circle_of_power",
}
REPRESENTATIVE_EFFECT_TYPES = {
    "animate_dead": {"summon", "command_allied"},
    "arcane_gate": {"hazard"},
    "arcane_lock": {"transform"},
    "armor_of_agathys": {"temp_hp", "apply_condition"},
    "aura_of_life": {"aoe", "apply_condition", "heal"},
    "aura_of_purity": {"aura", "apply_condition"},
    "bigbys_hand": {"summon", "damage", "apply_condition"},
    "blade_ward": {"apply_condition"},
    "chromatic_orb": {"damage", "ranged_spell_attack"},
    "circle_of_power": {"aoe", "apply_condition"},
}


def _owned_spell_ids() -> set[str]:
    ids: set[str] = set()
    with REGISTRY_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("leaf_task_id") == "W6-PAR-05K1":
                ids.add(row["content_id"])
    assert len(ids) == 66
    return ids


def _first_slice_ids() -> set[str]:
    assert FIRST_SLICE_IDS <= _owned_spell_ids()
    return set(FIRST_SLICE_IDS)


def test_w6_par_05k1_first_slice_records_are_supported_in_spell_manifest() -> None:
    manifest = build_spell_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}
    owned_ids = _first_slice_ids()

    missing_ids = sorted(owned_ids - set(by_id))
    assert missing_ids == []

    for content_id in sorted(owned_ids):
        record = by_id[content_id]
        assert record.content_type == "spell"
        assert record.runtime_hook_family == "effect"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.executable is True
        assert record.states.unsupported_reason is None


def test_w6_par_05k1_first_slice_records_are_supported_in_canonical_capability_records() -> None:
    io._canonical_capability_records.cache_clear()
    by_id = {record.content_id: record for record in io._canonical_capability_records()}
    owned_ids = _first_slice_ids()

    missing_ids = sorted(owned_ids - set(by_id))
    assert missing_ids == []

    for content_id in sorted(owned_ids):
        record = by_id[content_id]
        assert record.content_type == "spell"
        assert record.runtime_hook_family == "effect"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.executable is True
        assert record.states.unsupported_reason is None


def test_w6_par_05k1_first_slice_spell_effect_rows_use_known_canonical_effect_types() -> None:
    for content_id in sorted(_first_slice_ids()):
        slug = content_id.split(":", maxsplit=1)[1]
        payload = json.loads((SPELLS_DIR / f"{slug}.json").read_text(encoding="utf-8"))
        mechanics = payload["mechanics"]

        assert mechanics
        effect_types = []
        for row in mechanics:
            assert isinstance(row, dict)
            effect_type = str(row.get("effect_type", "")).strip()
            assert effect_type
            effect_types.append(effect_type)

        assert set(effect_types) <= KNOWN_EFFECT_TYPES
        assert validate_rule_mechanics_payload(kind="spell", payload=payload) == []


def test_w6_par_05k1_representative_spells_are_normalized_to_expected_families() -> None:
    for slug, expected_effect_types in sorted(REPRESENTATIVE_EFFECT_TYPES.items()):
        payload = json.loads((SPELLS_DIR / f"{slug}.json").read_text(encoding="utf-8"))
        seen = {
            str(row.get("effect_type", "")).strip()
            for row in payload["mechanics"]
            if isinstance(row, dict)
        }
        assert expected_effect_types <= seen
