from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SupportsRandInt(Protocol):
    def randint(self, a: int, b: int) -> int:
        ...


@dataclass(frozen=True, slots=True)
class AbilityCheckResult:
    natural_roll: int
    total: int
    modifier: int
    dc: int
    success: bool
    margin: int


@dataclass(frozen=True, slots=True)
class ContestCheckResult:
    attacker_roll: int
    attacker_total: int
    attacker_modifier: int
    defender_roll: int
    defender_total: int
    defender_modifier: int
    success: bool
    margin: int


@dataclass(frozen=True, slots=True)
class PassiveCheckResult:
    score: int
    dc: int
    success: bool
    margin: int


def _validate_int(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")


def _validate_dc(dc: int) -> None:
    _validate_int("dc", dc)
    if dc < 0:
        raise ValueError("dc must be >= 0")


def roll_d20(
    rng: SupportsRandInt,
    *,
    advantage: bool = False,
    disadvantage: bool = False,
) -> int:
    if advantage and disadvantage:
        advantage = False
        disadvantage = False

    if advantage:
        return max(rng.randint(1, 20), rng.randint(1, 20))
    if disadvantage:
        return min(rng.randint(1, 20), rng.randint(1, 20))
    return rng.randint(1, 20)


def evaluate_dc(total: int, dc: int) -> bool:
    _validate_int("total", total)
    _validate_dc(dc)
    return total >= dc


def resolve_ability_check(
    rng: SupportsRandInt,
    *,
    modifier: int,
    dc: int,
    advantage: bool = False,
    disadvantage: bool = False,
) -> AbilityCheckResult:
    _validate_int("modifier", modifier)
    _validate_dc(dc)

    natural_roll = roll_d20(
        rng,
        advantage=advantage,
        disadvantage=disadvantage,
    )
    total = natural_roll + modifier
    success = evaluate_dc(total, dc)
    return AbilityCheckResult(
        natural_roll=natural_roll,
        total=total,
        modifier=modifier,
        dc=dc,
        success=success,
        margin=total - dc,
    )


def resolve_contest(
    rng: SupportsRandInt,
    *,
    attacker_modifier: int,
    defender_modifiers: list[int],
    attacker_advantage: bool = False,
    attacker_disadvantage: bool = False,
    defender_advantage: bool = False,
    defender_disadvantage: bool = False,
) -> ContestCheckResult:
    _validate_int("attacker modifier", attacker_modifier)
    for modifier in defender_modifiers:
        if not isinstance(modifier, int) or isinstance(modifier, bool):
            raise ValueError("defender modifiers must be integers")

    defender_modifier = max(defender_modifiers) if defender_modifiers else 0

    attacker_roll = roll_d20(
        rng,
        advantage=attacker_advantage,
        disadvantage=attacker_disadvantage,
    )
    defender_roll = roll_d20(
        rng,
        advantage=defender_advantage,
        disadvantage=defender_disadvantage,
    )
    attacker_total = attacker_roll + attacker_modifier
    defender_total = defender_roll + defender_modifier
    success = attacker_total > defender_total  # Ties go to defender per 2014 rules.

    return ContestCheckResult(
        attacker_roll=attacker_roll,
        attacker_total=attacker_total,
        attacker_modifier=attacker_modifier,
        defender_roll=defender_roll,
        defender_total=defender_total,
        defender_modifier=defender_modifier,
        success=success,
        margin=attacker_total - defender_total,
    )


def passive_score(*, modifier: int, base: int = 10) -> int:
    _validate_int("modifier", modifier)
    _validate_int("base", base)
    if base < 0:
        raise ValueError("base must be >= 0")
    return base + modifier


def resolve_passive_check(*, modifier: int, dc: int, base: int = 10) -> PassiveCheckResult:
    score = passive_score(modifier=modifier, base=base)
    _validate_dc(dc)
    success = evaluate_dc(score, dc)
    return PassiveCheckResult(
        score=score,
        dc=dc,
        success=success,
        margin=score - dc,
    )


__all__ = [
    "AbilityCheckResult",
    "ContestCheckResult",
    "PassiveCheckResult",
    "evaluate_dc",
    "passive_score",
    "resolve_ability_check",
    "resolve_contest",
    "resolve_passive_check",
    "roll_d20",
]
