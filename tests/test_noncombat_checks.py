from __future__ import annotations

import random

import pytest

from dnd_sim.noncombat_checks import (
    evaluate_dc,
    passive_score,
    resolve_ability_check,
    resolve_contest,
    resolve_passive_check,
)


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        return self.values.pop(0)


def test_ability_check_is_deterministic_for_fixed_roll() -> None:
    rng = FixedRng([12])
    result = resolve_ability_check(rng, modifier=3, dc=15)

    assert result.natural_roll == 12
    assert result.total == 15
    assert result.success is True
    assert result.margin == 0


def test_ability_check_advantage_and_disadvantage_cancel_to_single_roll() -> None:
    rng_a = random.Random(123)
    rng_b = random.Random(123)

    cancelled = resolve_ability_check(
        rng_a,
        modifier=2,
        dc=20,
        advantage=True,
        disadvantage=True,
    )
    plain = resolve_ability_check(rng_b, modifier=2, dc=20)

    assert cancelled.natural_roll == plain.natural_roll
    assert cancelled.total == plain.total
    assert cancelled.success == plain.success


def test_contest_uses_best_defender_modifier_and_defender_wins_ties() -> None:
    rng = FixedRng([10, 10])
    result = resolve_contest(rng, attacker_modifier=2, defender_modifiers=[1, 2])

    assert result.attacker_total == 12
    assert result.defender_total == 12
    assert result.success is False
    assert result.margin == 0


def test_contest_honors_advantage_and_disadvantage() -> None:
    rng = FixedRng([4, 17, 19, 2])
    result = resolve_contest(
        rng,
        attacker_modifier=1,
        defender_modifiers=[0],
        attacker_advantage=True,
        defender_disadvantage=True,
    )

    assert result.attacker_roll == 17
    assert result.defender_roll == 2
    assert result.success is True


def test_passive_check_compares_passive_score_against_dc() -> None:
    assert passive_score(modifier=4) == 14

    result = resolve_passive_check(modifier=4, dc=15)
    assert result.score == 14
    assert result.success is False
    assert result.margin == -1


def test_evaluate_dc_uses_total_greater_than_or_equal_to_dc() -> None:
    assert evaluate_dc(total=14, dc=14) is True
    assert evaluate_dc(total=13, dc=14) is False


def test_ability_check_rejects_negative_dc() -> None:
    with pytest.raises(ValueError, match="dc must be >= 0"):
        resolve_ability_check(FixedRng([10]), modifier=0, dc=-1)


def test_contest_rejects_non_integer_defender_modifier() -> None:
    with pytest.raises(ValueError, match="defender modifiers must be integers"):
        resolve_contest(FixedRng([10, 10]), attacker_modifier=0, defender_modifiers=[1, "bad"])  # type: ignore[list-item]
