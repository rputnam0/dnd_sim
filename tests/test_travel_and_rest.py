from __future__ import annotations

import pytest

from dnd_sim.world_runtime import (
    REST_LONG,
    REST_SHORT,
    ForagingOutcome,
    NavigationOutcome,
    TravelPartyMemberState,
    day_cycle_phase,
    plan_travel_pace,
    resolve_foraging,
    resolve_navigation,
    run_travel_and_rest_cycle,
    create_exploration_state,
)


def test_plan_travel_pace_applies_expected_miles_per_day_and_segments() -> None:
    slow = plan_travel_pace(distance_miles=24, travel_pace="slow")
    normal = plan_travel_pace(distance_miles=24, travel_pace="normal")
    fast = plan_travel_pace(distance_miles=24, travel_pace="fast")

    assert slow.miles_per_day == pytest.approx(18.0)
    assert normal.miles_per_day == pytest.approx(24.0)
    assert fast.miles_per_day == pytest.approx(30.0)
    assert slow.segments == 2
    assert normal.segments == 1
    assert fast.segments == 1
    assert slow.travel_minutes > normal.travel_minutes > fast.travel_minutes


def test_resolve_navigation_applies_pace_dc_modifier_and_failure_hooks() -> None:
    success = resolve_navigation(check_total=12, dc=12, travel_pace="normal")
    failure = resolve_navigation(check_total=10, dc=12, travel_pace="fast")

    assert success == NavigationOutcome(
        success=True,
        check_total=12,
        effective_dc=12,
        margin=0,
        lost_minutes=0,
        encounter_check_required=False,
    )
    assert failure.success is False
    assert failure.effective_dc == 14
    assert failure.margin == -4
    assert failure.lost_minutes == 60
    assert failure.encounter_check_required is True


def test_resolve_foraging_respects_pace_and_sets_encounter_hook() -> None:
    slow = resolve_foraging(check_total=18, dc=15, travel_pace="slow")
    fast = resolve_foraging(check_total=18, dc=15, travel_pace="fast")

    assert slow == ForagingOutcome(
        success=True,
        check_total=18,
        effective_dc=13,
        margin=5,
        supplies_found=2,
        encounter_check_required=False,
    )
    assert fast.success is False
    assert fast.effective_dc == 20
    assert fast.supplies_found == 0
    assert fast.encounter_check_required is True


def test_run_travel_and_rest_cycle_integrates_travel_navigation_foraging_and_long_rest() -> None:
    state = create_exploration_state(
        day=1,
        hour=16,
        minute=30,
        light_sources={"torch": 1200},
    )
    party = {
        "hero": TravelPartyMemberState(
            actor_id="hero",
            hit_points=8,
            max_hit_points=20,
            resources={"ki": 0, "spell_slot_1": 1},
            max_resources={"ki": 2, "spell_slot_1": 4},
            short_rest_recovery=("ki",),
            conditions=("poisoned",),
        )
    }

    result = run_travel_and_rest_cycle(
        state,
        distance_miles=12,
        travel_pace="normal",
        navigation_check_total=14,
        navigation_dc=10,
        foraging_check_total=17,
        foraging_dc=15,
        rest_mode=REST_LONG,
        party=party,
    )

    assert result.day_cycle_start == "day"
    assert result.day_cycle_end == "night"
    assert result.travel.travel_minutes == 240
    assert result.navigation.success is True
    assert result.foraging is not None and result.foraging.success is True
    assert result.random_encounter_check is False
    assert result.state.clock.day == 2
    assert result.state.clock.hour == 4
    assert result.state.clock.minute == 30
    hero = result.party["hero"]
    assert hero.hit_points == 20
    assert hero.resources == {"ki": 2, "spell_slot_1": 4}
    assert hero.conditions == ()


def test_run_travel_and_rest_cycle_short_rest_heals_and_recovers_only_short_rest_resources() -> (
    None
):
    state = create_exploration_state(day=2, hour=10, minute=0)
    party = {
        "hero": TravelPartyMemberState(
            actor_id="hero",
            hit_points=12,
            max_hit_points=20,
            resources={"ki": 0, "spell_slot_1": 1},
            max_resources={"ki": 2, "spell_slot_1": 4},
            short_rest_recovery=("ki",),
            conditions=("frightened",),
        )
    }

    result = run_travel_and_rest_cycle(
        state,
        distance_miles=0,
        travel_pace="normal",
        navigation_check_total=10,
        navigation_dc=10,
        rest_mode=REST_SHORT,
        short_rest_healing=3,
        party=party,
    )

    hero = result.party["hero"]
    assert hero.hit_points == 15
    assert hero.resources["ki"] == 2
    assert hero.resources["spell_slot_1"] == 1
    assert hero.conditions == ("frightened",)
    assert result.state.clock.hour == 11


def test_run_travel_and_rest_cycle_rejects_unknown_rest_mode() -> None:
    state = create_exploration_state(day=1, hour=9, minute=0)

    with pytest.raises(ValueError, match="rest_mode must be one of"):
        run_travel_and_rest_cycle(
            state,
            distance_miles=1,
            travel_pace="normal",
            navigation_check_total=12,
            navigation_dc=10,
            rest_mode="camp",  # type: ignore[arg-type]
            party={},
        )


def test_day_cycle_phase_classifies_clock_ranges() -> None:
    assert day_cycle_phase(create_exploration_state(day=1, hour=6, minute=0).clock) == "dawn"
    assert day_cycle_phase(create_exploration_state(day=1, hour=12, minute=0).clock) == "day"
    assert day_cycle_phase(create_exploration_state(day=1, hour=18, minute=30).clock) == "dusk"
    assert day_cycle_phase(create_exploration_state(day=1, hour=2, minute=0).clock) == "night"
