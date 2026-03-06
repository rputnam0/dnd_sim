from __future__ import annotations

import csv
import json
from pathlib import Path

from dnd_sim.capability_manifest import build_spell_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs" / "program" / "parity_leaf_registry.csv"
REVIEW_CHECKLIST_PATH = REPO_ROOT / "docs" / "review_checklist.md"
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
    "spell:enlarge_reduce",
    "spell:elemental_bane",
    "spell:enhance_ability",
    "spell:expeditious_retreat",
    "spell:false_life",
    "spell:fizban_s_platinum_shield",
    "spell:fly",
    "spell:foresight",
    "spell:fortune_s_favor",
    "spell:gaseous_form",
    "spell:gift_of_alacrity",
    "spell:gift_of_gab",
    "spell:glibness",
    "spell:goodberry",
    "spell:greater_invisibility",
    "spell:guards_and_wards",
    "spell:haste",
    "spell:heroism",
    "spell:primordial_ward",
    "spell:sanctuary",
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
    assert CHECKPOINT_I2_SPELL_IDS == owned_ids


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
        "spell:bane": "baned",
        "spell:barkskin": "barkskin_ac_min_16",
        "spell:beacon_of_hope": "beacon_of_hope_max_healing",
        "spell:bestow_curse": "bestow_curse",
        "spell:bless": "blessed",
        "spell:blur": "blurred",
        "spell:borrowed_knowledge": "borrowed_knowledge_skill_proficiency",
        "spell:death_ward": "death_warded",
        "spell:enlarge_reduce": "enlarge_reduce_active",
        "spell:elemental_bane": "elemental_bane",
        "spell:enhance_ability": "enhance_ability_selected_option",
        "spell:expeditious_retreat": "expeditious_retreat_dash_bonus_action",
        "spell:fizban_s_platinum_shield": "fizbans_platinum_shield",
        "spell:fly": "flying_speed_60",
        "spell:foresight": "foresight",
        "spell:fortune_s_favor": "fortunes_favor_reroll_available",
        "spell:gaseous_form": "gaseous_form",
        "spell:gift_of_alacrity": "gift_of_alacrity_initiative_bonus",
        "spell:gift_of_gab": "gift_of_gab_memory_rewrite",
        "spell:glibness": "glibness",
        "spell:goodberry": "goodberries_created",
        "spell:greater_invisibility": "invisible",
        "spell:guards_and_wards": "guards_and_wards_warded_area",
        "spell:haste": "hasted",
        "spell:heroism": "heroism",
        "spell:primordial_ward": "primordial_ward_elemental_resistance",
        "spell:sanctuary": "sanctuary_warded",
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

    aid_payload = json.loads((SPELLS_DIR / "aid.json").read_text(encoding="utf-8"))
    aid_mechanics = aid_payload.get("mechanics")
    assert isinstance(aid_mechanics, list)
    assert any(
        isinstance(row, dict)
        and row.get("effect_type") == "max_hp_increase"
        and row.get("calculation") == "5 + 5 per slot level above 2"
        and row.get("duration_rounds") == 4800
        for row in aid_mechanics
    ), "spell:aid must contain max_hp_increase with canonical scaling"
    assert any(
        isinstance(row, dict)
        and row.get("effect_type") == "heal"
        and row.get("amount") == 5
        and row.get("upcast_bonus_per_slot") == 5
        for row in aid_mechanics
    ), "spell:aid must contain heal with canonical upcast bonus"

    darkvision_payload = json.loads((SPELLS_DIR / "darkvision.json").read_text(encoding="utf-8"))
    darkvision_mechanics = darkvision_payload.get("mechanics")
    assert isinstance(darkvision_mechanics, list)
    assert any(
        isinstance(row, dict)
        and row.get("effect_type") == "sense"
        and row.get("sense") == "darkvision"
        and row.get("range_ft") == 60
        and row.get("duration_rounds") == 4800
        for row in darkvision_mechanics
    ), "spell:darkvision must contain sense:darkvision with canonical range and duration"


def test_w6_par_05i2_checkpoint_top_level_save_ability_matches_spell_mechanics() -> None:
    expected_top_level_save_ability = {
        "spell:bane": "cha",
        "spell:slow": "wis",
    }

    for content_id, save_ability in sorted(expected_top_level_save_ability.items()):
        slug = content_id.split(":", maxsplit=1)[1]
        payload = json.loads((SPELLS_DIR / f"{slug}.json").read_text(encoding="utf-8"))
        assert payload.get("save_ability") == save_ability


def test_w6_par_05i2_review_checklist_stays_open_while_pr_is_open() -> None:
    checklist = REVIEW_CHECKLIST_PATH.read_text(encoding="utf-8")
    assert "- [ ] W6-PAR-05I2 Spell buff/debuff/mark mechanics leaf (PR #227 open)" in checklist
