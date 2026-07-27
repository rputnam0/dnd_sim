from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Literal, Protocol

from dnd_sim.models import ZeroHPIntent
from dnd_sim.spatial import check_cover, distance_chebyshev, move_towards

logger = logging.getLogger(__name__)
ReadyTrigger = Literal["enemy_turn_start", "enemy_enters_reach"]
ReactionChoice = Literal["use", "pass"]
ReactionKind = Literal[
    "opportunity_attack",
    "readied_response",
    "shield",
    "counterspell",
    "uncanny_dodge",
    "triggered_action",
    "trait",
]
_REMOVED_LEGACY_STRATEGY_METHODS = (
    "choose_action",
    "choose_targets",
    "decide_resource_spend",
)


@dataclass(slots=True)
class TargetRef:
    actor_id: str


@dataclass(slots=True)
class ResourceSpend:
    amounts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReactionOptionView:
    option_id: str
    action_name: str | None
    fixed_target_ids: tuple[str, ...] = ()
    legal_target_ids: tuple[str, ...] = ()
    legal_spell_slot_levels: tuple[int, ...] = ()
    legal_zero_hp_intents: tuple[ZeroHPIntent, ...] = ("normal",)
    resource_cost: tuple[tuple[str, int], ...] = ()
    attack_bonus: int | None = None
    damage_expression: str | None = None
    damage_type: str | None = None
    reach_ft: float | None = None


@dataclass(frozen=True, slots=True)
class ReactionTriggerView:
    kind: ReactionKind
    source_actor_id: str | None = None
    target_actor_id: str | None = None
    action_name: str | None = None
    spell_level: int | None = None
    attack_total: int | None = None
    movement_point: tuple[float, float, float] | None = None
    distance_ft: float | None = None


@dataclass(frozen=True, slots=True)
class ReactionWindowView:
    window_id: str
    reactor_id: str
    round_number: int | None
    turn_token: str | None
    trigger: ReactionTriggerView
    options: tuple[ReactionOptionView, ...]


@dataclass(slots=True)
class ReactionDecision:
    window_id: str
    choice: ReactionChoice
    option_id: str | None = None
    targets: list[TargetRef] = field(default_factory=list)
    resource_spend: ResourceSpend = field(default_factory=ResourceSpend)
    spell_slot_level: int | None = None
    zero_hp_intent: ZeroHPIntent = "normal"
    rationale: dict[str, Any] = field(default_factory=dict)


class ReactionDecisionProvider(Protocol):
    def __call__(self, window: ReactionWindowView) -> ReactionDecision: ...


@dataclass(slots=True)
class DeclaredAction:
    action_name: str | None
    targets: list[TargetRef] = field(default_factory=list)
    resource_spend: ResourceSpend = field(default_factory=ResourceSpend)
    spell_slot_level: int | None = None
    zero_hp_intent: ZeroHPIntent = "normal"
    rationale: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReactionPolicy:
    mode: Literal["auto", "none"] = "auto"
    rationale: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReadyDeclaration:
    trigger: ReadyTrigger
    response_action_name: str
    rationale: dict[str, Any] = field(default_factory=dict)
    zero_hp_intent: ZeroHPIntent = "normal"


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
    hidden: bool = False
    detected_by: set[str] = field(default_factory=set)
    surprised: bool = False
    dead: bool = False
    stable: bool = False
    uses_death_saves: bool | None = None
    death_successes: int = 0
    death_failures: int = 0
    stable_recovery_hours_remaining: int | None = None
    creature_type: str = "unknown"
    reaction_available: bool = True
    readied_action_name: str | None = None
    readied_trigger: str | None = None
    readied_zero_hp_intent: ZeroHPIntent = "normal"
    readied_reaction_reserved: bool = False
    readied_spell_held: bool = False


@dataclass(slots=True)
class BattleStateView:
    round_number: int
    actors: dict[str, ActorView]
    actor_order: list[str]
    metadata: dict[str, Any]


class StrategyModule(Protocol):
    def declare_turn(self, actor: ActorView, state: BattleStateView) -> TurnDeclaration | None: ...

    def decide_reaction(
        self,
        actor: ActorView,
        window: ReactionWindowView,
        state: BattleStateView,
    ) -> ReactionDecision: ...

    def on_round_start(self, state: BattleStateView) -> None: ...


class BaseStrategy:
    """Declaration-only baseline behavior."""

    def decide_reaction(
        self,
        actor: ActorView,
        window: ReactionWindowView,
        state: BattleStateView,
    ) -> ReactionDecision:
        del actor, state
        if not window.options:
            return ReactionDecision(
                window_id=window.window_id,
                choice="pass",
                rationale={"reason": "no_reaction_options"},
            )
        option = max(
            window.options,
            key=lambda value: (
                value.attack_bonus if value.attack_bonus is not None else -999,
                value.reach_ft if value.reach_ft is not None else 0.0,
            ),
        )
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=option.option_id,
            rationale={"reason": "default_reaction_priority"},
        )

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
            return TurnDeclaration(
                rationale={"reason": "unknown_action", "action_name": action_name}
            )

        mode = str(action_info.get("target_mode", "single_enemy"))
        if mode == "self":
            return TurnDeclaration(
                action=DeclaredAction(
                    action_name=action_name,
                    targets=[TargetRef(actor_id=actor.actor_id)],
                )
            )

        stabilize_effects = [
            effect
            for key in ("effects", "mechanics")
            for effect in action_info.get(key, [])
            if isinstance(effect, dict)
            and str(effect.get("effect_type", "")).strip().lower() == "stabilize"
        ]

        def _eligible_stabilize_target(view: ActorView) -> bool:
            if view.dead or view.hp != 0 or view.stable or view.uses_death_saves is False:
                return False
            creature_type = view.creature_type.strip().lower()
            return any(
                creature_type
                not in {
                    str(entry).strip().lower()
                    for entry in effect.get("excluded_creature_types", [])
                }
                for effect in stabilize_effects
            )

        if stabilize_effects:
            everyone = [view for view in state.actors.values() if _eligible_stabilize_target(view)]
        else:
            everyone = [view for view in state.actors.values() if view.hp > 0 and not view.dead]
        enemies = [view for view in everyone if view.team != actor.team]
        allies = [view for view in everyone if view.team == actor.team]

        explicit_modes = {
            "single_enemy",
            "single_ally",
            "single_creature",
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
        elif mode == "single_creature":
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
    from dnd_sim.action_legality import (
        validate_strategy_instance as _validate_strategy_instance_impl,
    )

    _validate_strategy_instance_impl(strategy)
    legacy_methods = sorted(
        name for name in _REMOVED_LEGACY_STRATEGY_METHODS if callable(getattr(strategy, name, None))
    )
    if legacy_methods:
        joined = ", ".join(legacy_methods)
        raise ValueError(
            "Strategy instance defines removed legacy methods: "
            f"{joined}. Use declare_turn(actor, state) as the canonical turn interface."
        )
