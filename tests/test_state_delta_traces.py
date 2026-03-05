from __future__ import annotations

import pytest

from dnd_sim.effects_runtime import (
    build_actor_state_delta_trace,
    build_effect_lifecycle_trace,
    effect_lifecycle_event_type,
)
from dnd_sim.telemetry import (
    EFFECT_LIFECYCLE_EVENT_TYPES,
    STATE_DELTA_EVENT_TYPE,
    build_event_envelope,
)


def test_actor_state_delta_trace_includes_before_after_and_changed_paths() -> None:
    before = {
        "hp": 24,
        "resources": {"ki": 2, "sorcery_points": 3},
        "conditions": ["blessed"],
        "position": [0, 0, 0],
    }
    after = {
        "hp": 17,
        "resources": {"ki": 1, "sorcery_points": 3},
        "conditions": ["blessed", "hasted"],
        "position": [5, 0, 0],
    }

    payload = build_actor_state_delta_trace(
        actor_id="hero",
        round_number=2,
        turn_token="2:hero:1",
        before_state=before,
        after_state=after,
        transition="tick",
    )

    assert payload is not None
    assert payload["actor_id"] == "hero"
    assert payload["round"] == 2
    assert payload["turn_token"] == "2:hero:1"
    assert payload["transition"] == "tick"
    assert payload["delta_count"] == 4
    assert payload["changed_fields"] == ["conditions", "hp", "position", "resources.ki"]
    assert payload["before"] == before
    assert payload["after"] == after

    event = build_event_envelope(
        event_type=STATE_DELTA_EVENT_TYPE,
        payload=payload,
        source="dnd_sim.effects_runtime",
    )
    assert event["telemetry_type"] == STATE_DELTA_EVENT_TYPE
    assert event["delta_count"] == 4


def test_actor_state_delta_trace_suppresses_no_op_deltas() -> None:
    state = {
        "hp": 18,
        "resources": {"ki": 1},
        "conditions": ["concentrating"],
    }

    payload = build_actor_state_delta_trace(
        actor_id="hero",
        round_number=3,
        turn_token="3:hero:1",
        before_state=state,
        after_state=dict(state),
        transition="refresh",
    )

    assert payload is None


@pytest.mark.parametrize(
    ("transition", "expected_event_type"),
    [
        ("apply", "effect_apply"),
        ("tick", "effect_tick"),
        ("refresh", "effect_refresh"),
        ("expire", "effect_expire"),
        ("concentration_break", "effect_concentration_break"),
    ],
)
def test_effect_lifecycle_trace_emits_supported_transition_payloads(
    transition: str,
    expected_event_type: str,
) -> None:
    payload = build_effect_lifecycle_trace(
        transition=transition,
        actor_id="hero",
        effect_id="bless",
        effect_type="buff",
        round_number=4,
        turn_token="4:hero:2",
        source_actor_id="cleric",
    )

    assert effect_lifecycle_event_type(transition) == expected_event_type
    assert expected_event_type in EFFECT_LIFECYCLE_EVENT_TYPES
    assert payload["transition"] == transition
    assert payload["actor_id"] == "hero"
    assert payload["effect_id"] == "bless"
    assert payload["effect_type"] == "buff"

    event = build_event_envelope(
        event_type=expected_event_type,
        payload=payload,
        source="dnd_sim.effects_runtime",
    )
    assert event["telemetry_type"] == expected_event_type
    assert event["transition"] == transition


def test_effect_lifecycle_trace_rejects_unknown_transition() -> None:
    with pytest.raises(ValueError, match="unsupported effect lifecycle transition"):
        build_effect_lifecycle_trace(
            transition="mutate",
            actor_id="hero",
            effect_id="bless",
        )
