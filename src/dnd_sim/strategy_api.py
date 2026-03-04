from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from dnd_sim.spatial import check_cover, distance_chebyshev, move_towards


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

    def on_round_start(self, state: BattleStateView) -> None: ...


class BaseStrategy:
    """Declaration-only baseline behavior."""

    def declare_turn(self, actor: ActorView, state: BattleStateView) -> TurnDeclaration | None:
        available = state.metadata.get("available_actions", {}).get(actor.actor_id, [])
        available_names = [str(name) for name in available if str(name)]
        if not available_names:
            return TurnDeclaration(rationale={"reason": "no_available_actions"})

        action_name = "basic" if "basic" in available_names else available_names[0]
        catalog = state.metadata.get("action_catalog", {}).get(actor.actor_id, [])
        action_info = next(
            (
                row
                for row in catalog
                if isinstance(row, dict) and str(row.get("name", "")) == action_name
            ),
            None,
        )
        if action_info is None:
            return TurnDeclaration(rationale={"reason": "unknown_action", "action_name": action_name})

        mode = str(action_info.get("target_mode", "single_enemy"))
        if mode == "self":
            return TurnDeclaration(
                action=DeclaredAction(
                    action_name=action_name,
                    targets=[TargetRef(actor_id=actor.actor_id)],
                )
            )

        enemies = [view for view in state.actors.values() if view.team != actor.team and view.hp > 0]
        allies = [view for view in state.actors.values() if view.team == actor.team and view.hp > 0]
        everyone = [view for view in state.actors.values() if view.hp > 0]

        explicit_modes = {
            "single_enemy",
            "single_ally",
            "n_enemies",
            "n_allies",
            "random_enemy",
            "random_ally",
        }

        if mode == "all_enemies":
            pool = enemies
        elif mode == "all_allies":
            pool = allies
        elif mode == "all_creatures":
            pool = everyone
        elif mode in {"single_ally", "n_allies", "random_ally"}:
            pool = allies
        else:
            pool = enemies

        if not pool:
            return TurnDeclaration(rationale={"reason": "no_targets", "action_name": action_name})

        def _target_sort_key(entry: ActorView) -> tuple[float, float]:
            hp_ratio = float(entry.hp) / float(max(entry.max_hp, 1))
            return (hp_ratio, float(entry.hp))

        sorted_targets = sorted(pool, key=_target_sort_key)
        primary = sorted_targets[0]

        def _action_range_ft() -> float | None:
            if mode == "self":
                return None
            action_type = str(action_info.get("action_type", ""))
            if isinstance(action_info.get("range_ft"), (int, float)):
                return float(action_info["range_ft"])
            if isinstance(action_info.get("range_normal_ft"), (int, float)):
                return float(action_info["range_normal_ft"])
            if isinstance(action_info.get("reach_ft"), (int, float)):
                return float(action_info["reach_ft"])
            if action_type == "attack":
                return 5.0
            if action_type == "utility":
                return 30.0
            return 60.0

        range_ft = _action_range_ft()
        movement_path: list[tuple[float, float, float]] = []
        if range_ft is not None:
            distance = distance_chebyshev(actor.position, primary.position)
            if distance > range_ft:
                required = distance - range_ft
                movement_budget = float(actor.movement_remaining)
                if required > movement_budget:
                    return TurnDeclaration(
                        rationale={
                            "reason": "target_out_of_reach",
                            "action_name": action_name,
                            "target": primary.actor_id,
                        }
                    )
                destination = move_towards(actor.position, primary.position, required)
                obstacles = state.metadata.get("obstacles", [])
                if isinstance(obstacles, list) and obstacles:
                    if check_cover(destination, primary.position, obstacles) == "TOTAL":
                        return TurnDeclaration(
                            rationale={
                                "reason": "target_blocked",
                                "action_name": action_name,
                                "target": primary.actor_id,
                            }
                        )
                movement_path = [
                    (float(actor.position[0]), float(actor.position[1]), float(actor.position[2])),
                    (float(destination[0]), float(destination[1]), float(destination[2])),
                ]

        targets: list[TargetRef]
        if mode == "all_enemies":
            targets = [TargetRef(actor_id=view.actor_id) for view in enemies]
        elif mode == "all_allies":
            targets = [TargetRef(actor_id=view.actor_id) for view in allies]
        elif mode == "all_creatures":
            targets = [TargetRef(actor_id=view.actor_id) for view in everyone]
        elif mode in {"n_enemies", "n_allies"}:
            max_targets = int(action_info.get("max_targets") or 1)
            targets = [TargetRef(actor_id=view.actor_id) for view in sorted_targets[:max_targets]]
        elif mode in explicit_modes:
            targets = [TargetRef(actor_id=primary.actor_id)]
        else:
            targets = [TargetRef(actor_id=primary.actor_id)]

        return TurnDeclaration(
            movement_path=movement_path,
            action=DeclaredAction(action_name=action_name, targets=targets),
        )

    def on_round_start(self, state: BattleStateView) -> None:
        return None


def validate_strategy_instance(strategy: Any) -> None:
    required = ["declare_turn", "on_round_start"]
    missing = [name for name in required if not callable(getattr(strategy, name, None))]
    if missing:
        joined = ", ".join(sorted(missing))
        raise ValueError(
            "Strategy instance missing required methods: "
            f"{joined}. Strategies must define callable declare_turn(actor, state) "
            "and on_round_start(state)."
        )
