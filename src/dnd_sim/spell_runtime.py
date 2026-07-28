from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any, Callable, Literal

from dnd_sim.models import (
    ActionDefinition,
    ActorRuntimeState,
    SpellCastRequest,
    SpellcastingAbility,
)
from dnd_sim.rules_2014 import ActionDeclaredEvent, CombatTimingEngine, ReactionWindowOpenedEvent
from dnd_sim.spell_reaction_runtime import (
    SpellCastFrame,
    build_child_spell_cast_frame,
    build_counterspell_candidates_for_action,
    build_counterspell_reaction_window,
    build_root_spell_cast_frame,
    record_counterspell_resolution,
)
from dnd_sim.strategy_api import ReactionDecision, ReactionDecisionProvider, TargetRef

TargetResolver = Callable[..., list[ActorRuntimeState]]
RangeFilter = Callable[..., list[ActorRuntimeState]]

logger = logging.getLogger(__name__)

_CLASS_SPELLCASTING_ABILITIES: dict[str, SpellcastingAbility] = {
    "artificer": "int",
    "bard": "cha",
    "cleric": "wis",
    "druid": "wis",
    "paladin": "cha",
    "ranger": "wis",
    "sorcerer": "cha",
    "warlock": "cha",
    "wizard": "int",
}


def normalize_spellcasting_ability(value: object) -> SpellcastingAbility | None:
    normalized = str(value or "").strip().lower()
    aliases = {
        "int": "int",
        "intelligence": "int",
        "wis": "wis",
        "wisdom": "wis",
        "cha": "cha",
        "charisma": "cha",
    }
    return aliases.get(normalized)  # type: ignore[return-value]


def infer_character_spellcasting_ability(
    character: dict[str, Any],
    spell: dict[str, Any],
    *,
    profile_ability: object = None,
) -> SpellcastingAbility | None:
    """Resolve an explicit spell source before using unambiguous class provenance."""

    for value in (
        spell.get("spellcasting_ability"),
        spell.get("casting_ability"),
        spell.get("source_class"),
        spell.get("class_name"),
        character.get("spellcasting_ability"),
        profile_ability,
    ):
        normalized = normalize_spellcasting_ability(value)
        if normalized is not None:
            return normalized
        source_class = str(value or "").strip().lower()
        if source_class in _CLASS_SPELLCASTING_ABILITIES:
            return _CLASS_SPELLCASTING_ABILITIES[source_class]

    raw_levels = character.get("class_levels")
    if not isinstance(raw_levels, dict):
        return None
    abilities = {
        ability
        for class_name, ability in _CLASS_SPELLCASTING_ABILITIES.items()
        if int(raw_levels.get(class_name, 0) or 0) > 0
    }
    return next(iter(abilities)) if len(abilities) == 1 else None


def spellcasting_ability_modifier(
    actor: ActorRuntimeState,
    ability: SpellcastingAbility | None = None,
) -> int:
    if ability is not None:
        return int(getattr(actor, f"{ability}_mod"))
    return max(actor.int_mod, actor.wis_mod, actor.cha_mod)


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
    counterspell_candidate_is_legal: Callable[..., bool]
    spend_resources: Callable[[ActorRuntimeState, dict[str, int]], dict[str, int]]
    mark_action_cost_used: Callable[[ActorRuntimeState, ActionDefinition], None]
    spellcasting_ability_mod: Callable[[ActorRuntimeState, SpellcastingAbility | None], int]
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
    cast_frame: SpellCastFrame


SpellPipelineStatus = Literal["blocked", "cancelled", "countered", "resolved"]


@dataclass(slots=True)
class SpellPipelineOutcome:
    status: SpellPipelineStatus
    result: SpellPipelineResult | None = None
    cast_frame: SpellCastFrame | None = None

    @property
    def spell_cast_occurred(self) -> bool:
        return self.status in {"countered", "resolved"}


def available_spell_slots(
    actor: ActorRuntimeState,
    *,
    minimum: int = 1,
) -> list[tuple[str, int]]:
    available: list[tuple[str, int]] = []
    for key, value in actor.resources.items():
        if not key.startswith("spell_slot_") or int(value) <= 0:
            continue
        try:
            level = int(key.split("_")[-1])
        except ValueError:
            continue
        if level >= minimum:
            available.append((key, level))
    available.sort(key=lambda item: item[1])
    return available


