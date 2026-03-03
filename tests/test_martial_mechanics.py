from __future__ import annotations

import random

import pytest

from dnd_sim.engine import (
    _action_available,
    _build_actor_from_character,
    _build_character_actions,
    _dispatch_combat_event,
    _execute_action,
    _find_best_bonus_action,
    _mark_action_cost_used,
)
from dnd_sim.models import ActorRuntimeState


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self.values:
            raise AssertionError("RNG exhausted")
        return self.values.pop(0)


def _gwm_character(*, damage: str) -> dict:
    return {
        "character_id": "gwm_hero",
        "name": "GWM Hero",
        "class_level": "Fighter 8",
        "max_hp": 50,
        "ac": 16,
        "speed_ft": 30,
        "ability_scores": {
            "str": 18,
            "dex": 12,
            "con": 14,
            "int": 10,
            "wis": 10,
            "cha": 10,
        },
        "save_mods": {"str": 4, "dex": 1, "con": 2, "int": 0, "wis": 0, "cha": 0},
        "skill_mods": {},
        "attacks": [
            {
                "name": "Greatsword",
                "to_hit": 8,
                "damage": damage,
                "damage_type": "slashing",
            }
        ],
        "resources": {},
        "traits": ["Great Weapon Master"],
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }


def _enemy(actor_id: str, *, hp: int) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team="enemy",
        name=actor_id,
        max_hp=hp,
        hp=hp,
        temp_hp=0,
        ac=10,
        initiative_mod=0,
        str_mod=0,
        dex_mod=0,
        con_mod=0,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def _combat_trackers(*actors: ActorRuntimeState) -> tuple[dict[str, int], ...]:
    damage_dealt = {actor.actor_id: 0 for actor in actors}
    damage_taken = {actor.actor_id: 0 for actor in actors}
    threat_scores = {actor.actor_id: 0 for actor in actors}
    return damage_dealt, damage_taken, threat_scores


