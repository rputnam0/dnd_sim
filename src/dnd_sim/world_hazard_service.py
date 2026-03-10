from __future__ import annotations

from typing import Any

from dnd_sim.world_hazards import (
    HazardActorState,
    HazardResolution,
    WorldHazardState,
    advance_disease_progression,
    advance_poison,
    apply_disease_exposure,
    apply_poison_exposure,
    create_world_hazard_state as _create_world_hazard_state,
    deserialize_world_hazard_state as _deserialize_world_hazard_state,
    resolve_environmental_exposure,
    serialize_world_hazard_state as _serialize_world_hazard_state,
)
from dnd_sim.world_contracts import WorldHazardTurnResult


def create_world_hazard_state(
    *,
    actors: dict[str, HazardActorState | dict[str, Any]] | None = None,
    minute_index: int = 0,
) -> WorldHazardState:
    return _create_world_hazard_state(actors=actors, minute_index=minute_index)


def serialize_world_hazard_state(state: WorldHazardState) -> dict[str, Any]:
    return _serialize_world_hazard_state(state)


def deserialize_world_hazard_state(payload: dict[str, Any]) -> WorldHazardState:
    return _deserialize_world_hazard_state(payload)


def run_world_hazard_turn(
    state: WorldHazardState,
    *,
    elapsed_minutes: int,
    exposure_checks: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    disease_save_outcomes: dict[str, bool] | None = None,
) -> WorldHazardTurnResult:
    if (
        not isinstance(elapsed_minutes, int)
        or isinstance(elapsed_minutes, bool)
        or elapsed_minutes <= 0
    ):
        raise ValueError("elapsed_minutes must be > 0")

    current_state = state
    events: list[HazardResolution] = []

    for check in exposure_checks:
        if not isinstance(check, dict):
            raise ValueError("exposure_checks must contain mapping entries")
        actor_id = check.get("actor_id")
        hazard_type = check.get("hazard_type")
        if actor_id is None or hazard_type is None:
            raise ValueError("exposure checks require actor_id and hazard_type")

        exposure = resolve_environmental_exposure(
            current_state,
            actor_id=str(actor_id),
            hazard_type=str(hazard_type),
            save_succeeded=bool(check.get("save_succeeded", False)),
            on_failure_damage=int(check.get("on_failure_damage", 0)),
            failure_exhaustion=int(check.get("failure_exhaustion", 1)),
        )
        current_state = exposure.state
        events.append(exposure)

        poison_duration = check.get("poison_duration_minutes")
        if poison_duration is not None:
            poison_exposure = apply_poison_exposure(
                current_state,
                actor_id=str(actor_id),
                duration_minutes=int(poison_duration),
                save_succeeded=bool(check.get("save_succeeded", False)),
            )
            current_state = poison_exposure.state
            events.append(poison_exposure)

        disease_id = check.get("disease_id")
        if disease_id is not None:
            disease_exposure = apply_disease_exposure(
                current_state,
                actor_id=str(actor_id),
                disease_id=str(disease_id),
                incubation_hours=int(check.get("incubation_hours", 24)),
                save_succeeded=bool(check.get("save_succeeded", False)),
            )
            current_state = disease_exposure.state
            events.append(disease_exposure)

    poison_tick = advance_poison(current_state, elapsed_minutes=elapsed_minutes)
    disease_tick = advance_disease_progression(
        poison_tick.state,
        elapsed_minutes=elapsed_minutes,
        save_outcomes=disease_save_outcomes,
    )

    return WorldHazardTurnResult(
        state=disease_tick.state,
        elapsed_minutes=elapsed_minutes,
        events=tuple(events),
        poison_tick=poison_tick,
        disease_tick=disease_tick,
    )
