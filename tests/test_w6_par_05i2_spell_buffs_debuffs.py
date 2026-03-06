from __future__ import annotations

import csv
import json
from pathlib import Path

from dnd_sim.capability_manifest import build_spell_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs" / "program" / "parity_leaf_registry.csv"
SPELLS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "spells"

CHECKPOINT_I2_SPELL_IDS = {
    "spell:aid",
    "spell:bane",
    "spell:barkskin",
    "spell:beacon_of_hope",
    "spell:bestow_curse",
    "spell:bless",
    "spell:blur",
    "spell:borrowed_knowledge",
    "spell:darkvision",
    "spell:death_ward",
    "spell:elemental_bane",
    "spell:enhance_ability",
    "spell:expeditious_retreat",
    "spell:false_life",
    "spell:fly",
    "spell:greater_invisibility",
    "spell:haste",
    "spell:heroism",
    "spell:see_invisibility",
    "spell:shield",
    "spell:shield_of_faith",
    "spell:slow",
    "spell:stoneskin",
}


def _owned_i2_spell_ids() -> set[str]:
    ids: set[str] = set()
    with REGISTRY_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if str(row.get("leaf_task_id", "")).strip() == "W6-PAR-05I2":
                content_id = str(row.get("content_id", "")).strip()
                if content_id:
                    ids.add(content_id)
    assert len(ids) == 35
    return ids


def test_w6_par_05i2_checkpoint_spells_are_owned_by_i2_registry() -> None:
    owned_ids = _owned_i2_spell_ids()
    assert CHECKPOINT_I2_SPELL_IDS <= owned_ids


def test_w6_par_05i2_checkpoint_spell_records_are_supported() -> None:
    manifest = build_spell_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(CHECKPOINT_I2_SPELL_IDS - set(by_id))
    assert missing_ids == []

    for content_id in sorted(CHECKPOINT_I2_SPELL_IDS):
        record = by_id[content_id]
        assert record.content_type == "spell"
        assert record.runtime_hook_family == "effect"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.executable is True
        assert record.states.unsupported_reason is None


def test_w6_par_05i2_checkpoint_spell_files_use_canonical_mechanics() -> None:
    for content_id in sorted(CHECKPOINT_I2_SPELL_IDS):
        slug = content_id.split(":", maxsplit=1)[1]
        payload = json.loads((SPELLS_DIR / f"{slug}.json").read_text(encoding="utf-8"))
        mechanics = payload.get("mechanics")

        assert isinstance(mechanics, list), f"{content_id} mechanics must be a list"
        assert mechanics, f"{content_id} mechanics must not be empty"
        for idx, row in enumerate(mechanics):
            assert isinstance(row, dict), f"{content_id} mechanics[{idx}] must be object"
            effect_type = str(row.get("effect_type", "")).strip()
            assert effect_type, f"{content_id} mechanics[{idx}] missing effect_type"
            assert (
                "meta_type" not in row
            ), f"{content_id} mechanics[{idx}] must not define trait meta_type"

        issues = validate_rule_mechanics_payload(kind="spell", payload=payload)
        assert issues == [], f"{content_id} has schema issues: {issues}"


def test_w6_par_05i2_checkpoint_spell_rows_capture_buff_debuff_intent() -> None:
    expected_condition_rows = {
        "spell:barkskin": "barkskin_ac_min_16",
        "spell:beacon_of_hope": "beacon_of_hope_max_healing",
        "spell:bestow_curse": "bestow_curse",
        "spell:borrowed_knowledge": "borrowed_knowledge_skill_proficiency",
        "spell:death_ward": "death_warded",
        "spell:elemental_bane": "elemental_bane",
        "spell:enhance_ability": "enhance_ability_selected_option",
        "spell:expeditious_retreat": "expeditious_retreat_dash_bonus_action",
        "spell:fly": "flying_speed_60",
        "spell:greater_invisibility": "invisible",
        "spell:haste": "hasted",
        "spell:heroism": "heroism",
        "spell:see_invisibility": "see_invisible",
        "spell:shield": "shield_spell_warded",
        "spell:shield_of_faith": "shield_of_faith_ac_bonus",
        "spell:slow": "slowed",
        "spell:stoneskin": "stoneskin_nonmagical_bps_resistance",
    }

    for content_id, condition in sorted(expected_condition_rows.items()):
        slug = content_id.split(":", maxsplit=1)[1]
        payload = json.loads((SPELLS_DIR / f"{slug}.json").read_text(encoding="utf-8"))
        mechanics = payload.get("mechanics")
        assert isinstance(mechanics, list)
        assert any(
            isinstance(row, dict)
            and row.get("effect_type") == "apply_condition"
            and row.get("condition") == condition
            for row in mechanics
        ), f"{content_id} must contain apply_condition:{condition}"

    false_life_payload = json.loads((SPELLS_DIR / "false_life.json").read_text(encoding="utf-8"))
    false_life_mechanics = false_life_payload.get("mechanics")
    assert isinstance(false_life_mechanics, list)
    assert any(
        isinstance(row, dict)
        and row.get("effect_type") == "temp_hp"
        and row.get("amount") == "1d4+4"
        for row in false_life_mechanics
    ), "spell:false_life must contain temp_hp:1d4+4"
