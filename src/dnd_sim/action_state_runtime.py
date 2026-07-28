from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import logging

from dnd_sim.models import ActionDefinition

_EXPLICIT_STATE_KEY_PREFIX = "action_state_key:"

logger = logging.getLogger(__name__)


def _explicit_action_state_key(action: ActionDefinition) -> str | None:
    configured = sorted(
        value
        for raw_tag in action.tags
        if str(raw_tag).strip().lower().startswith(_EXPLICIT_STATE_KEY_PREFIX)
        if (value := str(raw_tag).strip().split(":", 1)[1].strip())
    )
    return f"action_state:{configured[0]}" if configured else None


def _action_fingerprint(action: ActionDefinition) -> str:
    payload = json.dumps(
        asdict(action),
        allow_nan=False,
        default=repr,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def action_variant_state_key(
    actions: list[ActionDefinition],
    action: ActionDefinition,
    *,
    action_index: int | None = None,
) -> str:
    """Return a stable usage/recharge key while preserving legacy unique-name keys."""

    explicit = _explicit_action_state_key(action)
    if explicit is not None:
        return explicit

    same_name = [
        (index, candidate)
        for index, candidate in enumerate(actions)
        if candidate.name == action.name
    ]
    if len(same_name) <= 1:
        return action.name

    if action_index is None or not (
        0 <= action_index < len(actions) and actions[action_index] is action
    ):
        action_index = next(
            (index for index, candidate in same_name if candidate is action),
            same_name[0][0],
        )
    fingerprint = _action_fingerprint(action)
    ordinal = sum(
        1
        for index, candidate in same_name
        if index < action_index and _action_fingerprint(candidate) == fingerprint
    )
    return f"{action.name}::variant:{fingerprint}:{ordinal}"


def actions_by_variant_state_key(
    actions: list[ActionDefinition],
) -> dict[str, ActionDefinition]:
    """Resolve persisted variant state keys back to their action definitions."""

    resolved: dict[str, ActionDefinition] = {}
    for index, action in enumerate(actions):
        resolved.setdefault(
            action_variant_state_key(actions, action, action_index=index),
            action,
        )
    return resolved
