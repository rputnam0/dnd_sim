from __future__ import annotations

import logging
import random
from dataclasses import replace
from typing import Any, Callable

from dnd_sim.models import (
    ActionDefinition,
    ActorRuntimeState,
    FeatureHookRegistration,
    SpellCastRequest,
)
from dnd_sim.spatial import AABB, distance_chebyshev
from dnd_sim.rules_2014 import AttackResolvedEvent, sentinel_speed_reduction_applies_on_hit
from dnd_sim.strategy_api import (
    BattleStateView,
    ReactionDecision,
    ReactionDecisionProvider,
    ReactionOptionView,
    ReactionTriggerView,
    ReactionWindowView,
    TargetRef,
    ZeroHPIntent,
)

logger = logging.getLogger(__name__)


class ReactionDecisionValidationError(ValueError):
    def __init__(
        self,
        *,
        code: str,
        field: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.field = field
        self.message = message
        self.details = dict(details or {})
        super().__init__(f"{code} [{field}] {message}")


def _reaction_decision_error(
    *,
    code: str,
    field: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    raise ReactionDecisionValidationError(
        code=code,
        field=field,
        message=message,
        details=details,
    )


def _position_token(position: tuple[float, float, float]) -> str:
    return ",".join(f"{coordinate:g}" for coordinate in position)


def _opportunity_option_id(
    *,
    reactor_id: str,
    action: ActionDefinition,
    option_index: int,
) -> str:
    action_key = str(action.attack_profile_id or action.name).strip() or "attack"
    return f"{reactor_id}:opportunity_attack:{option_index}:{action_key}"


def build_opportunity_attack_window(
    *,
    reactor: ActorRuntimeState,
    mover: ActorRuntimeState,
    candidates: list[tuple[ActionDefinition, float]],
    trigger_point: tuple[float, float, float],
    trigger_distance: float,
    round_number: int | None,
    turn_token: str | None,
    window_ordinal: int,
    movement_source: str,
    mover_disengaged: bool,
    on_hit_effects: tuple[str, ...] = (),
) -> ReactionWindowView:
    options: list[ReactionOptionView] = []
    for option_index, (action, reach_ft) in enumerate(candidates):
        legal_zero_hp_intents: tuple[ZeroHPIntent, ...] = ("normal",)
        if action.attack_delivery in {"melee_weapon_attack", "melee_spell_attack"}:
            legal_zero_hp_intents = ("normal", "knock_out")
        options.append(
            ReactionOptionView(
                option_id=_opportunity_option_id(
                    reactor_id=reactor.actor_id,
                    action=action,
                    option_index=option_index,
                ),
                action_name=action.name,
                fixed_target_ids=(mover.actor_id,),
                legal_target_ids=(mover.actor_id,),
                legal_zero_hp_intents=legal_zero_hp_intents,
                resource_cost=tuple(
                    sorted(
                        (str(key), int(amount))
                        for key, amount in action.resource_cost.items()
                        if int(amount) > 0
                    )
                ),
                attack_bonus=action.to_hit,
                damage_expression=action.damage,
                damage_type=action.damage_type,
                reach_ft=float(reach_ft),
                on_hit_effects=on_hit_effects,
            )
        )
    window_id = ":".join(
        (
            str(turn_token or "no_turn"),
            "opportunity_attack",
            reactor.actor_id,
            mover.actor_id,
            str(window_ordinal),
            _position_token(trigger_point),
        )
    )
    return ReactionWindowView(
        window_id=window_id,
        reactor_id=reactor.actor_id,
        round_number=round_number,
        turn_token=turn_token,
        trigger=ReactionTriggerView(
            kind="opportunity_attack",
            source_actor_id=mover.actor_id,
            target_actor_id=reactor.actor_id,
            movement_point=trigger_point,
            distance_ft=float(trigger_distance),
            movement_source=movement_source,
            mover_disengaged=mover_disengaged,
        ),
        options=tuple(options),
    )


def default_reaction_decision(window: ReactionWindowView) -> ReactionDecision:
    if not window.options:
        return ReactionDecision(window_id=window.window_id, choice="pass")
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
    )


def build_strategy_reaction_decision_provider(
    *,
    state_provider: Callable[[], BattleStateView],
    strategy_registry: dict[str, Any],
    actor_strategy_overrides: dict[str, str],
    party_default_strategy: str,
    enemy_default_strategy: str,
) -> ReactionDecisionProvider:
    """Resolve each reaction against the reactor's strategy and current battle view."""

    def _decide(window: ReactionWindowView) -> ReactionDecision:
        state = state_provider()
        actor = state.actors.get(window.reactor_id)
        if actor is None:
            _reaction_decision_error(
                code="missing_reaction_actor",
                field="window.reactor_id",
                message="Reaction actor is not present in the current battle state.",
                details={"reactor_id": window.reactor_id},
            )
        strategy_name = actor_strategy_overrides.get(actor.actor_id)
        if strategy_name is None:
            strategy_name = (
                party_default_strategy if actor.team == "party" else enemy_default_strategy
            )
        strategy = strategy_registry.get(strategy_name)
        if strategy is None:
            _reaction_decision_error(
                code="missing_reaction_strategy",
                field="strategy_registry",
                message="No strategy is registered for the reacting actor.",
                details={"reactor_id": actor.actor_id, "strategy_name": strategy_name},
            )
        decide_reaction = getattr(strategy, "decide_reaction", None)
        if not callable(decide_reaction):
            return default_reaction_decision(window)
        return decide_reaction(actor, window, state)

    return _decide


def validate_reaction_decision(
    window: ReactionWindowView,
    decision: ReactionDecision,
) -> tuple[ReactionOptionView | None, ZeroHPIntent]:
    if not isinstance(decision, ReactionDecision):
        _reaction_decision_error(
            code="invalid_reaction_decision",
            field="decision",
            message="Reaction provider must return a ReactionDecision.",
        )
    if decision.window_id != window.window_id:
        _reaction_decision_error(
            code="stale_reaction_window",
            field="decision.window_id",
            message="Reaction decision does not match the open reaction window.",
            details={"expected": window.window_id, "received": decision.window_id},
        )
    choice = str(decision.choice or "").strip().lower()
    if choice not in {"use", "pass"}:
        _reaction_decision_error(
            code="invalid_reaction_choice",
            field="decision.choice",
            message="Reaction choice must be 'use' or 'pass'.",
        )
    raw_resource_spend = getattr(decision.resource_spend, "amounts", None)
    if not isinstance(raw_resource_spend, dict):
        _reaction_decision_error(
            code="invalid_reaction_resource_spend",
            field="decision.resource_spend",
            message="Reaction resource_spend must be a mapping.",
        )
    if choice == "pass":
        if (
            decision.option_id is not None
            or decision.targets
            or raw_resource_spend
            or decision.spell_slot_level is not None
            or str(decision.zero_hp_intent).strip().lower() != "normal"
        ):
            _reaction_decision_error(
                code="invalid_reaction_pass",
                field="decision",
                message="A pass decision cannot include an option or resolution choices.",
            )
        return None, "normal"

    selected = next(
        (option for option in window.options if option.option_id == decision.option_id),
        None,
    )
    if selected is None:
        _reaction_decision_error(
            code="unknown_reaction_option",
            field="decision.option_id",
            message="Selected reaction option is not legal in this window.",
        )
    if raw_resource_spend:
        _reaction_decision_error(
            code="unsupported_reaction_resource_spend",
            field="decision.resource_spend",
            message="Opportunity attacks do not accept extra declared resource spend.",
        )
    if decision.spell_slot_level is not None:
        _reaction_decision_error(
            code="illegal_reaction_spell_slot",
            field="decision.spell_slot_level",
            message="Selected opportunity attack does not accept a spell-slot override.",
        )
    target_ids: list[str] = []
    for index, target in enumerate(decision.targets):
        if not isinstance(target, TargetRef):
            _reaction_decision_error(
                code="invalid_reaction_target",
                field=f"decision.targets[{index}]",
                message="Reaction targets must be TargetRef values.",
            )
        target_ids.append(target.actor_id)
    if target_ids and tuple(target_ids) != selected.fixed_target_ids:
        _reaction_decision_error(
            code="illegal_reaction_target",
            field="decision.targets",
            message="Opportunity attack target is fixed by the movement trigger.",
            details={"legal_target_ids": list(selected.fixed_target_ids)},
        )
    normalized_intent = str(decision.zero_hp_intent or "").strip().lower()
    if normalized_intent not in selected.legal_zero_hp_intents:
        _reaction_decision_error(
            code="illegal_zero_hp_intent",
            field="decision.zero_hp_intent",
            message="Selected zero-HP intent is not legal for this reaction option.",
            details={"legal_zero_hp_intents": list(selected.legal_zero_hp_intents)},
        )
    return selected, normalized_intent


def _reaction_window_telemetry(
    telemetry: list[dict[str, Any]] | None,
    *,
    window: ReactionWindowView,
) -> None:
    if telemetry is None:
        return
    telemetry.append(
        {
            "telemetry_type": "reaction_window_opened",
            "window_id": window.window_id,
            "reaction_kind": window.trigger.kind,
            "round": window.round_number,
            "turn_token": window.turn_token,
            "reactor_id": window.reactor_id,
            "source_actor_id": window.trigger.source_actor_id,
            "target_actor_id": window.trigger.target_actor_id,
            "option_ids": [option.option_id for option in window.options],
        }
    )


def _reaction_decision_telemetry(
    telemetry: list[dict[str, Any]] | None,
    *,
    window: ReactionWindowView,
    decision: Any,
) -> None:
    if telemetry is None:
        return
    telemetry.append(
        {
            "telemetry_type": "reaction_decision",
            "window_id": window.window_id,
            "reaction_kind": window.trigger.kind,
            "round": window.round_number,
            "turn_token": window.turn_token,
            "reactor_id": window.reactor_id,
            "choice": str(getattr(decision, "choice", "")).strip().lower(),
            "option_id": getattr(decision, "option_id", None),
            "zero_hp_intent": str(getattr(decision, "zero_hp_intent", "normal")).strip().lower(),
            "rationale": (
                dict(decision.rationale)
                if isinstance(getattr(decision, "rationale", None), dict)
                else {}
            ),
        }
    )


def _reaction_window_closed_telemetry(
    telemetry: list[dict[str, Any]] | None,
    *,
    window: ReactionWindowView,
    status: str,
    option_id: str | None = None,
    reason: str | None = None,
) -> None:
    if telemetry is None:
        return
    telemetry.append(
        {
            "telemetry_type": "reaction_window_closed",
            "window_id": window.window_id,
            "reaction_kind": window.trigger.kind,
            "round": window.round_number,
            "turn_token": window.turn_token,
            "reactor_id": window.reactor_id,
            "status": status,
            "option_id": option_id,
            "reason": reason,
        }
    )


def _normalize_event_trigger(trigger: str | None) -> str | None:
    if trigger is None:
        return None
    text = str(trigger).strip().lower()
    return text or None


def refresh_reaction_at_turn_start(actor: ActorRuntimeState) -> None:
    """Restore the standard reaction at the start of this actor's turn."""

    actor.reaction_available = True


def can_take_reaction(actor: ActorRuntimeState) -> bool:
    from dnd_sim import engine_runtime as engine_module

    if not actor.reaction_available:
        return False
    if actor.dead or actor.hp <= 0:
        return False
    if engine_module.actor_is_incapacitated(actor):
        return False
    if engine_module.has_condition(actor, "open_hand_no_reactions"):
        return False
    return True


def as_readied_reaction_action(action: ActionDefinition) -> ActionDefinition:
    normalized_tags = {str(tag).strip().lower() for tag in action.tags}
    if "readied_response" in normalized_tags:
        return replace(action, action_cost="reaction")
    return replace(action, action_cost="reaction", tags=[*action.tags, "readied_response"])


def readied_trigger_matches(readied_trigger: str | None, *, trigger_event: str) -> bool:
    normalized_readied = _normalize_event_trigger(readied_trigger)
    normalized_event = _normalize_event_trigger(trigger_event)
    if normalized_event in {None, "enemy_turn_start", "on_enemy_turn_start"}:
        return normalized_readied in {None, "enemy_turn_start", "on_enemy_turn_start"}
    if normalized_event == "enemy_enters_reach":
        return normalized_readied in {
            "enemy_enters_reach",
            "on_enemy_enters_reach",
            "enters_reach",
            "on_enters_reach",
        }
    return normalized_readied == normalized_event


def readied_reach_entry_point(
    *,
    responder: ActorRuntimeState,
    path_points: list[tuple[float, float, float]],
) -> tuple[float, float, float] | None:
    from dnd_sim import engine_runtime as engine_module

    if "readying" not in responder.conditions:
        return None
    if not responder.readied_reaction_reserved:
        return None
    if not readied_trigger_matches(responder.readied_trigger, trigger_event="enemy_enters_reach"):
        return None
    readied = engine_module._resolve_named_action(responder, responder.readied_action_name)
    if readied is None or readied.name == "ready":
        return None

    reaction_action = as_readied_reaction_action(readied)
    if responder.readied_spell_held and "spell" in reaction_action.tags:
        reaction_action = replace(reaction_action, resource_cost={})
    trigger_range = engine_module._action_range_ft(reaction_action)
    if trigger_range is None or trigger_range <= 0:
        return None

    previous = path_points[0]
    was_in_range = distance_chebyshev(responder.position, previous) <= trigger_range
    for point in path_points[1:]:
        is_in_range = distance_chebyshev(responder.position, point) <= trigger_range
        if not was_in_range and is_in_range:
            return point
        was_in_range = is_in_range
    return None


def trigger_readied_actions(
    *,
    rng: random.Random,
    trigger_actor: ActorRuntimeState,
    trigger_event: str = "enemy_turn_start",
    eligible_reactors: set[str] | None = None,
    round_number: int | None = None,
    turn_token: str | None = None,
    actors: dict[str, ActorRuntimeState],
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    active_hazards: list[dict[str, Any]],
    obstacles: list[AABB] | None = None,
    light_level: str = "bright",
    rule_trace: list[dict[str, Any]] | None = None,
    telemetry: list[dict[str, Any]] | None = None,
) -> None:
    from dnd_sim import engine_runtime as engine_module

    normalized_trigger_event = _normalize_event_trigger(trigger_event)
    supports_standard_reactions = normalized_trigger_event in {
        None,
        "enemy_turn_start",
        "on_enemy_turn_start",
    }

    for actor in actors.values():
        if eligible_reactors is not None and actor.actor_id not in eligible_reactors:
            continue
        if actor.team == trigger_actor.team:
            continue
        if actor.dead or actor.hp <= 0:
            continue
        if not actor.reaction_available:
            continue

        if "readying" in actor.conditions and actor.readied_reaction_reserved:
            if readied_trigger_matches(actor.readied_trigger, trigger_event=trigger_event):
                readied = engine_module._resolve_named_action(actor, actor.readied_action_name)
                if readied is None:
                    engine_module._remove_condition(actor, "readying")
                elif readied.name != "ready":
                    reaction_action = as_readied_reaction_action(readied)
                    held_readied_spell = (
                        actor.readied_spell_held and "spell" in reaction_action.tags
                    )
                    spell_cast_request = (
                        SpellCastRequest(slot_level=actor.readied_spell_slot_level)
                        if held_readied_spell
                        else (SpellCastRequest() if "spell" in reaction_action.tags else None)
                    )
                    if held_readied_spell:
                        reaction_action = replace(reaction_action, resource_cost={})
                    if engine_module._action_available(
                        actor,
                        reaction_action,
                        spell_cast_request=spell_cast_request,
                        turn_token=turn_token,
                    ):
                        targets = engine_module._resolve_targets_for_action(
                            rng=rng,
                            actor=actor,
                            action=reaction_action,
                            actors=actors,
                            requested=[TargetRef(trigger_actor.actor_id)],
                            obstacles=obstacles,
                        )
                        if reaction_action.target_mode != "self":
                            targets = [
                                target
                                for target in targets
                                if target.actor_id == trigger_actor.actor_id
                            ]
                        targets = engine_module._filter_targets_in_range(
                            actor,
                            reaction_action,
                            targets,
                            active_hazards=active_hazards,
                            obstacles=obstacles,
                            light_level=light_level,
                        )
                        paid_reaction_cost = held_readied_spell
                        if targets and not paid_reaction_cost:
                            paid_reaction_cost = engine_module._spend_action_resource_cost(
                                actor,
                                reaction_action,
                                resources_spent,
                                spell_cast_request=spell_cast_request,
                                turn_token=turn_token,
                            )
                        if targets and paid_reaction_cost:
                            actor.reaction_available = False
                            if held_readied_spell:
                                actor.readied_spell_held = False
                                engine_module._break_concentration(actor, actors, active_hazards)
                            engine_module._execute_action(
                                rng=rng,
                                actor=actor,
                                action=reaction_action,
                                targets=targets,
                                actors=actors,
                                damage_dealt=damage_dealt,
                                damage_taken=damage_taken,
                                threat_scores=threat_scores,
                                resources_spent=resources_spent,
                                active_hazards=active_hazards,
                                obstacles=obstacles,
                                light_level=light_level,
                                round_number=round_number,
                                turn_token=turn_token,
                                spell_cast_request=spell_cast_request,
                                zero_hp_intent=actor.readied_zero_hp_intent,
                                rule_trace=rule_trace,
                                telemetry=telemetry,
                            )
                            engine_module._remove_condition(actor, "readying")
            if trigger_actor.dead or trigger_actor.hp <= 0:
                break

        if not supports_standard_reactions:
            if trigger_actor.dead or trigger_actor.hp <= 0:
                break
            continue

        if not actor.reaction_available:
            continue

        for reaction_action in actor.actions:
            if reaction_action.action_cost != "reaction":
                continue
            if engine_module._action_matches_reaction_spell_id(
                reaction_action,
                spell_id="shield",
            ) or engine_module._action_matches_reaction_spell_id(
                reaction_action,
                spell_id="counterspell",
            ):
                continue
            trigger = _normalize_event_trigger(reaction_action.event_trigger)
            if trigger not in {"enemy_turn_start", "on_enemy_turn_start"}:
                continue
            if not engine_module._action_available(actor, reaction_action, turn_token=turn_token):
                continue

            targets = engine_module._resolve_targets_for_action(
                rng=rng,
                actor=actor,
                action=reaction_action,
                actors=actors,
                requested=[TargetRef(trigger_actor.actor_id)],
                obstacles=obstacles,
            )
            targets = [target for target in targets if target.actor_id == trigger_actor.actor_id]
            targets = engine_module._filter_targets_in_range(
                actor,
                reaction_action,
                targets,
                active_hazards=active_hazards,
                obstacles=obstacles,
                light_level=light_level,
            )
            if not targets:
                continue
            spell_cast_request = SpellCastRequest() if "spell" in reaction_action.tags else None
            if not engine_module._spend_action_resource_cost(
                actor,
                reaction_action,
                resources_spent,
                spell_cast_request=spell_cast_request,
                turn_token=turn_token,
            ):
                continue

            actor.reaction_available = False
            engine_module._execute_action(
                rng=rng,
                actor=actor,
                action=reaction_action,
                targets=targets,
                actors=actors,
                damage_dealt=damage_dealt,
                damage_taken=damage_taken,
                threat_scores=threat_scores,
                resources_spent=resources_spent,
                active_hazards=active_hazards,
                obstacles=obstacles,
                light_level=light_level,
                round_number=round_number,
                turn_token=turn_token,
                spell_cast_request=spell_cast_request,
            )
            break

        if trigger_actor.dead or trigger_actor.hp <= 0:
            break


def run_opportunity_attacks_for_movement(
    *,
    rng: random.Random,
    mover: ActorRuntimeState,
    start_pos: tuple[float, float, float],
    end_pos: tuple[float, float, float],
    movement_path: list[tuple[float, float, float]] | None,
    actors: dict[str, ActorRuntimeState],
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    active_hazards: list[dict[str, Any]],
    obstacles: list[AABB] | None = None,
    light_level: str = "bright",
    round_number: int | None = None,
    turn_token: str | None = None,
    movement_kind: str = "voluntary",
    movement_source: str = "movement",
    movement_trigger_hooks: list[Callable[[Any], None]] | None = None,
    reaction_decision_provider: ReactionDecisionProvider | None = None,
    rule_trace: list[dict[str, Any]] | None = None,
    telemetry: list[dict[str, Any]] | None = None,
) -> None:
    from dnd_sim import engine_runtime as engine_module
    from dnd_sim.spatial import can_see

    if mover.dead or mover.hp <= 0:
        return
    standard_opportunity_trigger = engine_module._movement_triggers_opportunity_attacks(
        movement_kind=movement_kind,
        mover_conditions=set(mover.conditions),
        start_pos=start_pos,
        end_pos=end_pos,
    )
    sentinel_disengage_trigger = (
        movement_kind == "voluntary"
        and start_pos != end_pos
        and engine_module.has_condition(mover, "disengaging")
        and any(
            enemy.team != mover.team
            and not enemy.dead
            and enemy.hp > 0
            and engine_module._has_trait(enemy, "sentinel")
            for enemy in actors.values()
        )
    )
    if not standard_opportunity_trigger and not sentinel_disengage_trigger:
        return

    path_points = engine_module._expand_path_points(movement_path or [start_pos, end_pos])
    if len(path_points) < 2:
        return

    hooks = movement_trigger_hooks or []
    movement_stopped = False
    for enemy in actors.values():
        if enemy.team == mover.team or enemy.dead or enemy.hp <= 0:
            continue
        if not can_take_reaction(enemy):
            continue
        sentinel_reactor = engine_module._has_trait(enemy, "sentinel")
        readied_reach_entry = readied_reach_entry_point(
            responder=enemy,
            path_points=path_points,
        )
        if readied_reach_entry is not None:
            original_position = mover.position
            mover.position = readied_reach_entry
            trigger_readied_actions(
                rng=rng,
                trigger_actor=mover,
                trigger_event="enemy_enters_reach",
                eligible_reactors={enemy.actor_id},
                round_number=round_number,
                turn_token=turn_token,
                actors=actors,
                damage_dealt=damage_dealt,
                damage_taken=damage_taken,
                threat_scores=threat_scores,
                resources_spent=resources_spent,
                active_hazards=active_hazards,
                obstacles=obstacles,
                light_level=light_level,
                rule_trace=rule_trace,
                telemetry=telemetry,
            )
            mover.position = end_pos if mover.hp > 0 and not mover.dead else original_position
            if mover.dead or mover.hp <= 0:
                break

        if not can_take_reaction(enemy):
            continue
        if engine_module.has_condition(mover, "disengaging") and not sentinel_reactor:
            continue
        opportunity_candidates = engine_module._opportunity_attack_candidates(enemy)
        if not opportunity_candidates:
            continue
        max_reach = max(reach_ft for _, reach_ft in opportunity_candidates)
        transitions = engine_module._movement_reach_transitions(
            reactor_position=enemy.position,
            path_points=path_points,
            reach_ft=max_reach,
        )
        if not transitions:
            continue
        for window_ordinal, (trigger, trigger_point, trigger_distance) in enumerate(transitions):
            visible = can_see(
                observer_pos=enemy.position,
                target_pos=trigger_point,
                observer_traits=enemy.traits,
                target_conditions=mover.conditions,
                active_hazards=active_hazards,
                light_level=light_level,
            )
            if hooks:
                movement_trigger = engine_module.MovementReactionTrigger(
                    trigger=trigger,
                    mover_id=mover.actor_id,
                    reactor_id=enemy.actor_id,
                    point=trigger_point,
                    distance_ft=float(trigger_distance),
                    reach_ft=float(max_reach),
                    visible=visible,
                    movement_source=movement_source,
                )
                for hook in hooks:
                    hook(movement_trigger)

            if trigger != "exit_reach":
                continue
            if not visible:
                continue

            eligible_candidates = [
                (action, reach_ft)
                for action, reach_ft in opportunity_candidates
                if reach_ft + 1e-9 >= float(trigger_distance)
            ]
            if not eligible_candidates:
                continue
            window = build_opportunity_attack_window(
                reactor=enemy,
                mover=mover,
                candidates=eligible_candidates,
                trigger_point=trigger_point,
                trigger_distance=float(trigger_distance),
                round_number=round_number,
                turn_token=turn_token,
                window_ordinal=window_ordinal,
                movement_source=movement_source,
                mover_disengaged=engine_module.has_condition(mover, "disengaging"),
                on_hit_effects=(("speed_zero_for_turn",) if sentinel_reactor else ()),
            )
            _reaction_window_telemetry(telemetry, window=window)
            decision = (
                reaction_decision_provider(window)
                if reaction_decision_provider is not None
                else default_reaction_decision(window)
            )
            _reaction_decision_telemetry(telemetry, window=window, decision=decision)
            try:
                selected_option, zero_hp_intent = validate_reaction_decision(window, decision)
            except ReactionDecisionValidationError as exc:
                _reaction_window_closed_telemetry(
                    telemetry,
                    window=window,
                    status="rejected",
                    option_id=getattr(decision, "option_id", None),
                    reason=exc.code,
                )
                raise
            if selected_option is None:
                _reaction_window_closed_telemetry(
                    telemetry,
                    window=window,
                    status="passed",
                )
                continue

            selected_index = next(
                index
                for index, option in enumerate(window.options)
                if option.option_id == selected_option.option_id
            )
            selected_action, _ = eligible_candidates[selected_index]
            reaction_attack = replace(
                selected_action,
                attack_count=1,
                action_cost="reaction",
            )
            spell_cast_request = SpellCastRequest() if "spell" in reaction_attack.tags else None
            if not engine_module._spend_action_resource_cost(
                enemy,
                reaction_attack,
                resources_spent,
                spell_cast_request=spell_cast_request,
                turn_token=turn_token,
            ):
                _reaction_window_closed_telemetry(
                    telemetry,
                    window=window,
                    status="unavailable",
                    option_id=selected_option.option_id,
                    reason="resource_cost",
                )
                continue

            enemy.reaction_available = False
            enemy.per_action_uses[selected_action.name] = (
                enemy.per_action_uses.get(selected_action.name, 0) + 1
            )
            if selected_action.recharge:
                enemy.recharge_ready[selected_action.name] = False
            original_position = mover.position
            mover.position = trigger_point
            sentinel_hit = False
            timing_engine = None
            if sentinel_reactor:
                timing_engine = engine_module._create_combat_timing_engine()

                def _capture_sentinel_hit(event: AttackResolvedEvent) -> None:
                    nonlocal sentinel_hit
                    if (
                        event.attacker.actor_id == enemy.actor_id
                        and event.target.actor_id == mover.actor_id
                        and event.action is reaction_attack
                    ):
                        sentinel_hit = sentinel_speed_reduction_applies_on_hit(
                            hit=event.roll.hit,
                            opportunity_attack=True,
                        )

                timing_engine.subscribe(
                    AttackResolvedEvent,
                    _capture_sentinel_hit,
                    priority=-100,
                    name="rule:sentinel_opportunity_speed",
                )
            engine_module._execute_action(
                rng=rng,
                actor=enemy,
                action=reaction_attack,
                targets=[mover],
                actors=actors,
                damage_dealt=damage_dealt,
                damage_taken=damage_taken,
                threat_scores=threat_scores,
                resources_spent=resources_spent,
                active_hazards=active_hazards,
                obstacles=obstacles,
                light_level=light_level,
                round_number=round_number,
                turn_token=turn_token,
                timing_engine=timing_engine,
                spell_cast_request=spell_cast_request,
                allow_auto_movement=False,
                zero_hp_intent=zero_hp_intent,
                rule_trace=rule_trace,
                telemetry=telemetry,
            )
            if sentinel_hit:
                mover.position = trigger_point
                mover.movement_remaining = 0.0
                engine_module._apply_condition(
                    mover,
                    "sentinel_speed_zero",
                    duration_rounds=1,
                )
                movement_stopped = True
                if telemetry is not None:
                    telemetry.append(
                        {
                            "telemetry_type": "reaction_effect_applied",
                            "window_id": window.window_id,
                            "reaction_kind": window.trigger.kind,
                            "round": round_number,
                            "turn_token": turn_token,
                            "reactor_id": enemy.actor_id,
                            "target_actor_id": mover.actor_id,
                            "effect": "speed_zero_for_turn",
                        }
                    )
                if rule_trace is not None:
                    rule_trace.append(
                        {
                            "event": "opportunity_attack",
                            "round": round_number,
                            "turn": turn_token,
                            "handler": "trait:sentinel_speed_zero",
                            "actor_id": enemy.actor_id,
                            "target_id": mover.actor_id,
                            "result": "applied",
                        }
                    )
            else:
                mover.position = end_pos if mover.hp > 0 and not mover.dead else original_position
            _reaction_window_closed_telemetry(
                telemetry,
                window=window,
                status="resolved",
                option_id=selected_option.option_id,
            )
            break
        if movement_stopped or mover.dead or mover.hp <= 0:
            break


def reaction_attack_hook_matches(
    *,
    hook: FeatureHookRegistration,
    event: str,
    reactor: ActorRuntimeState,
    trigger_actor: ActorRuntimeState | None,
    trigger_target: ActorRuntimeState | None,
    trigger_action: ActionDefinition | None,
) -> bool:
    from dnd_sim import engine_runtime as engine_module

    if event != "after_action" or trigger_actor is None or trigger_action is None:
        return False

    trigger = hook.trigger
    if trigger == "creature_attacks_ally_within_5ft":
        if trigger_action.action_type != "attack" or trigger_target is None:
            return False
        if trigger_actor.team == reactor.team:
            return False
        if reactor.team != trigger_target.team or reactor.actor_id == trigger_target.actor_id:
            return False
        if engine_module._trait_lookup_key(
            hook.feature_name
        ) == "sentinel" and engine_module._has_trait(trigger_target, "sentinel"):
            return False
        return True

    if trigger == "spell_cast_within_5ft":
        if trigger_actor.team == reactor.team:
            return False
        return "spell" in trigger_action.tags

    if trigger == "hit_by_melee_attack_within_5ft":
        if trigger_action.action_type != "attack" or trigger_target is None:
            return False
        if trigger_actor.team == reactor.team:
            return False
        if trigger_target.actor_id != reactor.actor_id:
            return False
        return not engine_module._is_ranged_attack_action(trigger_action)

    return False


def run_trait_event_handlers(
    *,
    rng: random.Random,
    event: str,
    trigger_actor: ActorRuntimeState | None,
    trigger_target: ActorRuntimeState | None,
    trigger_action: ActionDefinition | None,
    actors: dict[str, ActorRuntimeState],
    round_number: int,
    turn_token: str,
    damage_dealt: dict[str, int],
    damage_taken: dict[str, int],
    threat_scores: dict[str, int],
    resources_spent: dict[str, dict[str, int]],
    active_hazards: list[dict[str, Any]],
    rule_trace: list[dict[str, Any]],
    obstacles: list[AABB],
    light_level: str,
) -> None:
    from dnd_sim import engine_runtime as engine_module

    if event != "after_action" or trigger_actor is None or trigger_action is None:
        return
    reactors = sorted(actors.values(), key=lambda value: value.actor_id)
    for reactor in reactors:
        if reactor.dead or reactor.hp <= 0:
            continue
        engine_module._register_actor_feature_hooks(reactor)
        if not reactor.feature_hooks:
            continue

        for hook in reactor.feature_hooks:
            if hook.hook_type != "reaction_attack":
                continue

            handler_name = engine_module._feature_hook_handler_name(hook)
            if hook.trigger not in engine_module._REACTION_ATTACK_HOOK_TRIGGERS:
                rule_trace.append(
                    {
                        "event": event,
                        "round": round_number,
                        "turn": turn_token,
                        "handler": "feature_hook:reaction_attack",
                        "actor_id": reactor.actor_id,
                        "hook_feature": hook.feature_name,
                        "hook_source": hook.source_type,
                        "hook_trigger": hook.trigger,
                        "result": "skipped",
                        "reason": "invalid_hook_trigger",
                    }
                )
                continue

            if not reaction_attack_hook_matches(
                hook=hook,
                event=event,
                reactor=reactor,
                trigger_actor=trigger_actor,
                trigger_target=trigger_target,
                trigger_action=trigger_action,
            ):
                continue

            if not reactor.reaction_available:
                continue

            attack_action = engine_module._fallback_action(reactor)
            if attack_action is None or attack_action.action_type != "attack":
                continue

            reactor.reaction_available = False
            engine_module._execute_action(
                rng=rng,
                actor=reactor,
                action=attack_action,
                targets=[trigger_actor],
                actors=actors,
                damage_dealt=damage_dealt,
                damage_taken=damage_taken,
                threat_scores=threat_scores,
                resources_spent=resources_spent,
                active_hazards=active_hazards,
                obstacles=obstacles,
                light_level=light_level,
                round_number=round_number,
                turn_token=turn_token,
                rule_trace=rule_trace,
            )
            rule_trace.append(
                {
                    "event": event,
                    "round": round_number,
                    "turn": turn_token,
                    "handler": handler_name,
                    "actor_id": reactor.actor_id,
                    "trigger_actor_id": trigger_actor.actor_id,
                    "hook_feature": hook.feature_name,
                    "hook_source": hook.source_type,
                    "hook_trigger": hook.trigger,
                    "result": "executed",
                }
            )
            if trigger_actor.dead or trigger_actor.hp <= 0:
                return
