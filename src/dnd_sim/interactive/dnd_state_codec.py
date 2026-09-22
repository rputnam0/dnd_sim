from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import fields
from typing import Any, cast, get_origin, get_type_hints

from pydantic import TypeAdapter, ValidationError

from dnd_sim.inventory import CurrencyWallet, InventoryItem, InventoryState
from dnd_sim.models import (
    ActionDefinition,
    ActorRuntimeState,
    ConditionTracker,
    EffectInstance,
    FeatureHookRegistration,
    SpellComponents,
    SpellDefinition,
    SpellRoll,
    SpellScaling,
)

from .contracts import JSONValue, normalize_json


class ActorStateCodecError(ValueError):
    """Raised when an actor runtime state is not a canonical JSON state graph."""


_ACTOR_ADAPTER = TypeAdapter(ActorRuntimeState)
_ACTION_ADAPTER = TypeAdapter(ActionDefinition)

_actor_type_hints = get_type_hints(ActorRuntimeState)
_ACTOR_SET_FIELDS = tuple(
    actor_field.name
    for actor_field in fields(ActorRuntimeState)
    if get_origin(_actor_type_hints[actor_field.name]) is set
)

_WILD_SHAPE_SNAPSHOT_FIELDS = frozenset(
    {
        "max_hp",
        "hp",
        "ac",
        "speed_ft",
        "str_mod",
        "dex_mod",
        "con_mod",
        "actions",
        "traits",
        "movement_modes",
    }
)
_WILD_SHAPE_INTEGER_FIELDS = (
    "max_hp",
    "hp",
    "ac",
    "speed_ft",
    "str_mod",
    "dex_mod",
    "con_mod",
)
_PENDING_SMITE_FIELDS = frozenset(
    {
        "name",
        "save_dc",
        "save_ability",
        "extra_damage",
        "rider_effects",
        "is_magical",
    }
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _normalize_object(value: Any, *, path: str) -> dict[str, JSONValue]:
    try:
        normalized = normalize_json(value, path=path)
    except (TypeError, ValueError) as exc:
        raise ActorStateCodecError(f"{path} must be a finite JSON value tree") from exc
    if not isinstance(normalized, dict):
        raise ActorStateCodecError(f"{path} must be a JSON object")
    return normalized


def _validate_exact_keys(
    payload: Mapping[str, Any],
    expected: frozenset[str],
    *,
    path: str,
) -> None:
    actual = set(payload)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected {', '.join(unexpected)}")
        raise ActorStateCodecError(f"{path} has noncanonical fields: {'; '.join(details)}")


def _validate_native_json_tree(value: Any, *, path: str) -> None:
    """Require an already-native JSON tree without lossy Python-only values."""

    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ActorStateCodecError(f"{path} must be a finite JSON value tree")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_native_json_tree(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ActorStateCodecError(f"{path} must be a finite JSON value tree")
            _validate_native_json_tree(item, path=f"{path}.{key}")
        return
    raise ActorStateCodecError(
        f"{path} must be a native JSON value tree, got {type(value).__name__}"
    )


def _validate_action_object(action: ActionDefinition, *, path: str) -> None:
    if not isinstance(action, ActionDefinition):
        raise ActorStateCodecError(f"{path} must be an ActionDefinition")
    _validate_native_json_tree(action.effects, path=f"{path}.effects")
    _validate_native_json_tree(action.mechanics, path=f"{path}.mechanics")

    spell = action.spell
    if spell is None:
        return
    if not isinstance(spell, SpellDefinition):
        raise ActorStateCodecError(f"{path}.spell must be a SpellDefinition")
    if not isinstance(spell.roll, SpellRoll):
        raise ActorStateCodecError(f"{path}.spell.roll must be a SpellRoll")
    if not isinstance(spell.scaling, SpellScaling):
        raise ActorStateCodecError(f"{path}.spell.scaling must be a SpellScaling")
    if not isinstance(spell.components, SpellComponents):
        raise ActorStateCodecError(f"{path}.spell.components must be SpellComponents")
    for level, effects in spell.scaling.upcast_effects.items():
        if not isinstance(level, int) or isinstance(level, bool):
            raise ActorStateCodecError(f"{path}.spell.scaling.upcast_effects keys must be integers")
        _validate_native_json_tree(
            effects,
            path=f"{path}.spell.scaling.upcast_effects[{level}]",
        )


def _encode_action_definition(action: ActionDefinition, *, path: str) -> dict[str, JSONValue]:
    _validate_action_object(action, path=path)
    try:
        payload = _ACTION_ADAPTER.dump_python(action, mode="json")
    except Exception as exc:  # pragma: no cover - pydantic exception type is not public API
        raise ActorStateCodecError(f"{path} could not be encoded") from exc
    return _normalize_object(payload, path=path)


def _decode_action_definition(payload: Any, *, path: str) -> ActionDefinition:
    normalized = _normalize_object(payload, path=path)
    try:
        action = _ACTION_ADAPTER.validate_json(_canonical_json(normalized), strict=True)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ActorStateCodecError(f"{path} does not match ActionDefinition") from exc
    canonical = _encode_action_definition(action, path=path)
    if _canonical_json(canonical) != _canonical_json(normalized):
        raise ActorStateCodecError(f"{path} is not a canonical ActionDefinition payload")
    return action


def _encode_wild_shape_snapshot(snapshot: Any) -> dict[str, JSONValue]:
    path = "actor.wild_shape_base_snapshot"
    if snapshot == {}:
        return {}
    if not isinstance(snapshot, dict):
        raise ActorStateCodecError(f"{path} must be a mapping")
    _validate_exact_keys(snapshot, _WILD_SHAPE_SNAPSHOT_FIELDS, path=path)
    for field_name in _WILD_SHAPE_INTEGER_FIELDS:
        value = snapshot[field_name]
        if not isinstance(value, int) or isinstance(value, bool):
            raise ActorStateCodecError(f"{path}.{field_name} must be an integer")

    raw_actions = snapshot["actions"]
    if not isinstance(raw_actions, list):
        raise ActorStateCodecError(f"{path}.actions must be a list")
    encoded_actions = [
        _encode_action_definition(action, path=f"{path}.actions[{index}]")
        for index, action in enumerate(raw_actions)
    ]

    traits = snapshot["traits"]
    movement_modes = snapshot["movement_modes"]
    if not isinstance(traits, dict):
        raise ActorStateCodecError(f"{path}.traits must be a mapping")
    if not isinstance(movement_modes, dict):
        raise ActorStateCodecError(f"{path}.movement_modes must be a mapping")
    _validate_native_json_tree(traits, path=f"{path}.traits")
    _validate_native_json_tree(movement_modes, path=f"{path}.movement_modes")

    encoded: dict[str, Any] = {
        field_name: snapshot[field_name] for field_name in _WILD_SHAPE_INTEGER_FIELDS
    }
    encoded.update(
        {
            "actions": encoded_actions,
            "traits": traits,
            "movement_modes": movement_modes,
        }
    )
    return _normalize_object(encoded, path=path)


def _decode_wild_shape_snapshot(payload: Any) -> dict[str, Any]:
    path = "actor.wild_shape_base_snapshot"
    normalized = _normalize_object(payload, path=path)
    if not normalized:
        return {}
    _validate_exact_keys(normalized, _WILD_SHAPE_SNAPSHOT_FIELDS, path=path)
    for field_name in _WILD_SHAPE_INTEGER_FIELDS:
        value = normalized[field_name]
        if not isinstance(value, int) or isinstance(value, bool):
            raise ActorStateCodecError(f"{path}.{field_name} must be an integer")

    raw_actions = normalized["actions"]
    if not isinstance(raw_actions, list):
        raise ActorStateCodecError(f"{path}.actions must be a list")
    actions = [
        _decode_action_definition(action, path=f"{path}.actions[{index}]")
        for index, action in enumerate(raw_actions)
    ]

    traits = normalized["traits"]
    movement_modes = normalized["movement_modes"]
    if not isinstance(traits, dict):
        raise ActorStateCodecError(f"{path}.traits must be a mapping")
    if not isinstance(movement_modes, dict):
        raise ActorStateCodecError(f"{path}.movement_modes must be a mapping")
    _validate_native_json_tree(traits, path=f"{path}.traits")
    _validate_native_json_tree(movement_modes, path=f"{path}.movement_modes")

    decoded: dict[str, Any] = {
        field_name: normalized[field_name] for field_name in _WILD_SHAPE_INTEGER_FIELDS
    }
    decoded.update(
        {
            "actions": actions,
            "traits": traits,
            "movement_modes": movement_modes,
        }
    )
    return decoded


def _validate_pending_smite_scalars(payload: Mapping[str, Any], *, path: str) -> None:
    if not isinstance(payload["name"], str):
        raise ActorStateCodecError(f"{path}.name must be a string")
    save_dc = payload["save_dc"]
    if save_dc is not None and (not isinstance(save_dc, int) or isinstance(save_dc, bool)):
        raise ActorStateCodecError(f"{path}.save_dc must be an integer or null")
    save_ability = payload["save_ability"]
    if save_ability is not None and not isinstance(save_ability, str):
        raise ActorStateCodecError(f"{path}.save_ability must be a string or null")
    if not isinstance(payload["is_magical"], bool):
        raise ActorStateCodecError(f"{path}.is_magical must be a boolean")
    riders = payload["rider_effects"]
    if not isinstance(riders, list) or any(not isinstance(rider, dict) for rider in riders):
        raise ActorStateCodecError(f"{path}.rider_effects must be a list of mappings")
    _validate_native_json_tree(riders, path=f"{path}.rider_effects")


def _encode_pending_smite(pending: Any) -> dict[str, JSONValue] | None:
    if pending is None:
        return None
    path = "actor.pending_smite"
    if not isinstance(pending, dict):
        raise ActorStateCodecError(f"{path} must be a mapping or null")
    _validate_exact_keys(pending, _PENDING_SMITE_FIELDS, path=path)
    _validate_pending_smite_scalars(pending, path=path)

    raw_components = pending["extra_damage"]
    if not isinstance(raw_components, list):
        raise ActorStateCodecError(f"{path}.extra_damage must be a list")
    components: list[list[str]] = []
    for index, component in enumerate(raw_components):
        if (
            not isinstance(component, tuple)
            or len(component) != 2
            or not all(isinstance(value, str) for value in component)
        ):
            raise ActorStateCodecError(f"{path}.extra_damage[{index}] must be a two-string tuple")
        components.append([component[0], component[1]])

    encoded = {
        "name": pending["name"],
        "save_dc": pending["save_dc"],
        "save_ability": pending["save_ability"],
        "extra_damage": components,
        "rider_effects": pending["rider_effects"],
        "is_magical": pending["is_magical"],
    }
    return _normalize_object(encoded, path=path)


def _decode_pending_smite(payload: Any) -> dict[str, Any] | None:
    if payload is None:
        return None
    path = "actor.pending_smite"
    normalized = _normalize_object(payload, path=path)
    _validate_exact_keys(normalized, _PENDING_SMITE_FIELDS, path=path)
    _validate_pending_smite_scalars(normalized, path=path)

    raw_components = normalized["extra_damage"]
    if not isinstance(raw_components, list):
        raise ActorStateCodecError(f"{path}.extra_damage must be a list")
    components: list[tuple[str, str]] = []
    for index, component in enumerate(raw_components):
        if (
            not isinstance(component, list)
            or len(component) != 2
            or not all(isinstance(value, str) for value in component)
        ):
            raise ActorStateCodecError(
                f"{path}.extra_damage[{index}] must be a two-string JSON array"
            )
        components.append((component[0], component[1]))

    return {
        "name": normalized["name"],
        "save_dc": normalized["save_dc"],
        "save_ability": normalized["save_ability"],
        "extra_damage": components,
        "rider_effects": normalized["rider_effects"],
        "is_magical": normalized["is_magical"],
    }


def _validate_inventory_identity(inventory: Any, *, path: str) -> None:
    if not isinstance(inventory, InventoryState):
        raise ActorStateCodecError(f"{path} must be an InventoryState")
    if not isinstance(inventory.currency, CurrencyWallet):
        raise ActorStateCodecError(f"{path}.currency must be a CurrencyWallet")
    for item_key, item in inventory.items.items():
        if not isinstance(item_key, str) or not isinstance(item, InventoryItem):
            raise ActorStateCodecError(f"{path}.items must map strings to InventoryItem values")
        if item_key != item.item_id:
            raise ActorStateCodecError(
                f"inventory item key '{item_key}' does not match item_id '{item.item_id}'"
            )
        _validate_native_json_tree(
            item.metadata,
            path=f"{path}.items.{item_key}.metadata",
        )
        _validate_native_json_tree(
            item.charge_recovery,
            path=f"{path}.items.{item_key}.charge_recovery",
        )


def _validate_actor_object_graph(actor: ActorRuntimeState) -> None:
    _validate_native_json_tree(actor.traits, path="actor.traits")
    for index, action in enumerate(actor.actions):
        _validate_action_object(action, path=f"actor.actions[{index}]")
    for index, hook in enumerate(actor.feature_hooks):
        if not isinstance(hook, FeatureHookRegistration):
            raise ActorStateCodecError(
                f"actor.feature_hooks[{index}] must be a FeatureHookRegistration"
            )
    for condition, tracker in actor.condition_durations.items():
        if not isinstance(condition, str) or not isinstance(tracker, ConditionTracker):
            raise ActorStateCodecError(
                "actor.condition_durations must map strings to ConditionTracker values"
            )
    for index, effect in enumerate(actor.effect_instances):
        if not isinstance(effect, EffectInstance):
            raise ActorStateCodecError(f"actor.effect_instances[{index}] must be an EffectInstance")
        if not isinstance(effect.internal_tags, set) or any(
            not isinstance(tag, str) for tag in effect.internal_tags
        ):
            raise ActorStateCodecError(
                f"actor.effect_instances[{index}].internal_tags must be a string set"
            )
    for field_name in _ACTOR_SET_FIELDS:
        values = getattr(actor, field_name)
        if not isinstance(values, set) or any(not isinstance(value, str) for value in values):
            raise ActorStateCodecError(f"actor.{field_name} must be a string set")
    _validate_inventory_identity(actor.inventory, path="actor.inventory")


def encode_actor_runtime_state(actor: ActorRuntimeState) -> dict[str, JSONValue]:
    """Encode the complete mutable actor graph as deterministic canonical JSON."""

    if not isinstance(actor, ActorRuntimeState):
        raise ActorStateCodecError("actor must be an ActorRuntimeState")
    _validate_actor_object_graph(actor)
    try:
        raw_payload = _ACTOR_ADAPTER.dump_python(actor, mode="json")
    except Exception as exc:  # pragma: no cover - pydantic exception type is not public API
        raise ActorStateCodecError("actor could not be encoded") from exc
    if not isinstance(raw_payload, dict):  # pragma: no cover - TypeAdapter contract guard
        raise ActorStateCodecError("actor must encode to a JSON object")

    for field_name in _ACTOR_SET_FIELDS:
        raw_payload[field_name] = sorted(getattr(actor, field_name))
    for index, effect in enumerate(actor.effect_instances):
        raw_payload["effect_instances"][index]["internal_tags"] = sorted(effect.internal_tags)

    raw_payload["wild_shape_base_snapshot"] = _encode_wild_shape_snapshot(
        actor.wild_shape_base_snapshot
    )
    raw_payload["pending_smite"] = _encode_pending_smite(actor.pending_smite)
    return _normalize_object(raw_payload, path="actor")


def decode_actor_runtime_state(payload: Mapping[str, Any]) -> ActorRuntimeState:
    """Decode only the full canonical JSON representation of an actor runtime state."""

    normalized = _normalize_object(payload, path="actor")
    try:
        actor = _ACTOR_ADAPTER.validate_json(_canonical_json(normalized), strict=True)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ActorStateCodecError("actor does not match ActorRuntimeState") from exc

    actor.wild_shape_base_snapshot = _decode_wild_shape_snapshot(
        normalized.get("wild_shape_base_snapshot", {})
    )
    actor.pending_smite = _decode_pending_smite(normalized.get("pending_smite"))
    canonical = encode_actor_runtime_state(actor)
    if _canonical_json(canonical) != _canonical_json(normalized):
        raise ActorStateCodecError("actor payload is not the full canonical runtime state")
    return actor


def encode_actor_runtime_state_map(
    actors: Mapping[str, ActorRuntimeState],
) -> dict[str, JSONValue]:
    """Encode an actor-id keyed runtime state map with identity checks."""

    if not isinstance(actors, Mapping):
        raise ActorStateCodecError("actors must be a mapping")
    for actor_id in actors:
        if not isinstance(actor_id, str):
            raise ActorStateCodecError("actor map keys must be strings")

    encoded: dict[str, JSONValue] = {}
    for actor_id in sorted(actors):
        actor = actors[actor_id]
        if not isinstance(actor, ActorRuntimeState):
            raise ActorStateCodecError(f"actors.{actor_id} must be an ActorRuntimeState")
        if actor_id != actor.actor_id:
            raise ActorStateCodecError(
                f"actor map key '{actor_id}' does not match actor_id '{actor.actor_id}'"
            )
        encoded[actor_id] = cast(JSONValue, encode_actor_runtime_state(actor))
    return encoded


def decode_actor_runtime_state_map(
    payload: Mapping[str, Any],
) -> dict[str, ActorRuntimeState]:
    """Decode an actor-id keyed canonical JSON state map with identity checks."""

    normalized = _normalize_object(payload, path="actors")
    decoded: dict[str, ActorRuntimeState] = {}
    for actor_id in sorted(normalized):
        actor_payload = normalized[actor_id]
        if not isinstance(actor_payload, dict):
            raise ActorStateCodecError(f"actors.{actor_id} must be a JSON object")
        actor = decode_actor_runtime_state(actor_payload)
        if actor_id != actor.actor_id:
            raise ActorStateCodecError(
                f"actor map key '{actor_id}' does not match actor_id '{actor.actor_id}'"
            )
        decoded[actor_id] = actor
    return decoded
