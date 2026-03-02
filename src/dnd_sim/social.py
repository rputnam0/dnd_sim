from __future__ import annotations

import random
from dataclasses import dataclass

ATTITUDE_STATES = ("hostile", "unfriendly", "indifferent", "friendly", "helpful")
CONTEST_DEGREES = ("critical_failure", "failure", "success", "critical_success")

_ATTITUDE_TO_INDEX = {state: i for i, state in enumerate(ATTITUDE_STATES)}
_DEGREE_SHIFT = {
    "critical_failure": -2,
    "failure": -1,
    "success": 1,
    "critical_success": 2,
}


@dataclass(slots=True)
class SocialContestResult:
    initiator_roll: int
    initiator_total: int
    defender_roll: int
    defender_total: int
    success: bool
    margin: int
    degree: str


@dataclass(slots=True)
class SocialConsequence:
    initial_attitude: str
    final_attitude: str
    attitude_shift: int
    impact_score: int
    outcome: str
    tags: tuple[str, ...]


@dataclass(slots=True)
class SocialCheckOutcome:
    contest: SocialContestResult
    consequence: SocialConsequence


def _roll_d20(
    rng: random.Random,
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


def _contest_degree(success: bool, margin: int) -> str:
    if success:
        return "critical_success" if margin >= 10 else "success"
    return "critical_failure" if margin >= 10 else "failure"


def _validate_attitude_state(attitude_state: str) -> None:
    if attitude_state not in _ATTITUDE_TO_INDEX:
        raise ValueError(f"Unknown attitude state: {attitude_state}")


def resolve_skill_contest(
    rng: random.Random,
    initiator_mod: int,
    defender_mods: list[int],
    *,
    initiator_advantage: bool = False,
    initiator_disadvantage: bool = False,
    defender_advantage: bool = False,
    defender_disadvantage: bool = False,
) -> SocialContestResult:
    initiator_roll = _roll_d20(
        rng,
        advantage=initiator_advantage,
        disadvantage=initiator_disadvantage,
    )
    defender_roll = _roll_d20(
        rng,
        advantage=defender_advantage,
        disadvantage=defender_disadvantage,
    )
    defender_mod = max(defender_mods) if defender_mods else 0

    initiator_total = initiator_roll + initiator_mod
    defender_total = defender_roll + defender_mod
    success = initiator_total > defender_total
    margin = abs(initiator_total - defender_total)

    return SocialContestResult(
        initiator_roll=initiator_roll,
        initiator_total=initiator_total,
        defender_roll=defender_roll,
        defender_total=defender_total,
        success=success,
        margin=margin,
        degree=_contest_degree(success, margin),
    )


def transition_attitude(current: str, degree: str) -> str:
    _validate_attitude_state(current)
    if degree not in _DEGREE_SHIFT:
        raise ValueError(f"Unknown contest degree: {degree}")

    current_index = _ATTITUDE_TO_INDEX[current]
    shift = _DEGREE_SHIFT[degree]
    next_index = min(max(0, current_index + shift), len(ATTITUDE_STATES) - 1)
    return ATTITUDE_STATES[next_index]


def model_social_consequence(
    *,
    current_attitude: str,
    contest_result: SocialContestResult,
    stakes: int = 1,
) -> SocialConsequence:
    _validate_attitude_state(current_attitude)
    if stakes < 1:
        raise ValueError("stakes must be >= 1")

    final_attitude = transition_attitude(current_attitude, contest_result.degree)
    shift = _ATTITUDE_TO_INDEX[final_attitude] - _ATTITUDE_TO_INDEX[current_attitude]
    impact_score = shift * stakes

    if shift >= 2:
        outcome = "major_concession"
        tags = ("trust_gain", "favorable_terms")
    elif shift == 1:
        outcome = "limited_concession"
        tags = ("trust_gain", "incremental_progress")
    elif shift == 0:
        outcome = "status_quo"
        tags = ("guarded_pause",)
    elif shift == -1:
        outcome = "social_resistance"
        tags = ("skepticism", "higher_cost")
    else:
        outcome = "social_backlash"
        tags = ("security_alert", "future_penalty")

    return SocialConsequence(
        initial_attitude=current_attitude,
        final_attitude=final_attitude,
        attitude_shift=shift,
        impact_score=impact_score,
        outcome=outcome,
        tags=tags,
    )


def resolve_social_check(
    rng: random.Random,
    initiator_mod: int,
    defender_mods: list[int],
    *,
    current_attitude: str,
    stakes: int = 1,
    initiator_advantage: bool = False,
    initiator_disadvantage: bool = False,
    defender_advantage: bool = False,
    defender_disadvantage: bool = False,
) -> SocialCheckOutcome:
    contest = resolve_skill_contest(
        rng,
        initiator_mod=initiator_mod,
        defender_mods=defender_mods,
        initiator_advantage=initiator_advantage,
        initiator_disadvantage=initiator_disadvantage,
        defender_advantage=defender_advantage,
        defender_disadvantage=defender_disadvantage,
    )
    consequence = model_social_consequence(
        current_attitude=current_attitude,
        contest_result=contest,
        stakes=stakes,
    )
    return SocialCheckOutcome(contest=contest, consequence=consequence)


__all__ = [
    "ATTITUDE_STATES",
    "CONTEST_DEGREES",
    "SocialContestResult",
    "SocialConsequence",
    "SocialCheckOutcome",
    "resolve_skill_contest",
    "transition_attitude",
    "model_social_consequence",
    "resolve_social_check",
]
