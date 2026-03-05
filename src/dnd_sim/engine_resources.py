from __future__ import annotations

import logging
from collections.abc import Mapping, MutableSequence
from typing import Any, Callable

from dnd_sim.telemetry import (
    build_invariant_violation_event,
    build_resource_delta_event,
    build_rng_audit_event,
)

logger = logging.getLogger(__name__)


def _actor_id(actor: Any) -> str:
    raw_actor_id = getattr(actor, "actor_id", None)
    if raw_actor_id is None:
        return "unknown"
    normalized = str(raw_actor_id).strip()
    return normalized or "unknown"


def _append_telemetry_event(
    telemetry_events: MutableSequence[dict[str, Any]] | None,
    event: dict[str, Any],
) -> None:
    if telemetry_events is None:
        return
    telemetry_events.append(event)


def _emit_resource_delta(
    telemetry_events: MutableSequence[dict[str, Any]] | None,
    *,
    actor: Any,
    resource: str,
    before: int,
    after: int,
    reason: str,
    source: str,
    context: str | None = None,
) -> None:
    if before == after:
        return
    event = build_resource_delta_event(
        source=source,
        actor_id=_actor_id(actor),
        resource=resource,
        before=before,
        after=after,
        reason=reason,
        context=context,
    )
    _append_telemetry_event(telemetry_events, event)


def emit_rng_audit_event(
    telemetry_events: MutableSequence[dict[str, Any]] | None,
    *,
    seed: int | None,
    context: str,
    draw_index: int,
    die_sides: int | None = None,
    roll_value: int | None = None,
    actor_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    source: str = "dnd_sim.engine_resources",
) -> dict[str, Any]:
    event = build_rng_audit_event(
        source=source,
        seed=seed,
        context=context,
        draw_index=draw_index,
        die_sides=die_sides,
        roll_value=roll_value,
        actor_id=actor_id,
        metadata=metadata,
    )
    _append_telemetry_event(telemetry_events, event)
    return event


def emit_invariant_violation_event(
    telemetry_events: MutableSequence[dict[str, Any]] | None,
    *,
    invariant_code: str,
    message: str,
    actor_id: str | None = None,
    severity: str = "error",
    details: Mapping[str, Any] | None = None,
    source: str = "dnd_sim.engine_resources",
) -> dict[str, Any]:
    event = build_invariant_violation_event(
        source=source,
        invariant_code=invariant_code,
        message=message,
        severity=severity,
        actor_id=actor_id,
        details=details,
    )
    _append_telemetry_event(telemetry_events, event)
    return event


def ensure_resource_cap(
    actor: Any,
    resource: str,
    max_value: int,
    *,
    telemetry_events: MutableSequence[dict[str, Any]] | None = None,
    source: str = "dnd_sim.engine_resources",
) -> None:
    normalized_resource = str(resource)
    if max_value <= 0:
        emit_invariant_violation_event(
            telemetry_events,
            invariant_code="RESOURCE_CAP_NON_POSITIVE",
            message="Resource cap update ignored because max value was non-positive",
            actor_id=_actor_id(actor),
            severity="warning",
            details={"resource": normalized_resource, "requested_cap": int(max_value)},
            source=source,
        )
        return
    existing_max = int(actor.max_resources.get(normalized_resource, 0))
    if existing_max < max_value:
        actor.max_resources[normalized_resource] = max_value
    cap = int(actor.max_resources[normalized_resource])
    if normalized_resource not in actor.resources:
        actor.resources[normalized_resource] = cap
        _emit_resource_delta(
            telemetry_events,
            actor=actor,
            resource=normalized_resource,
            before=0,
            after=cap,
            reason="resource_initialized",
            source=source,
        )
    else:
        before = int(actor.resources[normalized_resource])
        bounded = max(0, min(before, cap))
        if bounded != before:
            emit_invariant_violation_event(
                telemetry_events,
                invariant_code="RESOURCE_VALUE_OUT_OF_BOUNDS",
                message="Resource value was outside [0, cap] bounds and was clamped",
                actor_id=_actor_id(actor),
                severity="warning",
                details={
                    "resource": normalized_resource,
                    "before": before,
                    "after": bounded,
                    "cap": cap,
                },
                source=source,
            )
        actor.resources[normalized_resource] = bounded
        _emit_resource_delta(
            telemetry_events,
            actor=actor,
            resource=normalized_resource,
            before=before,
            after=bounded,
            reason="resource_clamped_to_cap",
            source=source,
        )


def fighter_superiority_dice_count(fighter_level: int) -> int:
    if fighter_level >= 15:
        return 6
    if fighter_level >= 7:
        return 5
    if fighter_level >= 3:
        return 4
    return 0


def barbarian_rage_uses_for_level(barbarian_level: int) -> int:
    if barbarian_level <= 0:
        return 0
    if barbarian_level >= 20:
        # Unlimited in tabletop rules; use a stable high cap for simulation bookkeeping.
        return 99
    if barbarian_level >= 17:
        return 6
    if barbarian_level >= 12:
        return 5
    if barbarian_level >= 6:
        return 4
    if barbarian_level >= 3:
        return 3
    return 2


def sorcery_points_for_level(sorcerer_level: int) -> int:
    if sorcerer_level < 2:
        return 0
    return min(20, sorcerer_level)


def iter_spell_slot_levels_desc(actor: Any) -> list[int]:
    levels: set[int] = set()
    for key in actor.max_resources.keys():
        if not str(key).startswith("spell_slot_"):
            continue
        try:
            level = int(str(key).rsplit("_", 1)[1])
        except ValueError:
            continue
        if level > 0:
            levels.add(level)
    return sorted(levels, reverse=True)


