"""Durable append-only annotation boards for renderer-neutral VTT geometry."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from .annotations import VTTAnnotation, parse_annotation, project_annotations

ANNOTATION_COMMAND_SCHEMA_VERSION = "vtt.annotation_command.v1"
ANNOTATION_EVENT_SCHEMA_VERSION = "vtt.annotation_event.v1"
ANNOTATION_RECEIPT_SCHEMA_VERSION = "vtt.annotation_receipt.v1"
ANNOTATION_STORE_SCHEMA_VERSION = "vtt.annotation_store.v1"
MAX_ACTIVE_ANNOTATIONS = 2_000

_METADATA_TABLE = "_vtt_annotation_store_metadata"
_EVENTS_TABLE = "_vtt_annotation_event_log"

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]


class AnnotationStoreError(RuntimeError):
    """Base error for durable annotation-board operations."""


class AnnotationStoreSchemaError(AnnotationStoreError):
    """Raised when SQLite contains an unsupported annotation-store schema."""


class AnnotationStoreCorruptionError(AnnotationStoreError):
    """Raised when a durable annotation record fails its public contracts."""


class AnnotationCommandConflictError(AnnotationStoreError):
    """Raised when a command ID is reused with different canonical content."""


class AnnotationRevisionConflictError(AnnotationStoreError):
    """Raised when a new command does not target the current table revision."""


class AnnotationNotFoundError(AnnotationStoreError):
    """Raised when deletion targets an annotation absent from the table."""


class AnnotationCapacityError(AnnotationStoreError):
    """Raised when a new record would exceed the active annotation ceiling."""


def _canonical_text(value: str, *, field_name: str, maximum_length: int = 128) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if normalized != value:
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    if len(value) > maximum_length:
        raise ValueError(f"{field_name} must be at most {maximum_length} characters")
    return value


def _audience(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("audience must be an ordered list or tuple")
    recipients: list[str] = []
    seen: set[str] = set()
    for item in value:
        recipient = _canonical_text(item, field_name="audience recipient ID")
        if recipient not in seen:
            recipients.append(recipient)
            seen.add(recipient)
    if not recipients:
        raise ValueError("audience must contain at least one recipient")
    if "all" in seen and recipients != ["all"]:
        raise ValueError("audience 'all' cannot be combined with explicit recipient IDs")
    return tuple(recipients)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _AnnotationCommandBase(_StrictModel):
    schema_version: Literal[ANNOTATION_COMMAND_SCHEMA_VERSION] = ANNOTATION_COMMAND_SCHEMA_VERSION
    table_id: str
    command_id: str
    expected_revision: NonNegativeInt

    @field_validator("table_id", "command_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)


class AnnotationPutCommand(_AnnotationCommandBase):
    """Create or replace one annotation within the command's table."""

    command_type: Literal["put"] = "put"
    annotation: VTTAnnotation


class AnnotationDeleteCommand(_AnnotationCommandBase):
    """Delete one existing annotation from the command's table."""

    command_type: Literal["delete"] = "delete"
    annotation_id: str

    @field_validator("annotation_id")
    @classmethod
    def validate_annotation_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="annotation_id")


AnnotationMutationCommand: TypeAlias = Annotated[
    AnnotationPutCommand | AnnotationDeleteCommand,
    Field(discriminator="command_type"),
]


class _AnnotationEventBase(_StrictModel):
    schema_version: Literal[ANNOTATION_EVENT_SCHEMA_VERSION] = ANNOTATION_EVENT_SCHEMA_VERSION
    table_id: str
    event_id: str
    sequence: PositiveInt
    revision: PositiveInt
    command_id: str
    annotation_id: str

    @field_validator("table_id", "command_id", "annotation_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="event_id", maximum_length=512)


class AnnotationPutEvent(_AnnotationEventBase):
    """A canonical annotation create or replacement event."""

    event_type: Literal["put"] = "put"
    annotation: VTTAnnotation

    @model_validator(mode="after")
    def validate_annotation_identity(self) -> "AnnotationPutEvent":
        if self.annotation.annotation_id != self.annotation_id:
            raise ValueError("annotation.annotation_id must match annotation_id")
        return self


class AnnotationDeleteEvent(_AnnotationEventBase):
    """A canonical tombstone retaining its former scene and audience."""

    event_type: Literal["delete"] = "delete"
    scene_id: str
    audience: tuple[str, ...]

    @field_validator("scene_id")
    @classmethod
    def validate_scene_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="scene_id")

    @field_validator("audience", mode="before")
    @classmethod
    def validate_audience(cls, value: Any) -> tuple[str, ...]:
        return _audience(value)


