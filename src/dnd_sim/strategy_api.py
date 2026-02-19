from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class ActionIntent:
    action_name: str | None
    action_type: str = "attack"
    action_cost: str = "action"


@dataclass(slots=True)
class TargetRef:
    actor_id: str


@dataclass(slots=True)
class ResourceSpend:
    amounts: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class ActorView:
    actor_id: str
    team: str
    hp: int
    max_hp: int
    ac: int
    save_mods: dict[str, int]
    resources: dict[str, int]
    conditions: set[str]


@dataclass(slots=True)
class BattleStateView:
    round_number: int
    actors: dict[str, ActorView]
    actor_order: list[str]
    metadata: dict[str, Any]


class StrategyModule(Protocol):
    def choose_action(self, actor: ActorView, state: BattleStateView) -> ActionIntent: ...

    def choose_targets(
        self,
        actor: ActorView,
        intent: ActionIntent,
        state: BattleStateView,
    ) -> list[TargetRef]: ...

    def decide_resource_spend(
        self,
        actor: ActorView,
        intent: ActionIntent,
        state: BattleStateView,
    ) -> ResourceSpend: ...

    def on_round_start(self, state: BattleStateView) -> None: ...


class BaseStrategy:
    """Default baseline behavior: first available action + focus lowest HP enemy."""

    def choose_action(self, actor: ActorView, state: BattleStateView) -> ActionIntent:
        return ActionIntent(action_name=None)

    def choose_targets(
        self,
        actor: ActorView,
        intent: ActionIntent,
        state: BattleStateView,
    ) -> list[TargetRef]:
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]
        if not enemies:
            return []
        target = min(enemies, key=lambda entry: (entry.hp, entry.max_hp))
        return [TargetRef(actor_id=target.actor_id)]

    def decide_resource_spend(
        self,
        actor: ActorView,
        intent: ActionIntent,
        state: BattleStateView,
    ) -> ResourceSpend:
        return ResourceSpend()

    def on_round_start(self, state: BattleStateView) -> None:
        return None


def validate_strategy_instance(strategy: Any) -> None:
    required = ["choose_action", "choose_targets", "decide_resource_spend", "on_round_start"]
    missing = [name for name in required if not callable(getattr(strategy, name, None))]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"Strategy instance missing required methods: {joined}")
