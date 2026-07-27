"""Fixed-roster encounter orchestration for interactive D&D combat turns."""

from __future__ import annotations

import json
import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

import dnd_sim.engine_runtime as engine_runtime
from dnd_sim.turn_kernel import CombatTurnContext, CombatTurnPrompt

from .contracts import (
    EngineVersionPins,
    EventDraft,
    JSONValue,
    PendingReaction,
    PreviewOutcome,
    SessionCommand,
    normalize_json,
)
from .dnd_contracts import DECLARATION_COMMAND_KIND
from .dnd_turn_driver import (
    PREPARE_TURN_COMMAND_KIND,
    DndCombatTurnDriver,
    DndCombatTurnState,
)
from .session import EngineSessionError, EngineTransition

DND_ENCOUNTER_STATE_SCHEMA_VERSION = "dnd.combat-encounter-state.v1"
START_ENCOUNTER_COMMAND_KIND = "dnd.start_encounter.v1"

EncounterOutcome = Literal["party_victory", "enemy_victory", "timeout"]

_STATE_FIELDS = frozenset(
    {
        "schema_version",
        "current_index",
        "max_rounds",
        "outcome",
        "turn",
    }
)
_OUTCOMES = frozenset({"party_victory", "enemy_victory", "timeout"})


@dataclass(slots=True)
class DndCombatEncounterState:
    """Durable encounter cursor wrapped around one prompt-bound actor turn."""

    turn: DndCombatTurnState
    current_index: int = 0
    max_rounds: int = 20
    outcome: EncounterOutcome | None = None


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _normalized_object(value: Any, *, path: str) -> dict[str, JSONValue]:
    normalized = normalize_json(value, path=path)
    if not isinstance(normalized, dict):
        raise ValueError(f"{path} must be a JSON object")
    return normalized


def _exact_keys(payload: Mapping[str, Any], expected: frozenset[str], *, path: str) -> None:
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(
            f"{path} has noncanonical fields; missing={missing}, unexpected={unexpected}"
        )