AnnotationMutationEvent: TypeAlias = Annotated[
    AnnotationPutEvent | AnnotationDeleteEvent,
    Field(discriminator="event_type"),
]


class AnnotationMutationReceipt(_StrictModel):
    """The immutable durable result of one successful annotation mutation."""

    schema_version: Literal[ANNOTATION_RECEIPT_SCHEMA_VERSION] = ANNOTATION_RECEIPT_SCHEMA_VERSION
    table_id: str
    command_id: str
    revision: PositiveInt
    event: AnnotationMutationEvent

    @field_validator("table_id", "command_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_event_identity(self) -> "AnnotationMutationReceipt":
        if self.event.table_id != self.table_id:
            raise ValueError("event.table_id must match table_id")
        if self.event.command_id != self.command_id:
            raise ValueError("event.command_id must match command_id")
        if self.event.revision != self.revision:
            raise ValueError("event.revision must match revision")
        return self


@dataclass(frozen=True, slots=True)
class AnnotationExecutionResult:
    """A receipt plus whether it came from an exact command retry."""

    receipt: AnnotationMutationReceipt
    replayed: bool


_COMMAND_ADAPTER = TypeAdapter(AnnotationMutationCommand)


def parse_annotation_command(value: Any) -> AnnotationMutationCommand:
    """Validate one decoded command through the strict discriminated union."""

    return _COMMAND_ADAPTER.validate_python(value)


def parse_annotation_command_json(
    value: str | bytes | bytearray,
) -> AnnotationMutationCommand:
    """Validate one encoded JSON command through the strict discriminated union."""

    return _COMMAND_ADAPTER.validate_json(value)


def _canonical_json(model: BaseModel) -> str:
    return json.dumps(
        model.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _reject_nonstandard_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant '{value}'")


def _decode_json_object(encoded: str, *, field_name: str) -> Mapping[str, Any]:
    try:
        value = json.loads(encoded, parse_constant=_reject_nonstandard_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AnnotationStoreCorruptionError(f"stored {field_name} is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise AnnotationStoreCorruptionError(f"stored {field_name} must be a JSON object")
    return value


class SQLiteAnnotationBoard:
    """Append-only, revision-checked annotation history for many isolated tables.

    The caller owns the SQLite connection. Every mutation owns one immediate
    transaction; projections are rebuilt from strictly validated public events.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        max_active_annotations: int = MAX_ACTIVE_ANNOTATIONS,
    ) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        if (
            type(max_active_annotations) is not int
            or max_active_annotations < 1
            or max_active_annotations > MAX_ACTIVE_ANNOTATIONS
        ):
            raise ValueError(
                f"max_active_annotations must be an integer from 1 to " f"{MAX_ACTIVE_ANNOTATIONS}"
            )
        if connection.in_transaction:
            raise AnnotationStoreError(
                "cannot initialize an annotation board inside an active transaction"
            )
        self._connection = connection
        self._max_active_annotations = max_active_annotations
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(f"""
                CREATE TABLE IF NOT EXISTS {_METADATA_TABLE} (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    schema_version TEXT NOT NULL
                )
                """)
            metadata = self._connection.execute(
                f"SELECT schema_version FROM {_METADATA_TABLE} WHERE singleton = 1"
            ).fetchone()
            if metadata is None:
                self._connection.execute(
                    f"INSERT INTO {_METADATA_TABLE} (singleton, schema_version) VALUES (1, ?)",
                    (ANNOTATION_STORE_SCHEMA_VERSION,),
                )
            elif str(metadata[0]) != ANNOTATION_STORE_SCHEMA_VERSION:
                raise AnnotationStoreSchemaError(
                    "unsupported annotation-store schema "
                    f"'{metadata[0]}'; expected '{ANNOTATION_STORE_SCHEMA_VERSION}'"
                )

            self._connection.execute(f"""
                CREATE TABLE IF NOT EXISTS {_EVENTS_TABLE} (
                    store_schema_version TEXT NOT NULL,
                    table_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL CHECK (sequence >= 1),
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    command_id TEXT NOT NULL,
                    command_json TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    PRIMARY KEY (table_id, command_id),
                    UNIQUE (table_id, sequence),
                    UNIQUE (table_id, revision),
                    CHECK (length(trim(table_id)) > 0),
                    CHECK (length(trim(command_id)) > 0),
                    CHECK (length(trim(command_json)) > 0),
                    CHECK (length(trim(receipt_json)) > 0)
                )
                """)
            self._connection.commit()
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def execute(self, command: AnnotationMutationCommand) -> AnnotationExecutionResult:
        """Commit one put/delete or return the receipt for an exact retry."""

        if not isinstance(command, (AnnotationPutCommand, AnnotationDeleteCommand)):
            raise TypeError("command must be an annotation mutation command")
        command = parse_annotation_command(command.model_dump(mode="json"))
        command_json = _canonical_json(command)

        if self._connection.in_transaction:
            raise AnnotationStoreError("execute cannot run inside an active transaction")

        try:
            self._connection.execute("BEGIN IMMEDIATE")
            existing = self._connection.execute(
                f"""
                SELECT store_schema_version, sequence, revision, command_json, receipt_json
                FROM {_EVENTS_TABLE}
                WHERE table_id = ? AND command_id = ?
                """,
                (command.table_id, command.command_id),
            ).fetchone()
            if existing is not None:
                self._validate_store_schema(str(existing[0]))
                if str(existing[3]) != command_json:
                    raise AnnotationCommandConflictError(
                        f"command_id '{command.command_id}' is already committed with "
                        "different content"
                    )
                receipt = self._parse_stored_receipt(
                    str(existing[4]),
                    table_id=command.table_id,
                    command_id=command.command_id,
                    sequence=int(existing[1]),
                    revision=int(existing[2]),
                )
                self._validate_command_receipt(command, receipt)
                self._connection.commit()
                return AnnotationExecutionResult(receipt=receipt, replayed=True)

            current_revision, next_sequence = self._revision_and_next_sequence_locked(
                command.table_id
            )
            if command.expected_revision != current_revision:
                raise AnnotationRevisionConflictError(
                    f"expected revision {current_revision}, received "
                    f"{command.expected_revision}"
                )
            current_annotations = self._annotations_locked(command.table_id)

            revision = current_revision + 1
            event_id = f"{command.table_id}:annotation:{next_sequence}"
            if isinstance(command, AnnotationPutCommand):
                annotation = parse_annotation(command.annotation.model_dump(mode="json"))
                if (
                    annotation.annotation_id not in current_annotations
                    and len(current_annotations) >= self._max_active_annotations
                ):
                    raise AnnotationCapacityError("active annotation capacity has been reached")
                event: AnnotationMutationEvent = AnnotationPutEvent(
                    table_id=command.table_id,
                    event_id=event_id,
                    sequence=next_sequence,
                    revision=revision,
                    command_id=command.command_id,
                    annotation_id=annotation.annotation_id,
                    annotation=annotation,
                )
            else:
                existing_annotation = current_annotations.get(command.annotation_id)
                if existing_annotation is None:
                    raise AnnotationNotFoundError(
                        f"annotation_id '{command.annotation_id}' is missing from table "
                        f"'{command.table_id}'"
                    )
                event = AnnotationDeleteEvent(
                    table_id=command.table_id,
                    event_id=event_id,
                    sequence=next_sequence,
                    revision=revision,
                    command_id=command.command_id,
                    annotation_id=command.annotation_id,
                    scene_id=existing_annotation.scene_id,
                    audience=existing_annotation.audience,
                )

            receipt = AnnotationMutationReceipt(
                table_id=command.table_id,
                command_id=command.command_id,
                revision=revision,
                event=event,
            )
            self._connection.execute(
                f"""
                INSERT INTO {_EVENTS_TABLE} (
                    store_schema_version,
                    table_id,
                    sequence,
                    revision,
                    command_id,
                    command_json,
                    receipt_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ANNOTATION_STORE_SCHEMA_VERSION,
                    command.table_id,
                    next_sequence,
                    revision,
                    command.command_id,
                    command_json,
                    _canonical_json(receipt),
                ),
            )
            self._connection.commit()
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

        return AnnotationExecutionResult(receipt=receipt, replayed=False)

    def revision(self, table_id: str) -> int:
        """Return the current durable revision for one table."""

        normalized_table_id = _canonical_text(table_id, field_name="table_id")
        row = self._connection.execute(
            f"SELECT COALESCE(MAX(revision), 0) FROM {_EVENTS_TABLE} WHERE table_id = ?",
            (normalized_table_id,),
        ).fetchone()
        if row is None:
            raise AnnotationStoreCorruptionError("failed to read annotation revision")
        return int(row[0])

    def events_after(self, table_id: str, sequence: int) -> tuple[AnnotationMutationEvent, ...]:
        """Return canonical events with sequence IDs strictly after the cursor."""

        normalized_table_id = _canonical_text(table_id, field_name="table_id")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        return self._events_after_locked(normalized_table_id, sequence)

    def annotations(self, table_id: str) -> tuple[VTTAnnotation, ...]:
        """Rebuild the table's latest annotation set from its append-only history."""

        normalized_table_id = _canonical_text(table_id, field_name="table_id")
        annotations = self._annotations_locked(normalized_table_id)
        return tuple(annotations[key] for key in sorted(annotations))

    def project(
        self,
        table_id: str,
        *,
        scene_id: str,
        recipient_id: str | None,
    ) -> tuple[VTTAnnotation, ...]:
        """Project current annotations by scene and audience without pixel geometry."""

        return project_annotations(
            self.annotations(table_id),
            scene_id=scene_id,
            recipient_id=recipient_id,
        )

    def _revision_and_next_sequence_locked(self, table_id: str) -> tuple[int, int]:
        row = self._connection.execute(
            f"""
            SELECT COALESCE(MAX(revision), 0), COALESCE(MAX(sequence), 0) + 1
            FROM {_EVENTS_TABLE}
            WHERE table_id = ?
            """,
            (table_id,),
        ).fetchone()
        if row is None:
            raise AnnotationStoreCorruptionError("failed to allocate annotation revision")
        return int(row[0]), int(row[1])

    def _events_after_locked(
        self, table_id: str, sequence: int
    ) -> tuple[AnnotationMutationEvent, ...]:
        rows = self._connection.execute(
            f"""
            SELECT store_schema_version, sequence, revision, command_id,
                   command_json, receipt_json
            FROM {_EVENTS_TABLE}
            WHERE table_id = ? AND sequence > ?
            ORDER BY sequence ASC
            """,
            (table_id, sequence),
        ).fetchall()
        events: list[AnnotationMutationEvent] = []
        for row in rows:
            self._validate_store_schema(str(row[0]))
            stored_sequence = int(row[1])
            stored_revision = int(row[2])
            command_id = str(row[3])
            command = self._parse_stored_command(
                str(row[4]), table_id=table_id, command_id=command_id
            )
            if command.expected_revision + 1 != stored_revision:
                raise AnnotationStoreCorruptionError(
                    "stored command expected_revision does not precede its revision"
                )
            receipt = self._parse_stored_receipt(
                str(row[5]),
                table_id=table_id,
                command_id=command_id,
                sequence=stored_sequence,
                revision=stored_revision,
            )
            self._validate_command_receipt(command, receipt)
            events.append(receipt.event)
        return tuple(events)

    def _annotations_locked(self, table_id: str) -> dict[str, VTTAnnotation]:
        current: dict[str, VTTAnnotation] = {}
        expected_sequence = 1
        expected_revision = 1
        for event in self._events_after_locked(table_id, 0):
            if event.sequence != expected_sequence or event.revision != expected_revision:
                raise AnnotationStoreCorruptionError(
                    "stored annotation history has a sequence or revision gap"
                )
            if isinstance(event, AnnotationPutEvent):
                current[event.annotation_id] = event.annotation
            else:
                previous = current.get(event.annotation_id)
                if previous is None:
                    raise AnnotationStoreCorruptionError(
                        "stored delete event targets a missing annotation"
                    )
                if previous.scene_id != event.scene_id or previous.audience != event.audience:
                    raise AnnotationStoreCorruptionError(
                        "stored delete tombstone does not match its annotation"
                    )
                del current[event.annotation_id]
            expected_sequence += 1
            expected_revision += 1
        return current

    @staticmethod
    def _parse_stored_command(
        encoded: str, *, table_id: str, command_id: str
    ) -> AnnotationMutationCommand:
        decoded = _decode_json_object(encoded, field_name="command")
        try:
            command = parse_annotation_command(decoded)
        except ValidationError as exc:
            raise AnnotationStoreCorruptionError(
                "stored command violates the annotation command contract"
            ) from exc
        if command.table_id != table_id or command.command_id != command_id:
            raise AnnotationStoreCorruptionError(
                "stored command identity does not match its event row"
            )
        return command

    @staticmethod
    def _parse_stored_receipt(
        encoded: str,
        *,
        table_id: str,
        command_id: str,
        sequence: int,
        revision: int,
    ) -> AnnotationMutationReceipt:
        decoded = _decode_json_object(encoded, field_name="receipt")
        try:
            receipt = AnnotationMutationReceipt.model_validate(decoded)
        except ValidationError as exc:
            raise AnnotationStoreCorruptionError(
                "stored receipt violates the annotation receipt contract"
            ) from exc
        if receipt.table_id != table_id or receipt.command_id != command_id:
            raise AnnotationStoreCorruptionError(
                "stored receipt identity does not match its event row"
            )
        if receipt.revision != revision or receipt.event.sequence != sequence:
            raise AnnotationStoreCorruptionError(
                "stored receipt revision or sequence does not match its event row"
            )
        expected_event_id = f"{table_id}:annotation:{sequence}"
        if receipt.event.event_id != expected_event_id:
            raise AnnotationStoreCorruptionError(
                "stored receipt event_id does not match its event row"
            )
        return receipt

    @staticmethod
    def _validate_command_receipt(
        command: AnnotationMutationCommand,
        receipt: AnnotationMutationReceipt,
    ) -> None:
        if command.expected_revision + 1 != receipt.revision:
            raise AnnotationStoreCorruptionError(
                "stored command expected_revision does not precede its receipt"
            )
        if isinstance(command, AnnotationPutCommand):
            if not isinstance(receipt.event, AnnotationPutEvent):
                raise AnnotationStoreCorruptionError("stored put command does not have a put event")
            if command.annotation != receipt.event.annotation:
                raise AnnotationStoreCorruptionError(
                    "stored put event annotation does not match its command"
                )
            return
        if not isinstance(receipt.event, AnnotationDeleteEvent):
            raise AnnotationStoreCorruptionError(
                "stored delete command does not have a delete event"
            )
        if command.annotation_id != receipt.event.annotation_id:
            raise AnnotationStoreCorruptionError(
                "stored delete event annotation_id does not match its command"
            )

    @staticmethod
    def _validate_store_schema(schema_version: str) -> None:
        if schema_version != ANNOTATION_STORE_SCHEMA_VERSION:
            raise AnnotationStoreSchemaError(
                f"stored annotation row uses schema '{schema_version}', expected "
                f"'{ANNOTATION_STORE_SCHEMA_VERSION}'"
            )


__all__ = [
    "ANNOTATION_COMMAND_SCHEMA_VERSION",
    "ANNOTATION_EVENT_SCHEMA_VERSION",
    "ANNOTATION_RECEIPT_SCHEMA_VERSION",
    "ANNOTATION_STORE_SCHEMA_VERSION",
    "MAX_ACTIVE_ANNOTATIONS",
    "AnnotationCapacityError",
    "AnnotationCommandConflictError",
    "AnnotationDeleteCommand",
    "AnnotationDeleteEvent",
    "AnnotationExecutionResult",
    "AnnotationMutationCommand",
    "AnnotationMutationEvent",
    "AnnotationMutationReceipt",
    "AnnotationNotFoundError",
    "AnnotationPutCommand",
    "AnnotationPutEvent",
    "AnnotationRevisionConflictError",
    "AnnotationStoreCorruptionError",
    "AnnotationStoreError",
    "AnnotationStoreSchemaError",
    "SQLiteAnnotationBoard",
    "parse_annotation_command",
    "parse_annotation_command_json",
]