def mode_requires_explicit_targets(mode: str) -> bool:
    return mode in {
        "single_enemy",
        "single_ally",
        "single_creature",
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
    allow_deferred_targets: bool = False,
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
    if (
        not allow_deferred_targets
        and mode_requires_explicit_targets(request.mode)
        and not request.target_actor_ids
    ):
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


def action_component_tags(action: ActionDefinition) -> set[str]:
    explicit = {
        str(tag).strip().lower()
        for tag in action.tags
        if str(tag).strip().lower().startswith("component:")
    }
    if explicit or action.spell is None:
        return explicit
    components = action.spell.components
    return {
        tag
        for tag, required in (
            ("component:verbal", components.verbal),
            ("component:somatic", components.somatic),
            ("component:material", components.material),
        )
        if required
    }


def _spell_cast_is_observable(action: ActionDefinition, *, subtle_spell: bool) -> bool:
    if not subtle_spell:
        return True
    return "component:material" in action_component_tags(action)


def run_spell_declaration_pipeline_outcome(
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
    obstacles: list[Any] | None = None,
    reaction_decision_provider: ReactionDecisionProvider | None = None,
    telemetry: list[dict[str, Any]] | None = None,
    allow_deferred_targets: bool = False,
    apply_result_state: bool = True,
) -> SpellPipelineOutcome:
    if not targets and not allow_deferred_targets:
        return SpellPipelineOutcome(status="blocked")
    if adapters.has_condition(actor, antimagic_suppression_condition):
        return SpellPipelineOutcome(status="blocked")
    if not adapters.ritual_casting_legal_for_context(action, turn_token):
        return SpellPipelineOutcome(status="blocked")
    if not adapters.spell_casting_legal_this_turn(actor, action, turn_token):
        return SpellPipelineOutcome(status="blocked")
    if not adapters.can_cast_spell_with_components(actor, action):
        return SpellPipelineOutcome(status="blocked")

    try:
        resolved_spell_cast_request = resolve_spell_cast_request(
            actor=actor,
            action=action,
            targets=targets,
            provided=spell_cast_request,
            required_spell_slot_level=adapters.required_spell_slot_level,
            preferred_spell_slot_level=adapters.preferred_spell_slot_level,
            allow_deferred_targets=allow_deferred_targets,
        )
    except ValueError:
        return SpellPipelineOutcome(status="blocked")

    spell_level = max(0, int(adapters.required_spell_slot_level(action)))
    if resolved_spell_cast_request.slot_level is not None:
        spell_level = int(resolved_spell_cast_request.slot_level)
        action = adapters.apply_upcast_scaling_for_slot(action, spell_level)

    declaration_event = timing_engine.emit(
        ActionDeclaredEvent(
            attacker=actor,
            target=targets[0] if targets else None,
            action=action,
            round_number=round_number,
            turn_token=turn_token,
        )
    )
    if declaration_event.cancelled:
        return SpellPipelineOutcome(status="cancelled")

    cast_ordinal = actor.next_spell_cast_ordinal
    actor.next_spell_cast_ordinal += 1
    cast_frame = build_root_spell_cast_frame(
        caster=actor,
        action=action,
        spell_level=spell_level,
        target_actor_id=(targets[0].actor_id if targets else None),
        cast_ordinal=cast_ordinal,
        round_number=round_number,
        turn_token=turn_token,
    )

    record_spell_cast_for_turn(
        actor,
        action,
        is_action_cantrip_spell=adapters.is_action_cantrip_spell,
    )

    if _spell_cast_is_observable(action, subtle_spell=subtle_spell):
        from dnd_sim.reaction_decision_runtime import (
            ReactionDecisionValidationError,
            default_reaction_decision,
            record_reaction_decision as _reaction_decision_telemetry,
            record_reaction_window_closed as _reaction_window_closed_telemetry,
            record_reaction_window_opened as _reaction_window_telemetry,
            validate_reaction_decision,
        )

        reactor_order = 0
        for enemy in sorted(actors.values(), key=lambda candidate: candidate.actor_id):
            if (
                enemy.actor_id == actor.actor_id
                or enemy.hp <= 0
                or enemy.dead
                or not adapters.can_take_reaction(enemy)
            ):
                continue
            counterspell_candidates = []
            for action_index, counterspell_action in enumerate(enemy.actions):
                if counterspell_action.action_cost != "reaction" or not (
                    adapters.action_matches_reaction_spell_id(
                        counterspell_action,
                        "counterspell",
                    )
                ):
                    continue
                for candidate in build_counterspell_candidates_for_action(
                    reactor=enemy,
                    action=counterspell_action,
                    action_index=action_index,
                ):
                    if adapters.counterspell_candidate_is_legal(
                        reactor=enemy,
                        candidate=candidate,
                        caster=actor,
                        incoming_spell_level=spell_level,
                        turn_token=turn_token,
                        active_hazards=active_hazards,
                        light_level=light_level,
                        obstacles=obstacles,
                    ):
                        counterspell_candidates.append(candidate)
            if not counterspell_candidates:
                continue

            counter_window = timing_engine.emit(
                ReactionWindowOpenedEvent(
                    window="counterspell",
                    reactor=enemy,
                    attacker=actor,
                    target=targets[0] if targets else actor,
                    action=action,
                    round_number=round_number,
                    turn_token=turn_token,
                )
            )
            if counter_window.cancelled:
                continue

            window = build_counterspell_reaction_window(
                reactor=enemy,
                caster=actor,
                spell_target=targets[0] if targets else None,
                incoming_action=action,
                incoming_spell_level=spell_level,
                candidates=counterspell_candidates,
                round_number=round_number,
                turn_token=turn_token,
                incoming_cast_frame=cast_frame,
                reactor_order=reactor_order,
            )
            reactor_order += 1
            _reaction_window_telemetry(telemetry, window=window)
            if reaction_decision_provider is not None:
                decision = reaction_decision_provider(window)
            elif enemy.team == actor.team:
                decision = ReactionDecision(window_id=window.window_id, choice="pass")
            else:
                decision = default_reaction_decision(window)
            _reaction_decision_telemetry(telemetry, window=window, decision=decision)
            try:
                selected_option, _ = validate_reaction_decision(window, decision)
            except ReactionDecisionValidationError as exc:
                _reaction_window_closed_telemetry(
                    telemetry,
                    window=window,
                    status="rejected",
                    option_id=getattr(decision, "option_id", None),
                    reason=exc.code,
                    spell_slot_level=getattr(decision, "spell_slot_level", None),
                )
                raise
            if selected_option is None:
                _reaction_window_closed_telemetry(telemetry, window=window, status="passed")
                continue

            selected_index = next(
                index
                for index, option in enumerate(window.options)
                if option.option_id == selected_option.option_id
            )
            selected_candidate = counterspell_candidates[selected_index]
            action_index = selected_candidate.action_index
            action_is_current = (
                0 <= action_index < len(enemy.actions)
                and enemy.actions[action_index] is selected_candidate.action
            )
            live_candidate = None
            if action_is_current:
                live_candidate = next(
                    (
                        candidate
                        for candidate in build_counterspell_candidates_for_action(
                            reactor=enemy,
                            action=selected_candidate.action,
                            action_index=action_index,
                        )
                        if candidate == selected_candidate
                    ),
                    None,
                )
            if live_candidate is not None and not adapters.counterspell_candidate_is_legal(
                reactor=enemy,
                candidate=live_candidate,
                caster=actor,
                incoming_spell_level=spell_level,
                turn_token=turn_token,
                active_hazards=active_hazards,
                light_level=light_level,
                obstacles=obstacles,
            ):
                live_candidate = None
            if live_candidate is None:
                _reaction_window_closed_telemetry(
                    telemetry,
                    window=window,
                    status="unavailable",
                    option_id=selected_option.option_id,
                    reason="state_changed",
                    spell_slot_level=selected_candidate.slot_level,
                )
                continue
            if (
                live_candidate.effective_spell_level < spell_level
                and live_candidate.spellcasting_ability is None
            ):
                _reaction_window_closed_telemetry(
                    telemetry,
                    window=window,
                    status="unavailable",
                    option_id=selected_option.option_id,
                    reason="missing_spellcasting_ability",
                    spell_slot_level=live_candidate.slot_level,
                )
                continue

            counterspell_action = live_candidate.action
            counter_level = live_candidate.effective_spell_level
            enemy_spent = resources_spent.setdefault(enemy.actor_id, {})
            for key, amount in adapters.spend_resources(
                enemy,
                dict(live_candidate.resource_cost),
            ).items():
                enemy_spent[key] = enemy_spent.get(key, 0) + amount

            state_key = live_candidate.state_key
            enemy.per_action_uses[state_key] = enemy.per_action_uses.get(state_key, 0) + 1
            if counterspell_action.recharge:
                enemy.recharge_ready[state_key] = False
            adapters.mark_action_cost_used(enemy, counterspell_action)
            record_spell_cast_for_turn(
                enemy,
                counterspell_action,
                is_action_cantrip_spell=adapters.is_action_cantrip_spell,
            )

            counterspell_cast_ordinal = enemy.next_spell_cast_ordinal
            enemy.next_spell_cast_ordinal += 1
            counterspell_frame = build_child_spell_cast_frame(
                parent=cast_frame,
                caster=enemy,
                action=counterspell_action,
                spell_level=counter_level,
                target_actor_id=actor.actor_id,
                cast_ordinal=counterspell_cast_ordinal,
                range_ft=live_candidate.range_ft,
            )

            if counter_level >= spell_level:
                record_counterspell_resolution(
                    telemetry,
                    window=window,
                    incoming_frame=cast_frame,
                    counterspell_frame=counterspell_frame,
                    candidate=live_candidate,
                    option_id=selected_option.option_id,
                    resolution_method="automatic",
                    d20_roll=None,
                    check_modifier=None,
                    check_dc=None,
                    check_total=None,
                    outcome="countered",
                )
                _reaction_window_closed_telemetry(
                    telemetry,
                    window=window,
                    status="resolved",
                    option_id=selected_option.option_id,
                    reason="countered",
                    spell_slot_level=live_candidate.slot_level,
                )
                return SpellPipelineOutcome(status="countered", cast_frame=cast_frame)
            check_dc = 10 + spell_level
            spellcasting_ability = live_candidate.spellcasting_ability
            assert spellcasting_ability is not None
            d20_roll = rng.randint(1, 20)
            check_modifier = adapters.spellcasting_ability_mod(enemy, spellcasting_ability)
            check_total = d20_roll + check_modifier
            outcome = "countered" if check_total >= check_dc else "counter_failed"
            record_counterspell_resolution(
                telemetry,
                window=window,
                incoming_frame=cast_frame,
                counterspell_frame=counterspell_frame,
                candidate=live_candidate,
                option_id=selected_option.option_id,
                resolution_method="ability_check",
                d20_roll=d20_roll,
                check_modifier=check_modifier,
                check_dc=check_dc,
                check_total=check_total,
                outcome=outcome,
            )
            if check_total >= check_dc:
                _reaction_window_closed_telemetry(
                    telemetry,
                    window=window,
                    status="resolved",
                    option_id=selected_option.option_id,
                    reason="countered",
                    spell_slot_level=live_candidate.slot_level,
                )
                return SpellPipelineOutcome(status="countered", cast_frame=cast_frame)
            _reaction_window_closed_telemetry(
                telemetry,
                window=window,
                status="resolved",
                option_id=selected_option.option_id,
                reason="counter_failed",
                spell_slot_level=live_candidate.slot_level,
            )

    if apply_result_state:
        apply_spell_result_state(
            actor=actor,
            action=action,
            spell_level=spell_level,
            actors=actors,
            active_hazards=active_hazards,
            break_concentration=adapters.break_concentration,
            is_smite_setup_action=adapters.is_smite_setup_action,
        )

    return SpellPipelineOutcome(
        status="resolved",
        cast_frame=cast_frame,
        result=SpellPipelineResult(
            action=action,
            spell_level=spell_level,
            spell_cast_request=resolved_spell_cast_request,
            spell_declared_for_resolution=True,
            cast_frame=cast_frame,
        ),
    )


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
    obstacles: list[Any] | None = None,
    reaction_decision_provider: ReactionDecisionProvider | None = None,
    telemetry: list[dict[str, Any]] | None = None,
) -> SpellPipelineResult | None:
    return run_spell_declaration_pipeline_outcome(
        rng=rng,
        actor=actor,
        action=action,
        targets=targets,
        actors=actors,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
        round_number=round_number,
        turn_token=turn_token,
        timing_engine=timing_engine,
        spell_cast_request=spell_cast_request,
        antimagic_suppression_condition=antimagic_suppression_condition,
        subtle_spell=subtle_spell,
        light_level=light_level,
        adapters=adapters,
        obstacles=obstacles,
        reaction_decision_provider=reaction_decision_provider,
        telemetry=telemetry,
    ).result