def _strict_int(value: Any, *, path: str, minimum: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{path} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{path} must be >= {minimum}")
    return value


class DndCombatEncounterDriver:
    """Advance a fixed initiative roster between durable declaration prompts."""

    def __init__(self, *, version_pins: EngineVersionPins) -> None:
        self.version_pins = EngineVersionPins.model_validate(version_pins.model_dump(mode="json"))
        self._turn_driver = DndCombatTurnDriver(version_pins=self.version_pins)

    def encode_state(self, state: DndCombatEncounterState) -> Mapping[str, Any]:
        if not isinstance(state, DndCombatEncounterState):
            raise TypeError("state must be DndCombatEncounterState")
        self._validate_state(state)
        payload = {
            "schema_version": DND_ENCOUNTER_STATE_SCHEMA_VERSION,
            "current_index": state.current_index,
            "max_rounds": state.max_rounds,
            "outcome": state.outcome,
            "turn": self._turn_driver.encode_state(state.turn),
        }
        normalized = normalize_json(payload, path="state")
        if not isinstance(normalized, dict):  # pragma: no cover - statically an object
            raise ValueError("state must encode to a JSON object")
        return normalized

    def decode_state(self, payload: Mapping[str, Any]) -> DndCombatEncounterState:
        normalized = _normalized_object(payload, path="state")
        _exact_keys(normalized, _STATE_FIELDS, path="state")
        if normalized["schema_version"] != DND_ENCOUNTER_STATE_SCHEMA_VERSION:
            raise ValueError("unsupported D&D encounter state schema_version")

        turn_payload = normalized["turn"]
        if not isinstance(turn_payload, dict):
            raise ValueError("turn must be a JSON object")
        outcome = normalized["outcome"]
        if outcome is not None and outcome not in _OUTCOMES:
            raise ValueError("outcome must be party_victory, enemy_victory, timeout, or null")
        state = DndCombatEncounterState(
            turn=self._turn_driver.decode_state(turn_payload),
            current_index=_strict_int(
                normalized["current_index"],
                path="current_index",
                minimum=0,
            ),
            max_rounds=_strict_int(
                normalized["max_rounds"],
                path="max_rounds",
                minimum=1,
            ),
            outcome=cast(EncounterOutcome | None, outcome),
        )
        self._validate_state(state)
        canonical = self.encode_state(state)
        if _canonical_json(canonical) != _canonical_json(normalized):
            raise ValueError("state payload is not the full canonical D&D encounter state")
        return state

    def preview(
        self,
        state: DndCombatEncounterState,
        command: SessionCommand,
        rng: random.Random,
    ) -> PreviewOutcome:
        events = self._apply_command(state, command, rng)
        return PreviewOutcome(
            projection=self.project_state(state),
            events=tuple(events),
        )

    def commit(
        self,
        state: DndCombatEncounterState,
        command: SessionCommand,
        rng: random.Random,
    ) -> EngineTransition:
        events = self._apply_command(state, command, rng)
        return EngineTransition(state=state, events=tuple(events))

    def respond_to_reaction(
        self,
        state: DndCombatEncounterState,
        command: SessionCommand,
        pending_reaction: PendingReaction,
        rng: random.Random,
    ) -> EngineTransition:
        del state, command, pending_reaction, rng
        raise EngineSessionError(
            "unsupported_reaction",
            "This D&D encounter driver version auto-resolves reactions.",
        )

    def _apply_command(
        self,
        state: DndCombatEncounterState,
        command: SessionCommand,
        rng: random.Random,
    ) -> list[EventDraft]:
        self._validate_state(state)
        if state.outcome is not None:
            raise EngineSessionError(
                "encounter_complete",
                "This encounter is already complete.",
                details={"outcome": state.outcome},
            )

        if command.kind == START_ENCOUNTER_COMMAND_KIND:
            events = self._apply_start(state, command, rng)
        elif command.kind == DECLARATION_COMMAND_KIND:
            events = self._apply_declaration(state, command, rng)
        else:
            raise EngineSessionError(
                "unsupported_command",
                "The D&D encounter driver only accepts start or declaration commands.",
                details={"kind": command.kind},
            )
        self._validate_state(state)
        return events

    def _apply_start(
        self,
        state: DndCombatEncounterState,
        command: SessionCommand,
        rng: random.Random,
    ) -> list[EventDraft]:
        if (
            state.turn.phase != "unprepared"
            or state.current_index != 0
            or state.turn.context.round_number != 1
        ):
            raise EngineSessionError(
                "encounter_already_started",
                "The encounter can only be started from its initial cursor.",
            )
        if command.mode != "admin":
            raise EngineSessionError(
                "unsupported_command_mode",
                "Encounter start requires admin mode.",
            )
        if command.actor_id is not None:
            raise EngineSessionError(
                "actor_mismatch",
                "Encounter start is an actor-independent admin command.",
                details={"received_actor_id": command.actor_id},
            )
        if command.payload:
            raise EngineSessionError(
                "invalid_command_payload",
                "Encounter start requires an empty payload.",
            )

        events = [
            EventDraft(
                kind="dnd.encounter.started",
                payload={
                    "active_actor_id": state.turn.actor_id,
                    "initiative_order": list(state.turn.context.initiative_order),
                    "round_number": state.turn.context.round_number,
                },
            )
        ]
        self._drive_to_prompt_or_terminal(state, command, rng, events)
        return events

    def _apply_declaration(
        self,
        state: DndCombatEncounterState,
        command: SessionCommand,
        rng: random.Random,
    ) -> list[EventDraft]:
        before_roster = self._roster_signature(state.turn.context)
        result = self._turn_driver.resolve_declaration(state.turn, command, rng)
        self._require_roster(state.turn.context, before_roster)
        events = [
            EventDraft(
                kind="dnd.turn.resolved",
                payload=self._turn_driver.result_payload(result),
            )
        ]
        self._drive_to_prompt_or_terminal(state, command, rng, events)
        return events

    def _drive_to_prompt_or_terminal(
        self,
        state: DndCombatEncounterState,
        command: SessionCommand,
        rng: random.Random,
        events: list[EventDraft],
    ) -> None:
        while True:
            if state.turn.phase == "unprepared":
                prepare_command = command.model_copy(
                    update={
                        "actor_id": state.turn.actor_id,
                        "mode": "admin",
                        "kind": PREPARE_TURN_COMMAND_KIND,
                        "payload": {},
                    }
                )
                before_roster = self._roster_signature(state.turn.context)
                prepared = self._turn_driver.prepare_turn(
                    state.turn,
                    prepare_command,
                    rng,
                )
                self._require_roster(state.turn.context, before_roster)
                if isinstance(prepared, CombatTurnPrompt):
                    events.append(
                        EventDraft(
                            kind="dnd.turn.prepared",
                            payload=self._turn_driver.prompt_payload(prepared),
                        )
                    )
                    return
                events.append(
                    EventDraft(
                        kind="dnd.turn.completed_automatically",
                        payload=self._turn_driver.result_payload(prepared),
                    )
                )

            self._finish_completed_turn(state)
            if state.outcome is not None:
                events.append(
                    EventDraft(
                        kind="dnd.encounter.completed",
                        payload=self._completion_payload(state),
                    )
                )
                return

    def _finish_completed_turn(self, state: DndCombatEncounterState) -> None:
        if state.turn.phase != "complete":
            raise RuntimeError("encounter cursor can only advance after a complete turn")
        context = state.turn.context
        victory = self._victory_outcome(context)
        if victory is not None:
            state.outcome = victory
            return

        final_index = len(context.initiative_order) - 1
        if state.current_index == final_index:
            if context.round_number >= state.max_rounds:
                state.outcome = "timeout"
                return
            context.round_number += 1
            for actor in context.actors.values():
                actor.lair_action_used_this_round = False
                actor.commanded_this_round = False
            state.current_index = 0
        else:
            state.current_index += 1

        state.turn = DndCombatTurnState(
            context=context,
            actor_id=context.initiative_order[state.current_index],
        )

    def _validate_state(self, state: DndCombatEncounterState) -> None:
        if not isinstance(state.turn, DndCombatTurnState):
            raise TypeError("state.turn must be DndCombatTurnState")
        _strict_int(state.current_index, path="current_index", minimum=0)
        _strict_int(state.max_rounds, path="max_rounds", minimum=1)
        context = state.turn.context
        self._turn_driver.encode_state(state.turn)
        if state.current_index >= len(context.initiative_order):
            raise ValueError("current_index must identify an initiative_order slot")
        if state.turn.actor_id != context.initiative_order[state.current_index]:
            raise ValueError("active turn actor must match the encounter cursor")
        if context.round_number > state.max_rounds:
            raise ValueError("round_number must not exceed max_rounds")
        self._reject_lair_actions(context)

        victory = self._victory_outcome(context)
        if state.outcome is None:
            if victory is not None:
                raise ValueError("nonterminal encounter state already satisfies a victory rule")
            if state.turn.phase == "complete":
                raise ValueError("nonterminal encounter state cannot contain a complete turn")
            return

        if state.outcome not in _OUTCOMES:
            raise ValueError("outcome is unsupported")
        if state.turn.phase != "complete":
            raise ValueError("terminal encounter state requires a complete turn")
        if victory is not None:
            if state.outcome != victory:
                raise ValueError("encounter outcome does not match the satisfied victory rule")
            return
        if state.outcome != "timeout":
            raise ValueError("victory outcome requires a satisfied victory rule")
        if (
            context.round_number != state.max_rounds
            or state.current_index != len(context.initiative_order) - 1
        ):
            raise ValueError("timeout requires the final slot of the final round")

    @staticmethod
    def _reject_lair_actions(context: CombatTurnContext) -> None:
        if any(
            str(action.action_cost).strip().lower() == "lair"
            for actor in context.actors.values()
            for action in actor.actions
        ):
            raise ValueError("lair actions are unsupported in encounter state v1")

    @staticmethod
    def _roster_signature(context: CombatTurnContext) -> tuple[tuple[str, ...], frozenset[str]]:
        return (tuple(context.initiative_order), frozenset(context.actors))

    @staticmethod
    def _require_roster(
        context: CombatTurnContext,
        expected: tuple[tuple[str, ...], frozenset[str]],
    ) -> None:
        if DndCombatEncounterDriver._roster_signature(context) != expected:
            raise EngineSessionError(
                "fixed_roster_violation",
                "Encounter v1 does not allow actors or initiative slots to change.",
            )

    @staticmethod
    def _victory_outcome(context: CombatTurnContext) -> EncounterOutcome | None:
        if engine_runtime._party_defeated(
            context.actors,
            context.party_defeat_rule,
        ):
            return "enemy_victory"
        if engine_runtime._enemies_defeated(
            context.actors,
            context.enemy_defeat_rule,
        ):
            return "party_victory"
        return None

    @staticmethod
    def _completion_payload(state: DndCombatEncounterState) -> dict[str, JSONValue]:
        winner: str | None
        if state.outcome == "party_victory":
            winner = "party"
        elif state.outcome == "enemy_victory":
            winner = "enemy"
        else:
            winner = None
        return {
            "outcome": state.outcome,
            "winner": winner,
            "round_number": state.turn.context.round_number,
            "current_index": state.current_index,
        }

    def project_state(self, state: DndCombatEncounterState) -> dict[str, JSONValue]:
        context = state.turn.context
        if state.outcome is not None:
            phase = "terminal"
            active_actor_id = None
        elif state.turn.phase == "unprepared":
            phase = "unstarted"
            active_actor_id = state.turn.actor_id
        else:
            phase = "awaiting_declaration"
            active_actor_id = state.turn.actor_id
        winner = self._completion_payload(state)["winner"]
        prompt = (
            self._turn_driver.prompt_payload(state.turn.prompt)
            if state.turn.prompt is not None
            else None
        )
        result = (
            self._turn_driver.result_payload(state.turn.last_result)
            if state.turn.last_result is not None
            else None
        )
        return {
            "phase": phase,
            "outcome": state.outcome,
            "winner": winner,
            "current_index": state.current_index,
            "active_actor_id": active_actor_id,
            "round_number": context.round_number,
            "max_rounds": state.max_rounds,
            "initiative_order": list(context.initiative_order),
            "actors": {
                actor_id: self._turn_driver.project_actor(context.actors[actor_id])
                for actor_id in sorted(context.actors)
            },
            "prompt": prompt,
            "result": result,
            "choices": self._turn_driver.project_choices(state.turn),
        }
