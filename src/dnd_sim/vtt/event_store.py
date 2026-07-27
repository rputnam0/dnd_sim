"""Transactional SQLite persistence for deterministic VTT session commits."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeAlias

EVENT_STORE_SCHEMA_VERSION = "vtt.event_store.v1"

JSONValue: TypeAlias = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]

_METADATA_TABLE = "vtt_event_store_metadata"
_COMMANDS_TABLE = "vtt_committed_commands"


class EventStoreError(RuntimeError):
    """Base error for persisted VTT session data."""


class EventStoreSchemaError(EventStoreError):
    """Raised when the database uses an unsupported event-store schema."""


class CommandConflictError(EventStoreError):
    """Raised when a command ID is reused for different command content."""


@dataclass(frozen=True, slots=True)
class StoredCommand:
    """One immutable committed command in per-session order."""

    schema_version: str
    session_id: str
    sequence: int
    command_id: str
    command: dict[str, JSONValue]
    receipt: dict[str, JSONValue]


@dataclass(frozen=True, slots=True)
class StoredSessionSnapshot:
    """The latest durable snapshot for one session."""

    schema_version: str
    session_id: str
    last_command_sequence: int
    snapshot: dict[str, JSONValue]


@dataclass(frozen=True, slots=True)
class AppendCommitResult:
    """Result of appending a new commit or replaying an existing one."""

    record: StoredCommand
    replayed: bool


def _required_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


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


def _canonical_json_object(
    value: Mapping[str, Any], *, field_name: str
) -> tuple[dict[str, JSONValue], str]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a JSON object")
    normalized = _normalize_json(value, path=field_name)
    if not isinstance(normalized, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    encoded = json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return normalized, encoded


def _decode_json_object(encoded: str, *, field_name: str) -> dict[str, JSONValue]:
    try:
        decoded = json.loads(encoded)
    except (TypeError, json.JSONDecodeError) as exc:
        raise EventStoreError(f"stored {field_name} is not valid JSON") from exc
    try:
        normalized = _normalize_json(decoded, path=field_name)
    except ValueError as exc:
        raise EventStoreError(f"stored {field_name} is not canonical JSON") from exc
    if not isinstance(normalized, dict):
        raise EventStoreError(f"stored {field_name} must be a JSON object")
    return normalized


def _validate_embedded_identity(
    payload: Mapping[str, JSONValue],
    *,
    field_name: str,
    session_id: str,
    command_id: str | None = None,
) -> None:
    embedded_session_id = payload.get("session_id")
    if embedded_session_id is not None and embedded_session_id != session_id:
        raise ValueError(f"{field_name}.session_id must match session_id")
    embedded_command_id = payload.get("command_id")
    if command_id is not None and embedded_command_id is not None:
        if embedded_command_id != command_id:
            raise ValueError(f"{field_name}.command_id must match command_id")


class SQLiteSessionEventStore:
    """Append-only command, receipt, and resulting-snapshot history for VTT sessions.

    The caller owns the supplied connection. Each ``append_commit`` call owns one
    immediate SQLite transaction and requires that the connection is not already
    inside a caller-managed transaction.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        if connection.in_transaction:
            raise EventStoreError("cannot initialize the event store inside an active transaction")
        self._connection = connection
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
                    f"""
                    INSERT INTO {_METADATA_TABLE} (singleton, schema_version)
                    VALUES (1, ?)
                    """,
                    (EVENT_STORE_SCHEMA_VERSION,),
                )
            elif str(metadata[0]) != EVENT_STORE_SCHEMA_VERSION:
                raise EventStoreSchemaError(
                    "unsupported VTT event-store schema "
                    f"'{metadata[0]}'; expected '{EVENT_STORE_SCHEMA_VERSION}'"
                )

            self._connection.execute(f"""
                CREATE TABLE IF NOT EXISTS {_COMMANDS_TABLE} (
                    schema_version TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL CHECK (sequence >= 1),
                    command_id TEXT NOT NULL,
                    command_json TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    PRIMARY KEY (session_id, command_id),
                    UNIQUE (session_id, sequence),
                    CHECK (length(trim(session_id)) > 0),
                    CHECK (length(trim(command_id)) > 0),
                    CHECK (length(trim(command_json)) > 0),
                    CHECK (length(trim(receipt_json)) > 0),
                    CHECK (length(trim(snapshot_json)) > 0)
                )
                """)
            self._connection.commit()
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def append_commit(
        self,
        *,
        session_id: str,
        command_id: str,
        command: Mapping[str, Any],
        receipt: Mapping[str, Any],
        snapshot: Mapping[str, Any],
    ) -> AppendCommitResult:
        """Atomically append one command, its receipt, and its resulting snapshot.

        An existing command ID with byte-equivalent canonical command content is an
        idempotent retry: its original stored receipt is returned and the supplied
        receipt and snapshot are ignored. Reusing the ID for another command fails.
        """

        normalized_session_id = _required_text(session_id, field_name="session_id")
        normalized_command_id = _required_text(command_id, field_name="command_id")
        normalized_command, command_json = _canonical_json_object(command, field_name="command")
        normalized_receipt, receipt_json = _canonical_json_object(receipt, field_name="receipt")
        normalized_snapshot, snapshot_json = _canonical_json_object(snapshot, field_name="snapshot")

        _validate_embedded_identity(
            normalized_command,
            field_name="command",
            session_id=normalized_session_id,
            command_id=normalized_command_id,
        )
        _validate_embedded_identity(
            normalized_receipt,
            field_name="receipt",
            session_id=normalized_session_id,
            command_id=normalized_command_id,
        )
        _validate_embedded_identity(
            normalized_snapshot,
            field_name="snapshot",
            session_id=normalized_session_id,
        )

        if self._connection.in_transaction:
            raise EventStoreError("append_commit cannot run inside an active transaction")

        try:
            self._connection.execute("BEGIN IMMEDIATE")
            existing = self._connection.execute(
                f"""
                SELECT schema_version, sequence, command_json, receipt_json
                FROM {_COMMANDS_TABLE}
                WHERE session_id = ? AND command_id = ?
                """,
                (normalized_session_id, normalized_command_id),
            ).fetchone()

            if existing is not None:
                self._validate_stored_schema(str(existing[0]))
                if str(existing[2]) != command_json:
                    raise CommandConflictError(
                        "command_id "
                        f"'{normalized_command_id}' is already committed with different content"
                    )
                record = StoredCommand(
                    schema_version=str(existing[0]),
                    session_id=normalized_session_id,
                    sequence=int(existing[1]),
                    command_id=normalized_command_id,
                    command=_decode_json_object(str(existing[2]), field_name="command"),
                    receipt=_decode_json_object(str(existing[3]), field_name="receipt"),
                )
                self._connection.commit()
                return AppendCommitResult(record=record, replayed=True)

            sequence_row = self._connection.execute(
                f"""
                SELECT COALESCE(MAX(sequence), 0) + 1
                FROM {_COMMANDS_TABLE}
                WHERE session_id = ?
                """,
                (normalized_session_id,),
            ).fetchone()
            if sequence_row is None:
                raise EventStoreError("failed to allocate the next command sequence")
            sequence = int(sequence_row[0])
            self._connection.execute(
                f"""
                INSERT INTO {_COMMANDS_TABLE} (
                    schema_version,
                    session_id,
                    sequence,
                    command_id,
                    command_json,
                    receipt_json,
                    snapshot_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    EVENT_STORE_SCHEMA_VERSION,
                    normalized_session_id,
                    sequence,
                    normalized_command_id,
                    command_json,
                    receipt_json,
                    snapshot_json,
                ),
            )
            self._connection.commit()
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

        return AppendCommitResult(
            record=StoredCommand(
                schema_version=EVENT_STORE_SCHEMA_VERSION,
                session_id=normalized_session_id,
                sequence=sequence,
                command_id=normalized_command_id,
                command=normalized_command,
                receipt=normalized_receipt,
            ),
            replayed=False,
        )

    def load_latest_snapshot(self, session_id: str) -> StoredSessionSnapshot | None:
        """Load the latest committed snapshot for ``session_id`` when present."""

        normalized_session_id = _required_text(session_id, field_name="session_id")
        row = self._connection.execute(
            f"""
            SELECT schema_version, sequence, snapshot_json
            FROM {_COMMANDS_TABLE}
            WHERE session_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (normalized_session_id,),
        ).fetchone()
        if row is None:
            return None
        self._validate_stored_schema(str(row[0]))
        return StoredSessionSnapshot(
            schema_version=str(row[0]),
            session_id=normalized_session_id,
            last_command_sequence=int(row[1]),
            snapshot=_decode_json_object(str(row[2]), field_name="snapshot"),
        )

    def load_commands(self, session_id: str) -> tuple[StoredCommand, ...]:
        """Load all committed commands in deterministic per-session order."""

        normalized_session_id = _required_text(session_id, field_name="session_id")
        rows = self._connection.execute(
            f"""
            SELECT schema_version, sequence, command_id, command_json, receipt_json
            FROM {_COMMANDS_TABLE}
            WHERE session_id = ?
            ORDER BY sequence ASC
            """,
            (normalized_session_id,),
        ).fetchall()
        records: list[StoredCommand] = []
        for row in rows:
            self._validate_stored_schema(str(row[0]))
            records.append(
                StoredCommand(
                    schema_version=str(row[0]),
                    session_id=normalized_session_id,
                    sequence=int(row[1]),
                    command_id=str(row[2]),
                    command=_decode_json_object(str(row[3]), field_name="command"),
                    receipt=_decode_json_object(str(row[4]), field_name="receipt"),
                )
            )
        return tuple(records)

    @staticmethod
    def _validate_stored_schema(schema_version: str) -> None:
        if schema_version != EVENT_STORE_SCHEMA_VERSION:
            raise EventStoreSchemaError(
                f"stored row uses schema '{schema_version}', expected "
                f"'{EVENT_STORE_SCHEMA_VERSION}'"
            )
