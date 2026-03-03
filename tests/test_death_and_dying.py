from __future__ import annotations

from dnd_sim.models import ActorRuntimeState
from dnd_sim.rules_2014 import apply_damage


def _actor(*, max_hp: int = 12, hp: int = 0, temp_hp: int = 0) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id="hero",
        team="party",
        name="Hero",
        max_hp=max_hp,
        hp=hp,
        temp_hp=temp_hp,
        ac=10,
        initiative_mod=0,
        str_mod=0,
        dex_mod=0,
        con_mod=0,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={},
        actions=[],
    )


def test_zero_hp_damage_without_mitigation_adds_one_failure() -> None:
    target = _actor(max_hp=10, hp=0, temp_hp=0)

    apply_damage(target, 1, "slashing")

    assert target.hp == 0
    assert target.death_failures == 1
    assert target.dead is False


def test_zero_hp_temp_hp_absorbs_damage_before_death_failures() -> None:
    target = _actor(max_hp=10, hp=0, temp_hp=5)

    apply_damage(target, 3, "slashing")

    assert target.hp == 0
    assert target.temp_hp == 2
    assert target.death_failures == 0
    assert target.dead is False


def test_stable_target_taking_damage_becomes_unstable() -> None:
    target = _actor(max_hp=10, hp=0, temp_hp=0)
    target.stable = True
    target.death_successes = 3

    apply_damage(target, 1, "piercing")

    assert target.stable is False
    assert target.death_successes == 0
    assert target.death_failures == 1
    assert target.dead is False


def test_critical_hit_at_zero_hp_adds_two_failures_when_damage_gets_through() -> None:
    target = _actor(max_hp=10, hp=0, temp_hp=1)

    apply_damage(target, 2, "bludgeoning", is_critical=True)

    assert target.hp == 0
    assert target.temp_hp == 0
    assert target.death_failures == 2
    assert target.dead is False


def test_instant_death_when_remaining_damage_from_zero_reaches_max_hp() -> None:
    target = _actor(max_hp=10, hp=4, temp_hp=0)

    apply_damage(target, 14, "necrotic")

    assert target.hp == 0
    assert target.dead is True


def test_instant_death_at_zero_hp_uses_remaining_damage_after_temp_hp() -> None:
    target = _actor(max_hp=10, hp=0, temp_hp=3)

    apply_damage(target, 13, "force")

    assert target.hp == 0
    assert target.temp_hp == 0
    assert target.dead is True


def test_wild_shape_like_overflow_does_not_false_trigger_instant_death() -> None:
    target = _actor(max_hp=12, hp=5, temp_hp=9)

    apply_damage(target, 20, "slashing")

    assert target.hp == 0
    assert target.temp_hp == 0
    assert target.dead is False

