from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import logging
import re
from typing import Literal

from dnd_sim.action_state_runtime import action_variant_state_key
from dnd_sim.models import ActionDefinition, ActorRuntimeState, SpellcastingAbility
from dnd_sim.reaction_decision_runtime import (
    _opaque_reaction_id,
    _reaction_action_identity,
)
from dnd_sim.spatial import distance_chebyshev
from dnd_sim.strategy_api import (
    ReactionDecision,
    ReactionOptionView,
    ReactionTriggerView,
    ReactionWindowView,
)
from dnd_sim.telemetry import build_event_envelope

logger = logging.getLogger(__name__)

_SLOT_RESOURCE = re.compile(r"(spell_slot|warlock_spell_slot)_(\d+)")
_SLOTLESS_TAGS = {"at-will", "at_will", "innate_spellcasting", "spellcasting:at_will"}
_SPELL_CAST_ID_SCHEMA = "dnd_sim.spell_cast_id.v1"


@dataclass(frozen=True, slots=True)
class SpellCastFrame:
    """Immutable identity and nesting context for one committed spell cast."""

    cast_id: str
    cast_ordinal: int
    reaction_chain_id: str
    parent_cast_id: str | None
    chain_depth: int
    caster_id: str
    action_identity: str
    spell_level: int
    target_actor_id: str | None


