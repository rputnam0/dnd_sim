"""Restart-safe append-only SQLite authority for scene token presentation."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from .token_contracts import (
    TOKEN_VIEW_SCHEMA_VERSION,
    TokenCreateCommand,
    TokenCreatedEvent,
    TokenDeleteCommand,
    TokenDeletedEvent,
    TokenDuplicateCommand,
    TokenDuplicatedEvent,
    TokenMutationCommand,
    TokenMutationEvent,
    TokenMutationReceipt,
    TokenRecord,
    TokenUpdateCommand,
    TokenUpdatedEvent,
    TokenView,
    parse_token_command,
)

TOKEN_STORE_SCHEMA_VERSION = "vtt.token_store.v1"
_METADATA_TABLE = "_vtt_token_store_metadata"
_EVENTS_TABLE = "_vtt_token_event_log"


class TokenStoreError(RuntimeError):
    """Base failure for durable token operations."""


class TokenStoreSchemaError(TokenStoreError):
    pass


class TokenStoreCorruptionError(TokenStoreError):
    pass


class TokenCommandConflictError(TokenStoreError):
    pass


class TokenRevisionConflictError(TokenStoreError):
    def __init__(self, *, current_revision: int, expected_revision: int) -> None:
        super().__init__(f"expected revision {current_revision}, received {expected_revision}")
        self.current_revision = current_revision
        self.expected_revision = expected_revision


class TokenIdConflictError(TokenStoreError):
    pass


class TokenNotFoundError(TokenStoreError):
    pass


class TokenSceneMismatchError(TokenStoreError):
    pass


class TokenLockedError(TokenStoreError):
    pass


@dataclass(frozen=True, slots=True)
class TokenExecutionResult:
    receipt: TokenMutationReceipt
    replayed: bool


@dataclass(frozen=True, slots=True)
class _TokenTruth:
    revision: int
    tokens: dict[str, TokenRecord]
    reserved_token_ids: frozenset[str]


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
        raise TokenStoreCorruptionError(f"stored {field_name} is not valid JSON") from exc


def _canonical_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    return value


def _stored_positive_int(value: Any, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise TokenStoreCorruptionError(f"stored {field_name} is not a positive integer")
    return value


class SQLiteTokenStore:
    """One connection-owned token event log spanning isolated tables and scenes."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        if connection.in_transaction:
            raise TokenStoreError("cannot initialize token storage in an active transaction")
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
                    (TOKEN_STORE_SCHEMA_VERSION,),
                )
            elif str(row[0]) != TOKEN_STORE_SCHEMA_VERSION:
                raise TokenStoreSchemaError("unsupported token store schema")
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
                    CHECK (length(trim(command_id)) > 0)
                )
                """)
            self._connection.commit()
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def execute(self, command: TokenMutationCommand) -> TokenExecutionResult:
        if not isinstance(
            command,
            (
                TokenCreateCommand,
                TokenUpdateCommand,
                TokenDuplicateCommand,
                TokenDeleteCommand,
            ),
        ):
            raise TypeError("command must be a token mutation command")
        command = parse_token_command(command.model_dump(mode="json"))
        command_json = _canonical_json(command)
        if self._connection.in_transaction:
            raise TokenStoreError("execute cannot run inside an active transaction")

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
                sequence = _stored_positive_int(existing[1], field_name="sequence")
                revision = _stored_positive_int(existing[2], field_name="revision")
                stored_command = self._parse_stored_command(
                    str(existing[3]),
                    table_id=command.table_id,
                    command_id=command.command_id,
                    revision=revision,
                )
                if str(existing[3]) != command_json:
                    raise TokenCommandConflictError(
                        f"command_id '{command.command_id}' has different content"
                    )
                receipt = self._parse_stored_receipt(
                    str(existing[4]),
                    table_id=command.table_id,
                    command_id=command.command_id,
                    sequence=sequence,
                    revision=revision,
                )
                self._validate_command_receipt(stored_command, receipt)
                self._connection.commit()
                return TokenExecutionResult(receipt=receipt, replayed=True)

            truth = self._truth_locked(command.table_id)
            if command.expected_revision != truth.revision:
                raise TokenRevisionConflictError(
                    current_revision=truth.revision,
                    expected_revision=command.expected_revision,
                )
            revision = truth.revision + 1
            event = self._build_event(command, truth=truth, revision=revision)
            receipt = TokenMutationReceipt(
                table_id=command.table_id,
                command_id=command.command_id,
                revision=revision,
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
                    TOKEN_STORE_SCHEMA_VERSION,
                    command.table_id,
                    revision,
                    revision,
                    command.command_id,
                    command_json,
                    _canonical_json(receipt),
                ),
            )
            self._connection.commit()
            return TokenExecutionResult(receipt=receipt, replayed=False)
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def replay(self, command: TokenMutationCommand) -> TokenExecutionResult | None:
        """Return an exact prior result without re-evaluating current domain state."""

        if not isinstance(
            command,
            (
                TokenCreateCommand,
                TokenUpdateCommand,
                TokenDuplicateCommand,
                TokenDeleteCommand,
            ),
        ):
            raise TypeError("command must be a token mutation command")
        command = parse_token_command(command.model_dump(mode="json"))
        encoded = _canonical_json(command)
        row = self._connection.execute(
            f"""
            SELECT store_schema_version, sequence, revision, command_json, receipt_json
            FROM {_EVENTS_TABLE}
            WHERE table_id = ? AND command_id = ?
            """,
            (command.table_id, command.command_id),
        ).fetchone()
        if row is None:
            return None
        self._validate_store_schema(str(row[0]))
        sequence = _stored_positive_int(row[1], field_name="sequence")
        revision = _stored_positive_int(row[2], field_name="revision")
        stored = self._parse_stored_command(
            str(row[3]),
            table_id=command.table_id,
            command_id=command.command_id,
            revision=revision,
        )
        if str(row[3]) != encoded:
            raise TokenCommandConflictError(
                f"command_id '{command.command_id}' has different content"
            )
        receipt = self._parse_stored_receipt(
            str(row[4]),
            table_id=command.table_id,
            command_id=command.command_id,
            sequence=sequence,
            revision=revision,
        )
        self._validate_command_receipt(stored, receipt)
        return TokenExecutionResult(receipt=receipt, replayed=True)

    def _build_event(
        self,
        command: TokenMutationCommand,
        *,
        truth: _TokenTruth,
        revision: int,
    ) -> TokenMutationEvent:
        common = {
            "table_id": command.table_id,
            "event_id": f"{command.table_id}:token:{revision}",
            "sequence": revision,
            "revision": revision,
            "command_id": command.command_id,
        }
        if isinstance(command, TokenCreateCommand):
            if command.token.token_id in truth.reserved_token_ids:
                raise TokenIdConflictError(f"token_id '{command.token.token_id}' was already used")
            return TokenCreatedEvent(**common, token=command.token)
        if isinstance(command, TokenUpdateCommand):
            current = truth.tokens.get(command.token.token_id)
            if current is None:
                raise TokenNotFoundError(f"token_id '{command.token.token_id}' is missing")
            if command.token.scene_id != current.scene_id:
                raise TokenSceneMismatchError("token update cannot move a token between scenes")
            if current.locked and command.token.pose != current.pose:
                raise TokenLockedError("unlock the token before changing its pose")
            return TokenUpdatedEvent(**common, token=command.token)
        if isinstance(command, TokenDuplicateCommand):
            source = truth.tokens.get(command.source_token_id)
            if source is None:
                raise TokenNotFoundError(f"source token_id '{command.source_token_id}' is missing")
            if command.new_token_id in truth.reserved_token_ids:
                raise TokenIdConflictError(f"token_id '{command.new_token_id}' was already used")
            token = TokenRecord.model_validate(
                {
                    **source.model_dump(mode="json"),
                    "token_id": command.new_token_id,
                    "pose": command.pose.model_dump(mode="json"),
                }
            )
            return TokenDuplicatedEvent(
                **common,
                source_token_id=command.source_token_id,
                token=token,
            )
        current = truth.tokens.get(command.token_id)
        if current is None:
            raise TokenNotFoundError(f"token_id '{command.token_id}' is missing")
        if current.scene_id != command.scene_id:
            raise TokenSceneMismatchError("token does not belong to the requested scene")
        return TokenDeletedEvent(
            **common,
            scene_id=command.scene_id,
            token_id=command.token_id,
        )

    def snapshot(self, table_id: str, scene_id: str) -> TokenView:
        table = _canonical_text(table_id, field_name="table_id")
        scene = _canonical_text(scene_id, field_name="scene_id")
        truth = self._truth_locked(table)
        return TokenView(
            schema_version=TOKEN_VIEW_SCHEMA_VERSION,
            table_id=table,
            scene_id=scene,
            revision=truth.revision,
            tokens=tuple(
                truth.tokens[token_id]
                for token_id in sorted(truth.tokens)
                if truth.tokens[token_id].scene_id == scene
            ),
        )

    def revision(self, table_id: str) -> int:
        return self._truth_locked(_canonical_text(table_id, field_name="table_id")).revision

    def token(self, table_id: str, token_id: str) -> TokenRecord | None:
        table = _canonical_text(table_id, field_name="table_id")
        token = _canonical_text(token_id, field_name="token_id")
        return self._truth_locked(table).tokens.get(token)

    def events_after(self, table_id: str, sequence: int) -> tuple[TokenMutationEvent, ...]:
        table = _canonical_text(table_id, field_name="table_id")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        rows = self._connection.execute(
            f"""
            SELECT store_schema_version, sequence, revision, command_id,
                   command_json, receipt_json
            FROM {_EVENTS_TABLE}
            WHERE table_id = ? AND sequence > ?
            ORDER BY sequence ASC
            """,
            (table, sequence),
        ).fetchall()
        return self._parse_rows(table, rows)

    def _truth_locked(self, table_id: str) -> _TokenTruth:
        rows = self._connection.execute(
            f"""
            SELECT store_schema_version, sequence, revision, command_id,
                   command_json, receipt_json
            FROM {_EVENTS_TABLE}
            WHERE table_id = ?
            ORDER BY sequence ASC
            """,
            (table_id,),
        ).fetchall()
        events = self._parse_rows(table_id, rows)
        tokens: dict[str, TokenRecord] = {}
        reserved: set[str] = set()
        expected_revision = 1
        for event in events:
            if event.sequence != expected_revision or event.revision != expected_revision:
                raise TokenStoreCorruptionError("token history has a sequence or revision gap")
            if isinstance(event, TokenCreatedEvent):
                if event.token.token_id in reserved:
                    raise TokenStoreCorruptionError("token history reuses a token ID")
                tokens[event.token.token_id] = event.token
                reserved.add(event.token.token_id)
            elif isinstance(event, TokenUpdatedEvent):
                current = tokens.get(event.token.token_id)
                if current is None or current.scene_id != event.token.scene_id:
                    raise TokenStoreCorruptionError("token update targets invalid history")
                if current.locked and current.pose != event.token.pose:
                    raise TokenStoreCorruptionError("locked token history changes its pose")
                tokens[event.token.token_id] = event.token
            elif isinstance(event, TokenDuplicatedEvent):
                source = tokens.get(event.source_token_id)
                if source is None or event.token.token_id in reserved:
                    raise TokenStoreCorruptionError("token duplicate targets invalid history")
                expected = source.model_copy(
                    update={"token_id": event.token.token_id, "pose": event.token.pose}
                )
                if event.token != expected:
                    raise TokenStoreCorruptionError("token duplicate does not match its source")
                tokens[event.token.token_id] = event.token
                reserved.add(event.token.token_id)
            else:
                current = tokens.get(event.token_id)
                if current is None or current.scene_id != event.scene_id:
                    raise TokenStoreCorruptionError("token delete targets invalid history")
                del tokens[event.token_id]
            expected_revision += 1
        return _TokenTruth(
            revision=expected_revision - 1,
            tokens=tokens,
            reserved_token_ids=frozenset(reserved),
        )

    def _parse_rows(
        self,
        table_id: str,
        rows: list[tuple[Any, ...]],
    ) -> tuple[TokenMutationEvent, ...]:
        events: list[TokenMutationEvent] = []
        for row in rows:
            self._validate_store_schema(str(row[0]))
            sequence = _stored_positive_int(row[1], field_name="sequence")
            revision = _stored_positive_int(row[2], field_name="revision")
            command = self._parse_stored_command(
                str(row[4]),
                table_id=table_id,
                command_id=str(row[3]),
                revision=revision,
            )
            receipt = self._parse_stored_receipt(
                str(row[5]),
                table_id=table_id,
                command_id=str(row[3]),
                sequence=sequence,
                revision=revision,
            )
            self._validate_command_receipt(command, receipt)
            events.append(receipt.event)
        return tuple(events)

    @staticmethod
    def _parse_stored_command(
        encoded: str,
        *,
        table_id: str,
        command_id: str,
        revision: int,
    ) -> TokenMutationCommand:
        try:
            command = parse_token_command(_decode_json(encoded, field_name="command"))
        except ValidationError as exc:
            raise TokenStoreCorruptionError("stored token command violates its contract") from exc
        if (
            command.table_id != table_id
            or command.command_id != command_id
            or command.expected_revision != revision - 1
            or _canonical_json(command) != encoded
        ):
            raise TokenStoreCorruptionError("stored token command identity is inconsistent")
        return command

    @staticmethod
    def _parse_stored_receipt(
        encoded: str,
        *,
        table_id: str,
        command_id: str,
        sequence: int,
        revision: int,
    ) -> TokenMutationReceipt:
        try:
            receipt = TokenMutationReceipt.model_validate(
                _decode_json(encoded, field_name="receipt")
            )
        except ValidationError as exc:
            raise TokenStoreCorruptionError("stored token receipt violates its contract") from exc
        if (
            receipt.table_id != table_id
            or receipt.command_id != command_id
            or receipt.revision != revision
            or receipt.event.sequence != sequence
            or _canonical_json(receipt) != encoded
        ):
            raise TokenStoreCorruptionError("stored token receipt identity is inconsistent")
        return receipt

    @staticmethod
    def _validate_command_receipt(
        command: TokenMutationCommand,
        receipt: TokenMutationReceipt,
    ) -> None:
        event = receipt.event
        valid = (
            (
                isinstance(command, TokenCreateCommand)
                and isinstance(event, TokenCreatedEvent)
                and event.token == command.token
            )
            or (
                isinstance(command, TokenUpdateCommand)
                and isinstance(event, TokenUpdatedEvent)
                and event.token == command.token
            )
            or (
                isinstance(command, TokenDuplicateCommand)
                and isinstance(event, TokenDuplicatedEvent)
                and event.source_token_id == command.source_token_id
                and event.token.token_id == command.new_token_id
                and event.token.pose == command.pose
            )
            or (
                isinstance(command, TokenDeleteCommand)
                and isinstance(event, TokenDeletedEvent)
                and event.scene_id == command.scene_id
                and event.token_id == command.token_id
            )
        )
        if not valid:
            raise TokenStoreCorruptionError("stored token command and receipt disagree")

    def _validate_store_schema(self, value: str) -> None:
        if value != TOKEN_STORE_SCHEMA_VERSION:
            raise TokenStoreSchemaError("unsupported token store schema")
