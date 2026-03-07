from __future__ import annotations

import json
from pathlib import Path

from dnd_sim.capability_manifest import build_feature_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
TRAITS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "traits"

G1_B_TRAIT_IDS = {
    "trait:genie_s_wrath",
    "trait:giant_s_might",
    "trait:gravity_well",
    "trait:hand_of_harm",
    "trait:hunter_s_rime",
    "trait:hurl_through_hell",
    "trait:infiltrator",
    "trait:instinctive_charm",
    "trait:invincible_conqueror",
    "trait:master_of_hexes",
}

EXPECTED_RUNTIME_FAMILIES = {
    "trait:genie_s_wrath": "effect",
    "trait:giant_s_might": "effect_meta",
    "trait:gravity_well": "effect",
    "trait:hand_of_harm": "effect",
    "trait:hunter_s_rime": "meta",
    "trait:hurl_through_hell": "effect_meta",
    "trait:infiltrator": "effect_meta",
    "trait:instinctive_charm": "meta",
    "trait:invincible_conqueror": "meta",
    "trait:master_of_hexes": "meta",
}


def _payload(content_id: str) -> dict[str, object]:
    slug = content_id.split(":", maxsplit=1)[1]
    return json.loads((TRAITS_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def test_g1_b_owned_trait_records_are_supported() -> None:
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(G1_B_TRAIT_IDS - set(by_id))
    assert missing_ids == []

    for content_id in sorted(G1_B_TRAIT_IDS):
        record = by_id[content_id]
        assert record.content_type == "trait"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.unsupported_reason is None
        assert record.runtime_hook_family == EXPECTED_RUNTIME_FAMILIES[content_id]


def test_g1_b_trait_files_use_canonical_mechanics_rows() -> None:
    for content_id in sorted(G1_B_TRAIT_IDS):
        payload = _payload(content_id)
        mechanics = payload.get("mechanics")
        assert isinstance(mechanics, list), f"{content_id} mechanics must be a list"
        assert mechanics, f"{content_id} mechanics must not be empty"
        for idx, row in enumerate(mechanics):
            assert isinstance(row, dict), f"{content_id} mechanics[{idx}] must be object"
            has_effect_type = str(row.get("effect_type", "")).strip()
            has_meta_type = str(row.get("meta_type", "")).strip()
            assert (
                has_effect_type or has_meta_type
            ), f"{content_id} mechanics[{idx}] needs effect_type or meta_type"
        issues = validate_rule_mechanics_payload(kind="trait", payload=payload)
        assert issues == [], f"{content_id} has schema issues: {issues}"


def test_g1_b_trait_rows_capture_owned_trait_intent() -> None:
    genie = _payload("trait:genie_s_wrath")["mechanics"]
    assert any(
        row.get("effect_type") == "extra_damage"
        and row.get("damage") == "proficiency_bonus"
        and row.get("damage_type") == "patron_determined"
        for row in genie
        if isinstance(row, dict)
    )

    giant = _payload("trait:giant_s_might")["mechanics"]
    assert any(
        row.get("meta_type") == "size_change" and row.get("size_target") == "Large"
        for row in giant
        if isinstance(row, dict)
    )
    assert any(
        row.get("effect_type") == "extra_damage" and row.get("damage") == "1d6"
        for row in giant
        if isinstance(row, dict)
    )

    gravity = _payload("trait:gravity_well")["mechanics"]
    assert any(
        row.get("effect_type") == "forced_movement" and row.get("distance_ft") == 5
        for row in gravity
        if isinstance(row, dict)
    )

    hand = _payload("trait:hand_of_harm")["mechanics"]
    assert any(
        row.get("effect_type") == "extra_damage"
        and row.get("damage_type") == "necrotic"
        and row.get("resource") == "ki"
        for row in hand
        if isinstance(row, dict)
    )

    rime = _payload("trait:hunter_s_rime")["mechanics"]
    assert any(
        row.get("meta_type") == "temporary_hit_points"
        and row.get("amount") == "1d10 + ranger_level"
        for row in rime
        if isinstance(row, dict)
    )
    assert any(
        row.get("meta_type") == "condition_restriction"
        and row.get("condition") == "target_marked_by_hunters_mark"
        for row in rime
        if isinstance(row, dict)
    )

    hell = _payload("trait:hurl_through_hell")["mechanics"]
    assert any(
        row.get("meta_type") == "conditional_banish"
        and row.get("duration") == "until_end_of_your_next_turn"
        for row in hell
        if isinstance(row, dict)
    )
    assert any(
        row.get("effect_type") == "damage"
        and row.get("damage") == "10d10"
        and row.get("damage_type") == "psychic"
        for row in hell
        if isinstance(row, dict)
    )

    infiltrator = _payload("trait:infiltrator")["mechanics"]
    assert any(
        row.get("effect_type") == "extra_damage"
        and row.get("damage") == "1d6"
        and row.get("damage_type") == "lightning"
        for row in infiltrator
        if isinstance(row, dict)
    )
    assert any(
        row.get("effect_type") == "speed_increase" and row.get("amount") == 5
        for row in infiltrator
        if isinstance(row, dict)
    )

    charm = _payload("trait:instinctive_charm")["mechanics"]
    assert any(
        row.get("meta_type") == "reaction"
        and row.get("range_ft") == 30
        and row.get("save", {}).get("ability") == "wis"
        for row in charm
        if isinstance(row, dict)
    )

    conqueror = _payload("trait:invincible_conqueror")["mechanics"]
    assert any(
        row.get("meta_type") == "grant_resistance" and row.get("damage_types") == ["all"]
        for row in conqueror
        if isinstance(row, dict)
    )
    assert any(
        row.get("meta_type") == "critical_range" and row.get("critical_range") == [19, 20]
        for row in conqueror
        if isinstance(row, dict)
    )

    hexes = _payload("trait:master_of_hexes")["mechanics"]
    assert any(
        row.get("meta_type") == "mark"
        and row.get("trigger") == "cursed_creature_death"
        and row.get("range_ft") == 30
        for row in hexes
        if isinstance(row, dict)
    )
