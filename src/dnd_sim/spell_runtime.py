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
    CounterspellCandidate,
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


ReactionSpellCompletion = Callable[
    [ActorRuntimeState, ActionDefinition, ActorRuntimeState | None, SpellPipelineOutcome],
    None,
]


@dataclass(slots=True)
class CounterspellChainState:
    reaction_chain_id: str | None = None
    max_depth: int = 8
    max_attempts: int = 32
    attempts: int = 0

    def can_open_for(self, incoming_frame: SpellCastFrame) -> bool:
        same_chain = self.reaction_chain_id in {None, incoming_frame.reaction_chain_id}
        return (
            same_chain
            and incoming_frame.chain_depth < max(0, int(self.max_depth))
            and self.attempts < max(0, int(self.max_attempts))
        )

    def reserve_attempt(self, incoming_frame: SpellCastFrame) -> bool:
        if not self.can_open_for(incoming_frame):
            return False
        if self.reaction_chain_id is None:
            self.reaction_chain_id = incoming_frame.reaction_chain_id
        self.attempts += 1
        return True


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


def _declare_spell_cast_frame(
    *,
    actor: ActorRuntimeState,
    action: ActionDefinition,
    target: ActorRuntimeState | None,
    spell_level: int,
    round_number: int | None,
    turn_token: str | None,
    timing_engine: CombatTimingEngine,
    adapters: SpellPipelineAdapters,
    parent: SpellCastFrame | None = None,
    range_ft: float | None = None,
) -> SpellCastFrame | None:
    declaration = timing_engine.emit(
        ActionDeclaredEvent(
            attacker=actor,
            target=target,
            action=action,
            round_number=round_number,
            turn_token=turn_token,
        )
    )
    if declaration.cancelled:
        return None

    cast_ordinal = actor.next_spell_cast_ordinal
    actor.next_spell_cast_ordinal += 1
    if parent is None:
        frame = build_root_spell_cast_frame(
            caster=actor,
            action=action,
            spell_level=spell_level,
            target_actor_id=target.actor_id if target is not None else None,
            cast_ordinal=cast_ordinal,
            round_number=round_number,
            turn_token=turn_token,
        )
    else:
        frame = build_child_spell_cast_frame(
            parent=parent,
            caster=actor,
            action=action,
            spell_level=spell_level,
            target_actor_id=target.actor_id if target is not None else None,
            cast_ordinal=cast_ordinal,
            range_ft=range_ft,
        )
    record_spell_cast_for_turn(
        actor,
        action,
        is_action_cantrip_spell=adapters.is_action_cantrip_spell,
    )
    return frame


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


def can_cast_spell_with_components(
    actor: ActorRuntimeState,
    action: ActionDefinition,
    *,
    has_trait: Callable[[ActorRuntimeState, str], bool],
) -> bool:
    if "spell" not in action.tags:
        return True
    components = action_component_tags(action)
    if not components:
        return True
    if "component:verbal" in components and actor.conditions.intersection(
        {"silenced", "gagged", "mute"}
    ):
        return False

    has_free_hand = int(actor.resources.get("free_hands", 1)) > 0
    has_focus = bool(actor.resources.get("spellcasting_focus", 0)) or has_trait(
        actor, "spellcasting focus"
    )
    needs_material = "component:material" in components
    needs_somatic = "component:somatic" in components
    if needs_material and not (has_focus or has_free_hand):
        return False
    if needs_somatic and not has_free_hand and not has_trait(actor, "war caster"):
        if not (needs_material and has_focus):
            return False
    return True


def _spell_cast_is_observable(action: ActionDefinition, *, subtle_spell: bool) -> bool:
    if not subtle_spell:
        return True
    return "component:material" in action_component_tags(action)


def _action_uses_subtle_spell(action: ActionDefinition) -> bool:
    return any(str(tag).strip().lower() == "metamagic:subtle" for tag in action.tags)


