from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import logging
import random
import re

from dnd_sim.models import ActionDefinition, ActorRuntimeState

_EXPLICIT_STATE_KEY_PREFIX = "action_state_key:"

logger = logging.getLogger(__name__)


def parse_recharge_threshold(spec: str) -> int | None:
    value = str(spec).strip().strip("()").replace("–", "-")
    match = re.fullmatch(
        r"(?:recharge\s+)?([1-6])(?:\s*-\s*([1-6]))?",
        value,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    low = int(match.group(1))
    high = int(match.group(2) or match.group(1))
    return low if low <= high else None


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


def roll_recharge_for_actor(rng: random.Random, actor: ActorRuntimeState) -> None:
    if not actor.recharge_ready:
        return
    by_name = {action.name: action for action in actor.actions}
    by_state_key = actions_by_variant_state_key(actor.actions)
    for state_key, is_ready in list(actor.recharge_ready.items()):
        if is_ready:
            continue
        action = by_state_key.get(state_key) or by_name.get(state_key)
        if not action or not action.recharge:
            actor.recharge_ready[state_key] = True
            continue
        threshold = parse_recharge_threshold(action.recharge)
        if threshold is None or rng.randint(1, 6) >= threshold:
            actor.recharge_ready[state_key] = True
