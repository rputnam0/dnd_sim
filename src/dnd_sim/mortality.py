from __future__ import annotations

import random
from dataclasses import dataclass

from dnd_sim.models import ActorRuntimeState


def _remove_condition_everywhere(target: ActorRuntimeState, condition: str) -> None:
    # Local import avoids a module-level cycle with engine runtime condition bookkeeping.
    from dnd_sim.engine_runtime import _remove_condition

    _remove_condition(target, condition)


@dataclass(slots=True)
class DeathSaveResult:
    became_stable: bool
    became_dead: bool
    regained_consciousness: bool


def _make_zero_hp_creature_stable(
    target: ActorRuntimeState,
    *,
    recovery_hours: int,
) -> None:
    target.stable = True
    target.death_successes = 0
    target.death_failures = 0
    target.stable_recovery_hours_remaining = recovery_hours
    target.update_manual_conditions({"unconscious", "incapacitated"})
    if "prone" not in target.condition_immunities and "all" not in target.condition_immunities:
        target.add_manual_condition("prone")


def stabilize_creature(
    target: ActorRuntimeState,
    *,
    recovery_hours: int,
) -> bool:
    """Make an eligible zero-HP creature stable and schedule 2014 recovery."""

    if recovery_hours < 1 or recovery_hours > 4:
        raise ValueError("recovery_hours must be between 1 and 4")
    if target.hp != 0 or target.dead or target.stable or target.uses_death_saves is False:
        return False
    _make_zero_hp_creature_stable(target, recovery_hours=recovery_hours)
    return True


def knock_out_creature(
    target: ActorRuntimeState,
    *,
    recovery_hours: int,
) -> bool:
    """Knock out a newly reduced creature regardless of death-save eligibility."""

    if recovery_hours < 1 or recovery_hours > 4:
        raise ValueError("recovery_hours must be between 1 and 4")
    if target.hp != 0 or target.dead or target.stable:
        return False
    _make_zero_hp_creature_stable(target, recovery_hours=recovery_hours)
    return True


def advance_stable_recovery(target: ActorRuntimeState, *, hours: int) -> bool:
    """Advance a stable creature's 1d4-hour recovery clock; return whether it awoke."""

    if hours < 0:
        raise ValueError("hours must be non-negative")
    remaining = target.stable_recovery_hours_remaining
    if hours == 0 or target.hp != 0 or target.dead or not target.stable or remaining is None:
        return False
    remaining = max(0, remaining - hours)
    target.stable_recovery_hours_remaining = remaining
    if remaining > 0:
        return False

    target.hp = 1
    target.stable = False
    target.was_downed = False
    target.stable_recovery_hours_remaining = None
    _remove_condition_everywhere(target, "unconscious")
    _remove_condition_everywhere(target, "incapacitated")
    return True


def resolve_death_save(rng: random.Random, target: ActorRuntimeState) -> DeathSaveResult:
    if target.hp > 0 or target.stable or target.dead:
        return DeathSaveResult(False, target.dead, False)
    if target.uses_death_saves is False:
        target.dead = True
        target.stable = False
        target.stable_recovery_hours_remaining = None
        target.death_failures = max(3, target.death_failures)
        target.update_manual_conditions({"dead", "unconscious", "incapacitated"})
        return DeathSaveResult(False, True, False)

    roll = rng.randint(1, 20)
    if roll == 1:
        target.death_failures += 2
    elif roll == 20:
        target.hp = 1
        target.death_successes = 0
        target.death_failures = 0
        target.stable = False
        target.was_downed = False
        target.stable_recovery_hours_remaining = None
        _remove_condition_everywhere(target, "unconscious")
        _remove_condition_everywhere(target, "incapacitated")
        return DeathSaveResult(False, False, True)
    elif roll >= 10:
        target.death_successes += 1
    else:
        target.death_failures += 1

    became_stable = False
    became_dead = False
    if target.death_successes >= 3:
        target.stable = True
        target.death_successes = 0
        target.death_failures = 0
        target.stable_recovery_hours_remaining = rng.randint(1, 4)
        became_stable = True
    if target.death_failures >= 3:
        target.dead = True
        target.stable = False
        target.stable_recovery_hours_remaining = None
        target.update_manual_conditions({"dead", "unconscious", "incapacitated"})
        became_dead = True

    return DeathSaveResult(became_stable, became_dead, False)
