from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue as JSONValue,
    field_validator,
    model_validator,
)

COMMAND_SCHEMA_VERSION = "engine.command.v1"
EVENT_SCHEMA_VERSION = "engine.event.v1"
RECEIPT_SCHEMA_VERSION = "engine.receipt.v1"
SNAPSHOT_SCHEMA_VERSION = "engine.snapshot.v1"
REACTION_SCHEMA_VERSION = "engine.reaction.v1"
RNG_ALGORITHM = "python-mt19937-v1"

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]


def normalize_json(value: Any, *, path: str = "value") -> JSONValue:
    """Return a detached, canonical JSON-compatible representation."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must not contain NaN or infinity")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings")
            normalized[key] = normalize_json(item, path=f"{path}.{key}")
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [normalize_json(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    raise ValueError(f"{path} contains unsupported type {type(value).__name__}")


def _non_empty(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _audience(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("audience must be an ordered list or tuple")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError("audience entries must be strings")
        actor_id = _non_empty(item, field_name="audience actor id")
        if actor_id not in seen:
            result.append(actor_id)
            seen.add(actor_id)
    if not result:
        raise ValueError("audience must contain at least one recipient")
    return tuple(result)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EngineVersionPins(ContractModel):
    engine_version: str
    rules_version: str
    content_version: str

    @field_validator("engine_version", "rules_version", "content_version")
    @classmethod
    def validate_version(cls, value: str, info: Any) -> str:
        return _non_empty(value, field_name=info.field_name)


class EventDraft(ContractModel):
    kind: str
    payload: dict[str, JSONValue] = Field(default_factory=dict)
    audience: tuple[str, ...] = ("all",)

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        return _non_empty(value, field_name="kind")

    @field_validator("payload", mode="before")
    @classmethod
    def validate_payload(cls, value: Any) -> dict[str, JSONValue]:
        normalized = normalize_json(value, path="payload")
        if not isinstance(normalized, dict):
            raise ValueError("payload must be a JSON object")
        return normalized

    @field_validator("audience", mode="before")
    @classmethod
    def validate_audience(cls, value: Sequence[str]) -> tuple[str, ...]:
        return _audience(value)


class SessionCommand(ContractModel):
    schema_version: Literal[COMMAND_SCHEMA_VERSION] = COMMAND_SCHEMA_VERSION
    command_id: str
    session_id: str
    actor_id: str | None = None
    expected_revision: NonNegativeInt
    mode: Literal["preview", "commit", "reaction", "admin"]
    kind: str
    version_pins: EngineVersionPins
    payload: dict[str, JSONValue] = Field(default_factory=dict)
    intent_metadata: dict[str, JSONValue] = Field(default_factory=dict)

    @field_validator("command_id", "session_id", "kind")
    @classmethod
    def validate_required_id(cls, value: str, info: Any) -> str:
        return _non_empty(value, field_name=info.field_name)

    @field_validator("actor_id")
    @classmethod
    def validate_actor_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _non_empty(value, field_name="actor_id")

    @field_validator("payload", "intent_metadata", mode="before")
    @classmethod
    def validate_json_object(cls, value: Any, info: Any) -> dict[str, JSONValue]:
        normalized = normalize_json(value, path=info.field_name)
        if not isinstance(normalized, dict):
            raise ValueError(f"{info.field_name} must be a JSON object")
        return normalized

    @model_validator(mode="after")
    def validate_reaction_payload(self) -> "SessionCommand":
        if self.mode == "reaction":
            reaction_id = self.payload.get("reaction_id")
            if not isinstance(reaction_id, str) or not reaction_id.strip():
                raise ValueError("reaction commands require a non-empty reaction_id")
        return self


class SessionEvent(ContractModel):
    schema_version: Literal[EVENT_SCHEMA_VERSION] = EVENT_SCHEMA_VERSION
    event_id: str
    session_id: str
    sequence: PositiveInt
    revision: PositiveInt
    kind: str
    command_id: str
    version_pins: EngineVersionPins
    causation_id: str | None = None
    audience: tuple[str, ...] = ("all",)
    payload: dict[str, JSONValue] = Field(default_factory=dict)

    @field_validator("event_id", "session_id", "kind", "command_id")
    @classmethod
    def validate_required_id(cls, value: str, info: Any) -> str:
        return _non_empty(value, field_name=info.field_name)

    @field_validator("causation_id")
    @classmethod
    def validate_causation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _non_empty(value, field_name="causation_id")

    @field_validator("payload", mode="before")
    @classmethod
    def validate_payload(cls, value: Any) -> dict[str, JSONValue]:
        normalized = normalize_json(value, path="payload")
        if not isinstance(normalized, dict):
            raise ValueError("payload must be a JSON object")
        return normalized

    @field_validator("audience", mode="before")
    @classmethod
    def validate_audience(cls, value: Sequence[str]) -> tuple[str, ...]:
        return _audience(value)


class PendingReactionDraft(ContractModel):
    reaction_id: str
    eligible_actor_ids: tuple[str, ...]
    prompt: dict[str, JSONValue]

    @field_validator("reaction_id")
    @classmethod
    def validate_reaction_id(cls, value: str) -> str:
        return _non_empty(value, field_name="reaction_id")

    @field_validator("eligible_actor_ids", mode="before")
    @classmethod
    def validate_eligible_actor_ids(cls, value: Sequence[str]) -> tuple[str, ...]:
        return _audience(value)

    @field_validator("prompt", mode="before")
    @classmethod
    def validate_prompt(cls, value: Any) -> dict[str, JSONValue]:
        normalized = normalize_json(value, path="prompt")
        if not isinstance(normalized, dict):
            raise ValueError("prompt must be a JSON object")
        return normalized


class PendingReaction(PendingReactionDraft):
    schema_version: Literal[REACTION_SCHEMA_VERSION] = REACTION_SCHEMA_VERSION
    opened_by_command_id: str
    opened_revision: PositiveInt

    @field_validator("opened_by_command_id")
    @classmethod
    def validate_opened_by_command_id(cls, value: str) -> str:
        return _non_empty(value, field_name="opened_by_command_id")


class PreviewOutcome(ContractModel):
    projection: dict[str, JSONValue]
    events: tuple[EventDraft, ...] = ()

    @field_validator("projection", mode="before")
    @classmethod
    def validate_projection(cls, value: Any) -> dict[str, JSONValue]:
        normalized = normalize_json(value, path="projection")
        if not isinstance(normalized, dict):
            raise ValueError("projection must be a JSON object")
        return normalized


class PreviewReceipt(ContractModel):
    schema_version: Literal[RECEIPT_SCHEMA_VERSION] = RECEIPT_SCHEMA_VERSION
    command_id: str
    session_id: str
    revision: NonNegativeInt
    version_pins: EngineVersionPins
    projection: dict[str, JSONValue]
    events: tuple[EventDraft, ...] = ()

    @field_validator("command_id", "session_id")
    @classmethod
    def validate_required_id(cls, value: str, info: Any) -> str:
        return _non_empty(value, field_name=info.field_name)

    @field_validator("projection", mode="before")
    @classmethod
    def validate_projection(cls, value: Any) -> dict[str, JSONValue]:
        normalized = normalize_json(value, path="projection")
        if not isinstance(normalized, dict):
            raise ValueError("projection must be a JSON object")
        return normalized


class CommandReceipt(ContractModel):
    schema_version: Literal[RECEIPT_SCHEMA_VERSION] = RECEIPT_SCHEMA_VERSION
    command_id: str
    session_id: str
    replayed: bool = False
    revision: PositiveInt
    version_pins: EngineVersionPins
    first_sequence: PositiveInt | None = None
    last_sequence: PositiveInt | None = None
    events: tuple[SessionEvent, ...] = ()

    @field_validator("command_id", "session_id")
    @classmethod
    def validate_required_id(cls, value: str, info: Any) -> str:
        return _non_empty(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_sequence_range(self) -> "CommandReceipt":
        if bool(self.events) != (self.first_sequence is not None):
            raise ValueError("sequence bounds must be present exactly when events are present")
        if self.events:
            if self.last_sequence is None:
                raise ValueError("last_sequence is required when events are present")
            if self.first_sequence != self.events[0].sequence:
                raise ValueError("first_sequence must match the first event")
            if self.last_sequence != self.events[-1].sequence:
                raise ValueError("last_sequence must match the last event")
        elif self.last_sequence is not None:
            raise ValueError("sequence bounds must be absent when events are absent")
        return self


class CommandRecord(ContractModel):
    command: SessionCommand
    receipt: CommandReceipt

    @model_validator(mode="after")
    def validate_identity(self) -> "CommandRecord":
        if self.command.command_id != self.receipt.command_id:
            raise ValueError("command and receipt command_id values must match")
        if self.command.session_id != self.receipt.session_id:
            raise ValueError("command and receipt session_id values must match")
        if self.command.version_pins != self.receipt.version_pins:
            raise ValueError("command and receipt version pins must match")
        return self


class SessionSnapshot(ContractModel):
    schema_version: Literal[SNAPSHOT_SCHEMA_VERSION] = SNAPSHOT_SCHEMA_VERSION
    rng_algorithm: Literal[RNG_ALGORITHM] = RNG_ALGORITHM
    session_id: str
    revision: NonNegativeInt
    next_sequence: PositiveInt
    version_pins: EngineVersionPins
    state: dict[str, JSONValue]
    random_state: JSONValue
    events: tuple[SessionEvent, ...] = ()
    command_records: tuple[CommandRecord, ...] = ()
    pending_reaction: PendingReaction | None = None
    checksum: str

    @field_validator("session_id", "checksum")
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        return _non_empty(value, field_name=info.field_name)

    @field_validator("state", mode="before")
    @classmethod
    def validate_state(cls, value: Any) -> dict[str, JSONValue]:
        normalized = normalize_json(value, path="state")
        if not isinstance(normalized, dict):
            raise ValueError("state must be a JSON object")
        return normalized

    @field_validator("random_state", mode="before")
    @classmethod
    def validate_random_state(cls, value: Any) -> JSONValue:
        return normalize_json(value, path="random_state")
