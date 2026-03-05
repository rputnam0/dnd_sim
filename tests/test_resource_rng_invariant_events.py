from __future__ import annotations

from types import SimpleNamespace

from dnd_sim.engine_resources import (
    apply_arcane_recovery,
    emit_invariant_violation_event,
    emit_rng_audit_event,
    ensure_resource_cap,
)
from dnd_sim.telemetry import (
    INVARIANT_VIOLATION_EVENT_TYPE,
    RESOURCE_DELTA_EVENT_TYPE,
    RNG_AUDIT_EVENT_TYPE,
    serialize_event,
)


def _actor(*, actor_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        actor_id=actor_id,
        resources={},
        max_resources={},
        class_levels={"wizard": 0},
        cha_mod=0,
    )


def test_ensure_resource_cap_emits_resource_delta_for_initialization() -> None:
    actor = _actor(actor_id="hero")
    telemetry: list[dict[str, object]] = []

    ensure_resource_cap(actor, "rage", 3, telemetry_events=telemetry)

    assert actor.max_resources["rage"] == 3
    assert actor.resources["rage"] == 3
    assert len(telemetry) == 1

    event = telemetry[0]
    assert event["telemetry_type"] == RESOURCE_DELTA_EVENT_TYPE
    assert event["actor_id"] == "hero"
    assert event["resource"] == "rage"
    assert event["before"] == 0
    assert event["after"] == 3
    assert event["delta"] == 3
    assert event["direction"] == "recover"
    assert event["reason"] == "resource_initialized"


def test_ensure_resource_cap_clamp_emits_invariant_violation_with_explicit_code() -> None:
    actor = _actor(actor_id="hero")
    actor.max_resources = {"rage": 2}
    actor.resources = {"rage": 9}
    telemetry: list[dict[str, object]] = []

    ensure_resource_cap(actor, "rage", 2, telemetry_events=telemetry)

    assert actor.resources["rage"] == 2

    invariant_event = next(
        event for event in telemetry if event["telemetry_type"] == INVARIANT_VIOLATION_EVENT_TYPE
    )
    assert invariant_event["invariant_code"] == "RESOURCE_VALUE_OUT_OF_BOUNDS"
    assert invariant_event["severity"] == "warning"

    delta_event = next(
        event for event in telemetry if event["telemetry_type"] == RESOURCE_DELTA_EVENT_TYPE
    )
    assert delta_event["before"] == 9
    assert delta_event["after"] == 2
    assert delta_event["delta"] == -7
    assert delta_event["direction"] == "spend"
    assert delta_event["reason"] == "resource_clamped_to_cap"


def test_emit_rng_audit_event_is_deterministic_and_keyed_by_seed_and_context() -> None:
    telemetry_a: list[dict[str, object]] = []
    telemetry_b: list[dict[str, object]] = []

    emit_rng_audit_event(
        telemetry_a,
        seed=1234,
        context="attack:hero:goblin",
        draw_index=2,
        die_sides=20,
        roll_value=17,
        actor_id="hero",
    )
    emit_rng_audit_event(
        telemetry_b,
        seed=1234,
        context="attack:hero:goblin",
        draw_index=2,
        die_sides=20,
        roll_value=17,
        actor_id="hero",
    )

    assert telemetry_a[0]["telemetry_type"] == RNG_AUDIT_EVENT_TYPE
    assert telemetry_a[0]["rng_seed"] == 1234
    assert telemetry_a[0]["rng_context"] == "attack:hero:goblin"
    assert telemetry_a[0]["draw_index"] == 2
    assert telemetry_a[0]["die_sides"] == 20
    assert telemetry_a[0]["roll_value"] == 17

    assert serialize_event(telemetry_a[0]) == serialize_event(telemetry_b[0])


def test_apply_arcane_recovery_emits_recovery_and_use_resource_events() -> None:
    actor = _actor(actor_id="wizard")
    actor.class_levels = {"wizard": 5}
    actor.max_resources = {"spell_slot_1": 4, "arcane_recovery": 1}
    actor.resources = {"spell_slot_1": 2, "arcane_recovery": 1}
    telemetry: list[dict[str, object]] = []

    apply_arcane_recovery(
        actor,
        has_trait=lambda _actor, trait_name: trait_name == "arcane recovery",
        telemetry_events=telemetry,
    )

    assert actor.resources["spell_slot_1"] == 4
    assert actor.resources["arcane_recovery"] == 0

    slot_recovery = next(
        event
        for event in telemetry
        if event["telemetry_type"] == RESOURCE_DELTA_EVENT_TYPE
        and event["resource"] == "spell_slot_1"
    )
    assert slot_recovery["delta"] == 2
    assert slot_recovery["direction"] == "recover"
    assert slot_recovery["reason"] == "arcane_recovery_slot_recovery"

    use_event = next(
        event
        for event in telemetry
        if event["telemetry_type"] == RESOURCE_DELTA_EVENT_TYPE
        and event["resource"] == "arcane_recovery"
    )
    assert use_event["delta"] == -1
    assert use_event["direction"] == "spend"
    assert use_event["reason"] == "arcane_recovery_use"


def test_emit_invariant_violation_event_appends_code_and_message() -> None:
    telemetry: list[dict[str, object]] = []

    emit_invariant_violation_event(
        telemetry,
        invariant_code="RESOURCE_NEGATIVE_AFTER_SPEND",
        message="resource dropped below zero",
        actor_id="hero",
    )

    assert len(telemetry) == 1
    assert telemetry[0]["telemetry_type"] == INVARIANT_VIOLATION_EVENT_TYPE
    assert telemetry[0]["invariant_code"] == "RESOURCE_NEGATIVE_AFTER_SPEND"
    assert telemetry[0]["message"] == "resource dropped below zero"
    assert telemetry[0]["actor_id"] == "hero"
