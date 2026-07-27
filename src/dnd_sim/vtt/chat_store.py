"""Restart-safe append-only SQLite storage for plain-text VTT chat."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from .chat_contracts import (
    ChatDeleteCommand,
    ChatDeletedEvent,
    ChatMessage,
    ChatMutationCommand,
    ChatMutationEvent,
    ChatMutationReceipt,
    ChatPostCommand,
    ChatPostedEvent,
    parse_chat_command,
)

CHAT_STORE_SCHEMA_VERSION = "vtt.chat_store.v1"
_METADATA_TABLE = "_vtt_chat_store_metadata"
_EVENTS_TABLE = "_vtt_chat_event_log"


class ChatStoreError(RuntimeError):
    """Base failure for durable chat operations."""


class ChatStoreSchemaError(ChatStoreError):
    pass


class ChatStoreCorruptionError(ChatStoreError):
    pass


class ChatCommandConflictError(ChatStoreError):
    pass


class ChatRevisionConflictError(ChatStoreError):
    pass


class ChatMessageConflictError(ChatStoreError):
    pass


class ChatMessageNotFoundError(ChatStoreError):
    pass


@dataclass(frozen=True, slots=True)
class ChatExecutionResult:
    receipt: ChatMutationReceipt
    replayed: bool


@dataclass(frozen=True, slots=True)
class ChatLogSnapshot:
    revision: int
    messages: tuple[ChatMessage, ...]
    events: tuple[ChatMutationEvent, ...]


def _canonical_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    return value


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
            encoded, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value))
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ChatStoreCorruptionError(f"stored {field_name} is not valid JSON") from exc


def _stored_positive_int(value: Any, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise ChatStoreCorruptionError(f"stored {field_name} is not a positive integer")
    return value


class SQLiteChatLog:
    """One connection-owned durable log supporting isolated chat tables."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        if connection.in_transaction:
            raise ChatStoreError("cannot initialize chat storage inside a transaction")
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
                    (CHAT_STORE_SCHEMA_VERSION,),
                )
            elif str(row[0]) != CHAT_STORE_SCHEMA_VERSION:
                raise ChatStoreSchemaError("unsupported chat-store schema")
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

    def execute(self, command: ChatMutationCommand) -> ChatExecutionResult:
        if not isinstance(command, (ChatPostCommand, ChatDeleteCommand)):
            raise TypeError("command must be a chat mutation command")
        command = parse_chat_command(command.model_dump(mode="json"))
        command_json = _canonical_json(command)
        if self._connection.in_transaction:
            raise ChatStoreError("execute cannot run inside an active transaction")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            existing = self._connection.execute(
                f"""
                SELECT store_schema_version, sequence, revision, command_json, receipt_json
                FROM {_EVENTS_TABLE} WHERE table_id = ? AND command_id = ?
                """,
                (command.table_id, command.command_id),
            ).fetchone()
            if existing is not None:
                self._validate_schema(str(existing[0]))
                sequence = _stored_positive_int(existing[1], field_name="sequence")
                revision = _stored_positive_int(existing[2], field_name="revision")
                stored_command = self._parse_command(
                    str(existing[3]),
                    table_id=command.table_id,
                    command_id=command.command_id,
                    revision=revision,
                )
                if str(existing[3]) != command_json:
                    raise ChatCommandConflictError(
                        f"command_id '{command.command_id}' has different content"
                    )
                receipt = self._parse_receipt(
                    str(existing[4]),
                    table_id=command.table_id,
                    command_id=command.command_id,
                    sequence=sequence,
                    revision=revision,
                )
                self._validate_command_receipt(stored_command, receipt)
                self._connection.commit()
                return ChatExecutionResult(receipt=receipt, replayed=True)

            snapshot = self._snapshot_locked(command.table_id)
            if command.expected_revision != snapshot.revision:
                raise ChatRevisionConflictError(
                    f"expected revision {snapshot.revision}, received {command.expected_revision}"
                )
            next_value = snapshot.revision + 1
            event_id = f"{command.table_id}:chat:{next_value}"
            if isinstance(command, ChatPostCommand):
                posted_ids = {
                    event.message_id
                    for event in snapshot.events
                    if isinstance(event, ChatPostedEvent)
                }
                if command.message.message_id in posted_ids:
                    raise ChatMessageConflictError(
                        f"message_id '{command.message.message_id}' was already used"
                    )
                event: ChatMutationEvent = ChatPostedEvent(
                    table_id=command.table_id,
                    event_id=event_id,
                    sequence=next_value,
                    revision=next_value,
                    command_id=command.command_id,
                    message_id=command.message.message_id,
                    message=command.message,
                )
            else:
                current = {message.message_id: message for message in snapshot.messages}
                message = current.get(command.message_id)
                if message is None:
                    raise ChatMessageNotFoundError(f"message_id '{command.message_id}' is missing")
                event = ChatDeletedEvent(
                    table_id=command.table_id,
                    event_id=event_id,
                    sequence=next_value,
                    revision=next_value,
                    command_id=command.command_id,
                    message_id=message.message_id,
                    author_id=message.author_id,
                    audience=message.audience,
                )
            receipt = ChatMutationReceipt(
                table_id=command.table_id,
                command_id=command.command_id,
                revision=next_value,
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
                    CHAT_STORE_SCHEMA_VERSION,
                    command.table_id,
                    next_value,
                    next_value,
                    command.command_id,
                    command_json,
                    _canonical_json(receipt),
                ),
            )
            self._connection.commit()
            return ChatExecutionResult(receipt=receipt, replayed=False)
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def snapshot(self, table_id: str) -> ChatLogSnapshot:
        return self._snapshot_locked(_canonical_text(table_id, field_name="table_id"))

    def revision(self, table_id: str) -> int:
        return self.snapshot(table_id).revision

    def messages(self, table_id: str) -> tuple[ChatMessage, ...]:
        return self.snapshot(table_id).messages

    def events_after(self, table_id: str, sequence: int) -> tuple[ChatMutationEvent, ...]:
        normalized = _canonical_text(table_id, field_name="table_id")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        return tuple(
            event for event in self._events_locked(normalized) if event.sequence > sequence
        )

    def _events_locked(self, table_id: str) -> tuple[ChatMutationEvent, ...]:
        rows = self._connection.execute(
            f"""
            SELECT store_schema_version, sequence, revision, command_id,
                   command_json, receipt_json
            FROM {_EVENTS_TABLE} WHERE table_id = ? ORDER BY sequence ASC
            """,
            (table_id,),
        ).fetchall()
        events: list[ChatMutationEvent] = []
        for row in rows:
            self._validate_schema(str(row[0]))
            sequence = _stored_positive_int(row[1], field_name="sequence")
            revision = _stored_positive_int(row[2], field_name="revision")
            command = self._parse_command(
                str(row[4]),
                table_id=table_id,
                command_id=str(row[3]),
                revision=revision,
            )
            receipt = self._parse_receipt(
                str(row[5]),
                table_id=table_id,
                command_id=str(row[3]),
                sequence=sequence,
                revision=revision,
            )
            self._validate_command_receipt(command, receipt)
            events.append(receipt.event)
        return tuple(events)

    def _snapshot_locked(self, table_id: str) -> ChatLogSnapshot:
        events = self._events_locked(table_id)
        current: dict[str, ChatMessage] = {}
        posted_ids: set[str] = set()
        expected = 1
        for event in events:
            if event.sequence != expected or event.revision != expected:
                raise ChatStoreCorruptionError("chat history has a sequence or revision gap")
            if isinstance(event, ChatPostedEvent):
                if event.message_id in posted_ids:
                    raise ChatStoreCorruptionError("chat history reuses a message ID")
                posted_ids.add(event.message_id)
                current[event.message_id] = event.message
            else:
                previous = current.get(event.message_id)
                if previous is None:
                    raise ChatStoreCorruptionError("chat delete targets a missing message")
                if previous.author_id != event.author_id or previous.audience != event.audience:
                    raise ChatStoreCorruptionError("chat delete tombstone is inconsistent")
                del current[event.message_id]
            expected += 1
        return ChatLogSnapshot(
            revision=expected - 1,
            messages=tuple(current.values()),
            events=events,
        )

    @staticmethod
    def _parse_command(
        encoded: str,
        *,
        table_id: str,
        command_id: str,
        revision: int,
    ) -> ChatMutationCommand:
        try:
            command = parse_chat_command(_decode_json(encoded, field_name="command"))
        except ValidationError as exc:
            raise ChatStoreCorruptionError("stored command violates its contract") from exc
        if (
            command.table_id != table_id
            or command.command_id != command_id
            or command.expected_revision != revision - 1
            or _canonical_json(command) != encoded
        ):
            raise ChatStoreCorruptionError("stored command identity is inconsistent")
        return command

    @staticmethod
    def _parse_receipt(
        encoded: str,
        *,
        table_id: str,
        command_id: str,
        sequence: int,
        revision: int,
    ) -> ChatMutationReceipt:
        try:
            receipt = ChatMutationReceipt.model_validate(
                _decode_json(encoded, field_name="receipt")
            )
        except ValidationError as exc:
            raise ChatStoreCorruptionError("stored receipt violates its contract") from exc
        if (
            receipt.table_id != table_id
            or receipt.command_id != command_id
            or receipt.revision != revision
            or receipt.event.sequence != sequence
            or receipt.event.event_id != f"{table_id}:chat:{sequence}"
        ):
            raise ChatStoreCorruptionError("stored receipt identity is inconsistent")
        return receipt

    @staticmethod
    def _validate_command_receipt(
        command: ChatMutationCommand,
        receipt: ChatMutationReceipt,
    ) -> None:
        event = receipt.event
        if isinstance(command, ChatPostCommand):
            if not isinstance(event, ChatPostedEvent) or event.message != command.message:
                raise ChatStoreCorruptionError("stored post command and event are inconsistent")
            return
        if not isinstance(event, ChatDeletedEvent) or event.message_id != command.message_id:
            raise ChatStoreCorruptionError("stored delete command and event are inconsistent")

    @staticmethod
    def _validate_schema(value: str) -> None:
        if value != CHAT_STORE_SCHEMA_VERSION:
            raise ChatStoreSchemaError("stored chat row uses an unsupported schema")


__all__ = [
    "CHAT_STORE_SCHEMA_VERSION",
    "ChatCommandConflictError",
    "ChatExecutionResult",
    "ChatLogSnapshot",
    "ChatMessageConflictError",
    "ChatMessageNotFoundError",
    "ChatRevisionConflictError",
    "ChatStoreCorruptionError",
    "ChatStoreError",
    "ChatStoreSchemaError",
    "SQLiteChatLog",
]
