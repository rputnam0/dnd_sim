from __future__ import annotations

from dnd_sim.inventory import InventoryItem
from dnd_sim.models import ActorRuntimeState
from dnd_sim.rules_2014 import (
    consume_shield_master_bonus_shove,
    consume_shield_master_reaction_no_damage,
    shield_master_bonus_shove_legality,
    shield_master_reaction_negation_legality,
    shield_master_save_bonus,
)


def _actor(actor_id: str = "hero") -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team="party",
        name=actor_id,
        max_hp=20,
        hp=20,
        temp_hp=0,
        ac=16,
        initiative_mod=2,
        str_mod=3,
        dex_mod=2,
        con_mod=2,
        int_mod=0,
        wis_mod=1,
        cha_mod=0,
        save_mods={"str": 3, "dex": 2, "con": 2, "wis": 1},
        actions=[],
    )


def _equip_shield(actor: ActorRuntimeState, *, ac_bonus: int = 2) -> None:
    actor.inventory.add_item(
        InventoryItem(
            item_id="shield",
            name="Shield",
            equip_slots=("shield",),
            metadata={"armor_type": "shield", "ac_bonus": ac_bonus},
        )
    )
    actor.inventory.equip_item("shield")


def test_shield_master_save_bonus_applies_only_for_self_targeted_dex_saves() -> None:
    hero = _actor("hero")
    hero.traits = {"shield master": {}}
    _equip_shield(hero, ac_bonus=3)

    assert (
        shield_master_save_bonus(
            hero,
            save_ability="dex",
            effect_target_ids=["hero"],
        )
        == 3
    )
    assert (
        shield_master_save_bonus(
            hero,
            save_ability="dex",
            effect_target_ids=["hero", "ally"],
        )
        == 0
    )


def test_shield_master_shove_window_opens_after_attack_action_on_actor_turn() -> None:
    hero = _actor("hero")
    hero.traits = {"shield master": {}}
    _equip_shield(hero)

    legal, reason = shield_master_bonus_shove_legality(hero, turn_token="1:hero")
    assert legal is False
    assert reason == "attack_action_not_taken"

    hero.took_attack_action_this_turn = True
    legal, reason = shield_master_bonus_shove_legality(hero, turn_token="1:hero")
    assert legal is True
    assert reason is None


def test_shield_master_shove_consumes_bonus_action_and_blocks_repeat_sequence() -> None:
    hero = _actor("hero")
    hero.traits = {"shield master": {}}
    _equip_shield(hero)
    hero.took_attack_action_this_turn = True

    used, reason = consume_shield_master_bonus_shove(hero, turn_token="1:hero")
    assert used is True
    assert reason is None
    assert hero.bonus_available is False

    used, reason = consume_shield_master_bonus_shove(hero, turn_token="1:hero")
    assert used is False
    assert reason == "bonus_unavailable"


def test_shield_master_shove_rejects_illegal_off_turn_sequence() -> None:
    hero = _actor("hero")
    hero.traits = {"shield master": {}}
    _equip_shield(hero)
    hero.took_attack_action_this_turn = True

    legal, reason = shield_master_bonus_shove_legality(hero, turn_token="1:enemy")
    assert legal is False
    assert reason == "off_turn"


def test_shield_master_reaction_negation_consumes_reaction_only_on_legal_success() -> None:
    hero = _actor("hero")
    hero.traits = {"shield master": {}}
    _equip_shield(hero)

    used, reason = consume_shield_master_reaction_no_damage(
        hero,
        save_ability="dex",
        half_on_save=True,
        save_succeeded=True,
    )
    assert used is True
    assert reason is None
    assert hero.reaction_available is False


def test_shield_master_reaction_negation_rejects_illegal_windows_without_spending() -> None:
    hero = _actor("hero")
    hero.traits = {"shield master": {}}
    _equip_shield(hero)

    legal, reason = shield_master_reaction_negation_legality(
        hero,
        save_ability="dex",
        half_on_save=True,
        save_succeeded=False,
    )
    assert legal is False
    assert reason == "save_failed"
    assert hero.reaction_available is True

    hero.reaction_available = False
    used, reason = consume_shield_master_reaction_no_damage(
        hero,
        save_ability="dex",
        half_on_save=True,
        save_succeeded=True,
    )
    assert used is False
    assert reason == "reaction_unavailable"
