from __future__ import annotations

import logging
import random
from collections.abc import Mapping, Sequence
from typing import Any

from dnd_sim.models import ABILITY_KEYS, ActorRuntimeState, ConditionTracker, EffectInstance

logger = logging.getLogger(__name__)


def effect_instance_condition_names(effect: EffectInstance) -> set[str]:
    from dnd_sim import engine_runtime as engine_module

    names = {effect.condition}
    names.update(engine_module._IMPLIED_CONDITION_MAP.get(effect.condition, set()))
    return names


def effect_condition_names(actor: ActorRuntimeState) -> set[str]:
    names: set[str] = set()
    for effect in actor.effect_instances:
        names.update(effect_instance_condition_names(effect))
    return names


def rebuild_condition_durations(actor: ActorRuntimeState) -> None:
    trackers: dict[str, ConditionTracker] = {}
    for effect in actor.effect_instances:
        if effect.duration_remaining is None and effect.save_dc is None:
            continue
        for condition in effect_instance_condition_names(effect):
            previous = trackers.get(condition)
            if previous is None:
                trackers[condition] = ConditionTracker(
                    remaining_rounds=effect.duration_remaining,
                    save_dc=effect.save_dc,
                    save_ability=effect.save_ability,
                )
                continue

            previous_rounds = previous.remaining_rounds
            current_rounds = effect.duration_remaining
            if previous_rounds is None:
                merged_rounds = None
            elif current_rounds is None:
                merged_rounds = None
            else:
                merged_rounds = max(previous_rounds, current_rounds)

            trackers[condition] = ConditionTracker(
                remaining_rounds=merged_rounds,
                save_dc=previous.save_dc if previous.save_dc is not None else effect.save_dc,
                save_ability=(
                    previous.save_ability
                    if previous.save_ability is not None
                    else effect.save_ability
                ),
            )
    actor.condition_durations = trackers


def sync_condition_state(
    actor: ActorRuntimeState,
    *,
    previous_effect_conditions: set[str] | None = None,
) -> None:
    previous = previous_effect_conditions if previous_effect_conditions is not None else set()
    actor.intrinsic_conditions.update(set(actor.conditions) - previous)
    effect_conditions = effect_condition_names(actor)
    actor.conditions = set(actor.intrinsic_conditions).union(effect_conditions)
    rebuild_condition_durations(actor)


def next_effect_instance_id(actor: ActorRuntimeState) -> str:
    actor.effect_instance_seq += 1
    return f"{actor.actor_id}:effect:{actor.effect_instance_seq}"


def remove_effect_instance(
    actor: ActorRuntimeState,
    instance_id: str,
    *,
    source_actor_id: str | None = None,
) -> bool:
    from dnd_sim import engine_runtime as engine_module

    previous_effect_conditions = effect_condition_names(actor)
    removed = False
    kept: list[EffectInstance] = []
    for effect in actor.effect_instances:
        if effect.instance_id != instance_id:
            kept.append(effect)
            continue
        if source_actor_id is not None and effect.source_actor_id != source_actor_id:
            kept.append(effect)
            continue
        removed = True
    if not removed:
        return False
    actor.effect_instances = kept
    sync_condition_state(actor, previous_effect_conditions=previous_effect_conditions)
    if not engine_module.has_condition(actor, "readying"):
        engine_module._clear_readied_action_state(actor, clear_held_spell=True)
    return True


