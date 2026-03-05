from __future__ import annotations

import logging
from typing import Any

from dnd_sim.strategy_api import TurnDeclaration

logger = logging.getLogger(__name__)


def build_declaration_validation_trace(
    *,
    actor_id: str,
    team: str,
    strategy_name: str | None,
    round_number: int | None,
    turn_token: str | None,
    declaration: TurnDeclaration | None,
    validation_state: str,
    code: str | None = None,
    field: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "round": round_number,
        "turn_token": turn_token,
        "strategy": strategy_name,
        "actor_id": actor_id,
        "team": team,
        "validation_state": validation_state,
        "declared_action": None,
        "declared_bonus_action": None,
        "ready_declared": False,
        "movement_path": [],
    }

    if declaration is not None:
        payload["declared_action"] = (
            declaration.action.action_name if declaration.action is not None else None
        )
        payload["declared_bonus_action"] = (
            declaration.bonus_action.action_name if declaration.bonus_action is not None else None
        )
        payload["ready_declared"] = declaration.ready is not None
        payload["movement_path"] = [
            [float(waypoint[0]), float(waypoint[1]), float(waypoint[2])]
            for waypoint in declaration.movement_path
        ]

    if code is not None:
        payload["error_code"] = code
    if field is not None:
        payload["field"] = field
    if message is not None:
        payload["message"] = message

    return payload
