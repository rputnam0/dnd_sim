from __future__ import annotations

import pytest

from dnd_sim.exploration_interaction import (
    AwarenessState,
    ExplorationInteractionState,
    InteractionEvent,
    InteractableState,
)
from dnd_sim.persistence import (
    deserialize_world_exploration_state,
    serialize_world_exploration_state,
)
from dnd_sim.world_runtime import (
    LightSourceState,
    WorldClock,
    create_exploration_state,
    run_exploration_turn,
)


def test_world_clock_advances_minutes_and_rolls_over_day_boundary() -> None:
    state = create_exploration_state(
        day=3,
        hour=23,
        minute=50,
        light_sources={"torch": 60},
    )

    result = run_exploration_turn(
        state,
        activity="travel",
        elapsed_minutes=20,
    )

    assert result.start_clock == WorldClock(day=3, minute_of_day=(23 * 60) + 50)
    assert result.end_clock == WorldClock(day=4, minute_of_day=10)
    assert result.state.clock.day == 4
    assert result.state.clock.hour == 0
    assert result.state.clock.minute == 10


def test_exploration_turn_structure_is_stable_and_increments_turn_index() -> None:
    state = create_exploration_state(day=1, hour=8, minute=0)

    first = run_exploration_turn(state, activity="search", elapsed_minutes=10)
    second = run_exploration_turn(first.state, activity="move", elapsed_minutes=10)

    assert first.phases == (
        "declare_intent",
        "resolve_activity",
        "advance_time",
        "update_lights",
    )
    assert first.state.turn_index == 1
    assert second.state.turn_index == 2


def test_light_sources_decay_only_when_lit_and_auto_extinguish_when_empty() -> None:
    state = create_exploration_state(
        day=1,
        hour=18,
        minute=0,
        light_sources={
            "lantern": LightSourceState(source_id="lantern", remaining_minutes=40, is_lit=True),
            "torch": LightSourceState(source_id="torch", remaining_minutes=15, is_lit=True),
            "hooded_lamp": LightSourceState(
                source_id="hooded_lamp",
                remaining_minutes=50,
                is_lit=False,
            ),
        },
    )

    result = run_exploration_turn(
        state,
        activity="explore",
        elapsed_minutes=20,
    )

    assert result.state.light_sources["lantern"].remaining_minutes == 20
    assert result.state.light_sources["lantern"].is_lit is True
    assert result.state.light_sources["torch"].remaining_minutes == 0
    assert result.state.light_sources["torch"].is_lit is False
    assert result.state.light_sources["hooded_lamp"].remaining_minutes == 50
    assert result.depleted_light_sources == ("torch",)


def test_exploration_state_round_trips_through_persistence_payload() -> None:
    state = create_exploration_state(
        day=5,
        hour=7,
        minute=15,
        location_id="sunken_path",
        light_sources={
            "torch": LightSourceState(source_id="torch", remaining_minutes=32, is_lit=True),
            "candle": LightSourceState(source_id="candle", remaining_minutes=8, is_lit=False),
        },
    )
    turned = run_exploration_turn(
        state,
        activity="map",
        elapsed_minutes=12,
    ).state

    payload = serialize_world_exploration_state(turned)
    restored = deserialize_world_exploration_state(payload)

    assert restored == turned


def test_run_exploration_turn_rejects_non_positive_elapsed_minutes() -> None:
    state = create_exploration_state(day=1, hour=8, minute=0)

    with pytest.raises(ValueError, match="elapsed_minutes must be > 0"):
        run_exploration_turn(
            state,
            activity="wait",
            elapsed_minutes=0,
        )


def test_run_exploration_turn_rejects_none_activity() -> None:
    state = create_exploration_state(day=1, hour=8, minute=0)

    with pytest.raises(ValueError, match="activity must be a string"):
        run_exploration_turn(  # type: ignore[arg-type]
            state,
            activity=None,
            elapsed_minutes=5,
        )


def test_deserialize_world_exploration_state_rejects_missing_light_source_id() -> None:
    with pytest.raises(ValueError, match="source_id must be a string"):
        deserialize_world_exploration_state(
            {
                "turn_index": 0,
                "clock": {"day": 1, "minute_of_day": 10},
                "light_sources": [
                    {
                        "remaining_minutes": 30,
                        "is_lit": True,
                    }
                ],
            }
        )


def test_run_exploration_turn_rejects_blank_activity() -> None:
    state = create_exploration_state(day=1, hour=8, minute=0)

    with pytest.raises(ValueError, match="activity must be non-empty"):
        run_exploration_turn(
            state,
            activity="   ",
            elapsed_minutes=5,
        )


def test_deserialize_world_exploration_state_rejects_non_string_light_source_id() -> None:
    with pytest.raises(ValueError, match="source_id must be a string"):
        deserialize_world_exploration_state(
            {
                "turn_index": 0,
                "clock": {"day": 1, "minute_of_day": 10},
                "light_sources": [
                    {
                        "source_id": 123,
                        "remaining_minutes": 30,
                        "is_lit": True,
                    }
                ],
            }
        )


def test_exploration_turn_preserves_interaction_state_across_time_advancement() -> None:
    state = create_exploration_state(
        day=1,
        hour=12,
        minute=0,
        interaction_state=ExplorationInteractionState(
            awareness={
                "rogue": AwarenessState(
                    actor_id="rogue",
                    hidden=True,
                    detected_by=(),
                    stealth_total=16,
                )
            },
            interactables={
                "chest_a": InteractableState(
                    object_id="chest_a",
                    kind="container",
                    discovered=True,
                    locked=True,
                    unlock_dc=14,
                    contents=("potion_healing",),
                )
            },
        ),
    )

    result = run_exploration_turn(state, activity="move", elapsed_minutes=10)

    assert result.state.interaction_state == state.interaction_state


def test_world_exploration_state_round_trip_preserves_interaction_payload() -> None:
    interaction_state = ExplorationInteractionState(
        awareness={
            "guard": AwarenessState(
                actor_id="guard",
                hidden=False,
                detected_by=("rogue",),
                surprised=True,
                stealth_total=5,
            )
        },
        interactables={
            "secret_door": InteractableState(
                object_id="secret_door",
                kind="secret",
                hidden=False,
                discovered=True,
                discovery_dc=15,
            )
        },
        event_log=(
            InteractionEvent(
                event_type="search",
                actor_id="rogue",
                outcome="resolved",
                object_id="secret_door",
            ),
        ),
    )
    state = create_exploration_state(
        day=3,
        hour=9,
        minute=5,
        interaction_state=interaction_state,
    )

    payload = serialize_world_exploration_state(state)
    restored = deserialize_world_exploration_state(payload)

    assert restored.interaction_state == interaction_state