def remove_condition(
    actor: ActorRuntimeState,
    condition: str,
    *,
    source_actor_id: str | None = None,
    effect_id: str | None = None,
    instance_id: str | None = None,
) -> None:
    from dnd_sim import engine_runtime as engine_module

    key = engine_module._normalize_condition(condition)
    if not key:
        return
    previous_effect_conditions = effect_condition_names(actor)

    removed_effect = False
    normalized_effect_id = (
        engine_module._normalize_condition(effect_id) if effect_id is not None else None
    )
    kept: list[EffectInstance] = []
    for effect in actor.effect_instances:
        if effect.condition != key:
            kept.append(effect)
            continue
        if source_actor_id is not None and effect.source_actor_id != source_actor_id:
            kept.append(effect)
            continue
        if normalized_effect_id is not None and effect.effect_id != normalized_effect_id:
            kept.append(effect)
            continue
        if instance_id is not None and effect.instance_id != instance_id:
            kept.append(effect)
            continue
        removed_effect = True
    if removed_effect:
        actor.effect_instances = kept

    should_remove_manual = (
        source_actor_id is None and normalized_effect_id is None and instance_id is None
    )
    if should_remove_manual:
        actor.discard_manual_condition(key)
        for implied in engine_module._IMPLIED_CONDITION_MAP.get(key, set()):
            actor.discard_manual_condition(implied)

    if removed_effect or should_remove_manual:
        sync_condition_state(actor, previous_effect_conditions=previous_effect_conditions)

    if key == "wild_shaped" and actor.wild_shape_active:
        engine_module._revert_wild_shape(actor)

    if key == "readying" and not engine_module.has_condition(actor, "readying"):
        engine_module._clear_readied_action_state(actor, clear_held_spell=True)


def has_active_concentration_state(actor: ActorRuntimeState) -> bool:
    return bool(
        actor.concentrating
        or actor.concentrated_targets
        or actor.concentrated_spell
        or actor.concentrated_spell_level
        or actor.concentration_conditions
        or actor.concentration_effect_instance_ids
    )


def is_hazard_linked_to_concentration_owner(
    hazard: dict[str, Any],
    *,
    owner_actor_id: str,
) -> bool:
    linked_owner_id = str(hazard.get("concentration_owner_id", "")).strip()
    if linked_owner_id:
        return linked_owner_id == owner_actor_id and bool(hazard.get("concentration_linked", False))
    # Backward-compatible fallback for hazards created before owner linkage metadata.
    return hazard.get("source_id") == owner_actor_id


def is_actor_linked_concentration_summon(
    actor: ActorRuntimeState,
    *,
    owner_actor_id: str,
) -> bool:
    summon_trait = actor.traits.get("summoned")
    if not isinstance(summon_trait, dict):
        return False
    return str(summon_trait.get("source_id", "")).strip() == owner_actor_id and bool(
        summon_trait.get("concentration_linked", False)
    )


def break_concentration(
    actor: ActorRuntimeState,
    actors: dict[str, ActorRuntimeState],
    active_hazards: list[dict[str, Any]],
) -> None:
    from dnd_sim import engine_runtime as engine_module

    if not has_active_concentration_state(actor):
        return
    actor.concentrating = False

    linked_ids = set(actor.concentration_effect_instance_ids)
    for target_actor in actors.values():
        for effect in list(target_actor.effect_instances):
            if effect.source_actor_id != actor.actor_id:
                continue
            if effect.instance_id in linked_ids or effect.concentration_linked:
                remove_effect_instance(
                    target_actor,
                    effect.instance_id,
                    source_actor_id=actor.actor_id,
                )

    summon_ids_to_remove: set[str] = set()
    for target_id in list(actor.concentrated_targets):
        target_actor = actors.get(target_id)
        if target_actor is not None and "summoned" in target_actor.conditions:
            summon_ids_to_remove.add(target_id)
    for summon_id, summon_actor in list(actors.items()):
        if is_actor_linked_concentration_summon(summon_actor, owner_actor_id=actor.actor_id):
            summon_ids_to_remove.add(summon_id)
    for summon_id in summon_ids_to_remove:
        if summon_id != actor.actor_id:
            actors.pop(summon_id, None)

    prior_hazard_count = len(active_hazards)
    active_hazards[:] = [
        hazard
        for hazard in active_hazards
        if not is_hazard_linked_to_concentration_owner(hazard, owner_actor_id=actor.actor_id)
    ]
    if len(active_hazards) != prior_hazard_count:
        engine_module._prune_actor_zone_memberships(actors, active_hazards)

    actor.concentrated_targets.clear()
    actor.concentration_conditions.clear()
    actor.concentration_effect_instance_ids.clear()

    actor.concentrated_spell = None
    actor.concentrated_spell_level = None

    if actor.readied_spell_held:
        remove_condition(actor, "readying")

    engine_module._sync_antimagic_suppression_for_all_actors(actors, active_hazards)