def _counterspell_candidates_for_reactor(
    *,
    reactor: ActorRuntimeState,
    caster: ActorRuntimeState,
    incoming_spell_level: int,
    turn_token: str | None,
    active_hazards: list[dict[str, Any]],
    light_level: str,
    obstacles: list[Any] | None,
    adapters: SpellPipelineAdapters,
) -> list[CounterspellCandidate]:
    candidates: list[CounterspellCandidate] = []
    for action_index, counterspell_action in enumerate(reactor.actions):
        if counterspell_action.action_cost != "reaction" or not (
            adapters.action_matches_reaction_spell_id(counterspell_action, "counterspell")
        ):
            continue
        for candidate in build_counterspell_candidates_for_action(
            reactor=reactor,
            action=counterspell_action,
            action_index=action_index,
        ):
            if adapters.counterspell_candidate_is_legal(
                reactor=reactor,
                candidate=candidate,
                caster=caster,
                incoming_spell_level=incoming_spell_level,
                turn_token=turn_token,
                active_hazards=active_hazards,
                light_level=light_level,
                obstacles=obstacles,
            ):
                candidates.append(candidate)
    return candidates


def _live_counterspell_candidate(
    *,
    reactor: ActorRuntimeState,
    selected: CounterspellCandidate,
    caster: ActorRuntimeState,
    incoming_spell_level: int,
    turn_token: str | None,
    active_hazards: list[dict[str, Any]],
    light_level: str,
    obstacles: list[Any] | None,
    adapters: SpellPipelineAdapters,
) -> CounterspellCandidate | None:
    action_index = selected.action_index
    if not (
        0 <= action_index < len(reactor.actions)
        and reactor.actions[action_index] is selected.action
    ):
        return None
    live = next(
        (
            candidate
            for candidate in build_counterspell_candidates_for_action(
                reactor=reactor,
                action=selected.action,
                action_index=action_index,
            )
            if candidate == selected
        ),
        None,
    )
    if live is None:
        return None
    if not adapters.counterspell_candidate_is_legal(
        reactor=reactor,
        candidate=live,
        caster=caster,
        incoming_spell_level=incoming_spell_level,
        turn_token=turn_token,
        active_hazards=active_hazards,
        light_level=light_level,
        obstacles=obstacles,
    ):
        return None
    return live