@pytest.mark.parametrize(
    ("damage", "target_hp", "roll"),
    [
        ("1", 10, 20),  # crit trigger
        ("50", 10, 15),  # kill trigger
    ],
)
def test_gwm_crit_or_kill_creates_one_eligible_bonus_attack(
    damage: str, target_hp: int, roll: int
) -> None:
    actor = _build_actor_from_character(_gwm_character(damage=damage), traits_db={})
    target = _enemy("ogre", hp=target_hp)
    actors = {actor.actor_id: actor, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores = _combat_trackers(actor, target)
    resources_spent = {actor.actor_id: {}, target.actor_id: {}}
    basic_attack = next(action for action in actor.actions if action.name == "basic")

    _execute_action(
        rng=FixedRng([roll]),
        actor=actor,
        action=basic_attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token=f"1:{actor.actor_id}",
    )

    assert actor.gwm_bonus_trigger_available is True
    bonus_action = _find_best_bonus_action(actor)
    assert bonus_action is not None
    assert bonus_action.name == "gwm_bonus_attack"

    _mark_action_cost_used(actor, bonus_action)
    assert actor.gwm_bonus_trigger_available is False


def test_gwm_unspent_trigger_expires_at_turn_end() -> None:
    actor = _build_actor_from_character(_gwm_character(damage="1"), traits_db={})
    target = _enemy("ogre", hp=10)
    actors = {actor.actor_id: actor, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores = _combat_trackers(actor, target)
    resources_spent = {actor.actor_id: {}, target.actor_id: {}}
    basic_attack = next(action for action in actor.actions if action.name == "basic")

    _execute_action(
        rng=FixedRng([20]),
        actor=actor,
        action=basic_attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token=f"1:{actor.actor_id}",
    )
    assert actor.gwm_bonus_trigger_available is True

    _dispatch_combat_event(
        rng=random.Random(1),
        event="turn_end",
        trigger_actor=actor,
        trigger_target=actor,
        trigger_action=None,
        actors=actors,
        round_number=1,
        turn_token=f"1:{actor.actor_id}",
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert actor.gwm_bonus_trigger_available is False
    assert _find_best_bonus_action(actor) is None


def test_gwm_trigger_is_not_reusable_on_later_turn() -> None:
    actor = _build_actor_from_character(_gwm_character(damage="1"), traits_db={})
    target = _enemy("ogre", hp=20)
    actors = {actor.actor_id: actor, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores = _combat_trackers(actor, target)
    resources_spent = {actor.actor_id: {}, target.actor_id: {}}
    basic_attack = next(action for action in actor.actions if action.name == "basic")

    _execute_action(
        rng=FixedRng([20]),
        actor=actor,
        action=basic_attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token=f"1:{actor.actor_id}",
    )
    assert actor.gwm_bonus_trigger_available is True

    _dispatch_combat_event(
        rng=random.Random(2),
        event="turn_end",
        trigger_actor=actor,
        trigger_target=actor,
        trigger_action=None,
        actors=actors,
        round_number=1,
        turn_token=f"1:{actor.actor_id}",
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    actor.bonus_available = True
    actor.took_attack_action_this_turn = False
    _execute_action(
        rng=FixedRng([12]),
        actor=actor,
        action=basic_attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=2,
        turn_token=f"2:{actor.actor_id}",
    )

    assert actor.gwm_bonus_trigger_available is False
    assert _find_best_bonus_action(actor) is None


def _martial_character(*, traits: list[str], attacks: list[dict]) -> dict:
    return {
        "character_id": "martial_tester",
        "name": "Martial Tester",
        "class_level": "Fighter 5",
        "max_hp": 40,
        "ac": 16,
        "speed_ft": 30,
        "ability_scores": {
            "str": 10,
            "dex": 18,
            "con": 14,
            "int": 10,
            "wis": 10,
            "cha": 10,
        },
        "save_mods": {"str": 0, "dex": 4, "con": 2, "int": 0, "wis": 0, "cha": 0},
        "skill_mods": {},
        "attacks": attacks,
        "resources": {},
        "traits": traits,
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }


def _dual_light_attacks() -> list[dict]:
    return [
        {
            "attack_profile_id": "mainhand_profile",
            "weapon_id": "weapon_mainhand",
            "item_id": "item_mainhand",
            "name": "Mainhand Shortsword",
            "to_hit": 8,
            "damage": "1d6+4",
            "damage_type": "piercing",
            "weapon_properties": ["light", "finesse"],
        },
        {
            "attack_profile_id": "offhand_profile",
            "weapon_id": "weapon_offhand",
            "item_id": "item_offhand",
            "name": "Offhand Dagger",
            "to_hit": 8,
            "damage": "1d4+4",
            "damage_type": "piercing",
            "weapon_properties": ["light", "finesse"],
        },
    ]


def test_two_weapon_offhand_baseline_preserves_identity_and_no_ability_damage() -> None:
    character = _martial_character(traits=["Extra Attack"], attacks=_dual_light_attacks())

    actions = _build_character_actions(character)
    off_hand = next(action for action in actions if action.name == "off_hand_attack")

    assert off_hand.action_cost == "bonus"
    assert off_hand.attack_profile_id == "offhand_profile"
    assert off_hand.weapon_id == "weapon_offhand"
    assert off_hand.item_id == "item_offhand"
    assert set(off_hand.weapon_properties) == {"light", "finesse"}
    assert off_hand.damage == "1d4"


def test_two_weapon_offhand_requires_attack_action_before_bonus_use() -> None:
    character = _martial_character(traits=["Extra Attack"], attacks=_dual_light_attacks())
    actor = _build_actor_from_character(character, traits_db={})
    off_hand = next(action for action in actor.actions if action.name == "off_hand_attack")

    actor.took_attack_action_this_turn = False
    assert _action_available(actor, off_hand) is False

    actor.took_attack_action_this_turn = True
    assert _action_available(actor, off_hand) is True


def test_two_weapon_offhand_style_adds_ability_modifier() -> None:
    character = _martial_character(
        traits=["Extra Attack", "Two-Weapon Fighting"],
        attacks=_dual_light_attacks(),
    )

    actions = _build_character_actions(character)
    off_hand = next(action for action in actions if action.name == "off_hand_attack")

    assert off_hand.damage == "1d4+4"


def test_two_weapon_offhand_baseline_keeps_negative_ability_modifier() -> None:
    character = _martial_character(traits=["Extra Attack"], attacks=_dual_light_attacks())
    character["ability_scores"]["str"] = 8
    character["save_mods"]["str"] = -1
    character["ability_scores"]["dex"] = 8
    character["save_mods"]["dex"] = -1
    offhand = next(
        attack for attack in character["attacks"] if attack["attack_profile_id"] == "offhand_profile"
    )
    offhand["damage"] = "1d4-1"

    actions = _build_character_actions(character)
    off_hand = next(action for action in actions if action.name == "off_hand_attack")

    assert off_hand.damage == "1d4-1"


def test_two_weapon_offhand_illegal_setup_rejected_without_override() -> None:
    character = _martial_character(
        traits=["Extra Attack", "Two-Weapon Fighting"],
        attacks=[
            {
                "attack_profile_id": "mainhand_profile",
                "weapon_id": "weapon_mainhand",
                "item_id": "item_mainhand",
                "name": "Mainhand Shortsword",
                "to_hit": 8,
                "damage": "1d6+4",
                "damage_type": "piercing",
                "weapon_properties": ["light", "finesse"],
            },
            {
                "attack_profile_id": "offhand_profile",
                "weapon_id": "weapon_offhand",
                "item_id": "item_offhand",
                "name": "Offhand Rapier",
                "to_hit": 8,
                "damage": "1d8+4",
                "damage_type": "piercing",
                "weapon_properties": ["finesse"],
            },
        ],
    )

    actions = _build_character_actions(character)

    assert "off_hand_attack" not in {action.name for action in actions}