def recover_spell_slots_with_budget(
    actor: Any,
    *,
    budget: int,
    max_individual_slot_level: int,
    telemetry_events: MutableSequence[dict[str, Any]] | None = None,
    source: str = "dnd_sim.engine_resources",
    delta_reason: str = "spell_slot_recovery",
) -> int:
    if budget <= 0:
        return 0
    recovered_levels = 0
    for slot_level in iter_spell_slot_levels_desc(actor):
        if slot_level > max_individual_slot_level or budget < slot_level:
            continue
        slot_key = f"spell_slot_{slot_level}"
        max_slots = int(actor.max_resources.get(slot_key, 0))
        current_slots = min(int(actor.resources.get(slot_key, 0)), max_slots)
        missing_slots = max(0, max_slots - current_slots)
        recoverable_slots = min(missing_slots, budget // slot_level)
        if recoverable_slots <= 0:
            continue
        before = current_slots
        after = current_slots + recoverable_slots
        actor.resources[slot_key] = after
        _emit_resource_delta(
            telemetry_events,
            actor=actor,
            resource=slot_key,
            before=before,
            after=after,
            reason=delta_reason,
            source=source,
        )
        recovered_levels += recoverable_slots * slot_level
        budget -= recoverable_slots * slot_level
        if budget <= 0:
            break
    return recovered_levels


def apply_inferred_fighter_resources(
    actor: Any,
    *,
    has_trait: Callable[[Any, str], bool],
    superiority_dice_count: Callable[[int], int] = fighter_superiority_dice_count,
) -> None:
    fighter_level = int(actor.class_levels.get("fighter", 0))

    if has_trait(actor, "action surge"):
        action_surge_uses = (
            2 if fighter_level >= 17 or has_trait(actor, "action surge (two uses)") else 1
        )
        ensure_resource_cap(actor, "action_surge", action_surge_uses)

    if has_trait(actor, "second wind"):
        ensure_resource_cap(actor, "second_wind", 1)

    superiority_sources = ("combat superiority", "maneuvers", "battle master", "martial adept")
    if any(has_trait(actor, trait_name) for trait_name in superiority_sources):
        superiority_dice = superiority_dice_count(fighter_level)
        if superiority_dice <= 0 and has_trait(actor, "martial adept"):
            superiority_dice = 1
        if superiority_dice > 0:
            ensure_resource_cap(actor, "superiority_dice", superiority_dice)


def apply_inferred_barbarian_resources(
    actor: Any,
    *,
    has_trait: Callable[[Any, str], bool],
) -> None:
    if not has_trait(actor, "rage"):
        return
    barbarian_level = int(actor.class_levels.get("barbarian", 0))
    rage_uses = barbarian_rage_uses_for_level(barbarian_level)
    if rage_uses <= 0:
        return
    ensure_resource_cap(actor, "rage", rage_uses)


def apply_inferred_bard_resources(
    actor: Any,
    *,
    has_trait: Callable[[Any, str], bool],
) -> None:
    if not has_trait(actor, "bardic inspiration"):
        return
    bard_level = int(actor.class_levels.get("bard", 0))
    if bard_level <= 0:
        return
    ensure_resource_cap(actor, "bardic_inspiration", max(1, int(actor.cha_mod)))


def apply_inferred_sorcerer_resources(
    actor: Any,
    *,
    has_trait: Callable[[Any, str], bool],
) -> None:
    if not has_trait(actor, "font of magic"):
        return
    sorcerer_level = int(actor.class_levels.get("sorcerer", 0))
    points = sorcery_points_for_level(sorcerer_level)
    if points <= 0:
        return
    ensure_resource_cap(actor, "sorcery_points", points)


def apply_inferred_druid_resources(
    actor: Any,
    *,
    has_trait: Callable[[Any, str], bool],
    druid_wild_shape_uses_for_level: Callable[[int], int],
) -> None:
    if not has_trait(actor, "wild shape"):
        return
    if has_trait(actor, "archdruid"):
        return
    druid_level = int(actor.class_levels.get("druid", 0))
    if druid_level <= 0:
        return
    ensure_resource_cap(actor, "wild_shape", druid_wild_shape_uses_for_level(druid_level))


def apply_inferred_wizard_resources(
    actor: Any,
    *,
    has_trait: Callable[[Any, str], bool],
) -> None:
    if not has_trait(actor, "arcane recovery"):
        return
    wizard_level = int(actor.class_levels.get("wizard", 0))
    if wizard_level <= 0:
        return
    ensure_resource_cap(actor, "arcane_recovery", 1)


def apply_arcane_recovery(
    actor: Any,
    *,
    has_trait: Callable[[Any, str], bool],
    telemetry_events: MutableSequence[dict[str, Any]] | None = None,
    source: str = "dnd_sim.engine_resources",
) -> None:
    if not has_trait(actor, "arcane recovery"):
        return
    uses_remaining = int(actor.resources.get("arcane_recovery", 0))
    if uses_remaining <= 0:
        return
    wizard_level = int(actor.class_levels.get("wizard", 0))
    if wizard_level <= 0:
        return
    recovery_budget = max(1, (wizard_level + 1) // 2)
    recovered_levels = recover_spell_slots_with_budget(
        actor,
        budget=recovery_budget,
        max_individual_slot_level=5,
        telemetry_events=telemetry_events,
        source=source,
        delta_reason="arcane_recovery_slot_recovery",
    )
    if recovered_levels <= 0:
        return
    before_uses = uses_remaining
    actor.resources["arcane_recovery"] = uses_remaining - 1
    _emit_resource_delta(
        telemetry_events,
        actor=actor,
        resource="arcane_recovery",
        before=before_uses,
        after=actor.resources["arcane_recovery"],
        reason="arcane_recovery_use",
        source=source,
    )
