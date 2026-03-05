from __future__ import annotations

from dnd_sim.world_hazards import (
    apply_disease_exposure,
    apply_poison_exposure,
    create_world_hazard_state,
    resolve_environmental_exposure,
    resolve_falling,
    start_drowning,
    start_suffocation,
    advance_drowning,
    advance_suffocation,
)
from dnd_sim.world_runtime import (
    deserialize_world_hazard_state,
    run_world_hazard_turn,
    serialize_world_hazard_state,
)


def test_falling_damage_caps_at_twenty_dice_and_is_deterministic() -> None:
    state = create_world_hazard_state(
        actors={
            "hero": {
                "hp": 90,
                "max_hp": 90,
                "con_mod": 2,
            }
        }
    )

    result = resolve_falling(
        state,
        actor_id="hero",
        distance_ft=250,
        dice_rolls=[6] * 20,
    )

    assert result.event_type == "fall"
    assert result.details["dice_count"] == 20
    assert result.details["damage"] == 120
    assert result.state.actors["hero"].hp == 0
    assert "unconscious" in result.state.actors["hero"].conditions


def test_suffocation_counts_breath_then_drops_to_zero_after_tolerance() -> None:
    state = create_world_hazard_state(
        actors={
            "hero": {
                "hp": 12,
                "max_hp": 12,
                "con_mod": 1,
            }
        }
    )

    started = start_suffocation(state, actor_id="hero")
    assert started.state.actors["hero"].breath_rounds_remaining == 20

    breath_spent = advance_suffocation(started.state, actor_id="hero", rounds=20)
    assert breath_spent.state.actors["hero"].breath_rounds_remaining == 0
    assert breath_spent.state.actors["hero"].hp == 12
    assert breath_spent.state.minute_index == 2
    assert breath_spent.details["elapsed_minutes"] == 2

    downed = advance_suffocation(breath_spent.state, actor_id="hero", rounds=2)
    assert downed.state.actors["hero"].hp == 0
    assert downed.details["suffocating_rounds"] == 2
    assert downed.state.minute_index == 3
    assert downed.details["elapsed_minutes"] == 1
    assert "unconscious" in downed.state.actors["hero"].conditions


def test_drowning_uses_suffocation_timing_rules() -> None:
    state = create_world_hazard_state(
        actors={
            "hero": {
                "hp": 10,
                "max_hp": 10,
                "con_mod": 0,
            }
        }
    )

    started = start_drowning(state, actor_id="hero")
    assert started.event_type == "drowning_start"
    assert started.state.actors["hero"].breath_rounds_remaining == 10

    first_tick = advance_drowning(started.state, actor_id="hero", rounds=11)
    assert first_tick.event_type == "drowning_tick"
    assert first_tick.state.actors["hero"].hp == 10

    second_tick = advance_drowning(first_tick.state, actor_id="hero", rounds=1)
    assert second_tick.state.actors["hero"].hp == 0
    assert second_tick.details["reason"] == "drowning"


def test_environmental_exposure_failure_applies_damage_and_exhaustion() -> None:
    state = create_world_hazard_state(
        actors={
            "hero": {
                "hp": 18,
                "max_hp": 18,
                "con_mod": 2,
            }
        }
    )

    result = resolve_environmental_exposure(
        state,
        actor_id="hero",
        hazard_type="Extreme_Cold",
        save_succeeded=False,
        on_failure_damage=4,
        failure_exhaustion=2,
    )

    assert result.details["hazard_type"] == "extreme_cold"
    assert result.state.actors["hero"].hp == 14
    assert result.state.actors["hero"].exhaustion_level == 2


def test_poison_and_disease_progress_persist_and_round_trip_via_world_runtime() -> None:
    state = create_world_hazard_state(
        actors={
            "hero": {
                "hp": 22,
                "max_hp": 22,
                "con_mod": 2,
            }
        }
    )

    first_turn = run_world_hazard_turn(
        state,
        elapsed_minutes=30,
        exposure_checks=[
            {
                "actor_id": "hero",
                "hazard_type": "swamp_miasma",
                "save_succeeded": False,
                "poison_duration_minutes": 90,
                "disease_id": "filth_fever",
                "incubation_hours": 1,
            }
        ],
    )

    assert len(first_turn.events) == 3
    hero_after_first = first_turn.state.actors["hero"]
    assert hero_after_first.poisoned_minutes_remaining == 60
    assert "poisoned" in hero_after_first.conditions
    assert hero_after_first.diseases["filth_fever"].stage == 0
    assert hero_after_first.diseases["filth_fever"].minutes_until_next_save == 30

    payload = serialize_world_hazard_state(first_turn.state)
    restored = deserialize_world_hazard_state(payload)
    assert restored == first_turn.state

    second_turn = run_world_hazard_turn(
        restored,
        elapsed_minutes=30,
        disease_save_outcomes={"hero:filth_fever": False},
    )
    hero_after_second = second_turn.state.actors["hero"]

    assert hero_after_second.poisoned_minutes_remaining == 30
    assert hero_after_second.diseases["filth_fever"].stage == 1
    assert hero_after_second.diseases["filth_fever"].minutes_until_next_save == 1440
    assert hero_after_second.exhaustion_level == 2
