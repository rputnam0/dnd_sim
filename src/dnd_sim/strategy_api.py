from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class ActionIntent:
    action_name: str | None
    action_type: str = "attack"
    action_cost: str = "action"
    rationale: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TargetRef:
    actor_id: str


@dataclass(slots=True)
class ResourceSpend:
    amounts: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class DeclaredAction:
    action_name: str | None
    targets: list[TargetRef] = field(default_factory=list)
    resource_spend: ResourceSpend = field(default_factory=ResourceSpend)
    spell_slot_level: int | None = None
    rationale: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReactionPolicy:
    mode: str = "auto"
    rationale: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReadyDeclaration:
    trigger: str
    response_action_name: str
    rationale: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TurnDeclaration:
    movement_path: list[tuple[float, float, float]] = field(default_factory=list)
    action: DeclaredAction | None = None
    bonus_action: DeclaredAction | None = None
    reaction_policy: ReactionPolicy = field(default_factory=ReactionPolicy)
    ready: ReadyDeclaration | None = None
    rationale: dict[str, Any] = field(default_factory=dict)


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
    position: tuple[float, float, float]
    speed_ft: int
    movement_remaining: float
    traits: dict[str, dict[str, Any]]
    concentrating: bool = False


@dataclass(slots=True)
class BattleStateView:
    round_number: int
    actors: dict[str, ActorView]
    actor_order: list[str]
    metadata: dict[str, Any]


class StrategyModule(Protocol):
    def declare_turn(self, actor: ActorView, state: BattleStateView) -> TurnDeclaration | None: ...

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

    def declare_turn(self, actor: ActorView, state: BattleStateView) -> TurnDeclaration | None:
        return None

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
    if not callable(getattr(strategy, "on_round_start", None)):
        raise ValueError("Strategy instance missing required methods: on_round_start")

    has_declare_turn = callable(getattr(strategy, "declare_turn", None))
    if has_declare_turn:
        return

    legacy_required = ["choose_action", "choose_targets", "decide_resource_spend"]
    missing = [name for name in legacy_required if not callable(getattr(strategy, name, None))]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(
            "Strategy instance must implement either declare_turn(...) or legacy methods: "
            f"{joined}"
        )
