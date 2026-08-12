"""Damage-expression parsing and RNG-boundary journal capture."""

from __future__ import annotations

import random
import re

from dnd_sim.models import ActorRuntimeState
from dnd_sim.roll_journal import BoundRollJournalRecorder, DamageAdjustment

_DAMAGE_RE = re.compile(r"^(?:(\d+)d(\d+))?([+-]\d+)?$")
_TRAIT_NORMALIZE_RE = re.compile(r"[\s_-]+")


def _normalize_trait_name(name: str) -> str:
    return _TRAIT_NORMALIZE_RE.sub(" ", str(name).strip().lower())


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


def roll_damage(
    rng: random.Random,
    expr: str,
    *,
    crit: bool = False,
    empowered_rerolls: int = 0,
    source: ActorRuntimeState | None = None,
    damage_type: str = "",
    journal_recorder: BoundRollJournalRecorder | None = None,
) -> int:
    """Roll raw damage and optionally capture the exact RNG-boundary facts."""

    if journal_recorder is not None and not isinstance(journal_recorder, BoundRollJournalRecorder):
        raise TypeError("journal_recorder must be a BoundRollJournalRecorder")
    n_dice, dice_size, flat = parse_damage_expression(expr)
    total = flat
    initial_values: tuple[int, ...] = ()
    rerolls: list[tuple[int, int]] = []
    raw_adjustments: list[DamageAdjustment] = []
    rolls_after_rerolls: tuple[int, ...] = ()
    if n_dice and dice_size:
        rolls = [rng.randint(1, dice_size) for _ in range(n_dice * (2 if crit else 1))]
        if journal_recorder is not None:
            initial_values = tuple(rolls)
        if empowered_rerolls > 0:
            sorted_initial_indices = (
                sorted(range(len(rolls)), key=lambda index: rolls[index])
                if journal_recorder is not None
                else []
            )
            rolls.sort()
            for index in range(min(empowered_rerolls, len(rolls))):
                if rolls[index] <= dice_size // 2:
                    replacement = rng.randint(1, dice_size)
                    rolls[index] = replacement
                    if journal_recorder is not None:
                        rerolls.append((sorted_initial_indices[index] + 1, replacement))

        if journal_recorder is not None:
            rolls_after_rerolls = tuple(rolls)

        if source and damage_type:
            floor = 1
            floor_source_id: str | None = None
            for trait_name, trait_data in source.traits.items():
                for mechanic in trait_data.get("mechanics", []):
                    if mechanic.get("effect_type") == "damage_roll_floor":
                        required_type = mechanic.get("damage_type", "").lower()
                        if required_type == damage_type.lower() or required_type == "any_elemental":
                            candidate_floor = mechanic.get("floor", 1)
                            if candidate_floor > floor:
                                floor = candidate_floor
                                if journal_recorder is not None:
                                    floor_source_id = f"trait:{_normalize_trait_name(trait_name)}:damage-floor:{floor}"
            if floor > 1:
                rolls = [max(roll, floor) for roll in rolls]
                floor_delta = (
                    sum(rolls) - sum(rolls_after_rerolls) if journal_recorder is not None else 0
                )
                if journal_recorder is not None and floor_delta:
                    raw_adjustments.append(
                        DamageAdjustment(
                            stage="raw",
                            kind="floor",
                            amount=floor_delta,
                            source_id=floor_source_id,
                        )
                    )

        total += sum(rolls)
    raw_total = max(total, 0)
    if journal_recorder is not None and raw_total != total:
        raw_adjustments.append(
            DamageAdjustment(
                stage="raw",
                kind="floor",
                amount=raw_total - total,
                source_id="rule:minimum-damage:0",
            )
        )
    if journal_recorder is not None:
        journal_recorder.record_damage(
            expression=expr.strip(),
            damage_type=damage_type.strip().lower() or None,
            die_sides=dice_size if initial_values else None,
            initial_values=initial_values,
            rerolls=tuple(rerolls),
            flat_modifier=flat,
            rolled_total=flat + sum(rolls_after_rerolls),
            raw_damage=raw_total,
            critical=crit,
            raw_adjustments=tuple(raw_adjustments),
        )
    return raw_total


def _damage_expr_has_dice(expr: str) -> bool:
    try:
        n_dice, dice_size, _flat = parse_damage_expression(expr)
    except ValueError:
        return False
    return n_dice > 0 and dice_size > 0


__all__ = ["parse_damage_expression", "roll_damage"]
