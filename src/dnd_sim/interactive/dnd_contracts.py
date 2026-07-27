"""Strict JSON contracts for interactive D&D turn declarations."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dnd_sim.strategy_api import (
    DeclaredAction,
    ReactionPolicy,
    ReadyDeclaration,
    ResourceSpend,
    TargetRef,
    TurnDeclaration,
)

from .contracts import JSONValue, normalize_json

DECLARATION_COMMAND_KIND = "dnd.declare_turn.v1"
TURN_CHOICES_SCHEMA_VERSION = "dnd.turn-choices.v1"
_EXPLICIT_TARGET_MODES = frozenset(
    {
        "single_enemy",
        "single_ally",
        "single_creature",
        "n_enemies",
        "n_allies",
        "random_enemy",
        "random_ally",
    }
)


class DndContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _non_empty_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _json_object(value: Any, *, field_name: str) -> dict[str, JSONValue]:
    normalized = normalize_json(value, path=field_name)
    if not isinstance(normalized, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return normalized


def _finite_number(value: Any, *, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


def _canonical_actor_ids(value: Any, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{field_name} must be an ordered list")
    target_ids = tuple(
        _non_empty_string(target_id, field_name=f"{field_name} actor id") for target_id in value
    )
    if len(set(target_ids)) != len(target_ids):
        raise ValueError(f"{field_name} must not contain duplicates")
    if target_ids != tuple(sorted(target_ids)):
        raise ValueError(f"{field_name} must use canonical actor-id order")
    return target_ids


class MovementChoicePayload(DndContractModel):
    """Current movement origin and remaining budget for one prompted actor."""

    origin: tuple[float, float, float]
    remaining_ft: float

    @field_validator("origin", mode="before")
    @classmethod
    def validate_origin(cls, value: Any) -> tuple[float, float, float]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            raise ValueError("origin must be a coordinate")
        if len(value) != 3:
            raise ValueError("origin must contain exactly 3 coordinates")
        coordinates = tuple(
            _finite_number(coordinate, field_name="origin coordinate") for coordinate in value
        )
        return (coordinates[0], coordinates[1], coordinates[2])

    @field_validator("remaining_ft", mode="before")
    @classmethod
    def validate_remaining_ft(cls, value: Any) -> float:
        normalized = _finite_number(value, field_name="remaining_ft")
        if normalized < 0.0:
            raise ValueError("remaining_ft must be non-negative")
        return normalized


class ActionChoicePayload(DndContractModel):
    """One declaration-compatible action in canonical actor action order."""

    action_name: str
    action_cost: Literal["action", "bonus", "none"]
    target_mode: str
    requires_explicit_targets: bool
    selectable_target_ids: tuple[str, ...] = ()
    legal_target_ids: tuple[str, ...] = ()
    reason: Literal["no_legal_targets"] | None = None

    @field_validator("action_name", "target_mode", mode="before")
    @classmethod
    def validate_required_text(cls, value: Any, info: Any) -> str:
        return _non_empty_string(value, field_name=info.field_name)

    @field_validator("requires_explicit_targets", mode="before")
    @classmethod
    def validate_requires_explicit_targets(cls, value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError("requires_explicit_targets must be a boolean")
        return value

    @field_validator("selectable_target_ids", "legal_target_ids", mode="before")
    @classmethod
    def validate_target_ids(cls, value: Any, info: Any) -> tuple[str, ...]:
        return _canonical_actor_ids(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_target_reason(self) -> Self:
        expected_explicit = self.target_mode in _EXPLICIT_TARGET_MODES
        if self.requires_explicit_targets != expected_explicit:
            raise ValueError("requires_explicit_targets does not match target_mode")
        if not set(self.legal_target_ids).issubset(self.selectable_target_ids):
            raise ValueError("legal_target_ids must be a subset of selectable_target_ids")
        if self.legal_target_ids and self.reason is not None:
            raise ValueError("an action with legal targets must not include a reason")
        if not self.legal_target_ids and self.reason != "no_legal_targets":
            raise ValueError("an action without legal targets requires no_legal_targets")
        return self


class TurnChoicesPayload(DndContractModel):
    """Authoritative choices for an actor awaiting a turn declaration."""

    schema_version: Literal[TURN_CHOICES_SCHEMA_VERSION] = TURN_CHOICES_SCHEMA_VERSION
    actor_id: str
    movement: MovementChoicePayload
    actions: tuple[ActionChoicePayload, ...] = ()
    reason: Literal["no_available_actions"] | None = None

    @field_validator("actor_id", mode="before")
    @classmethod
    def validate_actor_id(cls, value: Any) -> str:
        return _non_empty_string(value, field_name="actor_id")

    @model_validator(mode="after")
    def validate_action_reason(self) -> Self:
        action_names = [choice.action_name for choice in self.actions]
        if len(set(action_names)) != len(action_names):
            raise ValueError("actions must not contain duplicate action names")
        if self.actions and self.reason is not None:
            raise ValueError("choices with actions must not include a reason")
        if not self.actions and self.reason != "no_available_actions":
            raise ValueError("empty choices require no_available_actions")
        return self


class TargetRefPayload(DndContractModel):
    actor_id: str

    @field_validator("actor_id", mode="before")
    @classmethod
    def validate_actor_id(cls, value: Any) -> str:
        return _non_empty_string(value, field_name="actor_id")

    def to_domain(self) -> TargetRef:
        return TargetRef(actor_id=self.actor_id)


class ResourceSpendPayload(DndContractModel):
    amounts: dict[str, int] = Field(default_factory=dict)

    @field_validator("amounts", mode="before")
    @classmethod
    def validate_amounts(cls, value: Any) -> dict[str, int]:
        if not isinstance(value, Mapping):
            raise ValueError("amounts must be an object")
        result: dict[str, int] = {}
        for raw_name, raw_amount in value.items():
            name = _non_empty_string(raw_name, field_name="resource name")
            if not isinstance(raw_amount, int) or isinstance(raw_amount, bool):
                raise ValueError(f"resource amount for {name} must be an integer")
            if raw_amount < 0:
                raise ValueError(f"resource amount for {name} must be non-negative")
            result[name] = raw_amount
        return result

    def to_domain(self) -> ResourceSpend:
        return ResourceSpend(amounts=dict(self.amounts))


class DeclaredActionPayload(DndContractModel):
    action_name: str | None = None
    targets: tuple[TargetRefPayload, ...] = ()
    resource_spend: ResourceSpendPayload = Field(default_factory=ResourceSpendPayload)
    spell_slot_level: int | None = None
    rationale: dict[str, JSONValue] = Field(default_factory=dict)

    @field_validator("action_name", mode="before")
    @classmethod
    def validate_action_name(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _non_empty_string(value, field_name="action_name")

    @field_validator("spell_slot_level", mode="before")
    @classmethod
    def validate_spell_slot_level(cls, value: Any) -> int | None:
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("spell_slot_level must be a non-negative integer")
        return value

    @field_validator("rationale", mode="before")
    @classmethod
    def validate_rationale(cls, value: Any) -> dict[str, JSONValue]:
        return _json_object(value, field_name="rationale")

    @classmethod
    def from_domain(cls, action: DeclaredAction) -> "DeclaredActionPayload":
        return cls(
            action_name=action.action_name,
            targets=tuple(TargetRefPayload(actor_id=target.actor_id) for target in action.targets),
            resource_spend=ResourceSpendPayload(amounts=action.resource_spend.amounts),
            spell_slot_level=action.spell_slot_level,
            rationale=action.rationale,
        )

    def to_domain(self) -> DeclaredAction:
        return DeclaredAction(
            action_name=self.action_name,
            targets=[target.to_domain() for target in self.targets],
            resource_spend=self.resource_spend.to_domain(),
            spell_slot_level=self.spell_slot_level,
            rationale=dict(self.rationale),
        )


class ReactionPolicyPayload(DndContractModel):
    mode: Literal["auto", "none"] = "auto"
    rationale: dict[str, JSONValue] = Field(default_factory=dict)

    @field_validator("rationale", mode="before")
    @classmethod
    def validate_rationale(cls, value: Any) -> dict[str, JSONValue]:
        return _json_object(value, field_name="rationale")

    def to_domain(self) -> ReactionPolicy:
        return ReactionPolicy(mode=self.mode, rationale=dict(self.rationale))


class ReadyDeclarationPayload(DndContractModel):
    trigger: str
    response_action_name: str
    rationale: dict[str, JSONValue] = Field(default_factory=dict)

    @field_validator("trigger", "response_action_name", mode="before")
    @classmethod
    def validate_required_text(cls, value: Any, info: Any) -> str:
        return _non_empty_string(value, field_name=info.field_name)

    @field_validator("rationale", mode="before")
    @classmethod
    def validate_rationale(cls, value: Any) -> dict[str, JSONValue]:
        return _json_object(value, field_name="rationale")

    def to_domain(self) -> ReadyDeclaration:
        return ReadyDeclaration(
            trigger=self.trigger,
            response_action_name=self.response_action_name,
            rationale=dict(self.rationale),
        )


class TurnDeclarationPayload(DndContractModel):
    movement_path: tuple[tuple[float, float, float], ...] = ()
    action: DeclaredActionPayload | None = None
    bonus_action: DeclaredActionPayload | None = None
    reaction_policy: ReactionPolicyPayload = Field(default_factory=ReactionPolicyPayload)
    ready: ReadyDeclarationPayload | None = None
    rationale: dict[str, JSONValue] = Field(default_factory=dict)

    @field_validator("movement_path", mode="before")
    @classmethod
    def validate_movement_path(
        cls,
        value: Any,
    ) -> tuple[tuple[float, float, float], ...]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            raise ValueError("movement_path must be an ordered list")
        result: list[tuple[float, float, float]] = []
        for index, waypoint in enumerate(value):
            if not isinstance(waypoint, Sequence) or isinstance(
                waypoint,
                (str, bytes, bytearray),
            ):
                raise ValueError(f"movement_path[{index}] must be a coordinate")
            if len(waypoint) != 3:
                raise ValueError(f"movement_path[{index}] must contain exactly 3 coordinates")
            coordinates: list[float] = []
            for coordinate in waypoint:
                if not isinstance(coordinate, (int, float)) or isinstance(coordinate, bool):
                    raise ValueError("movement coordinates must be numbers")
                normalized = float(coordinate)
                if not math.isfinite(normalized):
                    raise ValueError("movement coordinates must be finite")
                coordinates.append(normalized)
            result.append((coordinates[0], coordinates[1], coordinates[2]))
        return tuple(result)

    @field_validator("rationale", mode="before")
    @classmethod
    def validate_rationale(cls, value: Any) -> dict[str, JSONValue]:
        return _json_object(value, field_name="rationale")

    @classmethod
    def from_domain(cls, declaration: TurnDeclaration) -> "TurnDeclarationPayload":
        return cls(
            movement_path=tuple(declaration.movement_path),
            action=(
                DeclaredActionPayload.from_domain(declaration.action)
                if declaration.action is not None
                else None
            ),
            bonus_action=(
                DeclaredActionPayload.from_domain(declaration.bonus_action)
                if declaration.bonus_action is not None
                else None
            ),
            reaction_policy=ReactionPolicyPayload(
                mode=declaration.reaction_policy.mode,
                rationale=declaration.reaction_policy.rationale,
            ),
            ready=(
                ReadyDeclarationPayload(
                    trigger=declaration.ready.trigger,
                    response_action_name=declaration.ready.response_action_name,
                    rationale=declaration.ready.rationale,
                )
                if declaration.ready is not None
                else None
            ),
            rationale=declaration.rationale,
        )

    def to_domain(self) -> TurnDeclaration:
        return TurnDeclaration(
            movement_path=list(self.movement_path),
            action=self.action.to_domain() if self.action is not None else None,
            bonus_action=(self.bonus_action.to_domain() if self.bonus_action is not None else None),
            reaction_policy=self.reaction_policy.to_domain(),
            ready=self.ready.to_domain() if self.ready is not None else None,
            rationale=dict(self.rationale),
        )
