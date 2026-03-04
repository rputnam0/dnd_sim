from __future__ import annotations

import pytest

from dnd_sim.engine import _build_actor_from_character
from dnd_sim.inventory import CurrencyWallet, InventoryItem, InventoryState
from tests.helpers import with_class_levels


def _base_character() -> dict[str, object]:
    return with_class_levels(
        {
            "character_id": "hero",
            "name": "Hero",
            "class_level": "Wizard 8",
            "max_hp": 38,
            "ac": 14,
            "speed_ft": 30,
            "ability_scores": {
                "str": 8,
                "dex": 14,
                "con": 14,
                "int": 18,
                "wis": 12,
                "cha": 10,
            },
            "save_mods": {"str": -1, "dex": 2, "con": 2, "int": 4, "wis": 1, "cha": 0},
            "skill_mods": {},
            "attacks": [
                {"name": "Staff", "to_hit": 5, "damage": "1d6+2", "damage_type": "bludgeoning"}
            ],
            "resources": {},
            "traits": [],
            "raw_fields": [],
            "source": {"pdf_name": "fixture.pdf"},
        }
    )


def test_attunement_requires_item_opt_in_and_respects_limit() -> None:
    inventory = InventoryState(attunement_limit=2)
    inventory.add_item(
        InventoryItem(
            item_id="ring_of_protection",
            name="Ring of Protection",
            requires_attunement=True,
        )
    )
    inventory.add_item(
        InventoryItem(
            item_id="cloak_of_elvenkind",
            name="Cloak of Elvenkind",
            requires_attunement=True,
        )
    )
    inventory.add_item(
        InventoryItem(
            item_id="amulet_of_health",
            name="Amulet of Health",
            requires_attunement=True,
        )
    )
    inventory.add_item(InventoryItem(item_id="hempen_rope", name="Hempen Rope"))

    with pytest.raises(ValueError, match="require attunement"):
        inventory.attune_item("hempen_rope")

    inventory.attune_item("ring_of_protection")
    inventory.attune_item("cloak_of_elvenkind")

    with pytest.raises(ValueError, match="Attunement limit"):
        inventory.attune_item("amulet_of_health")


def test_consuming_stackable_item_decrements_quantity_and_removes_when_empty() -> None:
    inventory = InventoryState()
    inventory.add_item(
        InventoryItem(
            item_id="potion_of_healing",
            name="Potion of Healing",
            consumable=True,
            quantity=2,
        )
    )

    inventory.consume_item("potion_of_healing")
    assert inventory.items["potion_of_healing"].quantity == 1

    inventory.consume_item("potion_of_healing")
    assert "potion_of_healing" not in inventory.items


def test_currency_flow_supports_spend_and_transfer_with_change() -> None:
    source = CurrencyWallet(gp=3, sp=5)
    recipient = CurrencyWallet()

    source.spend({"gp": 1, "sp": 8})
    assert source.total_cp == 170

    source.transfer_to(recipient, {"sp": 7})
    assert source.total_cp == 100
    assert recipient.total_cp == 70


def test_build_actor_hydrates_inventory_subsystem_from_character_payload() -> None:
    character = _base_character()
    character["inventory"] = [
        {
            "item_id": "amulet_of_health",
            "name": "Amulet of Health",
            "requires_attunement": True,
            "attuned": True,
        },
        {
            "item_id": "potion_of_healing",
            "name": "Potion of Healing",
            "consumable": True,
            "quantity": 2,
        },
    ]
    character["currency"] = {"gp": 12, "sp": 4}

    actor = _build_actor_from_character(character, traits_db={})

    assert actor.inventory.currency.total_cp == 1240
    assert actor.inventory.items["amulet_of_health"].attuned is True
    assert actor.inventory.items["potion_of_healing"].quantity == 2


def test_equipping_item_requires_known_item_legal_slot_and_attunement() -> None:
    inventory = InventoryState()
    inventory.add_item(
        InventoryItem(
            item_id="ring_of_protection",
            name="Ring of Protection",
            requires_attunement=True,
            equip_slots=("ring_left", "ring_right"),
        )
    )
    inventory.add_item(
        InventoryItem(
            item_id="longsword",
            name="Longsword",
            equip_slots=("main_hand",),
        )
    )

    with pytest.raises(KeyError, match="Unknown item_id=unknown_item"):
        inventory.equip_item("unknown_item")

    with pytest.raises(ValueError, match="must be attuned"):
        inventory.equip_item("ring_of_protection")

    inventory.attune_item("ring_of_protection")

    with pytest.raises(ValueError, match="cannot be equipped in slot"):
        inventory.equip_item("longsword", slot="off_hand")

    inventory.equip_item("longsword")
    assert inventory.is_item_equipped("longsword", slot="main_hand") is True

    inventory.unequip_item("longsword")
    assert inventory.is_item_equipped("longsword") is False


def test_has_equipped_shield_does_not_match_substring_names() -> None:
    inventory = InventoryState()
    inventory.add_item(
        InventoryItem(
            item_id="shieldbreaker_blade",
            name="Shieldbreaker Blade",
            equip_slots=("main_hand",),
        )
    )
    inventory.equip_item("shieldbreaker_blade")

    assert inventory.has_equipped_shield() is False


def test_build_actor_uses_trait_mechanics_to_increase_attunement_limit() -> None:
    character = _base_character()
    character["traits"] = ["Magic Item Savant"]

    actor = _build_actor_from_character(
        character,
        traits_db={
            "magic item savant": {
                "name": "Magic Item Savant",
                "mechanics": [{"effect_type": "increase_attunement_limit", "value": 5}],
            }
        },
    )

    assert actor.inventory.attunement_limit == 5
