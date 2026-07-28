from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import replace
from typing import Any, Callable

from dnd_sim.models import ActionDefinition
from dnd_sim.strategy_api import (
    BattleStateView,
    ReactionDecision,
    ReactionDecisionProvider,
    ReactionOptionView,
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


_REACTION_ID_SCHEMA = "dnd_sim.reaction_id.v1"


def _opaque_reaction_id(
    *,
    entity: str,
    kind: str,
    identity: dict[str, Any],
) -> str:
    """Return a stable opaque ID from a canonical, typed identity payload."""

    encoded = json.dumps(
        {
            "schema": _REACTION_ID_SCHEMA,
            "entity": entity,
            "kind": kind,
            "identity": identity,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    prefix = "rw1" if entity == "window" else "ro1"
    return f"{prefix}_{digest}"


def _reaction_action_identity(
    *,
    action: ActionDefinition,
    reach_ft: float,
) -> dict[str, Any]:
    return {
        "attack_profile_id": (
            str(action.attack_profile_id).strip() if action.attack_profile_id is not None else None
        ),
        "name": str(action.name),
        "action_type": str(action.action_type),
        "action_cost": str(action.action_cost),
        "attack_delivery": action.attack_delivery,
        "target_mode": str(action.target_mode),
        "attack_bonus": action.to_hit,
        "damage_expression": action.damage,
        "damage_type": str(action.damage_type),
        "reach_ft": float(reach_ft),
        "max_uses": action.max_uses,
        "recharge": action.recharge,
        "tags": sorted(str(tag) for tag in action.tags),
        "resource_cost": [
            [str(key), int(amount)]
            for key, amount in sorted(action.resource_cost.items())
            if int(amount) > 0
        ],
    }


def _reaction_option_id(
    *,
    kind: str,
    window_id: str,
    reactor_id: str,
    fixed_target_ids: tuple[str, ...],
    option_index: int,
    action: ActionDefinition,
    reach_ft: float,
) -> str:
    return _opaque_reaction_id(
        entity="option",
        kind=kind,
        identity={
            "window_id": window_id,
            "reactor_id": reactor_id,
            "fixed_target_ids": list(fixed_target_ids),
            "option_index": int(option_index),
            "action": _reaction_action_identity(action=action, reach_ft=reach_ft),
        },
    )


def default_reaction_decision(window: ReactionWindowView) -> ReactionDecision:
    if not window.options:
        return ReactionDecision(window_id=window.window_id, choice="pass")
    if window.trigger.kind == "counterspell":
        from dnd_sim.spell_reaction_runtime import default_counterspell_reaction_decision

        return default_counterspell_reaction_decision(window)
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
            if window.trigger.kind in {"counterspell", "trait"}:
                safe_options = tuple(
                    option
                    for option in window.options
                    if not any(
                        target_id in state.actors and state.actors[target_id].team == actor.team
                        for target_id in option.fixed_target_ids
                    )
                )
                if not safe_options:
                    return ReactionDecision(window_id=window.window_id, choice="pass")
                return default_reaction_decision(replace(window, options=safe_options))
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
            message="This reaction option does not accept extra declared resource spend.",
        )
    legal_slot_levels = selected.legal_spell_slot_levels
    if legal_slot_levels and (
        type(decision.spell_slot_level) is not int
        or decision.spell_slot_level not in legal_slot_levels
    ):
        _reaction_decision_error(
            code="illegal_reaction_spell_slot",
            field="decision.spell_slot_level",
            message="Selected spell-slot level is not legal for this reaction option.",
            details={"legal_spell_slot_levels": list(legal_slot_levels)},
        )
    if not legal_slot_levels and decision.spell_slot_level is not None:
        _reaction_decision_error(
            code="illegal_reaction_spell_slot",
            field="decision.spell_slot_level",
            message="Selected reaction option does not accept a spell-slot override.",
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
            message="Reaction target is fixed by the trigger.",
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


def _reaction_correlation_telemetry(window: ReactionWindowView) -> dict[str, Any]:
    return {
        "reaction_chain_id": window.reaction_chain_id,
        "chain_depth": window.chain_depth,
        "incoming_cast_id": window.incoming_cast_id,
        "incoming_cast_ordinal": window.incoming_cast_ordinal,
        "parent_cast_id": window.parent_cast_id,
        "reactor_order": window.reactor_order,
        "incoming_action_identity": window.incoming_action_identity,
    }


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
            "trigger_action": window.trigger.action_name,
            "feature_name": window.trigger.feature_name,
            "feature_trigger": window.trigger.feature_trigger,
            "feature_source_type": window.trigger.feature_source_type,
            **_reaction_correlation_telemetry(window),
            "option_ids": [option.option_id for option in window.options],
            "options": [
                {
                    "option_id": option.option_id,
                    "legal_spell_slot_levels": list(option.legal_spell_slot_levels),
                    "effective_spell_level": option.effective_spell_level,
                    "resource_cost": dict(option.resource_cost),
                }
                for option in window.options
            ],
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
    raw_resource_spend = getattr(getattr(decision, "resource_spend", None), "amounts", None)
    telemetry.append(
        {
            "telemetry_type": "reaction_decision",
            "window_id": window.window_id,
            "reaction_kind": window.trigger.kind,
            "round": window.round_number,
            "turn_token": window.turn_token,
            "reactor_id": window.reactor_id,
            **_reaction_correlation_telemetry(window),
            "choice": str(getattr(decision, "choice", "")).strip().lower(),
            "option_id": getattr(decision, "option_id", None),
            "spell_slot_level": getattr(decision, "spell_slot_level", None),
            "resource_spend": (
                dict(sorted((str(key), amount) for key, amount in raw_resource_spend.items()))
                if isinstance(raw_resource_spend, dict)
                else {}
            ),
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
    spell_slot_level: int | None = None,
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
            **_reaction_correlation_telemetry(window),
            "status": status,
            "option_id": option_id,
            "reason": reason,
            "spell_slot_level": spell_slot_level,
        }
    )


record_reaction_window_opened = _reaction_window_telemetry
record_reaction_decision = _reaction_decision_telemetry
record_reaction_window_closed = _reaction_window_closed_telemetry
