from __future__ import annotations

import random
import re
from dataclasses import dataclass

from dnd_sim.models import ActorRuntimeState

_DAMAGE_RE = re.compile(r"^(?:(\d+)d(\d+))?([+-]\d+)?$")
_TRAIT_NORMALIZE_RE = re.compile(r"[\s_-]+")


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


def _normalize_trait_name(name: str) -> str:
    return _TRAIT_NORMALIZE_RE.sub(" ", str(name).strip().lower())


def _has_trait(actor: ActorRuntimeState, trait_name: str) -> bool:
    needle = _normalize_trait_name(trait_name)
    return any(_normalize_trait_name(key) == needle for key in actor.traits.keys())


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


def run_contested_check(
    rng: random.Random,
    attacker_mod: int,
    defender_mods: list[int],
) -> bool:
    """Evaluates a contested check. Ties go to the defender."""
    attacker_roll = rng.randint(1, 20) + attacker_mod
    defender_mod = max(defender_mods) if defender_mods else 0
    defender_roll = rng.randint(1, 20) + defender_mod
    return attacker_roll > defender_roll


def roll_damage(
    rng: random.Random,
    expr: str,
    *,
    crit: bool = False,
    empowered_rerolls: int = 0,
    source: ActorRuntimeState | None = None,
    damage_type: str = "",
) -> int:
    n_dice, dice_size, flat = parse_damage_expression(expr)
    total = flat
    if n_dice and dice_size:
        rolls = [rng.randint(1, dice_size) for _ in range(n_dice * (2 if crit else 1))]
        if empowered_rerolls > 0:
            rolls.sort()
            for i in range(min(empowered_rerolls, len(rolls))):
                if rolls[i] <= dice_size // 2:
                    rolls[i] = rng.randint(1, dice_size)

        if source and damage_type:
            floor = 1
            for trait_data in source.traits.values():
                for mechanic in trait_data.get("mechanics", []):
                    if mechanic.get("effect_type") == "damage_roll_floor":
                        req_type = mechanic.get("damage_type", "").lower()
                        if req_type == damage_type.lower() or req_type == "any_elemental":
                            floor = max(floor, mechanic.get("floor", 1))
            if floor > 1:
                rolls = [max(r, floor) for r in rolls]

        total += sum(rolls)
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
    is_resistant = dtype in resistances or "all" in resistances
    is_vulnerable = dtype in vulnerabilities or "all" in vulnerabilities
    if is_resistant and is_vulnerable:
        pass  # cancel each other per RAW
    elif is_resistant:
        adjusted = half_damage(adjusted)
    elif is_vulnerable:
        adjusted *= 2
    return max(adjusted, 0)


def apply_damage(
    target: ActorRuntimeState,
    amount: int,
    damage_type: str,
    *,
    is_critical: bool = False,
    is_magical: bool = False,
    source: ActorRuntimeState | None = None,
) -> int:
    adjusted = amount

    for trait_data in target.traits.values():
        for mechanic in trait_data.get("mechanics", []):
            if mechanic.get("effect_type") == "reduce_damage_taken":
                if damage_type in mechanic.get("damage_types", []):
                    cond = mechanic.get("condition")
                    if cond == "nonmagical" and is_magical:
                        continue
                    amt = mechanic.get("amount", 0)
                    adjusted = max(0, adjusted - amt)

    # Check attacker traits for resistance bypass (e.g. Elemental Adept)
    effective_resistances = set(target.damage_resistances)

    # Phase 10: Barbarian Rage Resistance
    if "raging" in target.conditions:
        effective_resistances.update(["bludgeoning", "piercing", "slashing"])

    if source:
        for trait_data in source.traits.values():
            for mechanic in trait_data.get("mechanics", []):
                if mechanic.get("effect_type") == "ignore_resistance":
                    bypass_type = mechanic.get("damage_type", "").lower()
                    if bypass_type in {damage_type.lower(), "any_elemental"}:
                        effective_resistances.discard(damage_type.lower())

    adjusted = apply_damage_type_modifiers(
        adjusted,
        damage_type,
        resistances=effective_resistances,
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

    if adjusted > 0 and "turned" in target.conditions:
        for condition in ("turned", "frightened", "incapacitated"):
            target.conditions.discard(condition)
            target.condition_durations.pop(condition, None)

    return adjusted


def run_concentration_check(
    rng: random.Random,
    target: ActorRuntimeState,
    damage_taken: int,
    source: ActorRuntimeState | None = None,
) -> bool:
    if not target.concentrating:
        return True

    dc = concentration_check_dc(damage_taken)
    advantage = _has_trait(target, "war caster")
    disadvantage = bool(source and _has_trait(source, "mage slayer"))

    if advantage and not disadvantage:
        roll = max(rng.randint(1, 20), rng.randint(1, 20))
    elif disadvantage and not advantage:
        roll = min(rng.randint(1, 20), rng.randint(1, 20))
    else:
        roll = rng.randint(1, 20)

    save_mod = target.save_mods.get("con", target.con_mod)
    success = (roll + save_mod) >= dc
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
