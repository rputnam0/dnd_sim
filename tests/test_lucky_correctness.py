from __future__ import annotations

from dnd_sim.models import ActorRuntimeState
from dnd_sim.rules_2014 import (
    AttackRollResult,
    apply_lucky_attacker_reroll,
    apply_lucky_defender_reroll,
    apply_lucky_save_reroll,
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


def _actor(*, actor_id: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team="party",
        name=actor_id,
        max_hp=20,
        hp=20,
        temp_hp=0,
        ac=10,
        initiative_mod=0,
        str_mod=0,
        dex_mod=0,
        con_mod=2,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 0, "dex": 0, "con": 2, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def _resource_trackers(*actors: ActorRuntimeState) -> dict[str, dict[str, int]]:
    return {actor.actor_id: {} for actor in actors}


def test_lucky_attacker_reroll_uses_higher_die_and_spends_point() -> None:
    attacker = _actor(actor_id="attacker")
    attacker.traits["lucky"] = {}
    attacker.resources["luck_points"] = 2
    resources_spent = _resource_trackers(attacker)
    rng = _FixedRng([18])

    original = AttackRollResult(hit=False, crit=False, natural_roll=4, total=9)
    rerolled = apply_lucky_attacker_reroll(
        rng=rng,
        attacker=attacker,
        roll=original,
        to_hit_modifier=5,
        target_ac=15,
        resources_spent=resources_spent,
    )

    assert rerolled.natural_roll == 18
    assert rerolled.total == 23
    assert rerolled.hit is True
    assert attacker.resources["luck_points"] == 1
    assert resources_spent[attacker.actor_id]["luck_points"] == 1


def test_lucky_defender_reroll_uses_lower_die_and_spends_point() -> None:
    defender = _actor(actor_id="defender")
    defender.traits["lucky"] = {}
    defender.resources["luck_points"] = 1
    resources_spent = _resource_trackers(defender)
    rng = _FixedRng([2])

    original = AttackRollResult(hit=True, crit=False, natural_roll=17, total=23)
    rerolled = apply_lucky_defender_reroll(
        rng=rng,
        defender=defender,
        roll=original,
        to_hit_modifier=6,
        target_ac=15,
        resources_spent=resources_spent,
    )

    assert rerolled.natural_roll == 2
    assert rerolled.total == 8
    assert rerolled.hit is False
    assert defender.resources["luck_points"] == 0
    assert resources_spent[defender.actor_id]["luck_points"] == 1


def test_lucky_save_reroll_uses_higher_die_and_spends_point() -> None:
    target = _actor(actor_id="target")
    target.traits["lucky"] = {}
    target.resources["luck_points"] = 3
    resources_spent = _resource_trackers(target)
    rng = _FixedRng([14])

    final_roll = apply_lucky_save_reroll(
        rng=rng,
        target=target,
        save_roll=5,
        save_mod=2,
        dc=15,
        resources_spent=resources_spent,
    )

    assert final_roll == 14
    assert target.resources["luck_points"] == 2
    assert resources_spent[target.actor_id]["luck_points"] == 1


def test_lucky_does_not_spend_without_points_or_trait() -> None:
    attacker = _actor(actor_id="attacker")
    defender = _actor(actor_id="defender")
    target = _actor(actor_id="target")
    attacker.traits["lucky"] = {}
    defender.traits["lucky"] = {}
    attacker.resources["luck_points"] = 0
    defender.resources["luck_points"] = 0
    target.resources["luck_points"] = 1
    resources_spent = _resource_trackers(attacker, defender, target)
    rng = _FixedRng([20, 20, 20])

    attack_roll = AttackRollResult(hit=False, crit=False, natural_roll=4, total=9)
    attacker_result = apply_lucky_attacker_reroll(
        rng=rng,
        attacker=attacker,
        roll=attack_roll,
        to_hit_modifier=5,
        target_ac=15,
        resources_spent=resources_spent,
    )
    defender_result = apply_lucky_defender_reroll(
        rng=rng,
        defender=defender,
        roll=AttackRollResult(hit=True, crit=False, natural_roll=16, total=22),
        to_hit_modifier=6,
        target_ac=15,
        resources_spent=resources_spent,
    )
    save_result = apply_lucky_save_reroll(
        rng=rng,
        target=target,
        save_roll=3,
        save_mod=2,
        dc=15,
        resources_spent=resources_spent,
    )

    assert attacker_result == attack_roll
    assert defender_result.hit is True
    assert save_result == 3
    assert attacker.resources["luck_points"] == 0
    assert defender.resources["luck_points"] == 0
    assert target.resources["luck_points"] == 1
    assert resources_spent[attacker.actor_id] == {}
    assert resources_spent[defender.actor_id] == {}
    assert resources_spent[target.actor_id] == {}
    assert rng.calls == 0
