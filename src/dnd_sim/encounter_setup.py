"""Explicit battlefield placement shared by seeded batch encounters."""

from __future__ import annotations

import math
from typing import Any


def starting_positions(
    battlefield: dict[str, Any], *, actor_ids: set[str]
) -> dict[str, tuple[float, float, float]]:
    """Validate optional feet-space coordinates before any random draws occur."""
    raw = battlefield.get("starting_positions", {})
    if not isinstance(raw, dict):
        raise ValueError("battlefield.starting_positions must be an object")
    result = {}
    for actor_id, point in raw.items():
        path = f"battlefield.starting_positions.{actor_id}"
        if actor_id not in actor_ids:
            raise ValueError(f"{path}: unknown actor")
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            raise ValueError(f"{path}: expected three finite coordinates in feet")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in point
        ):
            raise ValueError(f"{path}: expected three finite coordinates in feet")
        result[actor_id] = tuple(float(value) for value in point)
    return result