def concentration_forced_end(actor: ActorRuntimeState) -> bool:
    from dnd_sim import engine_runtime as engine_module

    if not has_active_concentration_state(actor):
        return False
    if actor.dead or actor.hp <= 0:
        return True
    return any(
        engine_module.has_condition(actor, condition)
        for condition in engine_module._CONCENTRATION_FORCED_END_CONDITIONS
    )


def force_end_concentration_if_needed(
    actor: ActorRuntimeState,
    *,
    actors: dict[str, ActorRuntimeState],
    active_hazards: list[dict[str, Any]],
) -> bool:
    if not concentration_forced_end(actor):
        return False
    break_concentration(actor, actors, active_hazards)
    return True


def apply_condition(
    actor: ActorRuntimeState,
    condition: str,
    *,
    duration_rounds: int | None = None,
    save_dc: int | None = None,
    save_ability: str | None = None,
    source_actor_id: str | None = None,
    target_actor_id: str | None = None,
    effect_id: str | None = None,
    duration_timing: str = "turn_start",
    concentration_linked: bool = False,
    stack_policy: str = "independent",
    save_to_end: bool = False,
    internal_tags: set[str] | None = None,
) -> list[str]:
    from dnd_sim import engine_runtime as engine_module

    key = engine_module._normalize_condition(condition)
    if not key:
        return []
    if key in actor.condition_immunities or "all" in actor.condition_immunities:
        return []
    previous_effect_conditions = effect_condition_names(actor)

    normalized_source = str(source_actor_id).strip() if source_actor_id else None
    normalized_target = str(target_actor_id).strip() if target_actor_id else actor.actor_id
    normalized_effect_id = engine_module._normalize_condition(effect_id) if effect_id else key
    normalized_boundary = engine_module._normalize_duration_boundary(duration_timing)
    normalized_policy = engine_module._normalize_stack_policy(stack_policy)
    normalized_tags = set(internal_tags or set())
    normalized_duration = engine_module._coerce_positive_int(duration_rounds)
    normalized_save_dc = int(save_dc) if save_dc is not None else None
    normalized_save_ability = (
        engine_module._normalize_condition(save_ability) if save_ability else None
    )
    if normalized_save_ability not in ABILITY_KEYS:
        normalized_save_ability = None

    created_ids: list[str] = []

    if normalized_policy == "replace":
        actor.effect_instances = [
            effect for effect in actor.effect_instances if effect.condition != key
        ]
    elif normalized_policy == "refresh":
        for effect in actor.effect_instances:
            if effect.condition != key:
                continue
            if effect.effect_id != normalized_effect_id:
                continue
            if normalized_source and effect.source_actor_id != normalized_source:
                continue
            if normalized_duration is not None:
                current_duration = effect.duration_remaining or 0
                effect.duration_remaining = max(current_duration, normalized_duration)
            effect.duration_boundary = normalized_boundary
            effect.save_dc = normalized_save_dc
            effect.save_ability = normalized_save_ability
            effect.save_to_end = bool(save_to_end)
            effect.concentration_linked = bool(concentration_linked)
            effect.stack_policy = normalized_policy
            effect.internal_tags.update(engine_module._normalize_internal_tags(normalized_tags))
            effect.target_actor_id = normalized_target
            sync_condition_state(actor, previous_effect_conditions=previous_effect_conditions)
            if (
                key == "unconscious"
                and "prone" not in actor.condition_immunities
                and "all" not in actor.condition_immunities
            ):
                actor.add_manual_condition("prone")
            return [effect.instance_id]

    instance = EffectInstance(
        instance_id=next_effect_instance_id(actor),
        effect_id=normalized_effect_id,
        condition=key,
        source_actor_id=normalized_source,
        target_actor_id=normalized_target,
        duration_remaining=normalized_duration,
        duration_boundary=normalized_boundary,
        save_dc=normalized_save_dc,
        save_ability=normalized_save_ability,
        save_to_end=bool(save_to_end),
        concentration_linked=bool(concentration_linked),
        stack_policy=normalized_policy,
        internal_tags=engine_module._normalize_internal_tags(normalized_tags),
    )
    actor.effect_instances.append(instance)
    created_ids.append(instance.instance_id)
    sync_condition_state(actor, previous_effect_conditions=previous_effect_conditions)
    if (
        key == "unconscious"
        and "prone" not in actor.condition_immunities
        and "all" not in actor.condition_immunities
    ):
        actor.add_manual_condition("prone")
    return created_ids


