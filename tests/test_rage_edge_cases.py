from __future__ import annotations

from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.rules_2014 import (
    activate_rage,
    apply_damage,
    rage_activation_legality,
    rage_damage_bonus_for_action,
    rage_damage_bonus_for_level,
    rage_resistance_applies,
    run_concentration_check,
)


class _FixedRng:
    def __init__(self, values: list[int]) -> None:
        self._values = list(values)
        self.calls = 0

    def randint(self, _a: int, _b: int) -> int:
        self.calls += 1
        if not self._values:
            raise AssertionError("RNG exhausted")
        return self._values.pop(0)


def _actor(*, actor_id: str, level: int = 5) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team="party",
        name=actor_id,
        max_hp=40,
        hp=40,
        temp_hp=0,
        ac=14,
        initiative_mod=0,
        str_mod=3,
        dex_mod=1,
        con_mod=2,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 3, "dex": 1, "con": 2, "int": 0, "wis": 0, "cha": 0},
        actions=[],
        level=level,
    )


def test_rage_damage_bonus_scales_by_level_for_melee_strength_attack() -> None:
    action = ActionDefinition(
        name="battleaxe",
        action_type="attack",
        to_hit=6,
        damage="1d8+3",
        damage_type="slashing",
        range_ft=5,
    )
    low = _actor(actor_id="low", level=1)
    mid = _actor(actor_id="mid", level=9)
    high = _actor(actor_id="high", level=16)
    for actor in (low, mid, high):
        actor.update_manual_conditions({"raging"})

    assert rage_damage_bonus_for_level(1) == 2
    assert rage_damage_bonus_for_level(9) == 3
    assert rage_damage_bonus_for_level(16) == 4
    assert rage_damage_bonus_for_action(actor=low, action=action) == 2
    assert rage_damage_bonus_for_action(actor=mid, action=action) == 3
    assert rage_damage_bonus_for_action(actor=high, action=action) == 4


def test_rage_damage_bonus_rejects_dex_finesse_and_ranged_attacks() -> None:
    actor = _actor(actor_id="rogue_barb", level=5)
    actor.str_mod = 1
    actor.dex_mod = 4
    actor.update_manual_conditions({"raging"})
    finesse = ActionDefinition(
        name="rapier",
        action_type="attack",
        to_hit=7,
        damage="1d8+4",
        damage_type="piercing",
        weapon_properties=["finesse"],
        range_ft=5,
    )
    ranged = ActionDefinition(
        name="javelin_throw",
        action_type="attack",
        to_hit=5,
        damage="1d6+3",
        damage_type="piercing",
        weapon_properties=["thrown"],
        range_ft=30,
    )

    assert rage_damage_bonus_for_action(actor=actor, action=finesse) == 0
    assert rage_damage_bonus_for_action(actor=actor, action=ranged) == 0
    assert rage_damage_bonus_for_action(actor=actor, action=finesse, using_strength=True) == 2


def test_rage_resistance_scope_is_physical_only() -> None:
    target = _actor(actor_id="barb")
    target.update_manual_conditions({"raging"})

    assert rage_resistance_applies(actor=target, damage_type="slashing (magical)") is True
    assert rage_resistance_applies(actor=target, damage_type="fire") is False

    slashing_applied = apply_damage(target, 10, "slashing (magical)")
    fire_applied = apply_damage(target, 10, "fire")

    assert slashing_applied == 5
    assert fire_applied == 10


def test_stale_illegal_rage_state_does_not_grant_resistance() -> None:
    target = _actor(actor_id="downed")
    target.hp = 0
    target.update_manual_conditions({"raging", "unconscious"})

    applied = apply_damage(target, 10, "slashing")

    assert applied == 10
    assert "raging" not in target.conditions
    assert target.rage_sustained_since_last_turn is False


def test_rage_activation_legality_rejects_invalid_states() -> None:
    missing_trait = _actor(actor_id="missing_trait")
    missing_trait.resources["rage"] = 1
    legal, reason = rage_activation_legality(missing_trait)
    assert legal is False
    assert reason == "missing_trait"

    no_uses = _actor(actor_id="no_uses")
    no_uses.traits["rage"] = {}
    no_uses.resources["rage"] = 0
    legal, reason = rage_activation_legality(no_uses)
    assert legal is False
    assert reason == "no_uses_remaining"

    already_raging = _actor(actor_id="already_raging")
    already_raging.traits["rage"] = {}
    already_raging.resources["rage"] = 1
    already_raging.update_manual_conditions({"raging"})
    legal, reason = rage_activation_legality(already_raging)
    assert legal is False
    assert reason == "already_raging"

    incapacitated = _actor(actor_id="incapacitated")
    incapacitated.traits["rage"] = {}
    incapacitated.resources["rage"] = 1
    incapacitated.update_manual_conditions({"incapacitated"})
    legal, reason = rage_activation_legality(incapacitated)
    assert legal is False
    assert reason == "incapacitated"

    downed = _actor(actor_id="downed")
    downed.traits["rage"] = {}
    downed.resources["rage"] = 1
    downed.hp = 0
    legal, reason = rage_activation_legality(downed)
    assert legal is False
    assert reason == "unconscious_or_dead"


def test_activate_rage_spends_resource_and_preserves_concentration_cleanup_state() -> None:
    actor = _actor(actor_id="activator")
    actor.traits["rage"] = {}
    actor.resources["rage"] = 2
    actor.concentrating = True
    actor.concentrated_spell = "hex"
    actor.concentrated_spell_level = 1
    actor.concentrated_targets = {"enemy_1"}
    actor.concentration_conditions = {"hexed"}
    actor.concentration_effect_instance_ids = {"effect_1"}
    actor.took_attack_action_this_turn = True

    activated, reason = activate_rage(actor)

    assert activated is True
    assert reason is None
    assert actor.resources["rage"] == 1
    assert "raging" in actor.conditions
    assert actor.rage_sustained_since_last_turn is True
    # Engine must run _break_concentration with full context for linked cleanup.
    assert actor.concentrating is True
    assert actor.concentrated_spell == "hex"
    assert actor.concentrated_spell_level == 1
    assert actor.concentrated_targets == {"enemy_1"}
    assert actor.concentration_conditions == {"hexed"}
    assert actor.concentration_effect_instance_ids == {"effect_1"}


def test_run_concentration_check_fails_when_actor_is_raging() -> None:
    actor = _actor(actor_id="raging_caster")
    actor.concentrating = True
    actor.concentrated_spell = "bless"
    actor.concentration_conditions = {"bless"}
    actor.concentration_effect_instance_ids = {"bless_1"}
    actor.update_manual_conditions({"raging"})
    rng = _FixedRng([20])

    success = run_concentration_check(rng, actor, damage_taken=1)

    assert success is False
    # Engine caller should perform linked cleanup via _break_concentration.
    assert actor.concentrating is True
    assert actor.concentrated_spell == "bless"
    assert actor.concentration_conditions == {"bless"}
    assert actor.concentration_effect_instance_ids == {"bless_1"}
    assert rng.calls == 0
