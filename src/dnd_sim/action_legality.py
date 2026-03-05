from __future__ import annotations

import logging
from typing import Any

from dnd_sim.models import ActionDefinition, ActorRuntimeState, SpellCastRequest
from dnd_sim.spatial import distance_chebyshev
from dnd_sim.strategy_api import DeclaredAction, ReadyDeclaration, TargetRef, TurnDeclaration

logger = logging.getLogger(__name__)


class TurnDeclarationValidationError(ValueError):
    def __init__(
        self,
        *,
        actor_id: str,
        code: str,
        field: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.actor_id = actor_id
        self.code = code
        self.field = field
        self.message = message
        self.details = dict(details or {})
        super().__init__(f"{code} [{actor_id}:{field}] {message}")


def validate_strategy_instance(strategy: Any) -> None:
    required = ["declare_turn", "on_round_start"]
    missing = [name for name in required if not callable(getattr(strategy, name, None))]
    if missing:
        joined = ", ".join(sorted(missing))
        raise ValueError(
            "Strategy instance missing required methods: "
            f"{joined}. Strategies must define callable declare_turn(actor, state) "
            "and on_round_start(state)."
        )


def raise_turn_declaration_error(
    *,
    actor: ActorRuntimeState,
    code: str,
    field: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    raise TurnDeclarationValidationError(
        actor_id=actor.actor_id,
        code=code,
        field=field,
        message=message,
        details=details,
    )


def declared_action_or_error(
    actor: ActorRuntimeState,
    declaration: DeclaredAction,
    *,
    field_prefix: str,
    expected_cost: str,
) -> ActionDefinition:
    action_name = str(declaration.action_name or "").strip()
    if not action_name:
        raise_turn_declaration_error(
            actor=actor,
            code="missing_action_name",
            field=f"{field_prefix}.action_name",
            message="Declared action is missing action_name.",
        )

    selected = next((entry for entry in actor.actions if entry.name == action_name), None)
    if selected is None:
        raise_turn_declaration_error(
            actor=actor,
            code="unknown_action",
            field=f"{field_prefix}.action_name",
            message=f"Declared action '{action_name}' does not exist for actor.",
        )

    if expected_cost == "bonus" and selected.action_cost != "bonus":
        raise_turn_declaration_error(
            actor=actor,
            code="illegal_bonus_action",
            field=f"{field_prefix}.action_name",
            message=f"Action '{selected.name}' is not a bonus action.",
            details={"action_cost": selected.action_cost},
        )
    if expected_cost == "action" and selected.action_cost not in {"action", "none"}:
        raise_turn_declaration_error(
            actor=actor,
            code="illegal_action",
            field=f"{field_prefix}.action_name",
            message=f"Action '{selected.name}' cannot be used in the main action step.",
            details={"action_cost": selected.action_cost},
        )
    return selected


def declared_targets_or_error(
    actor: ActorRuntimeState,
    declaration: DeclaredAction,
    *,
    field_prefix: str,
) -> list[TargetRef]:
    raw_targets = declaration.targets
    if not isinstance(raw_targets, list):
        raise_turn_declaration_error(
            actor=actor,
            code="invalid_targets",
            field=f"{field_prefix}.targets",
            message="Declared targets must be a list.",
        )

    out: list[TargetRef] = []
    for idx, target in enumerate(raw_targets):
        if not isinstance(target, TargetRef):
            raise_turn_declaration_error(
                actor=actor,
                code="invalid_target_ref",
                field=f"{field_prefix}.targets[{idx}]",
                message="Declared targets must contain TargetRef entries.",
            )
        out.append(target)
    return out


def declared_extra_resource_cost_or_error(
    actor: ActorRuntimeState,
    declaration: DeclaredAction,
    *,
    field_prefix: str,
) -> dict[str, int]:
    raw = getattr(declaration.resource_spend, "amounts", {})
    if not isinstance(raw, dict):
        raise_turn_declaration_error(
            actor=actor,
            code="invalid_resource_spend",
            field=f"{field_prefix}.resource_spend",
            message="Declared resource_spend must be a mapping of resource -> amount.",
        )
    out: dict[str, int] = {}
    for key, amount in raw.items():
        try:
            parsed = int(amount)
        except (TypeError, ValueError):
            raise_turn_declaration_error(
                actor=actor,
                code="invalid_resource_amount",
                field=f"{field_prefix}.resource_spend.{key}",
                message="Declared resource spend amount must be an integer.",
            )
        if parsed <= 0:
            continue
        out[str(key)] = parsed
    return out


def declared_spell_request_or_error(
    actor: ActorRuntimeState,
    action: ActionDefinition,
    declaration: DeclaredAction,
    *,
    field_prefix: str,
) -> SpellCastRequest | None:
    raw_slot_level = declaration.spell_slot_level
    if "spell" not in action.tags:
        if raw_slot_level is not None:
            raise_turn_declaration_error(
                actor=actor,
                code="illegal_spell_slot_override",
                field=f"{field_prefix}.spell_slot_level",
                message="spell_slot_level can only be declared for spell actions.",
            )
        return None

    request = SpellCastRequest()
    if raw_slot_level is None:
        return request

    try:
        slot_level = int(raw_slot_level)
    except (TypeError, ValueError):
        raise_turn_declaration_error(
            actor=actor,
            code="invalid_spell_slot_level",
            field=f"{field_prefix}.spell_slot_level",
            message="Declared spell_slot_level must be an integer.",
        )
    if slot_level <= 0:
        raise_turn_declaration_error(
            actor=actor,
            code="invalid_spell_slot_level",
            field=f"{field_prefix}.spell_slot_level",
            message="Declared spell_slot_level must be >= 1.",
        )
    request.slot_level = slot_level
    return request


def declared_movement_path_or_error(
    actor: ActorRuntimeState,
    declaration: TurnDeclaration,
) -> list[tuple[float, float, float]]:
    if not isinstance(declaration.movement_path, list):
        raise_turn_declaration_error(
            actor=actor,
            code="invalid_movement_path",
            field="movement_path",
            message="movement_path must be a list of 3D waypoints.",
        )
    if not declaration.movement_path:
        return []

    normalized: list[tuple[float, float, float]] = []
    for idx, waypoint in enumerate(declaration.movement_path):
        if not isinstance(waypoint, (tuple, list)) or len(waypoint) != 3:
            raise_turn_declaration_error(
                actor=actor,
                code="invalid_waypoint",
                field=f"movement_path[{idx}]",
                message="Each movement waypoint must be a 3-value coordinate.",
            )
        try:
            normalized.append((float(waypoint[0]), float(waypoint[1]), float(waypoint[2])))
        except (TypeError, ValueError):
            raise_turn_declaration_error(
                actor=actor,
                code="invalid_waypoint",
                field=f"movement_path[{idx}]",
                message="Each movement waypoint value must be numeric.",
            )

    if distance_chebyshev(actor.position, normalized[0]) > 1e-6:
        raise_turn_declaration_error(
            actor=actor,
            code="movement_path_start_mismatch",
            field="movement_path[0]",
            message="movement_path must start at the actor's current position.",
            details={"current_position": actor.position},
        )
    return normalized


def validate_declared_ready_or_error(
    actor: ActorRuntimeState,
    declaration: TurnDeclaration,
) -> ReadyDeclaration | None:
    ready = declaration.ready
    if ready is None:
        return None
    if not isinstance(ready, ReadyDeclaration):
        raise_turn_declaration_error(
            actor=actor,
            code="invalid_ready_declaration",
            field="ready",
            message="ready must be a ReadyDeclaration object.",
        )

    action_name = declaration.action.action_name if declaration.action is not None else None
    if str(action_name or "").strip().lower() != "ready":
        raise_turn_declaration_error(
            actor=actor,
            code="ready_metadata_without_ready_action",
            field="ready",
            message="ready metadata is only legal when action.action_name is 'ready'.",
        )

    trigger = str(ready.trigger or "").strip()
    if not trigger:
        raise_turn_declaration_error(
            actor=actor,
            code="missing_ready_trigger",
            field="ready.trigger",
            message="Ready declaration trigger is required.",
        )
    response_name = str(ready.response_action_name or "").strip()
    if not response_name:
        raise_turn_declaration_error(
            actor=actor,
            code="missing_ready_response",
            field="ready.response_action_name",
            message="Ready declaration response_action_name is required.",
        )

    response_action = next((a for a in actor.actions if a.name == response_name), None)
    if response_action is None:
        raise_turn_declaration_error(
            actor=actor,
            code="unknown_ready_response",
            field="ready.response_action_name",
            message=f"Ready response action '{response_name}' does not exist for actor.",
        )
    if response_action.name == "ready" or response_action.action_cost not in {"action", "none"}:
        raise_turn_declaration_error(
            actor=actor,
            code="illegal_ready_response",
            field="ready.response_action_name",
            message="Ready response must be a non-ready action that uses action or no cost.",
            details={"action_cost": response_action.action_cost},
        )
    return ready


def apply_declared_reaction_policy_or_error(
    actor: ActorRuntimeState,
    declaration: TurnDeclaration,
    *,
    supported_modes: set[str],
) -> str:
    policy = declaration.reaction_policy
    mode = "auto"
    if policy is not None:
        mode = str(policy.mode or "auto").strip().lower()
    if mode not in supported_modes:
        raise_turn_declaration_error(
            actor=actor,
            code="invalid_reaction_policy",
            field="reaction_policy.mode",
            message=f"Unsupported reaction policy mode: {mode}",
            details={"supported_modes": sorted(supported_modes)},
        )
    if mode == "none":
        actor.reaction_available = False
    return mode