def _opaque_spell_cast_id(*, entity: str, identity: dict[str, object]) -> str:
    encoded = json.dumps(
        {
            "schema": _SPELL_CAST_ID_SCHEMA,
            "entity": entity,
            "identity": identity,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    prefix = "src1" if entity == "reaction_chain" else "sc1"
    return f"{prefix}_{hashlib.sha256(encoded).hexdigest()}"


def spell_action_identity(
    action: ActionDefinition,
    *,
    range_ft: float | None = None,
) -> str:
    """Return a canonical snapshot used by cast IDs and replay telemetry."""

    resolved_range = (
        float(range_ft)
        if range_ft is not None
        else float(action.range_ft or action.range_normal_ft or 0)
    )
    semantic_snapshot = asdict(action)
    semantic_snapshot["resolved_range_ft"] = resolved_range
    return json.dumps(
        semantic_snapshot,
        allow_nan=False,
        default=repr,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def action_spellcasting_ability(action: ActionDefinition) -> SpellcastingAbility | None:
    explicit = str(action.spellcasting_ability or "").strip().lower()
    if explicit in {"int", "wis", "cha"}:
        return explicit  # type: ignore[return-value]
    for raw_tag in action.tags:
        tag = str(raw_tag).strip().lower()
        for prefix in ("spellcasting_ability:", "casting_ability:"):
            if not tag.startswith(prefix):
                continue
            value = tag.split(":", 1)[1].strip()
            if value in {"int", "wis", "cha"}:
                return value  # type: ignore[return-value]
    return None


def build_root_spell_cast_frame(
    *,
    caster: ActorRuntimeState,
    action: ActionDefinition,
    spell_level: int,
    target_actor_id: str | None,
    cast_ordinal: int,
    round_number: int | None,
    turn_token: str | None,
) -> SpellCastFrame:
    action_identity = spell_action_identity(action)
    identity: dict[str, object] = {
        "round_number": round_number,
        "turn_token": turn_token,
        "cast_ordinal": int(cast_ordinal),
        "caster_id": caster.actor_id,
        "action_identity": action_identity,
        "spell_level": int(spell_level),
        "target_actor_id": target_actor_id,
        "parent_cast_id": None,
        "chain_depth": 0,
    }
    cast_id = _opaque_spell_cast_id(entity="cast", identity=identity)
    reaction_chain_id = _opaque_spell_cast_id(
        entity="reaction_chain",
        identity={"root_cast_id": cast_id},
    )
    return SpellCastFrame(
        cast_id=cast_id,
        cast_ordinal=int(cast_ordinal),
        reaction_chain_id=reaction_chain_id,
        parent_cast_id=None,
        chain_depth=0,
        caster_id=caster.actor_id,
        action_identity=action_identity,
        spell_level=int(spell_level),
        target_actor_id=target_actor_id,
    )


def build_child_spell_cast_frame(
    *,
    parent: SpellCastFrame,
    caster: ActorRuntimeState,
    action: ActionDefinition,
    spell_level: int,
    target_actor_id: str | None,
    cast_ordinal: int,
    range_ft: float | None = None,
) -> SpellCastFrame:
    action_identity = spell_action_identity(action, range_ft=range_ft)
    chain_depth = parent.chain_depth + 1
    identity: dict[str, object] = {
        "reaction_chain_id": parent.reaction_chain_id,
        "parent_cast_id": parent.cast_id,
        "chain_depth": chain_depth,
        "cast_ordinal": int(cast_ordinal),
        "caster_id": caster.actor_id,
        "action_identity": action_identity,
        "spell_level": int(spell_level),
        "target_actor_id": target_actor_id,
    }
    return SpellCastFrame(
        cast_id=_opaque_spell_cast_id(entity="cast", identity=identity),
        cast_ordinal=int(cast_ordinal),
        reaction_chain_id=parent.reaction_chain_id,
        parent_cast_id=parent.cast_id,
        chain_depth=chain_depth,
        caster_id=caster.actor_id,
        action_identity=action_identity,
        spell_level=int(spell_level),
        target_actor_id=target_actor_id,
    )


@dataclass(frozen=True, slots=True)
class CounterspellCandidate:
    """One action variant and one exact, already-affordable payment choice."""

    action: ActionDefinition
    action_index: int
    action_identity: str
    state_key: str
    effective_spell_level: int
    slot_resource_key: str | None
    slot_level: int | None
    resource_cost: tuple[tuple[str, int], ...]
    range_ft: float
    spellcasting_ability: SpellcastingAbility | None


def _positive_cost(action: ActionDefinition) -> dict[str, int]:
    return {
        str(key): int(amount) for key, amount in action.resource_cost.items() if int(amount) > 0
    }


def _tagged_level(action: ActionDefinition, prefix: str) -> int | None:
    for raw_tag in action.tags:
        tag = str(raw_tag).strip().lower()
        if not tag.startswith(prefix):
            continue
        try:
            level = int(tag.split(":", 1)[1])
        except (ValueError, IndexError):
            continue
        if level > 0:
            return level
    return None


def _counterspell_minimum_level(
    action: ActionDefinition,
    declared_slots: list[tuple[str, int, int]],
) -> int:
    metadata_level = 0
    if action.spell is not None:
        metadata_level = max(0, int(action.spell.level))
    if metadata_level <= 0:
        metadata_level = _tagged_level(action, "spell_level:") or 0

    declared_levels = [level for _key, level, _amount in declared_slots]
    if metadata_level > 0:
        # A pact key often represents the character's current Pact Magic slot level,
        # not the spell's declared minimum. Standard slot keys remain explicit floors.
        declared_floor = max(
            (level for key, level, _amount in declared_slots if key.startswith("spell_slot_")),
            default=0,
        )
    else:
        declared_floor = max(declared_levels, default=0)
    return max(3, metadata_level, declared_floor, _tagged_level(action, "upcast_level:") or 0)


def _can_pay(reactor: ActorRuntimeState, cost: tuple[tuple[str, int], ...]) -> bool:
    return all(int(reactor.resources.get(key, 0)) >= amount for key, amount in cost)


def _action_identity_snapshot(action: ActionDefinition, range_ft: float) -> str:
    return spell_action_identity(action, range_ft=range_ft)


def build_counterspell_candidates_for_action(
    *,
    reactor: ActorRuntimeState,
    action: ActionDefinition,
    action_index: int,
) -> list[CounterspellCandidate]:
    """Expand a Counterspell action into exact slot-pool payment candidates."""

    positive_cost = _positive_cost(action)
    declared_slots: list[tuple[str, int, int]] = []
    fixed_cost: dict[str, int] = {}
    for key, amount in positive_cost.items():
        match = _SLOT_RESOURCE.fullmatch(key)
        if match is None:
            fixed_cost[key] = amount
        else:
            declared_slots.append((key, int(match.group(2)), amount))

    minimum_level = _counterspell_minimum_level(action, declared_slots)
    normalized_tags = {str(tag).strip().lower() for tag in action.tags}
    slotless = bool(normalized_tags & _SLOTLESS_TAGS) and not declared_slots
    slot_amount = sum(amount for _key, _level, amount in declared_slots)
    if not slotless and slot_amount <= 0:
        # Compatibility for hand-authored spell actions that omitted the base slot cost.
        slot_amount = 1

    range_ft = float(action.range_ft or action.range_normal_ft or 60)
    action_identity = _action_identity_snapshot(action, range_ft)
    state_key = action_variant_state_key(
        reactor.actions,
        action,
        action_index=action_index,
    )
    spellcasting_ability = action_spellcasting_ability(action)
    if slotless:
        exact_cost = tuple(sorted(fixed_cost.items()))
        if not _can_pay(reactor, exact_cost):
            return []
        return [
            CounterspellCandidate(
                action=action,
                action_index=int(action_index),
                action_identity=action_identity,
                state_key=state_key,
                effective_spell_level=minimum_level,
                slot_resource_key=None,
                slot_level=None,
                resource_cost=exact_cost,
                range_ft=range_ft,
                spellcasting_ability=spellcasting_ability,
            )
        ]

    candidates: list[CounterspellCandidate] = []
    pools: list[tuple[int, str]] = []
    for resource_key, available in reactor.resources.items():
        match = _SLOT_RESOURCE.fullmatch(str(resource_key))
        if match is None or int(available) < slot_amount or int(match.group(2)) < minimum_level:
            continue
        pools.append((int(match.group(2)), str(resource_key)))
    for level, resource_key in sorted(pools):
        exact_cost = tuple(sorted({**fixed_cost, resource_key: slot_amount}.items()))
        if not _can_pay(reactor, exact_cost):
            continue
        candidates.append(
            CounterspellCandidate(
                action=action,
                action_index=int(action_index),
                action_identity=action_identity,
                state_key=state_key,
                effective_spell_level=level,
                slot_resource_key=resource_key,
                slot_level=level,
                resource_cost=exact_cost,
                range_ft=range_ft,
                spellcasting_ability=spellcasting_ability,
            )
        )
    return candidates


def _candidate_identity(candidate: CounterspellCandidate) -> dict[str, object]:
    return {
        "action_index": candidate.action_index,
        "action": json.loads(candidate.action_identity),
        "state_key": candidate.state_key,
        "effective_spell_level": candidate.effective_spell_level,
        "slot_resource_key": candidate.slot_resource_key,
        "slot_level": candidate.slot_level,
        "resource_cost": [list(item) for item in candidate.resource_cost],
        "range_ft": candidate.range_ft,
        "spellcasting_ability": candidate.spellcasting_ability,
    }


def default_counterspell_reaction_decision(window: ReactionWindowView) -> ReactionDecision:
    """Choose the cheapest option that guarantees success, including slotless casts."""

    if not window.options:
        return ReactionDecision(window_id=window.window_id, choice="pass")

    def effective_level(option: ReactionOptionView) -> int:
        if option.effective_spell_level is not None:
            return int(option.effective_spell_level)
        if option.legal_spell_slot_levels:
            return int(option.legal_spell_slot_levels[0])
        return 0

    def resource_burden(option: ReactionOptionView) -> tuple[int, int]:
        return (
            sum(max(0, int(amount)) for _key, amount in option.resource_cost),
            len(option.resource_cost),
        )

    incoming_level = max(0, int(window.trigger.spell_level or 0))
    guaranteed = [option for option in window.options if effective_level(option) >= incoming_level]
    selected = min(
        guaranteed or list(window.options),
        key=lambda option: (
            resource_burden(option),
            effective_level(option),
            option.resource_cost,
            option.option_id,
        ),
    )
    slot_level = (
        int(selected.legal_spell_slot_levels[0]) if selected.legal_spell_slot_levels else None
    )
    return ReactionDecision(
        window_id=window.window_id,
        choice="use",
        option_id=selected.option_id,
        spell_slot_level=slot_level,
        rationale={"reason": "default_counterspell_priority"},
    )


def build_counterspell_reaction_window(
    *,
    reactor: ActorRuntimeState,
    caster: ActorRuntimeState,
    spell_target: ActorRuntimeState | None,
    incoming_action: ActionDefinition,
    incoming_spell_level: int,
    candidates: list[CounterspellCandidate],
    round_number: int | None,
    turn_token: str | None,
    incoming_cast_frame: SpellCastFrame,
    reactor_order: int,
) -> ReactionWindowView:
    candidate_identities = [_candidate_identity(candidate) for candidate in candidates]
    window_id = _opaque_reaction_id(
        entity="window",
        kind="counterspell",
        identity={
            "round_number": round_number,
            "turn_token": turn_token,
            "incoming_cast_id": incoming_cast_frame.cast_id,
            "reaction_chain_id": incoming_cast_frame.reaction_chain_id,
            "chain_depth": incoming_cast_frame.chain_depth + 1,
            "reactor_order": int(reactor_order),
            "reactor_id": reactor.actor_id,
            "caster_id": caster.actor_id,
            "spell_target_id": spell_target.actor_id if spell_target is not None else None,
            "incoming_action": _reaction_action_identity(
                action=incoming_action,
                reach_ft=float(incoming_action.range_ft or 0),
            ),
            "incoming_spell_level": int(incoming_spell_level),
            "candidates": candidate_identities,
        },
    )
    options = tuple(
        ReactionOptionView(
            option_id=_opaque_reaction_id(
                entity="option",
                kind="counterspell",
                identity={
                    "window_id": window_id,
                    "reactor_id": reactor.actor_id,
                    "caster_id": caster.actor_id,
                    "candidate": identity,
                },
            ),
            action_name=candidate.action.name,
            fixed_target_ids=(caster.actor_id,),
            legal_target_ids=(caster.actor_id,),
            legal_spell_slot_levels=(
                (int(candidate.slot_level),) if candidate.slot_level is not None else ()
            ),
            effective_spell_level=int(candidate.effective_spell_level),
            resource_cost=candidate.resource_cost,
            reach_ft=candidate.range_ft,
        )
        for candidate, identity in zip(candidates, candidate_identities, strict=True)
    )
    return ReactionWindowView(
        window_id=window_id,
        reactor_id=reactor.actor_id,
        round_number=round_number,
        turn_token=turn_token,
        trigger=ReactionTriggerView(
            kind="counterspell",
            source_actor_id=caster.actor_id,
            target_actor_id=(spell_target.actor_id if spell_target is not None else None),
            action_name=incoming_action.name,
            spell_level=int(incoming_spell_level),
            distance_ft=float(distance_chebyshev(reactor.position, caster.position)),
        ),
        options=options,
        reaction_chain_id=incoming_cast_frame.reaction_chain_id,
        chain_depth=incoming_cast_frame.chain_depth + 1,
        incoming_cast_id=incoming_cast_frame.cast_id,
        incoming_cast_ordinal=incoming_cast_frame.cast_ordinal,
        parent_cast_id=incoming_cast_frame.parent_cast_id,
        reactor_order=int(reactor_order),
        incoming_action_identity=incoming_cast_frame.action_identity,
    )


def record_counterspell_resolution(
    telemetry: list[dict[str, object]] | None,
    *,
    window: ReactionWindowView,
    incoming_frame: SpellCastFrame,
    counterspell_frame: SpellCastFrame,
    candidate: CounterspellCandidate,
    option_id: str,
    resolution_method: Literal["automatic", "ability_check"],
    d20_roll: int | None,
    check_modifier: int | None,
    check_dc: int | None,
    check_total: int | None,
    outcome: Literal["countered", "counter_failed"],
) -> None:
    """Append one replay-safe resolution envelope for a paid Counterspell attempt."""

    if telemetry is None:
        return
    payload = {
        "reaction_kind": "counterspell",
        "round": window.round_number,
        "turn_token": window.turn_token,
        "reaction_chain_id": counterspell_frame.reaction_chain_id,
        "chain_depth": counterspell_frame.chain_depth,
        "parent_cast_id": counterspell_frame.parent_cast_id,
        "incoming_cast_id": incoming_frame.cast_id,
        "incoming_cast_ordinal": incoming_frame.cast_ordinal,
        "counterspell_cast_id": counterspell_frame.cast_id,
        "counterspell_cast_ordinal": counterspell_frame.cast_ordinal,
        "window_id": window.window_id,
        "reactor_id": window.reactor_id,
        "reactor_order": window.reactor_order,
        "source_actor_id": incoming_frame.caster_id,
        "target_actor_id": incoming_frame.target_actor_id,
        "trigger_action": window.trigger.action_name,
        "incoming_action_identity": incoming_frame.action_identity,
        "counterspell_action_identity": counterspell_frame.action_identity,
        "spell_level": incoming_frame.spell_level,
        "distance_ft": window.trigger.distance_ft,
        "option_id": option_id,
        "counterspell_spell_level": counterspell_frame.spell_level,
        "spellcasting_ability": candidate.spellcasting_ability,
        "spell_slot_level": candidate.slot_level,
        "spell_slot_resource_key": candidate.slot_resource_key,
        "resource_cost": dict(candidate.resource_cost),
        "resolution_method": resolution_method,
        "d20_roll": d20_roll,
        "check_modifier": check_modifier,
        "check_dc": check_dc,
        "check_total": check_total,
        "outcome": outcome,
    }
    telemetry.append(
        build_event_envelope(
            event_type="counterspell_resolution",
            payload=payload,
            source=__name__,
        )
    )
