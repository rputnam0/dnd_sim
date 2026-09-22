"""Strict renderer-neutral contracts for durable VTT participant presence."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .participants import TableRole

PRESENCE_RECORD_SCHEMA_VERSION = "vtt.presence_record.v1"
PRESENCE_COMMAND_SCHEMA_VERSION = "vtt.presence_command.v1"
PRESENCE_EVENT_SCHEMA_VERSION = "vtt.presence_event.v1"
PRESENCE_RECEIPT_SCHEMA_VERSION = "vtt.presence_receipt.v1"
PRESENCE_VIEW_SCHEMA_VERSION = "vtt.presence_view.v1"

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
PresenceStatus = Literal["online", "away", "offline"]


class _StrictPresenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _canonical_text(
    value: str,
    *,
    field_name: str,
    maximum_length: int | None = 128,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    if maximum_length is not None and len(value) > maximum_length:
        raise ValueError(f"{field_name} must be at most {maximum_length} characters")
    return value


class PresenceRecord(_StrictPresenceModel):
    """One audience-safe roster entry with a derived presence status."""

    schema_version: Literal[PRESENCE_RECORD_SCHEMA_VERSION] = PRESENCE_RECORD_SCHEMA_VERSION
    participant_id: str
    display_name: str
    role: TableRole
    status: PresenceStatus

    @field_validator("participant_id", "display_name")
    @classmethod
    def validate_text(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name, maximum_length=None)


class PresenceHeartbeatCommand(_StrictPresenceModel):
    """One idempotent client heartbeat without a client-controlled timestamp."""

    schema_version: Literal[PRESENCE_COMMAND_SCHEMA_VERSION] = PRESENCE_COMMAND_SCHEMA_VERSION
    command_type: Literal["heartbeat"] = "heartbeat"
    table_id: str
    command_id: str
    expected_revision: NonNegativeInt
    participant_id: str
    client_id: str

    @field_validator("table_id", "command_id", "participant_id", "client_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)


class PresenceHeartbeatEvent(_StrictPresenceModel):
    """Durable evidence that the server observed one client heartbeat."""

    schema_version: Literal[PRESENCE_EVENT_SCHEMA_VERSION] = PRESENCE_EVENT_SCHEMA_VERSION
    event_type: Literal["heartbeat"] = "heartbeat"
    table_id: str
    event_id: str
    sequence: PositiveInt
    revision: PositiveInt
    command_id: str
    participant_id: str
    client_id: str
    observed_at_ms: NonNegativeInt
    audience: tuple[Literal["all"], ...] = ("all",)

    @field_validator("table_id", "command_id", "participant_id", "client_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="event_id", maximum_length=512)

    @field_validator("audience", mode="before")
    @classmethod
    def validate_audience(cls, value: Any) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)) or tuple(value) != ("all",):
            raise ValueError("presence heartbeat events must have a public 'all' audience")
        return ("all",)

    @model_validator(mode="after")
    def validate_sequence_revision(self) -> Self:
        if self.sequence != self.revision:
            raise ValueError("sequence must match revision")
        return self


class PresenceHeartbeatReceipt(_StrictPresenceModel):
    """Stable idempotency receipt for one durable heartbeat."""

    schema_version: Literal[PRESENCE_RECEIPT_SCHEMA_VERSION] = PRESENCE_RECEIPT_SCHEMA_VERSION
    table_id: str
    command_id: str
    revision: PositiveInt
    event: PresenceHeartbeatEvent

    @field_validator("table_id", "command_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_event_identity(self) -> Self:
        if self.event.table_id != self.table_id:
            raise ValueError("event.table_id must match table_id")
        if self.event.command_id != self.command_id:
            raise ValueError("event.command_id must match command_id")
        if self.event.revision != self.revision:
            raise ValueError("event.revision must match revision")
        return self


class PresenceView(_StrictPresenceModel):
    """Audience-safe roster presence derived at an explicit server time."""

    schema_version: Literal[PRESENCE_VIEW_SCHEMA_VERSION] = PRESENCE_VIEW_SCHEMA_VERSION
    table_id: str
    revision: NonNegativeInt
    evaluated_at_ms: NonNegativeInt
    away_after_ms: PositiveInt
    offline_after_ms: PositiveInt
    records: tuple[PresenceRecord, ...]

    @field_validator("table_id")
    @classmethod
    def validate_table_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="table_id")

    @field_validator("records", mode="before")
    @classmethod
    def normalize_records(cls, value: Any) -> tuple[Any, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("records must be an ordered list or tuple")
        return tuple(value)

    @model_validator(mode="after")
    def validate_thresholds_and_records(self) -> Self:
        if self.away_after_ms >= self.offline_after_ms:
            raise ValueError("away_after_ms must be less than offline_after_ms")
        participant_ids = tuple(record.participant_id for record in self.records)
        if participant_ids != tuple(sorted(participant_ids)):
            raise ValueError("presence records must be sorted by participant_id")
        if len(set(participant_ids)) != len(participant_ids):
            raise ValueError("presence records must have unique participant IDs")
        return self


__all__ = [
    "PRESENCE_COMMAND_SCHEMA_VERSION",
    "PRESENCE_EVENT_SCHEMA_VERSION",
    "PRESENCE_RECEIPT_SCHEMA_VERSION",
    "PRESENCE_RECORD_SCHEMA_VERSION",
    "PRESENCE_VIEW_SCHEMA_VERSION",
    "PresenceHeartbeatCommand",
    "PresenceHeartbeatEvent",
    "PresenceHeartbeatReceipt",
    "PresenceRecord",
    "PresenceStatus",
    "PresenceView",
]
