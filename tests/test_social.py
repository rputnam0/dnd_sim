from __future__ import annotations

import pytest

from dnd_sim.social import (
    ATTITUDE_STATES,
    SocialContestResult,
    model_social_consequence,
    resolve_skill_contest,
    resolve_social_check,
    transition_attitude,
)


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self.values:
            raise AssertionError("RNG exhausted")
        return self.values.pop(0)


def test_resolve_skill_contest_uses_best_defender_modifier_and_defender_wins_ties() -> None:
    rng = FixedRng([12, 10])

    result = resolve_skill_contest(rng, initiator_mod=4, defender_mods=[1, 6])

    assert result == SocialContestResult(
        initiator_roll=12,
        initiator_total=16,
        defender_roll=10,
        defender_total=16,
        success=False,
        margin=0,
        degree="failure",
    )


def test_resolve_skill_contest_honors_advantage_and_disadvantage() -> None:
    rng = FixedRng([2, 17, 19, 4])

    result = resolve_skill_contest(
        rng,
        initiator_mod=5,
        defender_mods=[3],
        initiator_advantage=True,
        defender_disadvantage=True,
    )

    assert result.success is True
    assert result.initiator_roll == 17
    assert result.defender_roll == 4
    assert result.margin == 15
    assert result.degree == "critical_success"


@pytest.mark.parametrize(
    ("current", "degree", "expected"),
    [
        ("hostile", "critical_failure", "hostile"),
        ("hostile", "failure", "hostile"),
        ("hostile", "success", "unfriendly"),
        ("hostile", "critical_success", "indifferent"),
        ("unfriendly", "critical_failure", "hostile"),
        ("unfriendly", "failure", "hostile"),
        ("unfriendly", "success", "indifferent"),
        ("unfriendly", "critical_success", "friendly"),
        ("indifferent", "critical_failure", "hostile"),
        ("indifferent", "failure", "unfriendly"),
        ("indifferent", "success", "friendly"),
        ("indifferent", "critical_success", "helpful"),
        ("friendly", "critical_failure", "unfriendly"),
        ("friendly", "failure", "indifferent"),
        ("friendly", "success", "helpful"),
        ("friendly", "critical_success", "helpful"),
        ("helpful", "critical_failure", "indifferent"),
        ("helpful", "failure", "friendly"),
        ("helpful", "success", "helpful"),
        ("helpful", "critical_success", "helpful"),
    ],
)
def test_transition_attitude_matrix(current: str, degree: str, expected: str) -> None:
    assert transition_attitude(current, degree) == expected


def test_transition_attitude_rejects_unknown_inputs() -> None:
    with pytest.raises(ValueError, match="Unknown attitude state"):
        transition_attitude("neutral", "success")

    with pytest.raises(ValueError, match="Unknown contest degree"):
        transition_attitude("indifferent", "meh")


def test_model_social_consequence_positive_high_stakes() -> None:
    contest = SocialContestResult(
        initiator_roll=18,
        initiator_total=26,
        defender_roll=5,
        defender_total=8,
        success=True,
        margin=18,
        degree="critical_success",
    )

    consequence = model_social_consequence(
        current_attitude="unfriendly",
        contest_result=contest,
        stakes=2,
    )

    assert consequence.initial_attitude == "unfriendly"
    assert consequence.final_attitude == "friendly"
    assert consequence.attitude_shift == 2
    assert consequence.impact_score == 4
    assert consequence.outcome == "major_concession"
    assert consequence.tags == ("trust_gain", "favorable_terms")


def test_resolve_social_check_models_negative_backlash() -> None:
    rng = FixedRng([1, 20])

    outcome = resolve_social_check(
        rng,
        initiator_mod=4,
        defender_mods=[6],
        current_attitude="indifferent",
        stakes=3,
    )

    assert outcome.contest.degree == "critical_failure"
    assert outcome.consequence.final_attitude == "hostile"
    assert outcome.consequence.attitude_shift == -2
    assert outcome.consequence.impact_score == -6
    assert outcome.consequence.outcome == "social_backlash"
    assert outcome.consequence.tags == ("security_alert", "future_penalty")


def test_attitude_states_are_ordered_for_escalation_logic() -> None:
    assert ATTITUDE_STATES == ("hostile", "unfriendly", "indifferent", "friendly", "helpful")