def tick_conditions_for_actor(
    rng: random.Random,
    actor: ActorRuntimeState,
    *,
    boundary: str = "turn_start",
) -> None:
    """Tick condition durations for the configured turn boundary."""

    from dnd_sim import engine_runtime as engine_module

    tick_boundary = engine_module._normalize_duration_boundary(boundary)

    if tick_boundary == "turn_start":
        if engine_module.has_condition(actor, "raging"):
            persistent_rage_active = engine_module._has_trait(actor, "persistent rage")
            if engine_module.has_condition(actor, "unconscious") or actor.dead or actor.hp <= 0:
                remove_condition(actor, "raging")
            elif not persistent_rage_active and not actor.rage_sustained_since_last_turn:
                remove_condition(actor, "raging")
        actor.rage_sustained_since_last_turn = False
        actor.colossus_slayer_used_this_turn = False
        actor.horde_breaker_used_this_turn = False

    if not actor.effect_instances:
        return

    previous_effect_conditions = effect_condition_names(actor)
    changed = False
    kept: list[EffectInstance] = []
    for effect in actor.effect_instances:
        save_boundary = "turn_end" if effect.save_to_end else "turn_start"
        if effect.save_dc is not None and effect.save_ability and save_boundary == tick_boundary:
            save_key = engine_module._normalize_condition(effect.save_ability)
            if engine_module._auto_fails_strength_or_dex_save(actor, save_key):
                save_succeeds = False
            else:
                save_mod = int(actor.save_mods.get(save_key, 0))
                save_roll = rng.randint(1, 20) + save_mod
                save_succeeds = save_roll >= effect.save_dc
            if save_succeeds:
                changed = True
                continue

        if effect.duration_remaining is not None and effect.duration_boundary == tick_boundary:
            effect.duration_remaining -= 1
            changed = True
            if effect.duration_remaining <= 0:
                continue

        kept.append(effect)

    if changed:
        actor.effect_instances = kept
        sync_condition_state(actor, previous_effect_conditions=previous_effect_conditions)
        if not engine_module.has_condition(actor, "readying"):
            engine_module._clear_readied_action_state(actor, clear_held_spell=True)


_LIFECYCLE_EVENT_TYPE_BY_TRANSITION = {
    "apply": "effect_apply",
    "tick": "effect_tick",
    "refresh": "effect_refresh",
    "expire": "effect_expire",
    "concentration_break": "effect_concentration_break",
}

_MISSING = object()


def _coerce_json_value(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            normalized[key_text] = _coerce_json_value(item, path=f"{path}.{key_text}")
        return normalized

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_coerce_json_value(item, path=f"{path}[{idx}]") for idx, item in enumerate(value)]

    raise TypeError(
        f"{path} must be JSON-compatible; unsupported value type: {type(value).__name__}"
    )


def _normalize_snapshot(snapshot: Mapping[str, Any], *, path: str) -> dict[str, Any]:
    normalized = _coerce_json_value(snapshot, path=path)
    if not isinstance(normalized, dict):
        raise TypeError(f"{path} must be a JSON-compatible object")
    return normalized


