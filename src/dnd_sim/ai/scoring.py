from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _resource_cost(action: Mapping[str, Any]) -> dict[str, int]:
    raw = action.get("resource_cost")
    if not isinstance(raw, Mapping):
        return {}
    return {str(key): int(value) for key, value in raw.items()}


def _can_pay(resources: Mapping[str, int], cost: Mapping[str, int]) -> bool:
    for key, amount in cost.items():
        if int(resources.get(key, 0)) < int(amount):
            return False
    return True


def candidate_rejection_reason_for_action(
    action: Mapping[str, Any],
    *,
    resources: Mapping[str, int],
    used_count: int,
) -> str:
    action_cost = str(action.get("action_cost", "")).strip().lower()
    if action_cost in {"legendary", "lair", "reaction"}:
        return "unsupported_action_cost"

    max_uses = action.get("max_uses")
    if max_uses is not None and used_count >= int(max_uses):
        return "max_uses_exhausted"

    if not bool(action.get("recharge_ready", True)):
        return "recharge_not_ready"

    if not _can_pay(resources, _resource_cost(action)):
        return "insufficient_resources"

    return "not_viable"


def _score_components(candidate: Mapping[str, Any]) -> dict[str, float]:
    return {
        "base_score": float(candidate.get("base_score", 0.0)),
        "objective_bonus": float(candidate.get("objective_bonus", 0.0)),
        "lookahead_bonus": float(candidate.get("lookahead_bonus", 0.0)),
        "total_score": float(candidate.get("total_score", 0.0)),
    }


def build_candidate_trace_rows(
    *,
    ranked_candidates: Sequence[Mapping[str, Any]],
    excluded_candidates: Sequence[Mapping[str, Any]],
    selected_action: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for index, candidate in enumerate(ranked_candidates, start=1):
        action_name = str(candidate.get("name", "")).strip()
        if not action_name:
            continue
        is_selected = selected_action is not None and action_name == selected_action
        rows.append(
            {
                "action_name": action_name,
                "candidate_state": ("selected" if is_selected else "rejected"),
                "rejection_reason": (None if is_selected else "not_selected"),
                "rank": index,
                "cost": int(candidate.get("cost", 0)),
                "score_components": _score_components(candidate),
            }
        )

    for candidate in excluded_candidates:
        action_name = str(candidate.get("name", "")).strip()
        if not action_name:
            continue
        rows.append(
            {
                "action_name": action_name,
                "candidate_state": "excluded",
                "rejection_reason": str(candidate.get("rejection_reason", "not_viable")),
                "rank": None,
                "cost": int(candidate.get("cost", 0)),
                "score_components": {
                    "base_score": 0.0,
                    "objective_bonus": 0.0,
                    "lookahead_bonus": 0.0,
                    "total_score": 0.0,
                },
            }
        )

    return rows
