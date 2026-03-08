from __future__ import annotations

import json
from pathlib import Path

from dnd_sim.engine_runtime import _build_actor_from_character
from dnd_sim.inventory import InventoryState
from dnd_sim.items import build_item_catalog, load_default_item_catalog, load_item_catalog


def _write_item(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _base_character() -> dict[str, object]:
    return {
        "character_id": "hero_1",
        "name": "Hero",
        "class_levels": {"wizard": 5},
        "max_hp": 36,
        "ac": 14,
        "speed_ft": 30,
        "ability_scores": {"str": 8, "dex": 14, "con": 14, "int": 18, "wis": 12, "cha": 10},
        "save_mods": {"str": -1, "dex": 2, "con": 2, "int": 4, "wis": 1, "cha": 0},
        "skill_mods": {},
        "attacks": [{"name": "Quarterstaff", "to_hit": 6, "damage": "1d6+2"}],
        "resources": {},
        "traits": [],
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }


def test_item_catalog_build_and_load_round_trip(tmp_path: Path) -> None:
    _write_item(
        tmp_path / "longsword.json",
        {
            "name": "Longsword",
            "source_book": "PHB",
            "category": "weapon",
            "equip_slots": ["main_hand"],
            "weapon_properties": ["versatile"],
            "damage": "1d8",
            "damage_type": "slashing",
            "value_cp": 1500,
            "weight_lb": 3.0,
        },
    )

    catalog = load_item_catalog(items_dir=tmp_path)

    assert "longsword" in catalog
    longsword = catalog["longsword"]
    assert longsword.content_id == "item:longsword|PHB"
    assert longsword.item_id == "longsword"
    assert longsword.equip_slots == ("main_hand",)
    assert longsword.weapon_properties == ("versatile",)
    assert longsword.damage == "1d8"

    rebuilt = build_item_catalog(item_payloads=[longsword.model_dump(mode="json")])
    assert list(rebuilt.keys()) == ["longsword"]


def test_default_item_catalog_is_populated_with_core_and_magic_items() -> None:
    catalog = load_default_item_catalog()

    assert "longsword" in catalog
    assert "potion_of_healing" in catalog
    assert "wand_of_magic_missiles" in catalog
    assert catalog["wand_of_magic_missiles"].requires_attunement is True
    assert catalog["wand_of_magic_missiles"].max_charges == 7


def test_inventory_hydrates_item_shape_from_canonical_catalog(tmp_path: Path) -> None:
    _write_item(
        tmp_path / "ring_of_protection.json",
        {
            "name": "Ring of Protection",
            "source_book": "DMG",
            "category": "wondrous",
            "requires_attunement": True,
            "equip_slots": ["ring_left", "ring_right"],
            "passive_effects": [{"effect_type": "ac_bonus", "amount": 1}],
            "value_cp": 250000,
            "weight_lb": 0.0,
        },
    )
    catalog = load_item_catalog(items_dir=tmp_path)
    character = {
        "inventory": [
            {
                "item_id": "ring_of_protection",
                "quantity": 1,
                "attuned": True,
            }
        ]
    }

    inventory = InventoryState.from_character_payload(character, item_catalog=catalog)
    ring = inventory.items["ring_of_protection"]
    assert ring.requires_attunement is True
    assert ring.attuned is True
    assert ring.equip_slots == ("ring_left", "ring_right")
    assert ring.value_cp == 250000


def test_actor_build_adds_item_actions_and_charge_resources(tmp_path: Path) -> None:
    _write_item(
        tmp_path / "wand_of_magic_missiles.json",
        {
            "name": "Wand of Magic Missiles",
            "source_book": "DMG",
            "category": "wand",
            "requires_attunement": True,
            "equip_slots": ["main_hand", "off_hand"],
            "max_charges": 7,
            "charge_recovery": {"period": "dawn", "formula": "1d6+1"},
            "granted_actions": [
                {
                    "name": "wand_magic_missile",
                    "action_type": "utility",
                    "action_cost": "action",
                    "target_mode": "single_enemy",
                    "tags": ["item_granted", "spell"],
                }
            ],
        },
    )
    catalog = load_item_catalog(items_dir=tmp_path)
    character = _base_character()
    character["inventory"] = [
        {
            "item_id": "wand_of_magic_missiles",
            "quantity": 1,
            "attuned": True,
            "equipped_slot": "main_hand",
        }
    ]

    actor = _build_actor_from_character(character, traits_db={}, item_catalog=catalog)

    assert any(action.name == "wand_magic_missile" for action in actor.actions)
    assert actor.max_resources["item_charge:wand_of_magic_missiles"] == 7
    assert actor.resources["item_charge:wand_of_magic_missiles"] == 7


def test_actor_build_sums_charges_for_duplicate_items(tmp_path: Path) -> None:
    _write_item(
        tmp_path / "wand_of_magic_missiles.json",
        {
            "name": "Wand of Magic Missiles",
            "source_book": "DMG",
            "category": "wand",
            "requires_attunement": True,
            "equip_slots": ["main_hand", "off_hand"],
            "max_charges": 7,
            "granted_actions": [
                {
                    "name": "wand_magic_missile",
                    "action_type": "utility",
                    "action_cost": "action",
                    "target_mode": "single_enemy",
                }
            ],
        },
    )
    catalog = load_item_catalog(items_dir=tmp_path)
    character = _base_character()
    character["inventory"] = [
        {
            "item_id": "wand_of_magic_missiles",
            "quantity": 1,
            "current_charges": 7,
            "attuned": True,
            "equipped_slot": "main_hand",
        },
        {
            "item_id": "wand_of_magic_missiles",
            "quantity": 1,
            "current_charges": 7,
            "attuned": True,
            "equipped_slot": "main_hand",
        },
    ]

    actor = _build_actor_from_character(character, traits_db={}, item_catalog=catalog)

    assert actor.max_resources["item_charge:wand_of_magic_missiles"] == 14
    assert actor.resources["item_charge:wand_of_magic_missiles"] == 14
