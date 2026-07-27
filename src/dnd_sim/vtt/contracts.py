"""Strict client-facing contracts for the VTT session boundary."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from dnd_sim.interactive.contracts import (
    CommandReceipt,
    EngineVersionPins,
    EventDraft,
    PreviewReceipt,
    SessionCommand,
    SessionEvent,
)

VTT_COMMAND_SCHEMA_VERSION = "vtt.command.v1"
VTT_EVENT_SCHEMA_VERSION = "vtt.event.v1"
VTT_EVENT_DRAFT_SCHEMA_VERSION = "vtt.event_draft.v1"
VTT_VERSION_INFO_SCHEMA_VERSION = "vtt.version_info.v1"
VTT_PREVIEW_RESPONSE_SCHEMA_VERSION = "vtt.preview_response.v1"
VTT_COMMIT_RESPONSE_SCHEMA_VERSION = "vtt.commit_response.v1"

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
JSONValue: TypeAlias = JsonValue


def _normalize_json(value: Any, *, path: str) -> JSONValue:
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
            normalized[key] = _normalize_json(item, path=f"{path}.{key}")
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize_json(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    raise ValueError(f"{path} contains unsupported type {type(value).__name__}")


def _json_object(value: Any, *, path: str) -> dict[str, JSONValue]:
    normalized = _normalize_json(value, path=path)
    if not isinstance(normalized, dict):
        raise ValueError(f"{path} must be a JSON object")
    return normalized


def _required_text(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _audience(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("audience must be an ordered list or tuple")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError("audience entries must be strings")
        actor_id = _required_text(item, field_name="audience actor id")
        if actor_id not in seen:
            normalized.append(actor_id)
            seen.add(actor_id)
    if not normalized:
        raise ValueError("audience must contain at least one recipient")
    return tuple(normalized)


class VTTContractModel(BaseModel):
    """Immutable, non-coercing base for every public VTT payload."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class VTTVersionInfo(VTTContractModel):
    """Public version information without exposing the engine pin contract."""

    schema_version: Literal[VTT_VERSION_INFO_SCHEMA_VERSION] = VTT_VERSION_INFO_SCHEMA_VERSION
    engine: str
    rules: str
    content: str

    @field_validator("engine", "rules", "content")
    @classmethod
    def validate_version(cls, value: str, info: Any) -> str:
        return _required_text(value, field_name=info.field_name)

    @classmethod
    def from_engine(cls, version_pins: EngineVersionPins) -> "VTTVersionInfo":
        return cls(
            engine=version_pins.engine_version,
            rules=version_pins.rules_version,
            content=version_pins.content_version,
        )


class VTTCommand(VTTContractModel):
    """A client command translated to the pinned engine only inside the service."""

    schema_version: Literal[VTT_COMMAND_SCHEMA_VERSION] = VTT_COMMAND_SCHEMA_VERSION
    command_id: str
    session_id: str
    actor_id: str | None = None
    expected_revision: NonNegativeInt
    mode: Literal["preview", "commit", "reaction", "admin"]
    kind: str
    payload: dict[str, JSONValue] = Field(default_factory=dict)
    intent_metadata: dict[str, JSONValue] = Field(default_factory=dict)

    @field_validator("command_id", "session_id", "kind")
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        return _required_text(value, field_name=info.field_name)

    @field_validator("actor_id")
    @classmethod
    def validate_actor_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _required_text(value, field_name="actor_id")

    @field_validator("payload", "intent_metadata", mode="before")
    @classmethod
    def validate_json_object(cls, value: Any, info: Any) -> dict[str, JSONValue]:
        return _json_object(value, path=info.field_name)

    @model_validator(mode="after")
    def validate_reaction_payload(self) -> "VTTCommand":
        if self.mode == "reaction":
            reaction_id = self.payload.get("reaction_id")
            if not isinstance(reaction_id, str) or not reaction_id.strip():
                raise ValueError("reaction commands require a non-empty reaction_id")
        return self

    def to_session_command(self, version_pins: EngineVersionPins) -> SessionCommand:
        """Translate this wire command to the engine's internal command contract."""

        if not isinstance(version_pins, EngineVersionPins):
            raise TypeError("version_pins must be EngineVersionPins")
        return SessionCommand(
            command_id=self.command_id,
            session_id=self.session_id,
            actor_id=self.actor_id,
            expected_revision=self.expected_revision,
            mode=self.mode,
            kind=self.kind,
            version_pins=version_pins,
            payload=self.payload,
            intent_metadata=self.intent_metadata,
        )


class VTTEventDraft(VTTContractModel):
    """A non-canonical event projected by a preview."""

    schema_version: Literal[VTT_EVENT_DRAFT_SCHEMA_VERSION] = VTT_EVENT_DRAFT_SCHEMA_VERSION
    kind: str
    audience: tuple[str, ...] = ("all",)
    payload: dict[str, JSONValue] = Field(default_factory=dict)

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        return _required_text(value, field_name="kind")

    @field_validator("audience", mode="before")
    @classmethod
    def validate_audience(cls, value: Any) -> tuple[str, ...]:
        return _audience(value)

    @field_validator("payload", mode="before")
    @classmethod
    def validate_payload(cls, value: Any) -> dict[str, JSONValue]:
        return _json_object(value, path="payload")

    @classmethod
    def from_engine(cls, event: EventDraft) -> "VTTEventDraft":
        return cls(
            kind=event.kind,
            audience=event.audience,
            payload=event.payload,
        )


