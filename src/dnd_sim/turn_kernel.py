"""State boundary shared by batch and interactive declared-turn resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dnd_sim.models import ActorRuntimeState
from dnd_sim.rules_2014 import CombatTimingEngine
from dnd_sim.spatial import AABB


@dataclass(slots=True)
class DeclaredTurnRuntimeState:
    """All mutable runtime data a declared turn is allowed to change.

    The container is intentionally an in-memory domain object. A separate,
    versioned codec is required before it can cross the interactive session
    persistence boundary.
    """

    actors: dict[str, ActorRuntimeState]
    damage_dealt: dict[str, int]
    damage_taken: dict[str, int]
    threat_scores: dict[str, int]
    resources_spent: dict[str, dict[str, int]]
    active_hazards: list[dict[str, Any]]
    telemetry: list[dict[str, Any]]
    obstacles: list[AABB]
    light_level: str
    round_number: int | None
    turn_token: str | None
    rule_trace: list[dict[str, Any]]
    timing_engine: CombatTimingEngine
