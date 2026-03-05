from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from dnd_sim.models import ActionDefinition, ActorRuntimeState

logger = logging.getLogger(__name__)

ActionHandler = Callable[[ActionDefinition, list[ActorRuntimeState]], None]


@dataclass(slots=True)
class ActionResolutionHandlers:
    attack: ActionHandler
    save: ActionHandler
    utility: ActionHandler
    grapple_shove: ActionHandler
    item: ActionHandler | None = None
    fallback: ActionHandler | None = None


@dataclass(slots=True)
class ActionResolutionResult:
    action_name: str
    action_type: str
    attempted_target_ids: list[str]
    resolved_target_ids: list[str]
    invalid_target_ids: list[str]
    executed: bool
    dispatch_path: str
    skipped_reason: str | None = None


def _target_id(value: ActorRuntimeState) -> str:
    return str(getattr(value, "actor_id", "") or "").strip()


def _canonicalize_targets(
    *,
    targets: list[ActorRuntimeState],
    actors: dict[str, ActorRuntimeState],
) -> tuple[list[str], list[ActorRuntimeState], list[str]]:
    attempted: list[str] = []
    resolved: list[ActorRuntimeState] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for target in targets:
        actor_id = _target_id(target)
        attempted.append(actor_id or "<unknown>")
        if not actor_id:
            invalid.append("<unknown>")
            continue
        if actor_id in seen:
            continue
        canonical = actors.get(actor_id)
        if canonical is None:
            invalid.append(actor_id)
            continue
        resolved.append(canonical)
        seen.add(actor_id)
    return attempted, resolved, invalid


def _dispatch_handler(
    *,
    action: ActionDefinition,
    handlers: ActionResolutionHandlers,
) -> tuple[str, ActionHandler | None]:
    action_type = str(action.action_type or "").strip().lower()
    if action_type == "attack":
        return "attack", handlers.attack
    if action_type == "save":
        return "save", handlers.save
    if action_type in {"grapple", "shove"}:
        return "grapple_shove", handlers.grapple_shove
    if action_type in {"utility", "buff"}:
        return "utility", handlers.utility
    if action_type == "item":
        if handlers.item is not None:
            return "item", handlers.item
        return "utility", handlers.utility
    if handlers.fallback is not None:
        return "fallback", handlers.fallback
    return "unsupported", None


def execute_action_pipeline(
    *,
    action: ActionDefinition,
    targets: list[ActorRuntimeState],
    actors: dict[str, ActorRuntimeState],
    handlers: ActionResolutionHandlers,
) -> ActionResolutionResult:
    attempted_target_ids, resolved_targets, invalid_target_ids = _canonicalize_targets(
        targets=targets,
        actors=actors,
    )
    if not resolved_targets:
        return ActionResolutionResult(
            action_name=action.name,
            action_type=action.action_type,
            attempted_target_ids=attempted_target_ids,
            resolved_target_ids=[],
            invalid_target_ids=invalid_target_ids,
            executed=False,
            dispatch_path="skipped",
            skipped_reason="no_valid_targets",
        )

    dispatch_path, handler = _dispatch_handler(action=action, handlers=handlers)
    if handler is None:
        return ActionResolutionResult(
            action_name=action.name,
            action_type=action.action_type,
            attempted_target_ids=attempted_target_ids,
            resolved_target_ids=[target.actor_id for target in resolved_targets],
            invalid_target_ids=invalid_target_ids,
            executed=False,
            dispatch_path=dispatch_path,
            skipped_reason="unsupported_action_type",
        )

    if invalid_target_ids:
        logger.debug(
            "Action %s dropped invalid targets: %s",
            action.name,
            ",".join(invalid_target_ids),
        )
    handler(action, resolved_targets)
    return ActionResolutionResult(
        action_name=action.name,
        action_type=action.action_type,
        attempted_target_ids=attempted_target_ids,
        resolved_target_ids=[target.actor_id for target in resolved_targets],
        invalid_target_ids=invalid_target_ids,
        executed=True,
        dispatch_path=dispatch_path,
    )
