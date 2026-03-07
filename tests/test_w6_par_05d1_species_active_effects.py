from __future__ import annotations

import json
from pathlib import Path

from dnd_sim import io
from dnd_sim.capability_manifest import build_feature_capability_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
TRAITS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "traits"

W6_PAR_05D1_EXPECTED_FAMILIES = {
    "species:chromatic_ancestry": "meta",
    "species:gem_ancestry": "meta",
    "species:hammering_horns": "effect_meta",
    "species:hare_trigger": "meta",
    "species:imposing_presence": "meta",
    "species:metallic_ancestry": "meta",
    "species:secondary_arms": "meta",
    "species:shapechanger": "meta",
}

ANCESTRY_FILES = {
    "chromatic_ancestry": {
        "Black": "acid",
        "Blue": "lightning",
        "Green": "poison",
        "Red": "fire",
        "White": "cold",
    },
    "gem_ancestry": {
        "Amethyst": "force",
        "Crystal": "radiant",
        "Emerald": "psychic",
        "Sapphire": "thunder",
        "Topaz": "necrotic",
    },
    "metallic_ancestry": {
        "Brass": "fire",
        "Bronze": "lightning",
        "Copper": "acid",
        "Gold": "fire",
        "Silver": "cold",
    },
}


def _load_trait(slug: str) -> dict[str, object]:
    return json.loads((TRAITS_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def test_w6_par_05d1_species_records_are_supported_in_feature_manifest() -> None:
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(set(W6_PAR_05D1_EXPECTED_FAMILIES) - set(by_id))
    assert missing_ids == []

    for content_id, expected_family in sorted(W6_PAR_05D1_EXPECTED_FAMILIES.items()):
        record = by_id[content_id]
        assert record.content_type == "species"
        assert record.runtime_hook_family == expected_family
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.unsupported_reason is None


def test_w6_par_05d1_species_records_are_supported_in_canonical_capability_records() -> None:
    io._canonical_capability_records.cache_clear()
    by_id = {record.content_id: record for record in io._canonical_capability_records()}

    missing_ids = sorted(set(W6_PAR_05D1_EXPECTED_FAMILIES) - set(by_id))
    assert missing_ids == []

    for content_id, expected_family in sorted(W6_PAR_05D1_EXPECTED_FAMILIES.items()):
        record = by_id[content_id]
        assert record.content_type == "species"
        assert record.runtime_hook_family == expected_family
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.unsupported_reason is None


def test_w6_par_05d1_species_traits_use_canonical_mechanics_shapes() -> None:
    for slug, expected_map in sorted(ANCESTRY_FILES.items()):
        payload = _load_trait(slug)
        assert payload["mechanics"] == [
            {
                "meta_type": "choice",
                "options": [
                    {"name": name, "damage_type": damage_type}
                    for name, damage_type in expected_map.items()
                ],
                "choice_key": "ancestry",
                "grants": "associated_damage_type",
            }
        ]

    hammering_horns = _load_trait("hammering_horns")
    assert hammering_horns["mechanics"] == [
        {
            "meta_type": "bonus_action",
            "trigger": "after_hitting_with_melee_attack_during_attack_action",
            "range_ft": 5,
            "size_limit": "one_size_larger",
            "save": {
                "ability": "str",
                "dc_formula": "8 + proficiency_bonus + strength_modifier",
            },
        },
        {
            "effect_type": "forced_movement",
            "target": "target",
            "distance_ft": 10,
            "direction": "away_from_source",
            "apply_on": "save_fail",
        },
    ]

    hare_trigger = _load_trait("hare_trigger")
    assert hare_trigger["mechanics"] == [
        {
            "meta_type": "initiative_bonus",
            "value": "proficiency_bonus",
        }
    ]

    imposing_presence = _load_trait("imposing_presence")
    assert imposing_presence["mechanics"] == [
        {
            "meta_type": "grant_proficiencies",
            "grant_proficiency": {
                "category": "skill",
                "choices": ["Intimidation", "Persuasion"],
                "count": 1,
            },
        }
    ]

    secondary_arms = _load_trait("secondary_arms")
    assert secondary_arms["mechanics"] == [
        {
            "meta_type": "object_interaction",
            "allowed_interactions": [
                "manipulate_object",
                "open_or_close_door_or_container",
                "pick_up_or_set_down_tiny_object",
            ],
        },
        {
            "meta_type": "weapon_use",
            "allowed_weapon_property": "light",
        },
    ]

    shapechanger = _load_trait("shapechanger")
    assert shapechanger["mechanics"] == [
        {
            "meta_type": "action",
            "name": "Change Appearance",
            "activation": "action",
            "duration": "until_reverted_or_dead",
        },
        {
            "meta_type": "form",
            "changes": ["appearance", "voice", "coloration", "hair_length", "sex"],
            "can_adjust_height_weight": True,
            "size_changes_allowed": False,
            "can_appear_as_other_race": True,
            "requires_seen_form": True,
            "requires_same_basic_limb_arrangement": True,
            "changes_clothing_or_equipment": False,
            "revert_activation": "action",
        },
    ]
