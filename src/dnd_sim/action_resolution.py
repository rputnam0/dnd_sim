from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_action_selection_trace(
    *,
    actor_id: str,
    team: str,
    strategy_name: str | None,
    round_number: int | None,
    turn_token: str | None,
    field_prefix: str,
    action_name: str | None,
    requested_targets: list[str],
    resolved_targets: list[str],
    selection_state: str,
    error_code: str | None = None,
    field: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "round": round_number,
        "turn_token": turn_token,
        "strategy": strategy_name,
        "actor_id": actor_id,
        "team": team,
        "field_prefix": field_prefix,
        "action_name": action_name,
        "requested_targets": list(requested_targets),
        "resolved_targets": list(resolved_targets),
        "selection_state": selection_state,
    }
    if error_code is not None:
        payload["error_code"] = error_code
    if field is not None:
        payload["field"] = field
    if message is not None:
        payload["message"] = message
    return payload


def build_action_resolution_trace(
    *,
    actor_id: str,
    team: str,
    strategy_name: str | None,
    round_number: int | None,
    turn_token: str | None,
    field_prefix: str,
    action_name: str | None,
    resolved_targets: list[str],
    resolution_state: str,
) -> dict[str, Any]:
    return {
        "round": round_number,
        "turn_token": turn_token,
        "strategy": strategy_name,
        "actor_id": actor_id,
        "team": team,
        "field_prefix": field_prefix,
        "action_name": action_name,
        "resolved_targets": list(resolved_targets),
        "resolved_target_count": len(resolved_targets),
        "resolution_state": resolution_state,
    }


def build_action_outcome_trace(
    *,
    actor_id: str,
    team: str,
    strategy_name: str | None,
    round_number: int | None,
    turn_token: str | None,
    field_prefix: str,
    action_name: str | None,
    resolved_targets: list[str],
    outcome_state: str,
    damage_delta: int,
    defeated_targets: list[str],
    target_hp_after: dict[str, int],
) -> dict[str, Any]:
    return {
        "round": round_number,
        "turn_token": turn_token,
        "strategy": strategy_name,
        "actor_id": actor_id,
        "team": team,
        "field_prefix": field_prefix,
        "action_name": action_name,
        "resolved_targets": list(resolved_targets),
        "outcome_state": outcome_state,
        "damage_delta": int(damage_delta),
        "defeated_targets": list(defeated_targets),
        "target_hp_after": dict(target_hp_after),
    }
