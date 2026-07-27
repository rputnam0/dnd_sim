"""Real D&D whole-turn adapter for the transactional interactive session kernel."""

from __future__ import annotations

import json
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import ValidationError

import dnd_sim.engine_runtime as engine_runtime
from dnd_sim.action_legality import TurnDeclarationValidationError
from dnd_sim.models import ActorRuntimeState
from dnd_sim.spatial import AABB
from dnd_sim.turn_kernel import (
    CombatTurnContext,
    CombatTurnDecision,
    CombatTurnPrompt,
    CombatTurnResult,
)

from .contracts import (
    EngineVersionPins,
    EventDraft,
    JSONValue,
    PendingReaction,
    PreviewOutcome,
    SessionCommand,
    normalize_json,
)
from .dnd_contracts import DECLARATION_COMMAND_KIND, TurnDeclarationPayload
from .dnd_state_codec import (
    decode_actor_runtime_state_map,
    encode_actor_runtime_state_map,
)
from .session import EngineSessionError, EngineTransition

DND_TURN_STATE_SCHEMA_VERSION = "dnd.turn-session-state.v2"
PREPARE_TURN_COMMAND_KIND = "dnd.prepare_turn.v1"

_STATE_FIELDS = frozenset(
    {
        "schema_version",
        "phase",
        "actor_id",
        "prompt",
        "last_result",
        "actors",
        "initiative_order",
        "round_number",
        "damage_dealt",
        "damage_taken",
        "threat_scores",
        "resources_spent",
        "active_hazards",
        "telemetry",
        "rule_trace",
        "obstacles",
        "light_level",
        "burst_round_threshold",
        "strategy_overrides",
        "timing_next_subscription_id",
        "timing_next_event_sequence",
        "party_defeat_rule",
        "enemy_defeat_rule",
    }
)
_PROMPT_FIELDS = frozenset({"actor_id", "round_number", "turn_token"})
_RESULT_FIELDS = frozenset(
    {
        "actor_id",
        "round_number",
        "turn_token",
        "status",
        "strategy_name",
    }
)
_RESULT_STATUSES = frozenset(
    {
        "dead",
        "death_save",
        "start_hazard_defeat",
        "combat_ended",
        "readied_action_defeat",
        "incapacitated",
        "forced_dodge",
        "no_declaration",
        "resolved",
    }
)


@dataclass(slots=True)
class DndCombatTurnState:
    """Serializable state for one complete synchronous actor turn."""

    context: CombatTurnContext
    actor_id: str
    phase: Literal["unprepared", "awaiting_declaration", "complete"] = "unprepared"
    prompt: CombatTurnPrompt | None = None
    last_result: CombatTurnResult | None = None


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


def _normalized_list(value: Any, *, path: str) -> list[JSONValue]:
    normalized = normalize_json(value, path=path)
    if not isinstance(normalized, list):
        raise ValueError(f"{path} must be a JSON array")
    return normalized


def _normalized_object_list(value: Any, *, path: str) -> list[dict[str, JSONValue]]:
    payload = _normalized_list(value, path=path)
    return [_normalized_object(item, path=f"{path}[{index}]") for index, item in enumerate(payload)]


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


