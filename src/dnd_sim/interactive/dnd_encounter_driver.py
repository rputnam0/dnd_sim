"""Fixed-roster encounter orchestration for interactive D&D combat turns."""

from __future__ import annotations

import json
import logging
import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, NoReturn, cast

import dnd_sim.engine_runtime as engine_runtime
from dnd_sim.roll_journal import EngineRollJournalRecorder
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

logger = logging.getLogger(__name__)

DND_ENCOUNTER_STATE_SCHEMA_VERSION = "dnd.combat-encounter-state.v1"
START_ENCOUNTER_COMMAND_KIND = "dnd.start_encounter.v1"
COMBAT_CONTROL_COMMAND_KIND = "dnd.combat.control.v1"

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
        elif command.kind == COMBAT_CONTROL_COMMAND_KIND:
            events = self._apply_combat_control(state, command, rng)
        else:
            raise EngineSessionError(
                "unsupported_command",
                "The D&D encounter driver does not support this command.",
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

    def _apply_combat_control(
        self,
        state: DndCombatEncounterState,
        command: SessionCommand,
        rng: random.Random,
    ) -> list[EventDraft]:
        if command.mode != "admin":
            raise EngineSessionError(
                "unsupported_command_mode",
                "Combat tracker changes require admin mode.",
            )
        if command.actor_id is not None:
            raise EngineSessionError(
                "actor_mismatch",
                "Combat tracker changes are actor-independent admin commands.",
            )
        operation = command.payload.get("operation")
        if operation == "advance":
            return self._apply_cursor_advance(state, command, rng)
        if operation == "reorder":
            return self._apply_initiative_reorder(state, command)
        if operation == "delay":
            return self._apply_delay(state, command, rng)
        if operation == "override":
            return self._apply_cursor_override(state, command, rng)
        self._invalid_control()

    def _apply_cursor_advance(
        self,
        state: DndCombatEncounterState,
        command: SessionCommand,
        rng: random.Random,
    ) -> list[EventDraft]:
        self._require_control_payload(
            command,
            fields=frozenset({"operation", "direction", "reason"}),
        )
        self._require_started_tracker(state)
        direction = command.payload["direction"]
        if direction not in {"next", "previous"}:
            self._invalid_control()
        reason = self._control_reason(command)
        context = state.turn.context
        prior_actor_id = state.turn.actor_id
        prior_round = context.round_number
        next_index = state.current_index
        next_round = prior_round
        final_index = len(context.initiative_order) - 1
        if direction == "next":
            if next_index == final_index:
                if next_round >= state.max_rounds:
                    self._control_conflict(
                        "The tracker cannot advance past the configured final round."
                    )
                next_index = 0
                next_round += 1
                self._reset_round_flags(context)
            else:
                next_index += 1
        elif next_index == 0:
            if next_round == 1:
                self._control_conflict("The tracker cannot move before round one.")
            next_index = final_index
            next_round -= 1
        else:
            next_index -= 1

        self._replace_cursor(state, index=next_index, round_number=next_round)
        events = [
            self._cursor_event(
                state,
                operation=f"advance_{direction}",
                reason=reason,
                prior_actor_id=prior_actor_id,
                prior_round=prior_round,
            )
        ]
        self._drive_to_prompt_or_terminal(state, command, rng, events)
        return events

    def _apply_initiative_reorder(
        self,
        state: DndCombatEncounterState,
        command: SessionCommand,
    ) -> list[EventDraft]:
        self._require_control_payload(
            command,
            fields=frozenset({"operation", "initiative_order", "reason"}),
        )
        reason = self._control_reason(command)
        raw_order = command.payload["initiative_order"]
        if not isinstance(raw_order, list) or any(
            not isinstance(actor_id, str) or not actor_id or actor_id != actor_id.strip()
            for actor_id in raw_order
        ):
            self._invalid_control()
        initiative_order = cast(list[str], raw_order)
        actor_ids = set(state.turn.context.actors)
        if (
            len(initiative_order) != len(actor_ids)
            or len(set(initiative_order)) != len(initiative_order)
            or set(initiative_order) != actor_ids
        ):
            self._invalid_control()
        prior_order = list(state.turn.context.initiative_order)
        state.turn.context.initiative_order = list(initiative_order)
        if state.turn.phase == "unprepared":
            self._replace_cursor(
                state,
                index=0,
                round_number=state.turn.context.round_number,
            )
        else:
            state.current_index = initiative_order.index(state.turn.actor_id)
        return [
            EventDraft(
                kind="dnd.encounter.initiative_overridden",
                payload={
                    "operation": "reorder",
                    "reason": reason,
                    "active_actor_id": state.turn.actor_id,
                    "round_number": state.turn.context.round_number,
                    "previous_initiative_order": prior_order,
                    "initiative_order": list(initiative_order),
                },
            )
        ]

    def _apply_delay(
        self,
        state: DndCombatEncounterState,
        command: SessionCommand,
        rng: random.Random,
    ) -> list[EventDraft]:
        self._require_control_payload(
            command,
            fields=frozenset({"operation", "after_actor_id", "reason"}),
        )
        self._require_started_tracker(state)
        reason = self._control_reason(command)
        after_actor_id = command.payload["after_actor_id"]
        context = state.turn.context
        if not isinstance(after_actor_id, str) or after_actor_id not in context.actors:
            self._invalid_control()
        target_index = context.initiative_order.index(after_actor_id)
        if target_index <= state.current_index:
            self._control_conflict(
                "A combatant can delay only until a later slot in the current round."
            )
        delayed_actor_id = state.turn.actor_id
        prior_round = context.round_number
        initiative_order = list(context.initiative_order)
        initiative_order.pop(state.current_index)
        target_index = initiative_order.index(cast(str, after_actor_id))
        initiative_order.insert(target_index + 1, delayed_actor_id)
        context.initiative_order = initiative_order
        next_actor_id = initiative_order[state.current_index]
        self._replace_cursor(
            state,
            index=state.current_index,
            round_number=prior_round,
        )
        events = [
            EventDraft(
                kind="dnd.encounter.actor_delayed",
                payload={
                    "operation": "delay",
                    "reason": reason,
                    "delayed_actor_id": delayed_actor_id,
                    "after_actor_id": cast(str, after_actor_id),
                    "from_actor_id": delayed_actor_id,
                    "to_actor_id": next_actor_id,
                    "round_number": prior_round,
                    "initiative_order": list(initiative_order),
                },
            )
        ]
        self._drive_to_prompt_or_terminal(state, command, rng, events)
        return events

    def _apply_cursor_override(
        self,
        state: DndCombatEncounterState,
        command: SessionCommand,
        rng: random.Random,
    ) -> list[EventDraft]:
        self._require_control_payload(
            command,
            fields=frozenset({"operation", "active_actor_id", "round_number", "reason"}),
        )
        self._require_started_tracker(state)
        reason = self._control_reason(command)
        actor_id = command.payload["active_actor_id"]
        round_number = command.payload["round_number"]
        context = state.turn.context
        if not isinstance(actor_id, str) or actor_id not in context.actors:
            self._invalid_control()
        if (
            not isinstance(round_number, int)
            or isinstance(round_number, bool)
            or not 1 <= round_number <= state.max_rounds
        ):
            self._invalid_control()
        prior_actor_id = state.turn.actor_id
        prior_round = context.round_number
        self._replace_cursor(
            state,
            index=context.initiative_order.index(cast(str, actor_id)),
            round_number=round_number,
        )
        events = [
            self._cursor_event(
                state,
                operation="manual_override",
                reason=reason,
                prior_actor_id=prior_actor_id,
                prior_round=prior_round,
            )
        ]
        self._drive_to_prompt_or_terminal(state, command, rng, events)
        return events

    @staticmethod
    def _require_control_payload(
        command: SessionCommand,
        *,
        fields: frozenset[str],
    ) -> None:
        if set(command.payload) != fields:
            DndCombatEncounterDriver._invalid_control()

    @staticmethod
    def _control_reason(command: SessionCommand) -> str:
        reason = command.payload.get("reason")
        if not isinstance(reason, str) or reason != reason.strip() or not 1 <= len(reason) <= 256:
            DndCombatEncounterDriver._invalid_control()
        return reason

    @staticmethod
    def _require_started_tracker(state: DndCombatEncounterState) -> None:
        if state.turn.phase != "awaiting_declaration":
            DndCombatEncounterDriver._control_conflict(
                "The encounter must be started before changing its active cursor."
            )

    @staticmethod
    def _replace_cursor(
        state: DndCombatEncounterState,
        *,
        index: int,
        round_number: int,
    ) -> None:
        context = state.turn.context
        context.round_number = round_number
        state.current_index = index
        state.turn = DndCombatTurnState(
            context=context,
            actor_id=context.initiative_order[index],
        )

    @staticmethod
    def _reset_round_flags(context: CombatTurnContext) -> None:
        for actor in context.actors.values():
            actor.lair_action_used_this_round = False
            actor.commanded_this_round = False

    @staticmethod
    def _cursor_event(
        state: DndCombatEncounterState,
        *,
        operation: str,
        reason: str,
        prior_actor_id: str,
        prior_round: int,
    ) -> EventDraft:
        return EventDraft(
            kind="dnd.encounter.cursor_overridden",
            payload={
                "operation": operation,
                "reason": reason,
                "from_actor_id": prior_actor_id,
                "to_actor_id": state.turn.actor_id,
                "from_round_number": prior_round,
                "to_round_number": state.turn.context.round_number,
                "initiative_order": list(state.turn.context.initiative_order),
            },
        )

    @staticmethod
    def _invalid_control() -> NoReturn:
        raise EngineSessionError(
            "invalid_combat_control",
            "The combat tracker command is invalid.",
        )

    @staticmethod
    def _control_conflict(message: str) -> NoReturn:
        raise EngineSessionError("combat_control_conflict", message)

    def _apply_declaration(
        self,
        state: DndCombatEncounterState,
        command: SessionCommand,
        rng: random.Random,
    ) -> list[EventDraft]:
        before_roster = self._roster_signature(state.turn.context)
        if state.turn.prompt is None:
            result = self._turn_driver.resolve_declaration(state.turn, command, rng)
            recorder = None
        else:
            recorder = EngineRollJournalRecorder.empty(state.turn.prompt.turn_token)
            result = self._turn_driver.resolve_declaration(
                state.turn,
                command,
                rng,
                roll_journal_recorder=recorder,
            )
        self._require_roster(state.turn.context, before_roster)
        events = [
            EventDraft(
                kind="dnd.turn.resolved",
                payload=self._turn_driver.result_payload(result),
            )
        ]
        if recorder is not None:
            events.extend(self._turn_driver.roll_event_drafts(recorder.journal))
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
            self._reset_round_flags(context)
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
