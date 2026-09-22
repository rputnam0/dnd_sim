"""State boundary shared by batch and interactive declared-turn resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from dnd_sim.models import ActorRuntimeState
from dnd_sim.rules_2014 import CombatTimingEngine
from dnd_sim.spatial import AABB
from dnd_sim.strategy_api import ActorView, BattleStateView, TurnDeclaration


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


@dataclass(slots=True)
class CombatTurnContext:
    """Mutable encounter references required to resolve one actor's full turn."""

    actors: dict[str, ActorRuntimeState]
    initiative_order: list[str]
    round_number: int
    damage_dealt: dict[str, int]
    damage_taken: dict[str, int]
    threat_scores: dict[str, int]
    resources_spent: dict[str, dict[str, int]]
    active_hazards: list[dict[str, Any]]
    telemetry: list[dict[str, Any]]
    rule_trace: list[dict[str, Any]]
    obstacles: list[AABB]
    light_level: str
    burst_round_threshold: int
    strategy_overrides: dict[str, Any]
    timing_engine: CombatTimingEngine
    party_defeat_rule: str = "all_unconscious_or_dead"
    enemy_defeat_rule: str = "all_dead"


@dataclass(frozen=True, slots=True)
class CombatTurnDecision:
    """Strategy-independent decision supplied at the prompted turn boundary."""

    strategy_name: str
    declaration: TurnDeclaration | None


@dataclass(frozen=True, slots=True)
class CombatTurnPrompt:
    """Decision boundary reached after deterministic turn-start automation."""

    actor_id: str
    round_number: int
    turn_token: str
    actor_view: ActorView
    state_view: BattleStateView


CombatTurnDecisionProvider = Callable[
    [ActorView, BattleStateView],
    CombatTurnDecision,
]


@dataclass(frozen=True, slots=True)
class CombatTurnResult:
    """Stable summary of the synchronous path taken for one actor turn."""

    actor_id: str
    round_number: int
    turn_token: str
    status: Literal[
        "dead",
        "death_save",
        "start_hazard_defeat",
        "combat_ended",
        "readied_action_defeat",
        "incapacitated",
        "forced_dodge",
        "no_declaration",
        "resolved",
    ]
    strategy_name: str | None = None

    @property
    def combat_ended(self) -> bool:
        return self.status == "combat_ended"
