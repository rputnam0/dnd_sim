from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any, Callable

from dnd_sim.models import ActionDefinition, ActorRuntimeState, SpellCastRequest
from dnd_sim.rules_2014 import ActionDeclaredEvent, CombatTimingEngine, ReactionWindowOpenedEvent
from dnd_sim.strategy_api import TargetRef

TargetResolver = Callable[..., list[ActorRuntimeState]]
RangeFilter = Callable[..., list[ActorRuntimeState]]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SpellPipelineAdapters:
    has_condition: Callable[[ActorRuntimeState, str], bool]
    ritual_casting_legal_for_context: Callable[[ActionDefinition, str | None], bool]
    spell_casting_legal_this_turn: Callable[[ActorRuntimeState, ActionDefinition, str | None], bool]
    can_cast_spell_with_components: Callable[[ActorRuntimeState, ActionDefinition], bool]
    required_spell_slot_level: Callable[[ActionDefinition], int]
    preferred_spell_slot_level: Callable[[ActionDefinition], int | None]
    apply_upcast_scaling_for_slot: Callable[[ActionDefinition, int], ActionDefinition]
    can_take_reaction: Callable[[ActorRuntimeState], bool]
    action_matches_reaction_spell_id: Callable[[ActionDefinition, str], bool]
    counterspell_slot_if_legal: Callable[..., tuple[str, int] | None]
    split_spell_slot_cost: Callable[[dict[str, int]], tuple[dict[str, int], int, list[int]]]
    spend_resources: Callable[[ActorRuntimeState, dict[str, int]], dict[str, int]]
    mark_action_cost_used: Callable[[ActorRuntimeState, ActionDefinition], None]
    spellcasting_ability_mod: Callable[[ActorRuntimeState], int]
    is_action_cantrip_spell: Callable[[ActionDefinition], bool]
    break_concentration: Callable[
        [ActorRuntimeState, dict[str, ActorRuntimeState], list[dict[str, Any]]], None
    ]
    is_smite_setup_action: Callable[[ActionDefinition], bool]


@dataclass(slots=True)
class SpellPipelineResult:
    action: ActionDefinition
    spell_level: int
    spell_cast_request: SpellCastRequest
    spell_declared_for_resolution: bool


def mode_requires_explicit_targets(mode: str) -> bool:
    return mode in {
        "single_enemy",
        "single_ally",
        "n_enemies",
        "n_allies",
        "random_enemy",
        "random_ally",
    }


def resolve_spell_cast_request(
    *,
    actor: ActorRuntimeState,
    action: ActionDefinition,
    targets: list[ActorRuntimeState],
    provided: SpellCastRequest | None,
    required_spell_slot_level: Callable[[ActionDefinition], int],
    preferred_spell_slot_level: Callable[[ActionDefinition], int | None],
) -> SpellCastRequest:
    if provided is None:
        request = SpellCastRequest()
    else:
        request = SpellCastRequest(
            slot_level=provided.slot_level,
            mode=provided.mode,
            target_actor_ids=list(provided.target_actor_ids),
            origin=provided.origin,
        )

    if request.mode is None:
        request.mode = action.target_mode
    if not request.target_actor_ids and targets:
        request.target_actor_ids = [target.actor_id for target in targets]
    if request.origin is None:
        request.origin = actor.position

    required_slot_level = required_spell_slot_level(action)
    if required_slot_level > 0 and request.slot_level is None:
        preferred_slot = preferred_spell_slot_level(action)
        request.slot_level = preferred_slot if preferred_slot is not None else required_slot_level

    if request.mode is None:
        raise ValueError("Spell cast request requires a target mode.")
    if request.mode != action.target_mode:
        raise ValueError("Spell cast request mode must match action target mode.")
    if mode_requires_explicit_targets(request.mode) and not request.target_actor_ids:
        raise ValueError("Spell cast request requires at least one target.")
    if action.aoe_type and request.origin is None:
        raise ValueError("Spell cast request requires an origin for area spell templates.")
    if required_slot_level > 0:
        if request.slot_level is None:
            raise ValueError("Spell cast request requires a slot for leveled spells.")
        if int(request.slot_level) < required_slot_level:
            raise ValueError("Spell cast request slot level is below the spell level.")

    return request


def resolve_action_targets(
    *,
    rng: random.Random,
    actor: ActorRuntimeState,
    action: ActionDefinition,
    actors: dict[str, ActorRuntimeState],
    requested: list[TargetRef],
    obstacles: list[Any] | None,
    active_hazards: list[dict[str, Any]],
    light_level: str,
    spell_cast_request: SpellCastRequest | None,
    resolve_targets_for_action: TargetResolver,
    filter_targets_in_range: RangeFilter,
) -> list[ActorRuntimeState]:
    resolved_targets = resolve_targets_for_action(
        rng=rng,
        actor=actor,
        action=action,
        actors=actors,
        requested=requested,
        obstacles=obstacles,
        spell_cast_request=spell_cast_request,
    )
    if requested:
        requested_ids = {target.actor_id for target in requested}
        resolved_targets = [
            target for target in resolved_targets if target.actor_id in requested_ids
        ]
    return filter_targets_in_range(
        actor,
        action,
        resolved_targets,
        active_hazards=active_hazards,
        obstacles=obstacles,
        light_level=light_level,
    )


def record_spell_cast_for_turn(
    actor: ActorRuntimeState,
    action: ActionDefinition,
    *,
    is_action_cantrip_spell: Callable[[ActionDefinition], bool],
) -> None:
    if "spell" not in action.tags:
        return
    if not is_action_cantrip_spell(action):
        actor.non_action_cantrip_spell_cast_this_turn = True
    if action.action_cost == "bonus":
        actor.bonus_action_spell_restriction_active = True


