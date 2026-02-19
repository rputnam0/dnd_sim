from __future__ import annotations

import random
import re
from dataclasses import dataclass

from dnd_sim.models import ActorRuntimeState

_DAMAGE_RE = re.compile(r"^(?:(\d+)d(\d+))?([+-]\d+)?$")


@dataclass(slots=True)
class AttackRollResult:
    hit: bool
    crit: bool
    natural_roll: int
    total: int


@dataclass(slots=True)
class DeathSaveResult:
    became_stable: bool
    became_dead: bool
    regained_consciousness: bool


@dataclass(slots=True)
class DamageRollResult:
    rolled: int
    applied: int


def roll_dice(rng: random.Random, sides: int, count: int = 1) -> int:
    return sum(rng.randint(1, sides) for _ in range(count))


def parse_damage_expression(expr: str) -> tuple[int, int, int]:
    value = expr.strip().replace(" ", "")
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        return 0, 0, int(value)

    match = _DAMAGE_RE.fullmatch(value)
    if not match:
        raise ValueError(f"Invalid damage expression: {expr}")

    n_dice = int(match.group(1) or 0)
    dice_size = int(match.group(2) or 0)
    flat = int(match.group(3) or 0)
    return n_dice, dice_size, flat


def attack_roll(
    rng: random.Random,
    to_hit: int,
    target_ac: int,
    *,
    advantage: bool = False,
    disadvantage: bool = False,
) -> AttackRollResult:
    if advantage and disadvantage:
        advantage = False
        disadvantage = False

    if advantage:
        natural_roll = max(rng.randint(1, 20), rng.randint(1, 20))
    elif disadvantage:
        natural_roll = min(rng.randint(1, 20), rng.randint(1, 20))
    else:
        natural_roll = rng.randint(1, 20)

    crit = natural_roll == 20
    total = natural_roll + to_hit
    hit = crit or (natural_roll != 1 and total >= target_ac)
    return AttackRollResult(hit=hit, crit=crit, natural_roll=natural_roll, total=total)


def roll_damage(rng: random.Random, expr: str, *, crit: bool = False) -> int:
    n_dice, dice_size, flat = parse_damage_expression(expr)
    total = flat
    if n_dice and dice_size:
        total += roll_dice(rng, dice_size, n_dice * (2 if crit else 1))
    return max(total, 0)


def half_damage(value: int) -> int:
    return value // 2


def concentration_check_dc(damage: int) -> int:
    return max(10, damage // 2)


def apply_damage_type_modifiers(
    damage: int,
    damage_type: str,
    *,
    resistances: set[str],
    immunities: set[str],
    vulnerabilities: set[str],
) -> int:
    dtype = damage_type.lower()
    if dtype in immunities or "all" in immunities:
        return 0

    adjusted = damage
    if dtype in resistances or "all" in resistances:
        adjusted = half_damage(adjusted)
    if dtype in vulnerabilities or "all" in vulnerabilities:
        adjusted *= 2
    return max(adjusted, 0)


def apply_damage(
    target: ActorRuntimeState,
    amount: int,
    damage_type: str,
    *,
    is_critical: bool = False,
) -> int:
    adjusted = apply_damage_type_modifiers(
        amount,
        damage_type,
        resistances=target.damage_resistances,
        immunities=target.damage_immunities,
        vulnerabilities=target.damage_vulnerabilities,
    )

    if target.hp <= 0 and not target.dead:
        # Failed death save from taking damage while at 0.
        target.death_failures += 2 if is_critical else 1
        if target.death_failures >= 3:
            target.dead = True
            target.conditions.update({"dead", "unconscious", "incapacitated"})
        return adjusted

    remaining = adjusted
    if target.temp_hp > 0 and remaining > 0:
        consumed = min(target.temp_hp, remaining)
        target.temp_hp -= consumed
        remaining -= consumed

    if remaining > 0:
        target.hp -= remaining

    if target.hp <= 0 and not target.dead:
        target.hp = 0
        target.conditions.update({"unconscious", "incapacitated"})
        if not target.was_downed:
            target.downed_count += 1
            target.was_downed = True

    return adjusted


def run_concentration_check(
    rng: random.Random,
    target: ActorRuntimeState,
    damage_taken: int,
) -> bool:
    if not target.concentrating:
        return True

    dc = concentration_check_dc(damage_taken)
    roll = rng.randint(1, 20) + target.con_mod
    success = roll >= dc
    if not success:
        target.concentrating = False
    return success


def resolve_death_save(rng: random.Random, target: ActorRuntimeState) -> DeathSaveResult:
    if target.hp > 0 or target.stable or target.dead:
        return DeathSaveResult(False, target.dead, False)

    roll = rng.randint(1, 20)
    if roll == 1:
        target.death_failures += 2
    elif roll == 20:
        target.hp = 1
        target.death_successes = 0
        target.death_failures = 0
        target.stable = False
        target.conditions.discard("unconscious")
        target.conditions.discard("incapacitated")
        return DeathSaveResult(False, False, True)
    elif roll >= 10:
        target.death_successes += 1
    else:
        target.death_failures += 1

    became_stable = False
    became_dead = False
    if target.death_successes >= 3:
        target.stable = True
        became_stable = True
    if target.death_failures >= 3:
        target.dead = True
        target.conditions.update({"dead", "unconscious", "incapacitated"})
        became_dead = True

    return DeathSaveResult(became_stable, became_dead, False)
