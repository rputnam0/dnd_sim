from __future__ import annotations

import random

from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.rules_2014 import (
    attack_roll,
    great_weapon_master_toggle_state,
    roll_damage,
    sharpshooter_toggle_state,
)


class _FixedRng:
    def __init__(self, values: list[int]) -> None:
        self._values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self._values:
            raise AssertionError("RNG exhausted")
        return self._values.pop(0)


def _actor(*, actor_id: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team="party",
        name=actor_id,
        max_hp=30,
        hp=30,
        temp_hp=0,
        ac=14,
        initiative_mod=0,
        str_mod=4,
        dex_mod=2,
        con_mod=2,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 4, "dex": 2, "con": 2, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def test_gwm_toggle_damage_math_and_hit_modifier_are_deterministic() -> None:
    actor = _actor(actor_id="fighter")
    actor.traits["great weapon master"] = {}
    action = ActionDefinition(
        name="greatsword",
        action_type="attack",
        to_hit=8,
        damage="1d8+2",
        damage_type="slashing",
        weapon_properties=["heavy"],
        range_ft=5,
    )

    toggle = great_weapon_master_toggle_state(actor=actor, action=action, enabled=True)
    assert toggle.active is True
    assert toggle.to_hit_modifier == -5
    assert toggle.damage_bonus == 10
    assert toggle.reason is None

    roll = attack_roll(
        _FixedRng([11]),
        to_hit=action.to_hit + toggle.to_hit_modifier,
        target_ac=13,
    )
    assert roll.hit is True
    assert roll.total == 14

    base_damage = roll_damage(random.Random(1), action.damage, crit=False)
    assert base_damage == 5
    assert base_damage + toggle.damage_bonus == 15


def test_sharpshooter_toggle_respects_advantage_and_disadvantage_roll_modes() -> None:
    actor = _actor(actor_id="ranger")
    actor.traits["sharpshooter"] = {}
    action = ActionDefinition(
        name="longbow",
        action_type="attack",
        to_hit=8,
        damage="1d8+3",
        damage_type="piercing",
        weapon_properties=["ammunition"],
        range_normal_ft=150,
        range_long_ft=600,
    )

    toggle = sharpshooter_toggle_state(actor=actor, action=action, enabled=True)
    assert toggle.active is True
    assert toggle.to_hit_modifier == -5

    # Advantage picks the higher die (17) and still hits after the -5 penalty.
    advantage_roll = attack_roll(
        _FixedRng([3, 17]),
        to_hit=action.to_hit + toggle.to_hit_modifier,
        target_ac=16,
        advantage=True,
    )
    assert advantage_roll.natural_roll == 17
    assert advantage_roll.hit is True

    # Disadvantage picks the lower die (6) and misses due to the toggle penalty.
    disadvantage_roll = attack_roll(
        _FixedRng([18, 6]),
        to_hit=action.to_hit + toggle.to_hit_modifier,
        target_ac=13,
        disadvantage=True,
    )
    assert disadvantage_roll.natural_roll == 6
    assert disadvantage_roll.hit is False


def test_illegal_toggles_return_explicit_reasons() -> None:
    actor = _actor(actor_id="martial")
    actor.traits["great weapon master"] = {}
    actor.traits["sharpshooter"] = {}

    ranged_heavy = ActionDefinition(
        name="heavy_crossbow",
        action_type="attack",
        to_hit=6,
        damage="1d10+3",
        damage_type="piercing",
        weapon_properties=["heavy", "ammunition"],
        range_normal_ft=100,
        range_long_ft=400,
    )
    melee = ActionDefinition(
        name="warhammer",
        action_type="attack",
        to_hit=6,
        damage="1d8+3",
        damage_type="bludgeoning",
        weapon_properties=["versatile"],
        range_ft=5,
    )
    utility = ActionDefinition(
        name="dash",
        action_type="utility",
        action_cost="action",
        target_mode="self",
    )

    gwm_invalid = great_weapon_master_toggle_state(actor=actor, action=ranged_heavy, enabled=True)
    assert gwm_invalid.active is False
    assert gwm_invalid.reason == "weapon_not_melee"

    sharp_invalid = sharpshooter_toggle_state(actor=actor, action=melee, enabled=True)
    assert sharp_invalid.active is False
    assert sharp_invalid.reason == "weapon_not_ranged"

    no_feat_actor = _actor(actor_id="no_feat")
    missing_feat = great_weapon_master_toggle_state(actor=no_feat_actor, action=melee, enabled=True)
    assert missing_feat.active is False
    assert missing_feat.reason == "missing_trait"

    non_attack = sharpshooter_toggle_state(actor=actor, action=utility, enabled=True)
    assert non_attack.active is False
    assert non_attack.reason == "non_attack_action"


def test_weapon_property_checks_do_not_use_action_tags() -> None:
    actor = _actor(actor_id="tag_check")
    actor.traits["great weapon master"] = {}
    action = ActionDefinition(
        name="tagged_attack",
        action_type="attack",
        to_hit=6,
        damage="1d8+2",
        damage_type="slashing",
        weapon_properties=[],
        tags=["heavy"],
        range_ft=5,
    )

    toggle = great_weapon_master_toggle_state(actor=actor, action=action, enabled=True)

    assert toggle.active is False
    assert toggle.reason == "weapon_not_heavy"


def test_thrown_weapon_requires_range_values_to_count_as_ranged() -> None:
    actor = _actor(actor_id="thrower")
    actor.traits["sharpshooter"] = {}

    thrown_without_range = ActionDefinition(
        name="improvised_throw",
        action_type="attack",
        to_hit=6,
        damage="1d4+2",
        damage_type="bludgeoning",
        weapon_properties=["thrown"],
    )
    blocked_toggle = sharpshooter_toggle_state(
        actor=actor,
        action=thrown_without_range,
        enabled=True,
    )
    assert blocked_toggle.active is False
    assert blocked_toggle.reason == "weapon_not_ranged"

    thrown_with_range = ActionDefinition(
        name="dagger_throw",
        action_type="attack",
        to_hit=6,
        damage="1d4+2",
        damage_type="piercing",
        weapon_properties=["thrown"],
        range_ft=20,
    )
    active_toggle = sharpshooter_toggle_state(
        actor=actor,
        action=thrown_with_range,
        enabled=True,
    )
    assert active_toggle.active is True
    assert active_toggle.reason is None