def apply_spell_result_state(
    *,
    actor: ActorRuntimeState,
    action: ActionDefinition,
    spell_level: int,
    actors: dict[str, ActorRuntimeState],
    active_hazards: list[dict[str, Any]],
    break_concentration: Callable[
        [ActorRuntimeState, dict[str, ActorRuntimeState], list[dict[str, Any]]], None
    ],
    is_smite_setup_action: Callable[[ActionDefinition], bool],
) -> None:
    if not action.concentration:
        return
    break_concentration(actor, actors, active_hazards)
    actor.concentrating = True
    actor.concentrated_spell = action.name
    actor.concentrated_spell_level = spell_level
    actor.concentration_conditions.clear()
    actor.concentration_effect_instance_ids.clear()
    if is_smite_setup_action(action):
        actor.concentration_conditions.clear()
        actor.concentrated_targets.clear()
        actor.concentration_effect_instance_ids.clear()


def run_spell_declaration_pipeline(
    *,
    rng: random.Random,
    actor: ActorRuntimeState,
    action: ActionDefinition,
    targets: list[ActorRuntimeState],
    actors: dict[str, ActorRuntimeState],
    resources_spent: dict[str, dict[str, int]],
    active_hazards: list[dict[str, Any]],
    round_number: int | None,
    turn_token: str | None,
    timing_engine: CombatTimingEngine,
    spell_cast_request: SpellCastRequest | None,
    antimagic_suppression_condition: str,
    subtle_spell: bool,
    light_level: str,
    adapters: SpellPipelineAdapters,
) -> SpellPipelineResult | None:
    if not targets:
        return None
    if adapters.has_condition(actor, antimagic_suppression_condition):
        return None
    if not adapters.ritual_casting_legal_for_context(action, turn_token):
        return None
    if not adapters.spell_casting_legal_this_turn(actor, action, turn_token):
        return None
    if not adapters.can_cast_spell_with_components(actor, action):
        return None

    try:
        resolved_spell_cast_request = resolve_spell_cast_request(
            actor=actor,
            action=action,
            targets=targets,
            provided=spell_cast_request,
            required_spell_slot_level=adapters.required_spell_slot_level,
            preferred_spell_slot_level=adapters.preferred_spell_slot_level,
        )
    except ValueError:
        return None

    spell_level = max(0, int(adapters.required_spell_slot_level(action)))
    if resolved_spell_cast_request.slot_level is not None:
        spell_level = int(resolved_spell_cast_request.slot_level)
        action = adapters.apply_upcast_scaling_for_slot(action, spell_level)

    declaration_event = timing_engine.emit(
        ActionDeclaredEvent(
            attacker=actor,
            target=targets[0],
            action=action,
            round_number=round_number,
            turn_token=turn_token,
        )
    )
    if declaration_event.cancelled:
        return None

    record_spell_cast_for_turn(
        actor,
        action,
        is_action_cantrip_spell=adapters.is_action_cantrip_spell,
    )

    if not subtle_spell:
        for enemy in sorted(actors.values(), key=lambda candidate: candidate.actor_id):
            if (
                enemy.team == actor.team
                or enemy.hp <= 0
                or enemy.dead
                or not adapters.can_take_reaction(enemy)
            ):
                continue
            counterspell_action = next(
                (
                    candidate
                    for candidate in enemy.actions
                    if (
                        candidate.action_cost == "reaction"
                        and adapters.action_matches_reaction_spell_id(
                            candidate,
                            "counterspell",
                        )
                    )
                ),
                None,
            )
            if counterspell_action is None:
                continue

            counter_slot = adapters.counterspell_slot_if_legal(
                reactor=enemy,
                counterspell_action=counterspell_action,
                caster=actor,
                incoming_spell_level=spell_level,
                turn_token=turn_token,
                active_hazards=active_hazards,
                light_level=light_level,
            )
            if counter_slot is None:
                continue

            counter_window = timing_engine.emit(
                ReactionWindowOpenedEvent(
                    window="counterspell",
                    reactor=enemy,
                    attacker=actor,
                    target=targets[0],
                    action=action,
                    round_number=round_number,
                    turn_token=turn_token,
                )
            )
            if counter_window.cancelled:
                continue

            slot_key, counter_level = counter_slot
            enemy.resources[slot_key] -= 1
            enemy_spent = resources_spent.setdefault(enemy.actor_id, {})
            enemy_spent[slot_key] = enemy_spent.get(slot_key, 0) + 1

            non_slot_cost, _, _ = adapters.split_spell_slot_cost(counterspell_action.resource_cost)
            for key, amount in adapters.spend_resources(enemy, non_slot_cost).items():
                enemy_spent[key] = enemy_spent.get(key, 0) + amount

            enemy.per_action_uses[counterspell_action.name] = (
                enemy.per_action_uses.get(counterspell_action.name, 0) + 1
            )
            adapters.mark_action_cost_used(enemy, counterspell_action)
            record_spell_cast_for_turn(
                enemy,
                counterspell_action,
                is_action_cantrip_spell=adapters.is_action_cantrip_spell,
            )

            if counter_level >= spell_level:
                return None
            check_dc = 10 + spell_level
            check_total = rng.randint(1, 20) + adapters.spellcasting_ability_mod(enemy)
            if check_total >= check_dc:
                return None

    apply_spell_result_state(
        actor=actor,
        action=action,
        spell_level=spell_level,
        actors=actors,
        active_hazards=active_hazards,
        break_concentration=adapters.break_concentration,
        is_smite_setup_action=adapters.is_smite_setup_action,
    )

    return SpellPipelineResult(
        action=action,
        spell_level=spell_level,
        spell_cast_request=resolved_spell_cast_request,
        spell_declared_for_resolution=True,
    )