def _strict_text(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value.strip()


def _encode_int_map(values: Mapping[str, int], *, path: str) -> dict[str, JSONValue]:
    encoded: dict[str, JSONValue] = {}
    for key in sorted(values):
        name = _strict_text(key, path=f"{path} key")
        encoded[name] = _strict_int(values[key], path=f"{path}.{name}")
    return encoded


def _decode_int_map(
    value: Any,
    *,
    path: str,
    actor_ids: set[str],
) -> dict[str, int]:
    payload = _normalized_object(value, path=path)
    if set(payload) != actor_ids:
        raise ValueError(f"{path} keys must exactly match actors")
    return {
        actor_id: _strict_int(payload[actor_id], path=f"{path}.{actor_id}")
        for actor_id in sorted(payload)
    }


def _encode_resources_spent(
    values: Mapping[str, Mapping[str, int]],
) -> dict[str, JSONValue]:
    return {
        actor_id: cast(
            JSONValue,
            _encode_int_map(values[actor_id], path=f"resources_spent.{actor_id}"),
        )
        for actor_id in sorted(values)
    }


def _decode_resources_spent(
    value: Any,
    *,
    actor_ids: set[str],
) -> dict[str, dict[str, int]]:
    payload = _normalized_object(value, path="resources_spent")
    if set(payload) != actor_ids:
        raise ValueError("resources_spent keys must exactly match actors")
    result: dict[str, dict[str, int]] = {}
    for actor_id in sorted(payload):
        actor_payload = _normalized_object(
            payload[actor_id],
            path=f"resources_spent.{actor_id}",
        )
        result[actor_id] = {
            name: _strict_int(
                amount,
                path=f"resources_spent.{actor_id}.{name}",
                minimum=0,
            )
            for name, amount in sorted(actor_payload.items())
        }
    return result


def _coordinate(value: Any, *, path: str) -> tuple[float, float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{path} must be a coordinate array")
    if len(value) != 3:
        raise ValueError(f"{path} must contain three coordinates")
    result: list[float] = []
    for coordinate in value:
        if not isinstance(coordinate, (int, float)) or isinstance(coordinate, bool):
            raise ValueError(f"{path} coordinates must be numbers")
        normalized = float(coordinate)
        if not math.isfinite(normalized):
            raise ValueError(f"{path} coordinates must be finite")
        result.append(normalized)
    return (result[0], result[1], result[2])


def _encode_obstacles(obstacles: Sequence[AABB]) -> list[JSONValue]:
    result: list[JSONValue] = []
    for obstacle in obstacles:
        result.append(
            {
                "min_pos": list(obstacle.min_pos),
                "max_pos": list(obstacle.max_pos),
                "cover_level": obstacle.cover_level,
            }
        )
    return result


def _decode_obstacles(value: Any) -> list[AABB]:
    payload = _normalized_list(value, path="obstacles")
    result: list[AABB] = []
    for index, raw_obstacle in enumerate(payload):
        obstacle = _normalized_object(raw_obstacle, path=f"obstacles[{index}]")
        _exact_keys(
            obstacle,
            frozenset({"min_pos", "max_pos", "cover_level"}),
            path=f"obstacles[{index}]",
        )
        result.append(
            AABB(
                min_pos=_coordinate(obstacle["min_pos"], path=f"obstacles[{index}].min_pos"),
                max_pos=_coordinate(obstacle["max_pos"], path=f"obstacles[{index}].max_pos"),
                cover_level=_strict_text(
                    obstacle["cover_level"],
                    path=f"obstacles[{index}].cover_level",
                ),
            )
        )
    return result


def _encode_prompt(prompt: CombatTurnPrompt | None) -> JSONValue:
    if prompt is None:
        return None
    return {
        "actor_id": prompt.actor_id,
        "round_number": prompt.round_number,
        "turn_token": prompt.turn_token,
    }


def _decode_prompt(value: Any, *, context: CombatTurnContext) -> CombatTurnPrompt | None:
    if value is None:
        return None
    payload = _normalized_object(value, path="prompt")
    _exact_keys(payload, _PROMPT_FIELDS, path="prompt")
    actor_id = _strict_text(payload["actor_id"], path="prompt.actor_id")
    prompt = engine_runtime.build_combat_turn_prompt(
        context=context,
        actor_id=actor_id,
    )
    if (
        _strict_int(payload["round_number"], path="prompt.round_number", minimum=1)
        != prompt.round_number
        or _strict_text(payload["turn_token"], path="prompt.turn_token") != prompt.turn_token
    ):
        raise ValueError("prompt does not match the prepared combat turn context")
    return prompt


def _encode_result(result: CombatTurnResult | None) -> JSONValue:
    if result is None:
        return None
    return {
        "actor_id": result.actor_id,
        "round_number": result.round_number,
        "turn_token": result.turn_token,
        "status": result.status,
        "strategy_name": result.strategy_name,
    }


def _decode_result(value: Any) -> CombatTurnResult | None:
    if value is None:
        return None
    payload = _normalized_object(value, path="last_result")
    _exact_keys(payload, _RESULT_FIELDS, path="last_result")
    status = _strict_text(payload["status"], path="last_result.status")
    if status not in _RESULT_STATUSES:
        raise ValueError("last_result.status is unsupported")
    strategy_name = payload["strategy_name"]
    if strategy_name is not None:
        strategy_name = _strict_text(strategy_name, path="last_result.strategy_name")
    return CombatTurnResult(
        actor_id=_strict_text(payload["actor_id"], path="last_result.actor_id"),
        round_number=_strict_int(
            payload["round_number"],
            path="last_result.round_number",
            minimum=1,
        ),
        turn_token=_strict_text(payload["turn_token"], path="last_result.turn_token"),
        status=cast(Any, status),
        strategy_name=strategy_name,
    )


class DndCombatTurnDriver:
    """EngineSession driver backed by the real synchronous combat-turn kernel."""

    def __init__(self, *, version_pins: EngineVersionPins) -> None:
        self.version_pins = EngineVersionPins.model_validate(version_pins.model_dump(mode="json"))

    def encode_state(self, state: DndCombatTurnState) -> Mapping[str, Any]:
        if not isinstance(state, DndCombatTurnState):
            raise TypeError("state must be DndCombatTurnState")
        context = state.context
        actors = encode_actor_runtime_state_map(context.actors)
        actor_ids = set(context.actors)
        if state.actor_id not in actor_ids:
            raise ValueError("active actor_id must exist in actors")
        if (
            len(context.initiative_order) != len(set(context.initiative_order))
            or set(context.initiative_order) != actor_ids
        ):
            raise ValueError("initiative_order must contain every actor exactly once")
        if state.phase == "unprepared" and (
            state.prompt is not None or state.last_result is not None
        ):
            raise ValueError("unprepared state cannot have a prompt or result")
        if state.phase == "awaiting_declaration" and (
            state.prompt is None or state.last_result is not None
        ):
            raise ValueError("awaiting_declaration state requires only a prompt")
        if state.phase == "complete" and (state.prompt is not None or state.last_result is None):
            raise ValueError("complete state requires only a result")
        if state.prompt is not None and (
            state.prompt.actor_id != state.actor_id
            or state.prompt.round_number != context.round_number
        ):
            raise ValueError("prompt must match the active actor and round")
        if state.last_result is not None and (
            state.last_result.actor_id != state.actor_id
            or state.last_result.round_number != context.round_number
        ):
            raise ValueError("last_result must match the active actor and round")

        timing_next_subscription_id = _strict_int(
            context.timing_engine._next_subscription_id,
            path="timing_next_subscription_id",
            minimum=1,
        )
        timing_next_event_sequence = _strict_int(
            context.timing_engine._next_event_sequence,
            path="timing_next_event_sequence",
            minimum=1,
        )
        payload: dict[str, Any] = {
            "schema_version": DND_TURN_STATE_SCHEMA_VERSION,
            "phase": state.phase,
            "actor_id": state.actor_id,
            "prompt": _encode_prompt(state.prompt),
            "last_result": _encode_result(state.last_result),
            "actors": actors,
            "initiative_order": list(context.initiative_order),
            "round_number": context.round_number,
            "damage_dealt": _encode_int_map(context.damage_dealt, path="damage_dealt"),
            "damage_taken": _encode_int_map(context.damage_taken, path="damage_taken"),
            "threat_scores": _encode_int_map(context.threat_scores, path="threat_scores"),
            "resources_spent": _encode_resources_spent(context.resources_spent),
            "active_hazards": context.active_hazards,
            "telemetry": context.telemetry,
            "rule_trace": context.rule_trace,
            "obstacles": _encode_obstacles(context.obstacles),
            "light_level": context.light_level,
            "burst_round_threshold": context.burst_round_threshold,
            "strategy_overrides": context.strategy_overrides,
            "timing_next_subscription_id": timing_next_subscription_id,
            "timing_next_event_sequence": timing_next_event_sequence,
            "party_defeat_rule": context.party_defeat_rule,
            "enemy_defeat_rule": context.enemy_defeat_rule,
        }
        normalized = normalize_json(payload, path="state")
        if not isinstance(normalized, dict):  # pragma: no cover - payload is statically an object
            raise ValueError("state must encode to a JSON object")
        return normalized

    def decode_state(self, payload: Mapping[str, Any]) -> DndCombatTurnState:
        normalized = _normalized_object(payload, path="state")
        _exact_keys(normalized, _STATE_FIELDS, path="state")
        if normalized["schema_version"] != DND_TURN_STATE_SCHEMA_VERSION:
            raise ValueError("unsupported D&D turn state schema_version")

        phase = normalized["phase"]
        if phase not in {"unprepared", "awaiting_declaration", "complete"}:
            raise ValueError("phase must be unprepared, awaiting_declaration, or complete")
        actors_payload = normalized["actors"]
        if not isinstance(actors_payload, dict):
            raise ValueError("actors must be a JSON object")
        actors = decode_actor_runtime_state_map(actors_payload)
        actor_ids = set(actors)
        actor_id = _strict_text(normalized["actor_id"], path="actor_id")
        if actor_id not in actor_ids:
            raise ValueError("actor_id must exist in actors")

        raw_initiative = normalized["initiative_order"]
        if not isinstance(raw_initiative, list) or any(
            not isinstance(item, str) or not item for item in raw_initiative
        ):
            raise ValueError("initiative_order must be a string array")
        initiative_order = list(raw_initiative)
        if (
            len(initiative_order) != len(set(initiative_order))
            or set(initiative_order) != actor_ids
        ):
            raise ValueError("initiative_order must contain every actor exactly once")

        timing_engine = engine_runtime._create_combat_timing_engine()
        expected_next_subscription_id = timing_engine._next_subscription_id
        encoded_next_subscription_id = _strict_int(
            normalized["timing_next_subscription_id"],
            path="timing_next_subscription_id",
            minimum=1,
        )
        if encoded_next_subscription_id != expected_next_subscription_id:
            raise ValueError("custom timing-engine registrations are not serializable")
        timing_engine._next_event_sequence = _strict_int(
            normalized["timing_next_event_sequence"],
            path="timing_next_event_sequence",
            minimum=1,
        )

        context = CombatTurnContext(
            actors=actors,
            initiative_order=initiative_order,
            round_number=_strict_int(
                normalized["round_number"],
                path="round_number",
                minimum=1,
            ),
            damage_dealt=_decode_int_map(
                normalized["damage_dealt"],
                path="damage_dealt",
                actor_ids=actor_ids,
            ),
            damage_taken=_decode_int_map(
                normalized["damage_taken"],
                path="damage_taken",
                actor_ids=actor_ids,
            ),
            threat_scores=_decode_int_map(
                normalized["threat_scores"],
                path="threat_scores",
                actor_ids=actor_ids,
            ),
            resources_spent=_decode_resources_spent(
                normalized["resources_spent"],
                actor_ids=actor_ids,
            ),
            active_hazards=cast(
                list[dict[str, Any]],
                _normalized_object_list(
                    normalized["active_hazards"],
                    path="active_hazards",
                ),
            ),
            telemetry=cast(
                list[dict[str, Any]],
                _normalized_object_list(normalized["telemetry"], path="telemetry"),
            ),
            rule_trace=cast(
                list[dict[str, Any]],
                _normalized_object_list(normalized["rule_trace"], path="rule_trace"),
            ),
            obstacles=_decode_obstacles(normalized["obstacles"]),
            light_level=_strict_text(normalized["light_level"], path="light_level"),
            burst_round_threshold=_strict_int(
                normalized["burst_round_threshold"],
                path="burst_round_threshold",
                minimum=0,
            ),
            strategy_overrides=_normalized_object(
                normalized["strategy_overrides"],
                path="strategy_overrides",
            ),
            timing_engine=timing_engine,
            party_defeat_rule=_strict_text(
                normalized["party_defeat_rule"],
                path="party_defeat_rule",
            ),
            enemy_defeat_rule=_strict_text(
                normalized["enemy_defeat_rule"],
                path="enemy_defeat_rule",
            ),
        )
        prompt = _decode_prompt(normalized["prompt"], context=context)
        last_result = _decode_result(normalized["last_result"])
        state = DndCombatTurnState(
            context=context,
            actor_id=actor_id,
            phase=cast(Any, phase),
            prompt=prompt,
            last_result=last_result,
        )
        canonical = self.encode_state(state)
        if _canonical_json(canonical) != _canonical_json(normalized):
            raise ValueError("state payload is not the full canonical D&D turn state")
        return state

    def preview(
        self,
        state: DndCombatTurnState,
        command: SessionCommand,
        rng: random.Random,
    ) -> PreviewOutcome:
        transition_kind, payload = self._apply_command(state, command, rng)
        return PreviewOutcome(
            projection=self._project_state(state),
            events=(
                EventDraft(
                    kind="dnd.turn.previewed",
                    payload={"transition_kind": transition_kind, **payload},
                ),
            ),
        )

    def commit(
        self,
        state: DndCombatTurnState,
        command: SessionCommand,
        rng: random.Random,
    ) -> EngineTransition:
        transition_kind, payload = self._apply_command(state, command, rng)
        return EngineTransition(
            state=state,
            events=(
                EventDraft(
                    kind=transition_kind,
                    payload=payload,
                ),
            ),
        )

    def respond_to_reaction(
        self,
        state: DndCombatTurnState,
        command: SessionCommand,
        pending_reaction: PendingReaction,
        rng: random.Random,
    ) -> EngineTransition:
        del state, command, pending_reaction, rng
        raise EngineSessionError(
            "unsupported_reaction",
            "This D&D driver version auto-resolves reactions.",
        )

    def _apply_command(
        self,
        state: DndCombatTurnState,
        command: SessionCommand,
        rng: random.Random,
    ) -> tuple[str, dict[str, JSONValue]]:
        if command.kind == PREPARE_TURN_COMMAND_KIND:
            prepared = self._apply_prepare(state, command, rng)
            if isinstance(prepared, CombatTurnPrompt):
                return "dnd.turn.prepared", self._prompt_payload(prepared)
            return "dnd.turn.completed_automatically", self._result_payload(prepared)
        if command.kind == DECLARATION_COMMAND_KIND:
            result = self._apply_declaration(state, command, rng)
            return "dnd.turn.resolved", self._result_payload(result)
        raise EngineSessionError(
            "unsupported_command",
            "The D&D turn driver only accepts prepare or declaration commands.",
            details={"kind": command.kind},
        )

    def _apply_prepare(
        self,
        state: DndCombatTurnState,
        command: SessionCommand,
        rng: random.Random,
    ) -> CombatTurnPrompt | CombatTurnResult:
        if state.phase == "complete":
            raise EngineSessionError("turn_complete", "This actor turn is already complete.")
        if state.phase == "awaiting_declaration":
            raise EngineSessionError(
                "turn_already_prepared",
                "This actor turn is already awaiting a declaration.",
            )
        self._validate_actor(state, command)
        if command.mode not in {"preview", "commit", "admin"}:
            raise EngineSessionError(
                "unsupported_command_mode",
                "Turn preparation accepts preview, commit, or admin mode only.",
            )
        if command.payload:
            raise EngineSessionError(
                "invalid_command_payload",
                "Turn preparation requires an empty payload.",
            )

        prepared = engine_runtime.prepare_combat_turn(
            rng=rng,
            context=state.context,
            actor_id=state.actor_id,
        )
        if isinstance(prepared, CombatTurnPrompt):
            state.phase = "awaiting_declaration"
            state.prompt = prepared
            state.last_result = None
        else:
            state.phase = "complete"
            state.prompt = None
            state.last_result = prepared
        return prepared

    def _apply_declaration(
        self,
        state: DndCombatTurnState,
        command: SessionCommand,
        rng: random.Random,
    ) -> CombatTurnResult:
        if state.phase == "complete":
            raise EngineSessionError("turn_complete", "This actor turn is already complete.")
        if state.phase != "awaiting_declaration" or state.prompt is None:
            raise EngineSessionError(
                "turn_not_prepared",
                "Prepare this actor turn before submitting a declaration.",
            )
        self._validate_actor(state, command)
        if command.mode not in {"preview", "commit"}:
            raise EngineSessionError(
                "unsupported_command_mode",
                "The D&D turn driver accepts preview or commit mode only.",
            )

        try:
            declaration_payload = TurnDeclarationPayload.model_validate(command.payload)
        except ValidationError as exc:
            raise EngineSessionError(
                "invalid_command_payload",
                "The turn declaration payload is invalid.",
                details={"errors": cast(JSONValue, exc.errors(include_url=False))},
            ) from exc
        canonical_payload = declaration_payload.model_dump(mode="json")
        if _canonical_json(canonical_payload) != _canonical_json(command.payload):
            raise EngineSessionError(
                "invalid_command_payload",
                "The turn declaration payload must be complete and canonical.",
            )
        declaration = declaration_payload.to_domain()

        try:
            result = engine_runtime.resolve_prompted_combat_turn(
                rng=rng,
                context=state.context,
                prompt=state.prompt,
                decision=CombatTurnDecision(
                    strategy_name="interactive",
                    declaration=declaration,
                ),
            )
        except TurnDeclarationValidationError as exc:
            details: dict[str, JSONValue] = {
                "actor_id": exc.actor_id,
                "rule_error_code": exc.code,
                "field": exc.field,
            }
            normalized_rule_details = normalize_json(exc.details, path="rule_error_details")
            if isinstance(normalized_rule_details, dict):
                details["rule_error_details"] = normalized_rule_details
            raise EngineSessionError(
                "invalid_turn_declaration",
                exc.message,
                details=details,
            ) from exc

        state.phase = "complete"
        state.prompt = None
        state.last_result = result
        return result

    @staticmethod
    def _validate_actor(state: DndCombatTurnState, command: SessionCommand) -> None:
        if command.actor_id != state.actor_id:
            raise EngineSessionError(
                "actor_mismatch",
                "The command actor does not match the active turn actor.",
                details={
                    "expected_actor_id": state.actor_id,
                    "received_actor_id": command.actor_id,
                },
            )

    @staticmethod
    def _prompt_payload(prompt: CombatTurnPrompt) -> dict[str, JSONValue]:
        return {
            "actor_id": prompt.actor_id,
            "round_number": prompt.round_number,
            "turn_token": prompt.turn_token,
        }

    @staticmethod
    def _result_payload(result: CombatTurnResult) -> dict[str, JSONValue]:
        return {
            "actor_id": result.actor_id,
            "round_number": result.round_number,
            "turn_token": result.turn_token,
            "status": result.status,
            "strategy_name": result.strategy_name,
        }

    @staticmethod
    def _project_actor(actor: ActorRuntimeState) -> dict[str, JSONValue]:
        return {
            "actor_id": actor.actor_id,
            "team": actor.team,
            "name": actor.name,
            "hp": actor.hp,
            "max_hp": actor.max_hp,
            "temp_hp": actor.temp_hp,
            "ac": actor.ac,
            "position": list(actor.position),
            "movement_remaining": actor.movement_remaining,
            "conditions": sorted(actor.conditions),
            "dead": actor.dead,
            "stable": actor.stable,
            "bonus_available": actor.bonus_available,
            "reaction_available": actor.reaction_available,
            "actions": [
                {
                    "name": action.name,
                    "action_type": action.action_type,
                    "action_cost": action.action_cost,
                    "target_mode": action.target_mode,
                    "reach_ft": action.reach_ft,
                    "range_normal_ft": action.range_normal_ft,
                    "range_long_ft": action.range_long_ft,
                }
                for action in actor.actions
            ],
        }

    def _project_state(self, state: DndCombatTurnState) -> dict[str, JSONValue]:
        return {
            "phase": state.phase,
            "active_actor_id": state.actor_id,
            "round_number": state.context.round_number,
            "initiative_order": list(state.context.initiative_order),
            "actors": {
                actor_id: self._project_actor(state.context.actors[actor_id])
                for actor_id in sorted(state.context.actors)
            },
            "result": _encode_result(state.last_result),
        }