class VTTEvent(VTTContractModel):
    """A canonical committed event projected into the VTT namespace."""

    schema_version: Literal[VTT_EVENT_SCHEMA_VERSION] = VTT_EVENT_SCHEMA_VERSION
    event_id: str
    session_id: str
    sequence: PositiveInt
    revision: PositiveInt
    kind: str
    command_id: str
    versions: VTTVersionInfo
    causation_id: str | None = None
    audience: tuple[str, ...] = ("all",)
    payload: dict[str, JSONValue] = Field(default_factory=dict)

    @field_validator("event_id", "session_id", "kind", "command_id")
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        return _required_text(value, field_name=info.field_name)

    @field_validator("causation_id")
    @classmethod
    def validate_causation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _required_text(value, field_name="causation_id")

    @field_validator("audience", mode="before")
    @classmethod
    def validate_audience(cls, value: Any) -> tuple[str, ...]:
        return _audience(value)

    @field_validator("payload", mode="before")
    @classmethod
    def validate_payload(cls, value: Any) -> dict[str, JSONValue]:
        return _json_object(value, path="payload")

    @classmethod
    def from_engine(cls, event: SessionEvent) -> "VTTEvent":
        return cls(
            event_id=event.event_id,
            session_id=event.session_id,
            sequence=event.sequence,
            revision=event.revision,
            kind=event.kind,
            command_id=event.command_id,
            versions=VTTVersionInfo.from_engine(event.version_pins),
            causation_id=event.causation_id,
            audience=event.audience,
            payload=event.payload,
        )


class VTTPreviewResponse(VTTContractModel):
    """Client-safe projection of an engine preview receipt."""

    schema_version: Literal[VTT_PREVIEW_RESPONSE_SCHEMA_VERSION] = (
        VTT_PREVIEW_RESPONSE_SCHEMA_VERSION
    )
    response_type: Literal["preview"] = "preview"
    command_id: str
    session_id: str
    revision: NonNegativeInt
    versions: VTTVersionInfo
    projection: dict[str, JSONValue]
    events: tuple[VTTEventDraft, ...] = ()

    @field_validator("command_id", "session_id")
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        return _required_text(value, field_name=info.field_name)

    @field_validator("projection", mode="before")
    @classmethod
    def validate_projection(cls, value: Any) -> dict[str, JSONValue]:
        return _json_object(value, path="projection")

    @field_validator("events", mode="before")
    @classmethod
    def validate_events(cls, value: Any) -> tuple[Any, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("events must be an ordered list or tuple")
        return tuple(value)

    @classmethod
    def from_engine(cls, receipt: PreviewReceipt) -> "VTTPreviewResponse":
        return cls(
            command_id=receipt.command_id,
            session_id=receipt.session_id,
            revision=receipt.revision,
            versions=VTTVersionInfo.from_engine(receipt.version_pins),
            projection=receipt.projection,
            events=tuple(VTTEventDraft.from_engine(event) for event in receipt.events),
        )


class VTTCommitResponse(VTTContractModel):
    """Client-safe projection of a canonical engine commit receipt."""

    schema_version: Literal[VTT_COMMIT_RESPONSE_SCHEMA_VERSION] = VTT_COMMIT_RESPONSE_SCHEMA_VERSION
    response_type: Literal["commit"] = "commit"
    command_id: str
    session_id: str
    replayed: bool = False
    revision: PositiveInt
    versions: VTTVersionInfo
    first_sequence: PositiveInt | None = None
    last_sequence: PositiveInt | None = None
    events: tuple[VTTEvent, ...] = ()

    @field_validator("command_id", "session_id")
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        return _required_text(value, field_name=info.field_name)

    @field_validator("events", mode="before")
    @classmethod
    def validate_events(cls, value: Any) -> tuple[Any, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("events must be an ordered list or tuple")
        return tuple(value)

    @model_validator(mode="after")
    def validate_sequence_range(self) -> "VTTCommitResponse":
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

    @classmethod
    def from_engine(cls, receipt: CommandReceipt) -> "VTTCommitResponse":
        return cls(
            command_id=receipt.command_id,
            session_id=receipt.session_id,
            replayed=receipt.replayed,
            revision=receipt.revision,
            versions=VTTVersionInfo.from_engine(receipt.version_pins),
            first_sequence=receipt.first_sequence,
            last_sequence=receipt.last_sequence,
            events=tuple(VTTEvent.from_engine(event) for event in receipt.events),
        )


VTTResponse: TypeAlias = VTTPreviewResponse | VTTCommitResponse


__all__ = [
    "VTT_COMMAND_SCHEMA_VERSION",
    "VTT_COMMIT_RESPONSE_SCHEMA_VERSION",
    "VTT_EVENT_DRAFT_SCHEMA_VERSION",
    "VTT_EVENT_SCHEMA_VERSION",
    "VTT_PREVIEW_RESPONSE_SCHEMA_VERSION",
    "VTT_VERSION_INFO_SCHEMA_VERSION",
    "VTTCommand",
    "VTTCommitResponse",
    "VTTEvent",
    "VTTEventDraft",
    "VTTPreviewResponse",
    "VTTResponse",
    "VTTVersionInfo",
]
