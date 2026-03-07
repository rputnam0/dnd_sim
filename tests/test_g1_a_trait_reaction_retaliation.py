from __future__ import annotations

import csv
import json
from pathlib import Path

from dnd_sim.capability_manifest import build_feature_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_REGISTRY_PATH = REPO_ROOT / "docs" / "program" / "parity_batch_registry.csv"
TRAITS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "traits"

G1_A_IDS = {
    "trait:ambush_master",
    "trait:armor_of_hexes",
    "trait:blaze_of_glory",
    "trait:defy_death",
    "trait:elemental_attunement",
    "trait:emboldening_bond",
    "trait:emissary_of_redemption",
    "trait:eventide_s_splendor",
    "trait:favored_by_the_gods",
    "trait:gathered_swarm",
}


def _owned_g1_a_trait_ids() -> set[str]:
    owned: set[str] = set()
    with BATCH_REGISTRY_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if (
                row.get("batch_id") == "G1-A"
                and row.get("leaf_task_id") == "W6-PAR-05G1"
                and row.get("prompt_family") == "trait_reaction_retaliation"
                and row.get("target_test_file") == "tests/test_g1_a_trait_reaction_retaliation.py"
                and row.get("branch_name") == "codex/feat/g1-a-trait-reaction-retaliation"
            ):
                content_id = str(row.get("content_id", "")).strip()
                if content_id:
                    owned.add(content_id)

    assert owned == G1_A_IDS
    return owned


def _payload(content_id: str) -> dict[str, object]:
    trait_id = content_id.split(":", 1)[1]
    return json.loads((TRAITS_DIR / f"{trait_id}.json").read_text(encoding="utf-8"))


def test_g1_a_owned_trait_records_are_supported() -> None:
    owned_ids = _owned_g1_a_trait_ids()
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


def test_g1_a_trait_files_use_canonical_meta_rows() -> None:
    for content_id in sorted(_owned_g1_a_trait_ids()):
        payload = _payload(content_id)

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


def test_g1_a_trait_rows_capture_owned_intent() -> None:
    ambush = _payload("trait:ambush_master")["mechanics"]
    assert any(
        row.get("trigger") == "initiative roll"
        and row.get("target") == "self"
        and row.get("effect") == "advantage"
        for row in ambush
        if isinstance(row, dict)
    )
    assert any(
        row.get("duration") == "until the start of your next turn"
        and "first round of combat" in str(row.get("condition", ""))
        for row in ambush
        if isinstance(row, dict)
    )

    armor = _payload("trait:armor_of_hexes")["mechanics"]
    assert any(
        row.get("action") == "reaction"
        and "hexblade's curse" in str(row.get("trigger", ""))
        and "d6" in str(row.get("effect", ""))
        for row in armor
        if isinstance(row, dict)
    )

    blaze = _payload("trait:blaze_of_glory")["mechanics"]
    assert any(
        row.get("action") == "reaction"
        and row.get("movement", {}).get("type") == "move"
        and row.get("attack", {}).get("advantage") is True
        for row in blaze
        if isinstance(row, dict)
    )

    defy = _payload("trait:defy_death")["mechanics"]
    assert any(
        "death saving throw" in " ".join(row.get("trigger", []))
        and "spare the dying" in " ".join(row.get("trigger", []))
        and row.get("action") == "heal"
        for row in defy
        if isinstance(row, dict) and isinstance(row.get("trigger"), list)
    )

    attunement = _payload("trait:elemental_attunement")["mechanics"]
    assert any(
        row.get("trigger") == "start_of_turn"
        and row.get("cost", {}).get("resource") == "Focus Point"
        and row.get("cost", {}).get("amount") == 1
        for row in attunement
        if isinstance(row, dict)
    )
    assert any(
        any(effect.get("type") == "forced_movement" for effect in row.get("effects", []))
        for row in attunement
        if isinstance(row, dict) and isinstance(row.get("effects"), list)
    )

    bond = _payload("trait:emboldening_bond")["mechanics"]
    assert any(
        row.get("activation") == "action"
        and "30 feet" in str(row.get("target", ""))
        and row.get("uses", {}).get("max") == "proficiency bonus"
        for row in bond
        if isinstance(row, dict)
    )
    assert any(
        row.get("effect") == "add_d4_bonus" and "once per turn" in str(row.get("application", ""))
        for row in bond
        if isinstance(row, dict)
    )

    redemption = _payload("trait:emissary_of_redemption")["mechanics"]
    assert any(
        row.get("effect") == "resistance" and row.get("damage_source") == "creature"
        for row in redemption
        if isinstance(row, dict)
    )
    assert any(
        row.get("damage_type") == "radiant" and row.get("amount") == "half_damage_taken"
        for row in redemption
        if isinstance(row, dict)
    )

    splendor = _payload("trait:eventide_s_splendor")["mechanics"]
    assert any(
        row.get("trigger") == "use inspired eclipse"
        and row.get("duration") == "until start of next turn"
        for row in splendor
        if isinstance(row, dict)
    )
    assert any(
        row.get("trigger") == "use lunar vitality"
        and "Bardic Inspiration die" in json.dumps(row.get("effect", {}))
        for row in splendor
        if isinstance(row, dict)
    )

    favor = _payload("trait:favored_by_the_gods")["mechanics"]
    assert any(
        row.get("trigger") == "failed saving throw or missed attack roll"
        and "2d4" in str(row.get("action", ""))
        for row in favor
        if isinstance(row, dict)
    )

    swarm = _payload("trait:gathered_swarm")["mechanics"]
    assert any(
        row.get("trigger") == "hit"
        and row.get("usage") == "once per turn"
        and any(option.get("damage") == "1d6" for option in row.get("options", []))
        and any(option.get("distance") == 15 for option in row.get("options", []))
        and any(option.get("distance") == 5 for option in row.get("options", []))
        for row in swarm
        if isinstance(row, dict)
    )