def _counterspell_reactions_counter_incoming(
    *,
    rng: random.Random,
    caster: ActorRuntimeState,
    incoming_action: ActionDefinition,
    incoming_spell_level: int,
    spell_target: ActorRuntimeState | None,
    incoming_frame: SpellCastFrame,
    incoming_subtle_spell: bool,
    actors: dict[str, ActorRuntimeState],
    resources_spent: dict[str, dict[str, int]],
    active_hazards: list[dict[str, Any]],
    round_number: int | None,
    turn_token: str | None,
    timing_engine: CombatTimingEngine,
    light_level: str,
    adapters: SpellPipelineAdapters,
    obstacles: list[Any] | None,
    reaction_decision_provider: ReactionDecisionProvider | None,
    telemetry: list[dict[str, Any]] | None,
    chain_state: CounterspellChainState,
    on_reaction_spell_complete: ReactionSpellCompletion | None,
) -> SpellCastFrame | None:
    """Resolve a bounded chain and return the Counterspell that defeats the cast."""

    if not chain_state.can_open_for(incoming_frame) or not _spell_cast_is_observable(
        incoming_action,
        subtle_spell=incoming_subtle_spell,
    ):
        return None

    from dnd_sim.reaction_decision_runtime import (
        ReactionDecisionValidationError,
        default_reaction_decision,
        record_reaction_decision,
        record_reaction_window_closed,
        record_reaction_window_opened,
        validate_reaction_decision,
    )

    reactor_order = 0
    for reactor in sorted(actors.values(), key=lambda candidate: candidate.actor_id):
        if not chain_state.can_open_for(incoming_frame):
            break
        if (
            reactor.actor_id == caster.actor_id
            or reactor.hp <= 0
            or reactor.dead
            or not adapters.can_take_reaction(reactor)
        ):
            continue
        candidates = _counterspell_candidates_for_reactor(
            reactor=reactor,
            caster=caster,
            incoming_spell_level=incoming_spell_level,
            turn_token=turn_token,
            active_hazards=active_hazards,
            light_level=light_level,
            obstacles=obstacles,
            adapters=adapters,
        )
        if not candidates:
            continue

        counter_window = timing_engine.emit(
            ReactionWindowOpenedEvent(
                window="counterspell",
                reactor=reactor,
                attacker=caster,
                target=spell_target if spell_target is not None else caster,
                action=incoming_action,
                round_number=round_number,
                turn_token=turn_token,
            )
        )
        if counter_window.cancelled:
            continue

        window = build_counterspell_reaction_window(
            reactor=reactor,
            caster=caster,
            spell_target=spell_target,
            incoming_action=incoming_action,
            incoming_spell_level=incoming_spell_level,
            candidates=candidates,
            round_number=round_number,
            turn_token=turn_token,
            incoming_cast_frame=incoming_frame,
            reactor_order=reactor_order,
        )
        reactor_order += 1
        record_reaction_window_opened(telemetry, window=window)
        if reaction_decision_provider is not None:
            decision = reaction_decision_provider(window)
        elif reactor.team == caster.team:
            decision = ReactionDecision(window_id=window.window_id, choice="pass")
        else:
            decision = default_reaction_decision(window)
        record_reaction_decision(telemetry, window=window, decision=decision)
        try:
            selected_option, _ = validate_reaction_decision(window, decision)
        except ReactionDecisionValidationError as exc:
            record_reaction_window_closed(
                telemetry,
                window=window,
                status="rejected",
                option_id=getattr(decision, "option_id", None),
                reason=exc.code,
                spell_slot_level=getattr(decision, "spell_slot_level", None),
            )
            raise
        if selected_option is None:
            record_reaction_window_closed(telemetry, window=window, status="passed")
            continue

        selected_index = next(
            index
            for index, option in enumerate(window.options)
            if option.option_id == selected_option.option_id
        )
        selected_candidate = candidates[selected_index]
        live_candidate = _live_counterspell_candidate(
            reactor=reactor,
            selected=selected_candidate,
            caster=caster,
            incoming_spell_level=incoming_spell_level,
            turn_token=turn_token,
            active_hazards=active_hazards,
            light_level=light_level,
            obstacles=obstacles,
            adapters=adapters,
        )
        if live_candidate is None:
            record_reaction_window_closed(
                telemetry,
                window=window,
                status="unavailable",
                option_id=selected_option.option_id,
                reason="state_changed",
                spell_slot_level=selected_candidate.slot_level,
            )
            continue
        if (
            live_candidate.effective_spell_level < incoming_spell_level
            and live_candidate.spellcasting_ability is None
        ):
            record_reaction_window_closed(
                telemetry,
                window=window,
                status="unavailable",
                option_id=selected_option.option_id,
                reason="missing_spellcasting_ability",
                spell_slot_level=live_candidate.slot_level,
            )
            continue
        if not chain_state.reserve_attempt(incoming_frame):
            record_reaction_window_closed(
                telemetry,
                window=window,
                status="unavailable",
                option_id=selected_option.option_id,
                reason="counterspell_chain_limit",
                spell_slot_level=live_candidate.slot_level,
            )
            break

        counterspell_action = live_candidate.action
        counter_level = live_candidate.effective_spell_level
        reactor_spent = resources_spent.setdefault(reactor.actor_id, {})
        for key, amount in adapters.spend_resources(
            reactor,
            dict(live_candidate.resource_cost),
        ).items():
            reactor_spent[key] = reactor_spent.get(key, 0) + amount
        state_key = live_candidate.state_key
        reactor.per_action_uses[state_key] = reactor.per_action_uses.get(state_key, 0) + 1
        if counterspell_action.recharge:
            reactor.recharge_ready[state_key] = False
        adapters.mark_action_cost_used(reactor, counterspell_action)

        counterspell_frame = _declare_spell_cast_frame(
            actor=reactor,
            action=counterspell_action,
            target=caster,
            spell_level=counter_level,
            round_number=round_number,
            turn_token=turn_token,
            timing_engine=timing_engine,
            adapters=adapters,
            parent=incoming_frame,
            range_ft=live_candidate.range_ft,
        )
        if counterspell_frame is None:
            record_reaction_window_closed(
                telemetry,
                window=window,
                status="cancelled",
                option_id=selected_option.option_id,
                reason="action_declaration_cancelled",
                spell_slot_level=live_candidate.slot_level,
            )
            continue

        countering_frame = _counterspell_reactions_counter_incoming(
            rng=rng,
            caster=reactor,
            incoming_action=counterspell_action,
            incoming_spell_level=counter_level,
            spell_target=caster,
            incoming_frame=counterspell_frame,
            incoming_subtle_spell=_action_uses_subtle_spell(counterspell_action),
            actors=actors,
            resources_spent=resources_spent,
            active_hazards=active_hazards,
            round_number=round_number,
            turn_token=turn_token,
            timing_engine=timing_engine,
            light_level=light_level,
            adapters=adapters,
            obstacles=obstacles,
            reaction_decision_provider=reaction_decision_provider,
            telemetry=telemetry,
            chain_state=chain_state,
            on_reaction_spell_complete=on_reaction_spell_complete,
        )
        if countering_frame is not None:
            record_counterspell_resolution(
                telemetry,
                window=window,
                incoming_frame=incoming_frame,
                counterspell_frame=counterspell_frame,
                candidate=live_candidate,
                option_id=selected_option.option_id,
                resolution_method="interrupted",
                d20_roll=None,
                check_modifier=None,
                check_dc=None,
                check_total=None,
                outcome="counterspell_countered",
                countered_by_cast_id=countering_frame.cast_id,
            )
            record_reaction_window_closed(
                telemetry,
                window=window,
                status="resolved",
                option_id=selected_option.option_id,
                reason="counterspell_countered",
                spell_slot_level=live_candidate.slot_level,
            )
            if on_reaction_spell_complete is not None:
                on_reaction_spell_complete(
                    reactor,
                    counterspell_action,
                    caster,
                    SpellPipelineOutcome(status="countered", cast_frame=counterspell_frame),
                )
            continue

        resolution_method: Literal["automatic", "ability_check"]
        d20_roll: int | None = None
        check_modifier: int | None = None
        check_dc: int | None = None
        check_total: int | None = None
        countered = counter_level >= incoming_spell_level
        if countered:
            resolution_method = "automatic"
        else:
            resolution_method = "ability_check"
            spellcasting_ability = live_candidate.spellcasting_ability
            assert spellcasting_ability is not None
            check_dc = 10 + incoming_spell_level
            d20_roll = rng.randint(1, 20)
            check_modifier = adapters.spellcasting_ability_mod(reactor, spellcasting_ability)
            check_total = d20_roll + check_modifier
            countered = check_total >= check_dc
        outcome = "countered" if countered else "counter_failed"
        record_counterspell_resolution(
            telemetry,
            window=window,
            incoming_frame=incoming_frame,
            counterspell_frame=counterspell_frame,
            candidate=live_candidate,
            option_id=selected_option.option_id,
            resolution_method=resolution_method,
            d20_roll=d20_roll,
            check_modifier=check_modifier,
            check_dc=check_dc,
            check_total=check_total,
            outcome=outcome,
        )
        record_reaction_window_closed(
            telemetry,
            window=window,
            status="resolved",
            option_id=selected_option.option_id,
            reason=outcome,
            spell_slot_level=live_candidate.slot_level,
        )
        if on_reaction_spell_complete is not None:
            on_reaction_spell_complete(
                reactor,
                counterspell_action,
                caster,
                SpellPipelineOutcome(status="resolved", cast_frame=counterspell_frame),
            )
        if countered:
            return counterspell_frame
    return None


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
    counterspell_chain_state: CounterspellChainState | None = None,
    on_reaction_spell_complete: ReactionSpellCompletion | None = None,
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

    cast_frame = _declare_spell_cast_frame(
        actor=actor,
        action=action,
        target=targets[0] if targets else None,
        spell_level=spell_level,
        round_number=round_number,
        turn_token=turn_token,
        timing_engine=timing_engine,
        adapters=adapters,
    )
    if cast_frame is None:
        return SpellPipelineOutcome(status="cancelled")

    chain_state = counterspell_chain_state or CounterspellChainState()
    if chain_state.reaction_chain_id is None:
        chain_state.reaction_chain_id = cast_frame.reaction_chain_id
    if _counterspell_reactions_counter_incoming(
        rng=rng,
        caster=actor,
        incoming_action=action,
        incoming_spell_level=spell_level,
        spell_target=targets[0] if targets else None,
        incoming_frame=cast_frame,
        incoming_subtle_spell=subtle_spell,
        actors=actors,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
        round_number=round_number,
        turn_token=turn_token,
        timing_engine=timing_engine,
        light_level=light_level,
        adapters=adapters,
        obstacles=obstacles,
        reaction_decision_provider=reaction_decision_provider,
        telemetry=telemetry,
        chain_state=chain_state,
        on_reaction_spell_complete=on_reaction_spell_complete,
    ):
        return SpellPipelineOutcome(status="countered", cast_frame=cast_frame)

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
