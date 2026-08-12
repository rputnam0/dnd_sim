"""Restart-safe append-only SQLite storage for VTT participant presence."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from .participants import TableRoster
from .presence_contracts import (
    PresenceHeartbeatCommand,
    PresenceHeartbeatEvent,
    PresenceHeartbeatReceipt,
    PresenceRecord,
    PresenceView,
)

PRESENCE_STORE_SCHEMA_VERSION = "vtt.presence_store.v1"
DEFAULT_PRESENCE_AWAY_AFTER_MS = 30_000
DEFAULT_PRESENCE_OFFLINE_AFTER_MS = 90_000
_METADATA_TABLE = "_vtt_presence_store_metadata"
_EVENTS_TABLE = "_vtt_presence_event_log"


class PresenceStoreError(RuntimeError):
    """Base failure for durable presence operations."""


class PresenceStoreSchemaError(PresenceStoreError):
    pass


class PresenceStoreCorruptionError(PresenceStoreError):
    pass


class PresenceCommandConflictError(PresenceStoreError):
    pass


class PresenceRevisionConflictError(PresenceStoreError):
    def __init__(self, *, current_revision: int, expected_revision: int) -> None:
        super().__init__(f"expected revision {current_revision}, received {expected_revision}")
        self.current_revision = current_revision
        self.expected_revision = expected_revision


class PresenceParticipantNotFoundError(PresenceStoreError):
    pass


class PresenceTableMismatchError(PresenceStoreError):
    pass


class PresenceTimeRegressionError(PresenceStoreError):
    pass


@dataclass(frozen=True, slots=True)
class PresenceExecutionResult:
    receipt: PresenceHeartbeatReceipt
    replayed: bool


@dataclass(frozen=True, slots=True)
class _PresenceSnapshot:
    revision: int
    events: tuple[PresenceHeartbeatEvent, ...]
    latest_by_client: dict[tuple[str, str], int]
    latest_observed_at_ms: int | None


def _canonical_json(model: BaseModel) -> str:
    return json.dumps(
        model.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_json(encoded: str, *, field_name: str) -> Any:
    try:
        return json.loads(
            encoded,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PresenceStoreCorruptionError(f"stored {field_name} is not valid JSON") from exc


def _non_negative_int(value: Any, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _stored_positive_int(value: Any, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise PresenceStoreCorruptionError(f"stored {field_name} is not a positive integer")
    return value


class SQLitePresenceStore:
    """One roster-scoped durable presence log with deterministic time inputs."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        roster: TableRoster,
        away_after_ms: int = DEFAULT_PRESENCE_AWAY_AFTER_MS,
        offline_after_ms: int = DEFAULT_PRESENCE_OFFLINE_AFTER_MS,
    ) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        if not isinstance(roster, TableRoster):
            raise TypeError("roster must be a TableRoster")
        away = _non_negative_int(away_after_ms, field_name="away_after_ms")
        offline = _non_negative_int(offline_after_ms, field_name="offline_after_ms")
        if away < 1:
            raise ValueError("away_after_ms must be a positive integer")
        if offline <= away:
            raise ValueError("offline_after_ms must be greater than away_after_ms")
        if connection.in_transaction:
            raise PresenceStoreError("cannot initialize presence storage inside a transaction")

        self._connection = connection
        self._roster = roster.model_copy(deep=True)
        self._away_after_ms = away
        self._offline_after_ms = offline
        self._initialize_schema()

    @property
    def table_id(self) -> str:
        return self._roster.table_id

    @property
    def roster(self) -> TableRoster:
        return self._roster.model_copy(deep=True)

    @property
    def revision(self) -> int:
        return self._snapshot_locked().revision

    @property
    def away_after_ms(self) -> int:
        return self._away_after_ms

    @property
    def offline_after_ms(self) -> int:
        return self._offline_after_ms

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
                    (PRESENCE_STORE_SCHEMA_VERSION,),
                )
            elif str(row[0]) != PRESENCE_STORE_SCHEMA_VERSION:
                raise PresenceStoreSchemaError("unsupported presence-store schema")
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
            self._connection.execute("PRAGMA optimize")
            self._connection.commit()
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def heartbeat(
        self,
        command: PresenceHeartbeatCommand,
        *,
        observed_at_ms: int,
    ) -> PresenceExecutionResult:
        if not isinstance(command, PresenceHeartbeatCommand):
            raise TypeError("command must be a PresenceHeartbeatCommand")
        command = PresenceHeartbeatCommand.model_validate(command.model_dump(mode="json"))
        observed_at = _non_negative_int(observed_at_ms, field_name="observed_at_ms")
        self._validate_command_scope(command)
        command_json = _canonical_json(command)
        if self._connection.in_transaction:
            raise PresenceStoreError("heartbeat cannot run inside an active transaction")

        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._validate_metadata()
            existing = self._connection.execute(
                f"""
                SELECT store_schema_version, sequence, revision, command_json, receipt_json
                FROM {_EVENTS_TABLE} WHERE table_id = ? AND command_id = ?
                """,
                (self.table_id, command.command_id),
            ).fetchone()
            if existing is not None:
                self._validate_schema(str(existing[0]))
                sequence = _stored_positive_int(existing[1], field_name="sequence")
                revision = _stored_positive_int(existing[2], field_name="revision")
                stored_command = self._parse_command(
                    str(existing[3]),
                    command_id=command.command_id,
                    revision=revision,
                )
                if str(existing[3]) != command_json:
                    raise PresenceCommandConflictError(
                        f"command_id '{command.command_id}' has different content"
                    )
                receipt = self._parse_receipt(
                    str(existing[4]),
                    command_id=command.command_id,
                    sequence=sequence,
                    revision=revision,
                )
                self._validate_command_receipt(stored_command, receipt)
                self._connection.commit()
                return PresenceExecutionResult(receipt=receipt, replayed=True)

            snapshot = self._snapshot_locked()
            if command.expected_revision != snapshot.revision:
                raise PresenceRevisionConflictError(
                    current_revision=snapshot.revision,
                    expected_revision=command.expected_revision,
                )
            if (
                snapshot.latest_observed_at_ms is not None
                and observed_at < snapshot.latest_observed_at_ms
            ):
                raise PresenceTimeRegressionError(
                    "observed_at_ms must not precede the latest durable presence observation"
                )

            next_revision = snapshot.revision + 1
            event = PresenceHeartbeatEvent(
                table_id=self.table_id,
                event_id=f"{self.table_id}:presence:{next_revision}",
                sequence=next_revision,
                revision=next_revision,
                command_id=command.command_id,
                participant_id=command.participant_id,
                client_id=command.client_id,
                observed_at_ms=observed_at,
                audience=("all",),
            )
            receipt = PresenceHeartbeatReceipt(
                table_id=self.table_id,
                command_id=command.command_id,
                revision=next_revision,
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
                    PRESENCE_STORE_SCHEMA_VERSION,
                    self.table_id,
                    next_revision,
                    next_revision,
                    command.command_id,
                    command_json,
                    _canonical_json(receipt),
                ),
            )
            self._connection.commit()
            return PresenceExecutionResult(receipt=receipt, replayed=False)
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def view(self, *, viewer_id: str, evaluated_at_ms: int) -> PresenceView:
        self._require_participant(viewer_id)
        evaluated_at = _non_negative_int(evaluated_at_ms, field_name="evaluated_at_ms")
        snapshot = self._snapshot_locked()
        if (
            snapshot.latest_observed_at_ms is not None
            and evaluated_at < snapshot.latest_observed_at_ms
        ):
            raise PresenceTimeRegressionError(
                "evaluated_at_ms must not precede the latest durable presence observation"
            )

        latest_by_participant: dict[str, int] = {}
        for (participant_id, _client_id), observed_at in snapshot.latest_by_client.items():
            latest = latest_by_participant.get(participant_id)
            if latest is None or observed_at > latest:
                latest_by_participant[participant_id] = observed_at

        records: list[PresenceRecord] = []
        for participant in self._roster.participants:
            latest = latest_by_participant.get(participant.participant_id)
            if latest is None:
                status = "offline"
            else:
                age = evaluated_at - latest
                if age < self._away_after_ms:
                    status = "online"
                elif age < self._offline_after_ms:
                    status = "away"
                else:
                    status = "offline"
            records.append(
                PresenceRecord(
                    participant_id=participant.participant_id,
                    display_name=participant.display_name,
                    role=participant.role,
                    status=status,
                )
            )

        return PresenceView(
            table_id=self.table_id,
            revision=snapshot.revision,
            evaluated_at_ms=evaluated_at,
            away_after_ms=self._away_after_ms,
            offline_after_ms=self._offline_after_ms,
            records=tuple(records),
        )

    def events_after(
        self,
        *,
        viewer_id: str,
        sequence: int,
    ) -> tuple[PresenceHeartbeatEvent, ...]:
        self._require_participant(viewer_id)
        normalized_sequence = _non_negative_int(sequence, field_name="sequence")
        self._validate_metadata()
        rows = self._connection.execute(
            f"""
            SELECT store_schema_version, sequence, revision, command_id,
                   command_json, receipt_json
            FROM {_EVENTS_TABLE}
            WHERE table_id = ? AND sequence > ?
            ORDER BY sequence ASC
            """,
            (self.table_id, normalized_sequence),
        ).fetchall()
        events = self._parse_event_rows(rows)
        expected_sequence = normalized_sequence + 1
        for event in events:
            if event.sequence != expected_sequence:
                raise PresenceStoreCorruptionError("presence history has a sequence gap")
            expected_sequence += 1
        return events

    def _events_locked(self) -> tuple[PresenceHeartbeatEvent, ...]:
        self._validate_metadata()
        rows = self._connection.execute(
            f"""
            SELECT store_schema_version, sequence, revision, command_id,
                   command_json, receipt_json
            FROM {_EVENTS_TABLE} WHERE table_id = ? ORDER BY sequence ASC
            """,
            (self.table_id,),
        ).fetchall()
        return self._parse_event_rows(rows)

    def _parse_event_rows(
        self,
        rows: list[tuple[Any, ...]],
    ) -> tuple[PresenceHeartbeatEvent, ...]:
        events: list[PresenceHeartbeatEvent] = []
        for row in rows:
            self._validate_schema(str(row[0]))
            sequence = _stored_positive_int(row[1], field_name="sequence")
            revision = _stored_positive_int(row[2], field_name="revision")
            command = self._parse_command(
                str(row[4]),
                command_id=str(row[3]),
                revision=revision,
            )
            receipt = self._parse_receipt(
                str(row[5]),
                command_id=str(row[3]),
                sequence=sequence,
                revision=revision,
            )
            self._validate_command_receipt(command, receipt)
            self._validate_stored_participant(command.participant_id)
            events.append(receipt.event)
        return tuple(events)

    def _snapshot_locked(self) -> _PresenceSnapshot:
        events = self._events_locked()
        expected_revision = 1
        latest_observed_at_ms: int | None = None
        latest_by_client: dict[tuple[str, str], int] = {}
        for event in events:
            if event.sequence != expected_revision or event.revision != expected_revision:
                raise PresenceStoreCorruptionError(
                    "presence history has a sequence or revision gap"
                )
            if latest_observed_at_ms is not None and event.observed_at_ms < latest_observed_at_ms:
                raise PresenceStoreCorruptionError(
                    "presence history contains a regressing observation time"
                )
            latest_observed_at_ms = event.observed_at_ms
            latest_by_client[(event.participant_id, event.client_id)] = event.observed_at_ms
            expected_revision += 1
        return _PresenceSnapshot(
            revision=expected_revision - 1,
            events=events,
            latest_by_client=latest_by_client,
            latest_observed_at_ms=latest_observed_at_ms,
        )

    def _validate_command_scope(self, command: PresenceHeartbeatCommand) -> None:
        if command.table_id != self.table_id:
            raise PresenceTableMismatchError(
                f"command table '{command.table_id}' does not match '{self.table_id}'"
            )
        self._require_participant(command.participant_id)

    def _require_participant(self, participant_id: str) -> None:
        try:
            participant = self._roster.participant(participant_id)
        except TypeError as exc:
            raise PresenceParticipantNotFoundError(
                "participant is not in the table roster"
            ) from exc
        if participant is None:
            raise PresenceParticipantNotFoundError("participant is not in the table roster")

    def _validate_stored_participant(self, participant_id: str) -> None:
        if self._roster.participant(participant_id) is None:
            raise PresenceStoreCorruptionError(
                "stored heartbeat participant is not in the current roster"
            )

    def _validate_metadata(self) -> None:
        row = self._connection.execute(
            f"SELECT schema_version FROM {_METADATA_TABLE} WHERE singleton = 1"
        ).fetchone()
        if row is None:
            raise PresenceStoreCorruptionError("presence-store metadata is missing")
        self._validate_schema(str(row[0]))

    @staticmethod
    def _validate_schema(value: str) -> None:
        if value != PRESENCE_STORE_SCHEMA_VERSION:
            raise PresenceStoreSchemaError("unsupported presence-store schema")

    def _parse_command(
        self,
        encoded: str,
        *,
        command_id: str,
        revision: int,
    ) -> PresenceHeartbeatCommand:
        try:
            command = PresenceHeartbeatCommand.model_validate(
                _decode_json(encoded, field_name="command")
            )
        except ValidationError as exc:
            raise PresenceStoreCorruptionError("stored presence command is invalid") from exc
        if command.table_id != self.table_id or command.command_id != command_id:
            raise PresenceStoreCorruptionError("stored presence command identity is inconsistent")
        if command.expected_revision != revision - 1:
            raise PresenceStoreCorruptionError("stored presence command revision is inconsistent")
        return command

    def _parse_receipt(
        self,
        encoded: str,
        *,
        command_id: str,
        sequence: int,
        revision: int,
    ) -> PresenceHeartbeatReceipt:
        try:
            receipt = PresenceHeartbeatReceipt.model_validate(
                _decode_json(encoded, field_name="receipt")
            )
        except ValidationError as exc:
            raise PresenceStoreCorruptionError("stored presence receipt is invalid") from exc
        event = receipt.event
        if (
            receipt.table_id != self.table_id
            or receipt.command_id != command_id
            or receipt.revision != revision
            or event.sequence != sequence
            or event.event_id != f"{self.table_id}:presence:{revision}"
        ):
            raise PresenceStoreCorruptionError("stored presence receipt identity is inconsistent")
        return receipt

    @staticmethod
    def _validate_command_receipt(
        command: PresenceHeartbeatCommand,
        receipt: PresenceHeartbeatReceipt,
    ) -> None:
        event = receipt.event
        if (
            event.command_id != command.command_id
            or event.table_id != command.table_id
            or event.participant_id != command.participant_id
            or event.client_id != command.client_id
        ):
            raise PresenceStoreCorruptionError(
                "stored presence command and receipt are inconsistent"
            )


__all__ = [
    "DEFAULT_PRESENCE_AWAY_AFTER_MS",
    "DEFAULT_PRESENCE_OFFLINE_AFTER_MS",
    "PRESENCE_STORE_SCHEMA_VERSION",
    "PresenceCommandConflictError",
    "PresenceExecutionResult",
    "PresenceParticipantNotFoundError",
    "PresenceRevisionConflictError",
    "PresenceStoreCorruptionError",
    "PresenceStoreError",
    "PresenceStoreSchemaError",
    "PresenceTableMismatchError",
    "PresenceTimeRegressionError",
    "SQLitePresenceStore",
]