def _normalize_required_text(*, name: str, value: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _normalize_optional_text(*, name: str, value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty when provided")
    return normalized


def _delta_path(prefix: str, key: str) -> str:
    return key if not prefix else f"{prefix}.{key}"


def _append_delta(*, deltas: list[dict[str, Any]], path: str, before: Any, after: Any) -> None:
    row: dict[str, Any] = {
        "path": path,
        "before": None if before is _MISSING else before,
        "after": None if after is _MISSING else after,
    }
    if before is _MISSING:
        row["before_missing"] = True
    if after is _MISSING:
        row["after_missing"] = True
    deltas.append(row)


def _collect_state_deltas(
    *, before: Any, after: Any, path: str, deltas: list[dict[str, Any]]
) -> None:
    if isinstance(before, dict) and isinstance(after, dict):
        keys = sorted(set(before) | set(after), key=str.casefold)
        for key in keys:
            before_value = before.get(key, _MISSING)
            after_value = after.get(key, _MISSING)
            child_path = _delta_path(path, key)
            if before_value is _MISSING or after_value is _MISSING:
                _append_delta(
                    deltas=deltas, path=child_path, before=before_value, after=after_value
                )
                continue
            _collect_state_deltas(
                before=before_value,
                after=after_value,
                path=child_path,
                deltas=deltas,
            )
        return

    if isinstance(before, list) and isinstance(after, list):
        if before != after:
            _append_delta(deltas=deltas, path=path, before=before, after=after)
        return

    if before != after:
        _append_delta(deltas=deltas, path=path, before=before, after=after)


def effect_lifecycle_event_type(transition: str) -> str:
    normalized = str(transition).strip().lower()
    event_type = _LIFECYCLE_EVENT_TYPE_BY_TRANSITION.get(normalized)
    if event_type is None:
        supported = ", ".join(sorted(_LIFECYCLE_EVENT_TYPE_BY_TRANSITION))
        raise ValueError(
            f"unsupported effect lifecycle transition '{transition}' " f"(supported: {supported})"
        )
    return event_type


def build_actor_state_delta_trace(
    *,
    actor_id: str,
    round_number: int | None,
    turn_token: str | None,
    before_state: Mapping[str, Any],
    after_state: Mapping[str, Any],
    transition: str | None = None,
) -> dict[str, Any] | None:
    normalized_actor_id = _normalize_required_text(name="actor_id", value=actor_id)
    normalized_before = _normalize_snapshot(before_state, path="before_state")
    normalized_after = _normalize_snapshot(after_state, path="after_state")

    deltas: list[dict[str, Any]] = []
    _collect_state_deltas(before=normalized_before, after=normalized_after, path="", deltas=deltas)
    if not deltas:
        return None

    deltas.sort(key=lambda row: str(row.get("path", "")).casefold())
    changed_fields = [str(row["path"]) for row in deltas]

    payload: dict[str, Any] = {
        "round": round_number,
        "turn_token": turn_token,
        "actor_id": normalized_actor_id,
        "delta_count": len(deltas),
        "changed_fields": changed_fields,
        "deltas": deltas,
        "before": normalized_before,
        "after": normalized_after,
    }
    if transition is not None:
        payload["transition"] = str(transition).strip().lower()
    return payload


def build_effect_lifecycle_trace(
    *,
    transition: str,
    actor_id: str,
    effect_id: str,
    effect_type: str | None = None,
    round_number: int | None = None,
    turn_token: str | None = None,
    source_actor_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_transition = str(transition).strip().lower()
    effect_lifecycle_event_type(normalized_transition)

    payload: dict[str, Any] = {
        "round": round_number,
        "turn_token": turn_token,
        "transition": normalized_transition,
        "actor_id": _normalize_required_text(name="actor_id", value=actor_id),
        "effect_id": _normalize_required_text(name="effect_id", value=effect_id),
    }

    normalized_effect_type = _normalize_optional_text(name="effect_type", value=effect_type)
    if normalized_effect_type is not None:
        payload["effect_type"] = normalized_effect_type

    normalized_source_actor = _normalize_optional_text(
        name="source_actor_id",
        value=source_actor_id,
    )
    if normalized_source_actor is not None:
        payload["source_actor_id"] = normalized_source_actor

    if metadata is not None:
        payload["metadata"] = _normalize_snapshot(metadata, path="metadata")

    return payload
