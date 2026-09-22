"""Restart-safe append-only SQLite state for VTT visibility authoring."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter, ValidationError

from .visibility_contracts import (
    FogOperation,
    LightEmitter,
    SceneEnvironment,
    SightBarrier,
    TokenVision,
    VisibilityCatalogView,
    VisibilityChangedEvent,
    VisibilityCommand,
    VisibilityDeleteCommand,
    VisibilityDoorStateCommand,
    VisibilityFogUndoCommand,
    VisibilityMutationReceipt,
    VisibilityPutCommand,
    VisibilityRecord,
)

VISIBILITY_STORE_SCHEMA_VERSION = "vtt.visibility_store.v1"
MAX_BARRIERS_PER_SCENE = 2_000
MAX_LIGHTS_PER_SCENE = 500
MAX_TOKEN_VISION_PER_SCENE = 500
MAX_FOG_OPERATIONS_PER_SCENE = 2_000

_METADATA_TABLE = "_vtt_visibility_store_metadata"
_EVENTS_TABLE = "_vtt_visibility_event_log"
_COMMAND_ADAPTER = TypeAdapter(VisibilityCommand)
_RECORD_ADAPTER = TypeAdapter(VisibilityRecord)


class VisibilityStoreError(RuntimeError):
    pass


class VisibilityStoreSchemaError(VisibilityStoreError):
    pass


class VisibilityStoreCorruptionError(VisibilityStoreError):
    pass


class VisibilityRevisionConflictError(VisibilityStoreError):
    def __init__(self, *, current_revision: int, expected_revision: int) -> None:
        super().__init__(f"expected revision {current_revision}, received {expected_revision}")
        self.current_revision = current_revision
        self.expected_revision = expected_revision


class VisibilityCommandConflictError(VisibilityStoreError):
    pass


class VisibilityRecordConflictError(VisibilityStoreError):
    pass


class VisibilityRecordNotFoundError(VisibilityStoreError):
    pass


class VisibilityLimitError(VisibilityStoreError):
    pass


@dataclass(frozen=True, slots=True)
class VisibilityExecutionResult:
    receipt: VisibilityMutationReceipt
    replayed: bool


def _canonical_id(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    return value


def _canonical_json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class SQLiteVisibilityStore:
    """One connection-owned visibility event log with table-wide revisions."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        if connection.in_transaction:
            raise VisibilityStoreError("cannot initialize visibility storage in a transaction")
        self._connection = connection
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
            row = self._connection.execute(
                f"SELECT schema_version FROM {_METADATA_TABLE} WHERE singleton = 1"
            ).fetchone()
            if row is None:
                self._connection.execute(
                    f"INSERT INTO {_METADATA_TABLE} (singleton, schema_version) VALUES (1, ?)",
                    (VISIBILITY_STORE_SCHEMA_VERSION,),
                )
            elif str(row[0]) != VISIBILITY_STORE_SCHEMA_VERSION:
                raise VisibilityStoreSchemaError("unsupported visibility store schema")
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
                    UNIQUE (table_id, revision)
                )
                """)
            self._connection.commit()
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def execute(self, command: VisibilityCommand) -> VisibilityExecutionResult:
        command = self._validate_command(command)
        command_json = _canonical_json(command)
        if self._connection.in_transaction:
            raise VisibilityStoreError("execute cannot run inside an active transaction")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            existing = self._connection.execute(
                f"""
                SELECT store_schema_version, command_json, receipt_json
                FROM {_EVENTS_TABLE}
                WHERE table_id = ? AND command_id = ?
                """,
                (command.table_id, command.command_id),
            ).fetchone()
            if existing is not None:
                if str(existing[0]) != VISIBILITY_STORE_SCHEMA_VERSION:
                    raise VisibilityStoreCorruptionError("stored visibility schema is unsupported")
                if str(existing[1]) != command_json:
                    raise VisibilityCommandConflictError(
                        "visibility command ID was reused with different content"
                    )
                receipt = self._parse_receipt(str(existing[2]))
                self._validate_replay_binding(command, receipt)
                self._connection.commit()
                return VisibilityExecutionResult(receipt=receipt, replayed=True)

            snapshots = self._snapshots_locked(command.table_id)
            current_revision = self._revision_locked(command.table_id)
            if command.expected_revision != current_revision:
                raise VisibilityRevisionConflictError(
                    current_revision=current_revision,
                    expected_revision=command.expected_revision,
                )
            event = self._build_event(command, snapshots, revision=current_revision + 1)
            next_snapshots = self._apply_event(snapshots, event)
            self._validate_limits(next_snapshots[event.scene_id])
            receipt = VisibilityMutationReceipt(
                table_id=command.table_id,
                command_id=command.command_id,
                revision=event.revision,
                event=event,
            )
            self._connection.execute(
                f"""
                INSERT INTO {_EVENTS_TABLE} (
                    store_schema_version, table_id, sequence, revision,
                    command_id, command_json, receipt_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    VISIBILITY_STORE_SCHEMA_VERSION,
                    command.table_id,
                    event.sequence,
                    event.revision,
                    command.command_id,
                    command_json,
                    _canonical_json(receipt),
                ),
            )
            self._connection.commit()
            return VisibilityExecutionResult(receipt=receipt, replayed=False)
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def replay(self, command: VisibilityCommand) -> VisibilityExecutionResult | None:
        """Return an exact prior result without applying a new visibility command."""

        command = self._validate_command(command)
        if self._connection.in_transaction:
            raise VisibilityStoreError("replay cannot run inside an active transaction")
        row = self._connection.execute(
            f"""
            SELECT store_schema_version, command_json, receipt_json
            FROM {_EVENTS_TABLE}
            WHERE table_id = ? AND command_id = ?
            """,
            (command.table_id, command.command_id),
        ).fetchone()
        if row is None:
            return None
        if str(row[0]) != VISIBILITY_STORE_SCHEMA_VERSION:
            raise VisibilityStoreCorruptionError("stored visibility schema is unsupported")
        if str(row[1]) != _canonical_json(command):
            raise VisibilityCommandConflictError(
                "visibility command ID was reused with different content"
            )
        receipt = self._parse_receipt(str(row[2]))
        self._validate_replay_binding(command, receipt)
        return VisibilityExecutionResult(receipt=receipt, replayed=True)

    @staticmethod
    def _validate_command(command: VisibilityCommand) -> VisibilityCommand:
        try:
            return _COMMAND_ADAPTER.validate_python(
                command.model_dump(mode="json")  # type: ignore[union-attr]
            )
        except (AttributeError, ValidationError) as exc:
            raise TypeError("command must be a visibility command") from exc

    @staticmethod
    def _validate_replay_binding(
        command: VisibilityCommand,
        receipt: VisibilityMutationReceipt,
    ) -> None:
        if receipt.table_id != command.table_id or receipt.command_id != command.command_id:
            raise VisibilityStoreCorruptionError(
                "stored visibility receipt does not match its command"
            )

    def snapshot(self, table_id: str, scene_id: str) -> VisibilityCatalogView:
        table_id = _canonical_id(table_id, field_name="table_id")
        scene_id = _canonical_id(scene_id, field_name="scene_id")
        snapshots = self._snapshots_locked(table_id)
        return snapshots.get(
            scene_id,
            VisibilityCatalogView(
                table_id=table_id,
                scene_id=scene_id,
                revision=self._revision_locked(table_id),
            ),
        )

    def revision(self, table_id: str) -> int:
        return self._revision_locked(_canonical_id(table_id, field_name="table_id"))

    def events_after(self, table_id: str, sequence: int) -> tuple[VisibilityChangedEvent, ...]:
        table_id = _canonical_id(table_id, field_name="table_id")
        if type(sequence) is not int or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        rows = self._connection.execute(
            f"""
            SELECT store_schema_version, receipt_json
            FROM {_EVENTS_TABLE}
            WHERE table_id = ? AND sequence > ?
            ORDER BY sequence ASC
            """,
            (table_id, sequence),
        ).fetchall()
        events = []
        for row in rows:
            if str(row[0]) != VISIBILITY_STORE_SCHEMA_VERSION:
                raise VisibilityStoreCorruptionError("stored visibility schema is unsupported")
            events.append(self._parse_receipt(str(row[1])).event)
        return tuple(events)

    def _revision_locked(self, table_id: str) -> int:
        row = self._connection.execute(
            f"SELECT COALESCE(MAX(revision), 0) FROM {_EVENTS_TABLE} WHERE table_id = ?",
            (table_id,),
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def _snapshots_locked(self, table_id: str) -> dict[str, VisibilityCatalogView]:
        rows = self._connection.execute(
            f"""
            SELECT store_schema_version, command_json, receipt_json
            FROM {_EVENTS_TABLE}
            WHERE table_id = ?
            ORDER BY sequence ASC
            """,
            (table_id,),
        ).fetchall()
        snapshots: dict[str, VisibilityCatalogView] = {}
        expected_revision = 1
        for row in rows:
            if str(row[0]) != VISIBILITY_STORE_SCHEMA_VERSION:
                raise VisibilityStoreCorruptionError("stored visibility schema is unsupported")
            try:
                raw_command = json.loads(str(row[1]))
                command = _COMMAND_ADAPTER.validate_python(raw_command)
            except (ValueError, json.JSONDecodeError, ValidationError) as exc:
                raise VisibilityStoreCorruptionError(
                    "stored visibility command is invalid"
                ) from exc
            if _canonical_json(command) != str(row[1]):
                raise VisibilityStoreCorruptionError("stored visibility command is not canonical")
            receipt = self._parse_receipt(str(row[2]))
            if (
                receipt.event.revision != expected_revision
                or receipt.event.sequence != expected_revision
                or receipt.command_id != command.command_id
                or receipt.table_id != command.table_id
            ):
                raise VisibilityStoreCorruptionError("visibility history has invalid continuity")
            try:
                snapshots = self._apply_event(snapshots, receipt.event)
            except ValidationError as exc:
                raise VisibilityStoreCorruptionError(
                    "stored visibility event produces invalid state"
                ) from exc
            expected_revision += 1
        revision = expected_revision - 1
        return {
            scene_id: snapshot.model_copy(update={"revision": revision})
            for scene_id, snapshot in snapshots.items()
        }

    @staticmethod
    def _parse_receipt(encoded: str) -> VisibilityMutationReceipt:
        try:
            payload = json.loads(encoded)
            receipt = VisibilityMutationReceipt.model_validate(payload)
        except (ValueError, json.JSONDecodeError, ValidationError) as exc:
            raise VisibilityStoreCorruptionError("stored visibility receipt is invalid") from exc
        if _canonical_json(receipt) != encoded:
            raise VisibilityStoreCorruptionError("stored visibility receipt is not canonical")
        return receipt

    @staticmethod
    def _build_event(
        command: VisibilityCommand,
        snapshots: dict[str, VisibilityCatalogView],
        *,
        revision: int,
    ) -> VisibilityChangedEvent:
        record: VisibilityRecord | None = None
        deleted_record_id: str | None = None
        if isinstance(command, VisibilityPutCommand):
            record = command.record
            snapshot = snapshots.get(record.scene_id)
            current = (
                None
                if snapshot is None
                else next(
                    (item for item in snapshot.records if item.record_id == record.record_id),
                    None,
                )
            )
            if isinstance(record, FogOperation):
                fog_count = (
                    0
                    if snapshot is None
                    else sum(isinstance(item, FogOperation) for item in snapshot.records)
                )
                if current is not None or record.operation_index != fog_count + 1:
                    raise VisibilityRecordConflictError(
                        "fog operations must append with a new ID and contiguous index"
                    )
            elif current is not None and type(current) is not type(record):
                raise VisibilityRecordConflictError(
                    "visibility record IDs cannot change record type"
                )
            if (
                isinstance(record, TokenVision)
                and snapshot is not None
                and any(
                    isinstance(item, TokenVision)
                    and item.record_id != record.record_id
                    and item.token_id == record.token_id
                    for item in snapshot.records
                )
            ):
                raise VisibilityRecordConflictError("a token may contain at most one vision record")
            operation = "put"
            scene_id = record.scene_id
        elif isinstance(command, VisibilityDeleteCommand):
            snapshot = snapshots.get(command.scene_id)
            current = (
                None
                if snapshot is None
                else next(
                    (item for item in snapshot.records if item.record_id == command.record_id),
                    None,
                )
            )
            if current is None:
                raise VisibilityRecordNotFoundError("visibility record is missing")
            if isinstance(current, FogOperation):
                raise VisibilityRecordConflictError("fog history is append-only")
            scene_id = command.scene_id
            deleted_record_id = command.record_id
            operation = "delete"
        elif isinstance(command, VisibilityDoorStateCommand):
            snapshot = snapshots.get(command.scene_id)
            current = (
                None
                if snapshot is None
                else next(
                    (item for item in snapshot.records if item.record_id == command.barrier_id),
                    None,
                )
            )
            if not isinstance(current, SightBarrier) or current.behavior != "door":
                raise VisibilityRecordNotFoundError("door barrier is missing")
            if current.portal_state == command.portal_state:
                raise VisibilityRecordConflictError("door already has the requested state")
            record = current.model_copy(update={"portal_state": command.portal_state})
            scene_id = command.scene_id
            operation = "set_door_state"
        else:
            assert isinstance(command, VisibilityFogUndoCommand)
            snapshot = snapshots.get(command.scene_id)
            target = (
                None
                if snapshot is None
                else next(
                    (
                        item
                        for item in snapshot.records
                        if item.record_id == command.target_record_id
                    ),
                    None,
                )
            )
            if not isinstance(target, FogOperation):
                raise VisibilityRecordNotFoundError("fog operation is missing")
            if snapshot is not None and any(
                item.record_id == command.inverse_record_id for item in snapshot.records
            ):
                raise VisibilityRecordConflictError("inverse fog record ID is already used")
            fog_count = (
                sum(isinstance(item, FogOperation) for item in snapshot.records)
                if snapshot is not None
                else 0
            )
            record = FogOperation(
                record_id=command.inverse_record_id,
                scene_id=command.scene_id,
                operation_index=fog_count + 1,
                operation="hide" if target.operation == "reveal" else "reveal",
                polygon=target.polygon,
                inverse_of=target.record_id,
            )
            scene_id = command.scene_id
            operation = "undo_fog"
        return VisibilityChangedEvent(
            sequence=revision,
            revision=revision,
            table_id=command.table_id,
            command_id=command.command_id,
            scene_id=scene_id,
            operation=operation,
            record=record,
            deleted_record_id=deleted_record_id,
        )

    @staticmethod
    def _apply_event(
        snapshots: dict[str, VisibilityCatalogView],
        event: VisibilityChangedEvent,
    ) -> dict[str, VisibilityCatalogView]:
        updated = dict(snapshots)
        current = updated.get(
            event.scene_id,
            VisibilityCatalogView(
                table_id=event.table_id,
                scene_id=event.scene_id,
                revision=event.revision - 1,
            ),
        )
        records = {record.record_id: record for record in current.records}
        if event.operation == "delete":
            assert event.deleted_record_id is not None
            records.pop(event.deleted_record_id, None)
        else:
            assert event.record is not None
            records[event.record.record_id] = _RECORD_ADAPTER.validate_python(
                event.record.model_dump(mode="json")
            )
        updated[event.scene_id] = VisibilityCatalogView(
            table_id=event.table_id,
            scene_id=event.scene_id,
            revision=event.revision,
            records=tuple(records[record_id] for record_id in sorted(records)),
        )
        return updated

    @staticmethod
    def _validate_limits(snapshot: VisibilityCatalogView) -> None:
        limits = (
            (SightBarrier, MAX_BARRIERS_PER_SCENE),
            (LightEmitter, MAX_LIGHTS_PER_SCENE),
            (TokenVision, MAX_TOKEN_VISION_PER_SCENE),
            (FogOperation, MAX_FOG_OPERATIONS_PER_SCENE),
        )
        for record_type, maximum in limits:
            if sum(isinstance(record, record_type) for record in snapshot.records) > maximum:
                raise VisibilityLimitError("visibility record count exceeds the scene limit")
        if sum(isinstance(record, SceneEnvironment) for record in snapshot.records) > 1:
            raise VisibilityLimitError("a scene may have only one environment")


__all__ = [
    "MAX_BARRIERS_PER_SCENE",
    "MAX_FOG_OPERATIONS_PER_SCENE",
    "MAX_LIGHTS_PER_SCENE",
    "MAX_TOKEN_VISION_PER_SCENE",
    "VISIBILITY_STORE_SCHEMA_VERSION",
    "SQLiteVisibilityStore",
    "VisibilityCommandConflictError",
    "VisibilityExecutionResult",
    "VisibilityLimitError",
    "VisibilityRecordConflictError",
    "VisibilityRecordNotFoundError",
    "VisibilityRevisionConflictError",
    "VisibilityStoreCorruptionError",
    "VisibilityStoreError",
    "VisibilityStoreSchemaError",
]
