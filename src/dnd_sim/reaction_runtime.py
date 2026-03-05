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
from dnd_sim.strategy_api import TargetRef

logger = logging.getLogger(__name__)


def _normalize_event_trigger(trigger: str | None) -> str | None:
    if trigger is None:
        return None
    text = str(trigger).strip().lower()
    return text or None


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
) -> None:
    from dnd_sim import engine_runtime as engine_module
    from dnd_sim.spatial import can_see

    if mover.dead or mover.hp <= 0:
        return
    if not engine_module._movement_triggers_opportunity_attacks(
        movement_kind=movement_kind,
        mover_conditions=set(mover.conditions),
        start_pos=start_pos,
        end_pos=end_pos,
    ):
        return

    path_points = engine_module._expand_path_points(movement_path or [start_pos, end_pos])
    if len(path_points) < 2:
        return

    hooks = movement_trigger_hooks or []
    for enemy in actors.values():
        if enemy.team == mover.team or enemy.dead or enemy.hp <= 0:
            continue
        if not can_take_reaction(enemy):
            continue
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
            )
            mover.position = end_pos if mover.hp > 0 and not mover.dead else original_position
            if mover.dead or mover.hp <= 0:
                break

        if not can_take_reaction(enemy):
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
        for trigger, trigger_point, trigger_distance in transitions:
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

            reaction_result = engine_module._find_opportunity_attack_action(
                enemy,
                required_reach_ft=float(trigger_distance),
            )
            if reaction_result is None:
                continue
            reaction_attack, _ = reaction_result
            spell_cast_request = SpellCastRequest() if "spell" in reaction_attack.tags else None
            if not engine_module._spend_action_resource_cost(
                enemy,
                reaction_attack,
                resources_spent,
                spell_cast_request=spell_cast_request,
                turn_token=turn_token,
            ):
                continue

            enemy.reaction_available = False
            original_position = mover.position
            mover.position = trigger_point
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
                spell_cast_request=spell_cast_request,
            )
            mover.position = end_pos if mover.hp > 0 and not mover.dead else original_position
            break
        if mover.dead or mover.hp <= 0:
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
    lock_key = f"event_reaction_round:{round_number}"
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
            if reactor.per_action_uses.get(lock_key, 0) > 0:
                rule_trace.append(
                    {
                        "event": event,
                        "round": round_number,
                        "turn": turn_token,
                        "handler": handler_name,
                        "actor_id": reactor.actor_id,
                        "hook_feature": hook.feature_name,
                        "hook_source": hook.source_type,
                        "hook_trigger": hook.trigger,
                        "result": "skipped",
                        "reason": "reaction_lock",
                    }
                )
                continue

            attack_action = engine_module._fallback_action(reactor)
            if attack_action is None or attack_action.action_type != "attack":
                continue

            reactor.reaction_available = False
            reactor.per_action_uses[lock_key] = 1
            if hook.trigger == "creature_attacks_ally_within_5ft":
                trigger_actor.movement_remaining = 0.0

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
