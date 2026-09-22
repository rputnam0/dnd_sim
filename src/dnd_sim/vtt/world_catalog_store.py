"""Tamper-evident append-only SQLite storage for standalone VTT worlds."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from .world_catalog_contracts import (
    MAX_ACTIVE_WORLDS,
    MAX_WORLD_RECORDS,
    WORLD_CATALOG_VIEW_SCHEMA_VERSION,
    WorldArchiveCommand,
    WorldArchivedEvent,
    WorldCatalogEntry,
    WorldCatalogView,
    WorldCreateCommand,
    WorldCreatedEvent,
    WorldMutationCommand,
    WorldMutationEvent,
    WorldMutationReceipt,
    WorldRecord,
    WorldRenameCommand,
    WorldRenamedEvent,
    parse_world_command,
    world_name_key,
)

WORLD_CATALOG_STORE_SCHEMA_VERSION = "vtt.world_catalog_store.v1"
logger = logging.getLogger(__name__)
_METADATA_TABLE = "_vtt_world_catalog_metadata"
_HEAD_TABLE = "_vtt_world_catalog_head"
_EVENTS_TABLE = "_vtt_world_catalog_events"
_EMPTY_HEAD_HASH = "0" * 64


class WorldCatalogStoreError(RuntimeError):
    """Base failure for durable world catalog operations."""


class WorldCatalogStoreSchemaError(WorldCatalogStoreError):
    pass


class WorldCatalogCorruptionError(WorldCatalogStoreError):
    pass


class WorldCommandConflictError(WorldCatalogStoreError):
    pass


class WorldRevisionConflictError(WorldCatalogStoreError):
    def __init__(self, *, current_revision: int, expected_revision: int) -> None:
        super().__init__(f"expected revision {current_revision}, received {expected_revision}")
        self.current_revision = current_revision
        self.expected_revision = expected_revision


class WorldIdConflictError(WorldCatalogStoreError):
    pass


class WorldNameConflictError(WorldCatalogStoreError):
    pass


class WorldTableConflictError(WorldCatalogStoreError):
    pass


class WorldNotFoundError(WorldCatalogStoreError):
    pass


class WorldArchivedError(WorldCatalogStoreError):
    pass


class WorldNameUnchangedError(WorldCatalogStoreError):
    pass


class WorldLimitError(WorldCatalogStoreError):
    pass


@dataclass(frozen=True, slots=True)
class WorldExecutionResult:
    receipt: WorldMutationReceipt
    replayed: bool


@dataclass(frozen=True, slots=True)
class _StoredHistoryEntry:
    command: WorldMutationCommand
    receipt: WorldMutationReceipt
    entry_hash: str


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
        raise WorldCatalogCorruptionError(f"stored {field_name} is not valid JSON") from exc


def _stored_non_negative_int(value: Any, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise WorldCatalogCorruptionError(f"stored {field_name} is not a non-negative integer")
    return value


def _stored_positive_int(value: Any, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise WorldCatalogCorruptionError(f"stored {field_name} is not a positive integer")
    return value


def _stored_hash(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise WorldCatalogCorruptionError(f"stored {field_name} is not a lowercase SHA-256 digest")
    return value


def _entry_hash(
    *,
    revision: int,
    command_json: str,
    receipt_json: str,
    previous_hash: str,
) -> str:
    payload = json.dumps(
        {
            "command_json": command_json,
            "previous_hash": previous_hash,
            "receipt_json": receipt_json,
            "revision": revision,
            "store_schema_version": WORLD_CATALOG_STORE_SCHEMA_VERSION,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _active_name_owner(
    view: WorldCatalogView,
    name: str,
    *,
    excluding_world_id: str | None = None,
) -> str | None:
    key = world_name_key(name)
    return next(
        (
            entry.world.world_id
            for entry in view.active_worlds
            if entry.world.world_id != excluding_world_id
            and world_name_key(entry.world.name) == key
        ),
        None,
    )


def _table_owner(view: WorldCatalogView, table_id: str) -> str | None:
    return next(
        (entry.world.world_id for entry in view.worlds if entry.world.table_id == table_id),
        None,
    )


class WorldCatalogTransaction:
    """One caller-composable catalog transaction with explicit lifetime.

    The underlying connection is deliberately not exposed: callers cannot commit,
    roll back, or issue SQL that bypasses catalog validation.
    """

    def __init__(self, store: "SQLiteWorldCatalog") -> None:
        self._store = store
        self._active = True

    def _require_active(self) -> None:
        if not self._active:
            raise WorldCatalogStoreError("world catalog transaction is closed")
        if not self._store._connection.in_transaction:
            raise WorldCatalogStoreError("world catalog transaction was finalized externally")

    def execute(self, command: WorldMutationCommand) -> WorldExecutionResult:
        self._require_active()
        return self._store._execute_locked(command)

    def snapshot(self) -> WorldCatalogView:
        self._require_active()
        return self._store._read_history_locked()[0]

    def receipts_after(self, sequence: int) -> tuple[WorldMutationReceipt, ...]:
        self._require_active()
        return self._store._receipts_after_locked(sequence)

    def _close(self) -> None:
        self._active = False


class SQLiteWorldCatalog:
    """A single-installation world catalog backed by an append-only event log."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        if connection.in_transaction:
            raise WorldCatalogStoreError(
                "cannot initialize world catalog inside an active transaction"
            )
        self._connection = connection
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            table_names = {_METADATA_TABLE, _HEAD_TABLE, _EVENTS_TABLE}
            existing_tables = {
                str(row[0])
                for row in self._connection.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table' AND name IN (?, ?, ?)
                    """,
                    tuple(sorted(table_names)),
                ).fetchall()
            }
            if existing_tables and existing_tables != table_names:
                raise WorldCatalogStoreSchemaError("world catalog store schema is incomplete")
            fresh_store = not existing_tables
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
                if not fresh_store:
                    raise WorldCatalogCorruptionError("world catalog metadata row is missing")
                self._connection.execute(
                    f"INSERT INTO {_METADATA_TABLE} (singleton, schema_version) VALUES (1, ?)",
                    (WORLD_CATALOG_STORE_SCHEMA_VERSION,),
                )
            elif metadata[0] != WORLD_CATALOG_STORE_SCHEMA_VERSION:
                raise WorldCatalogStoreSchemaError("unsupported world catalog store schema")

            self._connection.execute(f"""
                CREATE TABLE IF NOT EXISTS {_HEAD_TABLE} (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    revision INTEGER NOT NULL CHECK (revision >= 0),
                    head_hash TEXT NOT NULL CHECK (length(head_hash) = 64)
                )
                """)
            head = self._connection.execute(
                f"SELECT revision, head_hash FROM {_HEAD_TABLE} WHERE singleton = 1"
            ).fetchone()
            if head is None:
                if not fresh_store:
                    raise WorldCatalogCorruptionError("world catalog head is missing")
                self._connection.execute(
                    f"INSERT INTO {_HEAD_TABLE} (singleton, revision, head_hash) VALUES (1, 0, ?)",
                    (_EMPTY_HEAD_HASH,),
                )

            self._connection.execute(f"""
                CREATE TABLE IF NOT EXISTS {_EVENTS_TABLE} (
                    store_schema_version TEXT NOT NULL,
                    revision INTEGER PRIMARY KEY CHECK (revision >= 1),
                    command_id TEXT NOT NULL UNIQUE,
                    command_json TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL CHECK (length(previous_hash) = 64),
                    entry_hash TEXT NOT NULL CHECK (length(entry_hash) = 64),
                    CHECK (length(trim(command_id)) > 0),
                    CHECK (length(trim(command_json)) > 0),
                    CHECK (length(trim(receipt_json)) > 0)
                )
                """)
            self._read_history_locked()
            self._connection.commit()
        except BaseException:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    @contextmanager
    def transaction(self) -> Iterator[WorldCatalogTransaction]:
        """Open one atomic write boundary for one or more catalog operations."""

        if self._connection.in_transaction:
            raise WorldCatalogStoreError(
                "cannot start world catalog transaction inside an active transaction"
            )
        transaction = WorldCatalogTransaction(self)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield transaction
            if not self._connection.in_transaction:
                raise WorldCatalogStoreError("world catalog transaction was finalized externally")
            self._read_history_locked()
            self._connection.commit()
        except BaseException:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise
        finally:
            transaction._close()

    def execute(self, command: WorldMutationCommand) -> WorldExecutionResult:
        with self.transaction() as transaction:
            return transaction.execute(command)

    def snapshot(self) -> WorldCatalogView:
        return self._read_public()[0]

    def revision(self) -> int:
        return self.snapshot().revision

    def receipts_after(self, sequence: int) -> tuple[WorldMutationReceipt, ...]:
        self._validate_sequence(sequence)
        view, history = self._read_public()
        del view
        return tuple(entry.receipt for entry in history if entry.receipt.revision > sequence)

    def events_after(self, sequence: int) -> tuple[WorldMutationEvent, ...]:
        return tuple(receipt.event for receipt in self.receipts_after(sequence))

    def _read_public(self) -> tuple[WorldCatalogView, tuple[_StoredHistoryEntry, ...]]:
        if self._connection.in_transaction:
            raise WorldCatalogStoreError("cannot read world catalog inside an active transaction")
        try:
            self._connection.execute("BEGIN")
            result = self._read_history_locked()
            self._connection.commit()
            return result
        except BaseException:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def _execute_locked(self, command: WorldMutationCommand) -> WorldExecutionResult:
        if not isinstance(
            command,
            (WorldCreateCommand, WorldRenameCommand, WorldArchiveCommand),
        ):
            raise TypeError("command must be a world catalog mutation command")
        command = parse_world_command(command.model_dump(mode="json"))
        command_json = _canonical_json(command)

        snapshot, history = self._read_history_locked()
        existing = next(
            (entry for entry in history if entry.command.command_id == command.command_id),
            None,
        )
        if existing is not None:
            if existing.command != command:
                raise WorldCommandConflictError(
                    f"command_id '{command.command_id}' has different content"
                )
            return WorldExecutionResult(receipt=existing.receipt, replayed=True)

        if command.expected_revision != snapshot.revision:
            raise WorldRevisionConflictError(
                current_revision=snapshot.revision,
                expected_revision=command.expected_revision,
            )
        revision = snapshot.revision + 1
        event = self._build_event(command, snapshot=snapshot, revision=revision)
        receipt = WorldMutationReceipt(
            command_id=command.command_id,
            revision=revision,
            event=event,
        )
        receipt_json = _canonical_json(receipt)
        previous_hash = history[-1].entry_hash if history else _EMPTY_HEAD_HASH
        entry_hash = _entry_hash(
            revision=revision,
            command_json=command_json,
            receipt_json=receipt_json,
            previous_hash=previous_hash,
        )
        self._connection.execute(
            f"""
            INSERT INTO {_EVENTS_TABLE} (
                store_schema_version, revision, command_id, command_json,
                receipt_json, previous_hash, entry_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                WORLD_CATALOG_STORE_SCHEMA_VERSION,
                revision,
                command.command_id,
                command_json,
                receipt_json,
                previous_hash,
                entry_hash,
            ),
        )
        updated = self._connection.execute(
            f"""
            UPDATE {_HEAD_TABLE}
            SET revision = ?, head_hash = ?
            WHERE singleton = 1 AND revision = ? AND head_hash = ?
            """,
            (revision, entry_hash, snapshot.revision, previous_hash),
        )
        if updated.rowcount != 1:
            raise WorldCatalogCorruptionError("world catalog head changed unexpectedly")
        return WorldExecutionResult(receipt=receipt, replayed=False)

    def _build_event(
        self,
        command: WorldMutationCommand,
        *,
        snapshot: WorldCatalogView,
        revision: int,
    ) -> WorldMutationEvent:
        common = {
            "event_id": f"world-{revision}",
            "sequence": revision,
            "revision": revision,
            "command_id": command.command_id,
        }
        if isinstance(command, WorldCreateCommand):
            if snapshot.world(command.world.world_id) is not None:
                raise WorldIdConflictError(f"world_id '{command.world.world_id}' was already used")
            if len(snapshot.worlds) >= MAX_WORLD_RECORDS:
                raise WorldLimitError("world catalog reached its total world limit")
            if len(snapshot.active_worlds) >= MAX_ACTIVE_WORLDS:
                raise WorldLimitError("world catalog reached its active world limit")
            owner = _active_name_owner(snapshot, command.world.name)
            if owner is not None:
                raise WorldNameConflictError(f"active world name is already used by '{owner}'")
            owner = _table_owner(snapshot, command.world.table_id)
            if owner is not None:
                raise WorldTableConflictError(
                    f"table_id '{command.world.table_id}' is already linked to '{owner}'"
                )
            return WorldCreatedEvent(**common, world=command.world)

        target = snapshot.world(command.world_id)
        if target is None:
            raise WorldNotFoundError(f"world_id '{command.world_id}' is missing")
        if target.archived:
            raise WorldArchivedError(f"world_id '{command.world_id}' is archived")
        if isinstance(command, WorldRenameCommand):
            if command.name == target.world.name:
                raise WorldNameUnchangedError(
                    f"world_id '{command.world_id}' already has that name"
                )
            owner = _active_name_owner(
                snapshot,
                command.name,
                excluding_world_id=command.world_id,
            )
            if owner is not None:
                raise WorldNameConflictError(f"active world name is already used by '{owner}'")
            return WorldRenamedEvent(
                **common,
                world_id=command.world_id,
                old_name=target.world.name,
                new_name=command.name,
            )
        return WorldArchivedEvent(**common, world_id=command.world_id)

    def _read_history_locked(
        self,
    ) -> tuple[WorldCatalogView, tuple[_StoredHistoryEntry, ...]]:
        metadata_row = self._connection.execute(
            f"SELECT schema_version FROM {_METADATA_TABLE} WHERE singleton = 1"
        ).fetchone()
        if metadata_row is None:
            raise WorldCatalogCorruptionError("world catalog metadata row is missing")
        if metadata_row[0] != WORLD_CATALOG_STORE_SCHEMA_VERSION:
            raise WorldCatalogStoreSchemaError("unsupported world catalog store schema")
        head_row = self._connection.execute(
            f"SELECT revision, head_hash FROM {_HEAD_TABLE} WHERE singleton = 1"
        ).fetchone()
        if head_row is None:
            raise WorldCatalogCorruptionError("world catalog head is missing")
        head_revision = _stored_non_negative_int(head_row[0], field_name="head revision")
        head_hash = _stored_hash(head_row[1], field_name="head hash")

        rows = self._connection.execute(f"""
            SELECT store_schema_version, revision, command_id, command_json,
                   receipt_json, previous_hash, entry_hash
            FROM {_EVENTS_TABLE}
            ORDER BY revision ASC
            """).fetchall()
        entries: dict[str, WorldCatalogEntry] = {}
        history: list[_StoredHistoryEntry] = []
        expected_revision = 1
        previous_hash = _EMPTY_HEAD_HASH
        for row in rows:
            self._validate_store_schema(row[0])
            revision = _stored_positive_int(row[1], field_name="revision")
            if revision != expected_revision:
                raise WorldCatalogCorruptionError("world catalog history has a revision gap")
            command_id = row[2]
            command_json = row[3]
            receipt_json = row[4]
            if not all(
                isinstance(value, str) for value in (command_id, command_json, receipt_json)
            ):
                raise WorldCatalogCorruptionError("world catalog row contains non-text JSON")
            stored_previous_hash = _stored_hash(row[5], field_name="previous hash")
            stored_entry_hash = _stored_hash(row[6], field_name="entry hash")
            if stored_previous_hash != previous_hash:
                raise WorldCatalogCorruptionError("world catalog hash chain is broken")
            calculated_hash = _entry_hash(
                revision=revision,
                command_json=command_json,
                receipt_json=receipt_json,
                previous_hash=stored_previous_hash,
            )
            if stored_entry_hash != calculated_hash:
                raise WorldCatalogCorruptionError("world catalog entry hash is inconsistent")

            command = self._parse_stored_command(
                command_json,
                command_id=command_id,
                revision=revision,
            )
            receipt = self._parse_stored_receipt(
                receipt_json,
                command_id=command_id,
                revision=revision,
            )
            self._validate_command_receipt(command, receipt)
            self._apply_event(entries, receipt.event)
            history.append(
                _StoredHistoryEntry(
                    command=command,
                    receipt=receipt,
                    entry_hash=stored_entry_hash,
                )
            )
            previous_hash = stored_entry_hash
            expected_revision += 1

        revision = expected_revision - 1
        if head_revision != revision or head_hash != previous_hash:
            raise WorldCatalogCorruptionError(
                "world catalog head does not match its append-only history"
            )
        try:
            view = WorldCatalogView(
                schema_version=WORLD_CATALOG_VIEW_SCHEMA_VERSION,
                revision=revision,
                worlds=tuple(entries[key] for key in sorted(entries)),
            )
        except ValidationError as exc:
            raise WorldCatalogCorruptionError(
                "world catalog history produces an invalid projection"
            ) from exc
        return view, tuple(history)

    @staticmethod
    def _apply_event(
        entries: dict[str, WorldCatalogEntry],
        event: WorldMutationEvent,
    ) -> None:
        if isinstance(event, WorldCreatedEvent):
            world = event.world
            if world.world_id in entries:
                raise WorldCatalogCorruptionError("world history reuses a world ID")
            if len(entries) >= MAX_WORLD_RECORDS:
                raise WorldCatalogCorruptionError("world history exceeds the total world limit")
            active = tuple(entry for entry in entries.values() if not entry.archived)
            if len(active) >= MAX_ACTIVE_WORLDS:
                raise WorldCatalogCorruptionError("world history exceeds the active world limit")
            if any(
                world_name_key(entry.world.name) == world_name_key(world.name) for entry in active
            ):
                raise WorldCatalogCorruptionError("world history reuses an active world name")
            if any(entry.world.table_id == world.table_id for entry in entries.values()):
                raise WorldCatalogCorruptionError("world history reuses a table link")
            entries[world.world_id] = WorldCatalogEntry(world=world, archived=False)
            return

        target = entries.get(event.world_id)
        if target is None or target.archived:
            raise WorldCatalogCorruptionError("world history mutates a missing or archived world")
        if isinstance(event, WorldRenamedEvent):
            if target.world.name != event.old_name:
                raise WorldCatalogCorruptionError("world rename does not match the prior name")
            if any(
                entry.world.world_id != event.world_id
                and not entry.archived
                and world_name_key(entry.world.name) == world_name_key(event.new_name)
                for entry in entries.values()
            ):
                raise WorldCatalogCorruptionError("world rename reuses an active world name")
            try:
                renamed = WorldRecord.model_validate(
                    {**target.world.model_dump(mode="json"), "name": event.new_name}
                )
            except ValidationError as exc:
                raise WorldCatalogCorruptionError(
                    "world rename produces an invalid record"
                ) from exc
            entries[event.world_id] = WorldCatalogEntry(world=renamed, archived=False)
            return
        entries[event.world_id] = WorldCatalogEntry(world=target.world, archived=True)

    @staticmethod
    def _parse_stored_command(
        encoded: str,
        *,
        command_id: str,
        revision: int,
    ) -> WorldMutationCommand:
        try:
            command = parse_world_command(_decode_json(encoded, field_name="command"))
        except ValidationError as exc:
            raise WorldCatalogCorruptionError("stored world command violates its contract") from exc
        if (
            command.command_id != command_id
            or command.expected_revision != revision - 1
            or _canonical_json(command) != encoded
        ):
            raise WorldCatalogCorruptionError("stored world command identity is inconsistent")
        return command

    @staticmethod
    def _parse_stored_receipt(
        encoded: str,
        *,
        command_id: str,
        revision: int,
    ) -> WorldMutationReceipt:
        try:
            receipt = WorldMutationReceipt.model_validate(
                _decode_json(encoded, field_name="receipt")
            )
        except ValidationError as exc:
            raise WorldCatalogCorruptionError("stored world receipt violates its contract") from exc
        if (
            receipt.command_id != command_id
            or receipt.revision != revision
            or receipt.event.sequence != revision
            or receipt.event.event_id != f"world-{revision}"
            or _canonical_json(receipt) != encoded
        ):
            raise WorldCatalogCorruptionError("stored world receipt identity is inconsistent")
        return receipt

    @staticmethod
    def _validate_command_receipt(
        command: WorldMutationCommand,
        receipt: WorldMutationReceipt,
    ) -> None:
        event = receipt.event
        valid = False
        if isinstance(command, WorldCreateCommand):
            valid = isinstance(event, WorldCreatedEvent) and event.world == command.world
        elif isinstance(command, WorldRenameCommand):
            valid = (
                isinstance(event, WorldRenamedEvent)
                and event.world_id == command.world_id
                and event.new_name == command.name
            )
        elif isinstance(command, WorldArchiveCommand):
            valid = isinstance(event, WorldArchivedEvent) and event.world_id == command.world_id
        if not valid:
            raise WorldCatalogCorruptionError("stored world command and receipt are inconsistent")

    def _receipts_after_locked(self, sequence: int) -> tuple[WorldMutationReceipt, ...]:
        self._validate_sequence(sequence)
        _, history = self._read_history_locked()
        return tuple(entry.receipt for entry in history if entry.receipt.revision > sequence)

    @staticmethod
    def _validate_sequence(sequence: int) -> None:
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")

    @staticmethod
    def _validate_store_schema(value: Any) -> None:
        if value != WORLD_CATALOG_STORE_SCHEMA_VERSION:
            raise WorldCatalogStoreSchemaError("stored world row uses an unsupported schema")


__all__ = [
    "WORLD_CATALOG_STORE_SCHEMA_VERSION",
    "SQLiteWorldCatalog",
    "WorldArchivedError",
    "WorldCatalogCorruptionError",
    "WorldCatalogStoreError",
    "WorldCatalogStoreSchemaError",
    "WorldCatalogTransaction",
    "WorldCommandConflictError",
    "WorldExecutionResult",
    "WorldIdConflictError",
    "WorldLimitError",
    "WorldNameConflictError",
    "WorldNameUnchangedError",
    "WorldNotFoundError",
    "WorldRevisionConflictError",
    "WorldTableConflictError",
]
