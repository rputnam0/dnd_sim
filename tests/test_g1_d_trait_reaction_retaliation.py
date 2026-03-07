from __future__ import annotations

import csv
import json
from pathlib import Path

from dnd_sim.capability_manifest import build_feature_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
TRAITS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "traits"
REGISTRY_PATH = REPO_ROOT / "docs" / "program" / "parity_batch_registry.csv"

G1_D_IDS = {
    "trait:superior_hunter_s_prey",
    "trait:swarming_dispersal",
    "trait:unbreakable_majesty",
    "trait:vengeful_ancestors",
    "trait:violent_attraction",
    "trait:war_god_s_blessing",
    "trait:withdraw_cost_1d6",
    "trait:wrath_of_the_sea",
}

EXPECTED_RUNTIME_FAMILIES = {
    "trait:superior_hunter_s_prey": "effect_meta",
    "trait:swarming_dispersal": "meta",
    "trait:unbreakable_majesty": "meta",
    "trait:vengeful_ancestors": "effect_meta",
    "trait:violent_attraction": "effect_meta",
    "trait:war_god_s_blessing": "meta",
    "trait:withdraw_cost_1d6": "meta",
    "trait:wrath_of_the_sea": "effect_meta",
}


def _payload(content_id: str) -> dict[str, object]:
    slug = content_id.split(":", maxsplit=1)[1]
    return json.loads((TRAITS_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def test_g1_d_registry_rows_match_owned_batch() -> None:
    seen: set[str] = set()
    statuses: set[str] = set()
    with REGISTRY_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("batch_id") != "G1-D":
                continue
            content_id = str(row.get("content_id", "")).strip()
            if content_id:
                seen.add(content_id)
                statuses.add(str(row.get("status", "")).strip())

    assert seen == G1_D_IDS
    assert statuses <= {"in_progress", "pr_open"}


def test_g1_d_owned_trait_records_are_supported() -> None:
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(G1_D_IDS - set(by_id))
    assert missing_ids == []

    blocked_traits_missing_hook = {
        record.content_id
        for record in manifest.records
        if record.content_type == "trait"
        and record.states.unsupported_reason == "missing_runtime_hook_family"
    }
    assert blocked_traits_missing_hook.isdisjoint(G1_D_IDS)

    for content_id in sorted(G1_D_IDS):
        record = by_id[content_id]
        assert record.content_type == "trait"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.unsupported_reason is None
        assert record.runtime_hook_family == EXPECTED_RUNTIME_FAMILIES[content_id]


def test_g1_d_trait_files_use_canonical_mechanics_rows() -> None:
    for content_id in sorted(G1_D_IDS):
        payload = _payload(content_id)
        mechanics = payload.get("mechanics")
        assert isinstance(mechanics, list), f"{content_id} mechanics must be a list"
        assert mechanics, f"{content_id} mechanics must not be empty"
        for idx, row in enumerate(mechanics):
            assert isinstance(row, dict), f"{content_id} mechanics[{idx}] must be object"
            has_effect_type = str(row.get("effect_type", "")).strip()
            has_meta_type = str(row.get("meta_type", "")).strip()
            assert has_effect_type or has_meta_type, (
                f"{content_id} mechanics[{idx}] needs effect_type or meta_type"
            )
        issues = validate_rule_mechanics_payload(kind="trait", payload=payload)
        assert issues == [], f"{content_id} has schema issues: {issues}"


def test_g1_d_rows_capture_reaction_retaliation_intent() -> None:
    superior = _payload("trait:superior_hunter_s_prey")["mechanics"]
    assert any(
        row.get("effect_type") == "extra_damage"
        and row.get("trigger") == "deal_damage_to_hunters_marked_target"
        and row.get("damage") == "hunters_mark_extra_damage"
        and row.get("target") == "different_creature_within_30ft_of_marked_target"
        for row in superior
        if isinstance(row, dict)
    )

    dispersal = _payload("trait:swarming_dispersal")["mechanics"]
    assert any(
        row.get("meta_type") == "grant_resistance"
        and row.get("trigger") == "take_damage"
        and row.get("damage_type") == "damage_type_of_trigger"
        for row in dispersal
        if isinstance(row, dict)
    )
    assert any(
        row.get("meta_type") == "teleport" and row.get("distance_ft") == 30
        for row in dispersal
        if isinstance(row, dict)
    )

    majesty = _payload("trait:unbreakable_majesty")["mechanics"]
    assert any(
        row.get("meta_type") == "presence"
        and row.get("activation") == "bonus_action"
        and row.get("duration_rounds") == 10
        for row in majesty
        if isinstance(row, dict)
    )
    assert any(
        row.get("meta_type") == "reaction"
        and row.get("save", {}).get("ability") == "cha"
        and row.get("save", {}).get("dc") == "spell_save_dc"
        for row in majesty
        if isinstance(row, dict)
    )

    ancestors = _payload("trait:vengeful_ancestors")["mechanics"]
    assert any(
        row.get("effect_type") == "damage"
        and row.get("damage") == "spirit_shield_prevented_damage"
        and row.get("damage_type") == "force"
        for row in ancestors
        if isinstance(row, dict)
    )

    attraction = _payload("trait:violent_attraction")["mechanics"]
    assert any(
        row.get("effect_type") == "extra_damage"
        and row.get("trigger") == "ally_weapon_attack_hit_within_60ft"
        and row.get("damage") == "1d10"
        and row.get("damage_type") == "weapon"
        for row in attraction
        if isinstance(row, dict)
    )
    assert any(
        row.get("effect_type") == "damage"
        and row.get("trigger") == "creature_fall_damage_within_60ft"
        and row.get("damage") == "2d10"
        and row.get("damage_type") == "bludgeoning"
        for row in attraction
        if isinstance(row, dict)
    )

    blessing = _payload("trait:war_god_s_blessing")["mechanics"]
    assert any(
        row.get("meta_type") == "resource_spend"
        and row.get("resource") == "channel_divinity"
        for row in blessing
        if isinstance(row, dict)
    )
    assert any(
        row.get("meta_type") == "spell_override"
        and row.get("spell") == "shield_of_faith"
        and row.get("concentration") is False
        for row in blessing
        if isinstance(row, dict)
    )
    assert any(
        row.get("meta_type") == "spell_override"
        and row.get("spell") == "spiritual_weapon"
        and row.get("concentration") is False
        for row in blessing
        if isinstance(row, dict)
    )

    withdraw = _payload("trait:withdraw_cost_1d6")["mechanics"]
    assert any(
        row.get("meta_type") == "movement"
        and row.get("trigger") == "after_attack"
        and row.get("distance") == "half_speed"
        and row.get("no_opportunity_attacks") is True
        for row in withdraw
        if isinstance(row, dict)
    )

    wrath = _payload("trait:wrath_of_the_sea")["mechanics"]
    assert any(
        row.get("meta_type") == "aura"
        and row.get("radius_ft") == 5
        and row.get("resource") == "wild_shape_use"
        for row in wrath
        if isinstance(row, dict)
    )
    assert any(
        row.get("effect_type") == "damage"
        and row.get("damage") == "max(1,wisdom_modifier)d6"
        and row.get("damage_type") == "cold"
        and row.get("save_ability") == "con"
        for row in wrath
        if isinstance(row, dict)
    )
    assert any(
        row.get("effect_type") == "push"
        and row.get("distance_ft") == 15
        and row.get("size_max") == "large"
        for row in wrath
        if isinstance(row, dict)
    )
