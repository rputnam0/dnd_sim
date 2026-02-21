from __future__ import annotations

import random

from dnd_sim.models import ActorRuntimeState
from dnd_sim.rules_2014 import (
    apply_damage_type_modifiers,
    attack_roll,
    concentration_check_dc,
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


def test_concentration_check_rolls_once_without_advantage_or_disadvantage() -> None:
    actor = _actor()
    actor.hp = 5
    actor.concentrating = True
    rng = CountingRng([12])
    assert run_concentration_check(rng, actor, damage_taken=10) is True
    assert rng.calls == 1


def test_run_contested_check_tie_goes_to_defender() -> None:
    rng = FixedRng([10, 10])
    assert run_contested_check(rng, attacker_mod=2, defender_mods=[2]) is False
