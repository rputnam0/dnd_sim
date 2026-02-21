from __future__ import annotations

import random

from dnd_sim.models import ActorRuntimeState
from dnd_sim.rules_2014 import (
    apply_damage,
    apply_damage_type_modifiers,
    attack_roll,
    concentration_check_dc,
    run_concentration_check,
    resolve_death_save,
    roll_damage,
    run_concentration_check,
    run_contested_check,
)


class FixedRng:
    def __init__(self, values):
        self.values = list(values)

    def randint(self, _a, _b):
        return self.values.pop(0)


class CountingRng(FixedRng):
    def __init__(self, values):
        super().__init__(values)
        self.calls = 0

    def randint(self, _a, _b):
        self.calls += 1
        return super().randint(_a, _b)


def _actor() -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id="x",
        team="party",
        name="x",
        max_hp=10,
        hp=0,
        temp_hp=0,
        ac=10,
        initiative_mod=0,
        str_mod=0,
        dex_mod=0,
        con_mod=2,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"con": 2},
        actions=[],
    )


def test_advantage_disadvantage_cancels() -> None:
    rng_a = random.Random(123)
    rng_b = random.Random(123)
    cancelled = attack_roll(rng_a, to_hit=5, target_ac=15, advantage=True, disadvantage=True)
    plain = attack_roll(rng_b, to_hit=5, target_ac=15)
    assert cancelled.natural_roll == plain.natural_roll


def test_crit_doubles_damage_dice() -> None:
    rng = random.Random(42)
    normal = roll_damage(rng, "1d1+0", crit=False)
    crit = roll_damage(rng, "1d1+0", crit=True)
    assert normal == 1
    assert crit == 2


def test_damage_modifiers_immunity_overrides_resistance() -> None:
    dmg = apply_damage_type_modifiers(
        20,
        "fire",
        resistances={"fire"},
        immunities={"fire"},
        vulnerabilities=set(),
    )
    assert dmg == 0


def test_concentration_dc_rule() -> None:
    assert concentration_check_dc(8) == 10
    assert concentration_check_dc(40) == 20


def test_death_save_natural_20_recovers() -> None:
    actor = _actor()
    rng = FixedRng([20])
    result = resolve_death_save(rng, actor)
    assert result.regained_consciousness is True
    assert actor.hp == 1


def test_concentration_check_honors_war_caster_with_space_separated_trait_key() -> None:
    actor = _actor()
    actor.hp = 5
    actor.concentrating = True
    actor.traits = {"war caster": {}}

    # Without advantage this would fail (1 + 2 < 10). With advantage, it succeeds on 20.
    rng = FixedRng([1, 20])
    assert run_concentration_check(rng, actor, damage_taken=10) is True
    assert actor.concentrating is True


def test_concentration_check_honors_mage_slayer_with_underscore_trait_key() -> None:
    target = _actor()
    target.hp = 5
    target.concentrating = True
    source = _actor()
    source.traits = {"mage_slayer": {}}

    # Without disadvantage this would succeed (20 + 2 >= 10).
    # With disadvantage, the min roll is 1 and concentration fails.
    rng = FixedRng([20, 1])
    assert run_concentration_check(rng, target, damage_taken=10, source=source) is False
    assert target.concentrating is False


def test_concentration_check_uses_single_rng_draw_without_advantage_or_disadvantage() -> None:
    target = _actor()
    target.hp = 5
    target.concentrating = True
    rng = CountingRng([12])
    assert run_concentration_check(rng, target, damage_taken=10) is True
    assert rng.calls == 1


def test_ignore_resistance_any_elemental_bypasses_case_insensitive_damage_type() -> None:
    target = _actor()
    target.hp = 20
    target.max_hp = 20
    target.damage_resistances = {"fire"}
    source = _actor()
    source.traits = {
        "elemental adept": {
            "mechanics": [{"effect_type": "ignore_resistance", "damage_type": "ANY_ELEMENTAL"}]
        }
    }

    applied = apply_damage(target, 10, "Fire", is_magical=True, source=source)

    assert applied == 10
    assert target.hp == 10
