"""Restart-safe append-only SQLite storage for the VTT journal."""

from __future__ import annotations

import json
import logging
import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from .journal_contracts import (
    MAX_JOURNAL_DOCUMENTS,
    MAX_JOURNAL_FOLDER_DEPTH,
    MAX_JOURNAL_FOLDERS,
    MAX_JOURNAL_SEARCH_RESULTS,
    JournalDeleteDocumentCommand,
    JournalDeleteFolderCommand,
    JournalDocument,
    JournalDocumentDeletedEvent,
    JournalDocumentLinkBlock,
    JournalDocumentPutEvent,
    JournalFolder,
    JournalFolderDeletedEvent,
    JournalFolderPutEvent,
    JournalMutationCommand,
    JournalMutationEvent,
    JournalMutationReceipt,
    JournalPutDocumentCommand,
    JournalPutFolderCommand,
    journal_document_sort_key,
    journal_folder_sort_key,
    parse_journal_command,
    parse_journal_event,
)

JOURNAL_STORE_SCHEMA_VERSION = "vtt.journal_store.v1"
_METADATA_TABLE = "_vtt_journal_store_metadata"
_EVENTS_TABLE = "_vtt_journal_event_log"

logger = logging.getLogger(__name__)


class JournalStoreError(RuntimeError):
    pass


class JournalStoreSchemaError(JournalStoreError):
    pass


class JournalStoreCorruptionError(JournalStoreError):
    pass


class JournalCommandConflictError(JournalStoreError):
    pass


class JournalRevisionConflictError(JournalStoreError):
    pass


class JournalRecordNotFoundError(JournalStoreError):
    pass


class JournalCapacityError(JournalStoreError):
    pass


class JournalFolderReferenceError(JournalStoreError):
    pass


class JournalFolderCycleError(JournalStoreError):
    pass


class JournalFolderNotEmptyError(JournalStoreError):
    pass


class JournalDocumentLinkError(JournalStoreError):
    pass


class JournalLinkedDocumentError(JournalStoreError):
    pass


@dataclass(frozen=True, slots=True)
class JournalSnapshot:
    revision: int
    folders: tuple[JournalFolder, ...]
    documents: tuple[JournalDocument, ...]
    events: tuple[JournalMutationEvent, ...]


@dataclass(frozen=True, slots=True)
class JournalExecutionResult:
    receipt: JournalMutationReceipt
    replayed: bool


def _canonical_json(model: BaseModel) -> str:
    return json.dumps(
        model.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _document_links(document: JournalDocument) -> frozenset[str]:
    return frozenset(
        block.document_id
        for block in document.blocks
        if isinstance(block, JournalDocumentLinkBlock)
    )


def _command_matches_event(
    command: JournalMutationCommand,
    event: JournalMutationEvent,
) -> bool:
    if isinstance(command, JournalPutFolderCommand):
        return isinstance(event, JournalFolderPutEvent) and event.folder == command.folder
    if isinstance(command, JournalDeleteFolderCommand):
        return (
            isinstance(event, JournalFolderDeletedEvent)
            and event.folder.folder_id == command.folder_id
        )
    if isinstance(command, JournalPutDocumentCommand):
        return isinstance(event, JournalDocumentPutEvent) and event.document == command.document
    return (
        isinstance(event, JournalDocumentDeletedEvent)
        and event.document.document_id == command.document_id
    )


def _search_text(document: JournalDocument) -> str:
    values = [document.title, *document.tags]
    for block in document.blocks:
        if hasattr(block, "text"):
            values.append(block.text)
        elif hasattr(block, "items"):
            values.extend(block.items)
        elif isinstance(block, JournalDocumentLinkBlock):
            values.append(block.label)
    return unicodedata.normalize("NFKC", " ".join(values)).casefold()


class SQLiteJournalStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        if connection.in_transaction:
            raise JournalStoreError("cannot initialize journal storage inside a transaction")
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
                    (JOURNAL_STORE_SCHEMA_VERSION,),
                )
            elif str(row[0]) != JOURNAL_STORE_SCHEMA_VERSION:
                raise JournalStoreSchemaError("unsupported journal-store schema")
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

    def execute(self, command: JournalMutationCommand) -> JournalExecutionResult:
        command = parse_journal_command(command.model_dump(mode="json"))
        command_json = _canonical_json(command)
        if self._connection.in_transaction:
            raise JournalStoreError("execute cannot run inside an active transaction")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            existing = self._connection.execute(
                f"SELECT store_schema_version, table_id, sequence, revision, command_id, "
                f"command_json, receipt_json FROM {_EVENTS_TABLE} "
                "WHERE table_id = ? AND command_id = ?",
                (command.table_id, command.command_id),
            ).fetchone()
            if existing is not None:
                self._parse_event_row(command.table_id, existing)
                if str(existing[5]) != command_json:
                    raise JournalCommandConflictError("command ID has different content")
                receipt = self._parse_receipt(str(existing[6]))
                self._connection.commit()
                return JournalExecutionResult(receipt=receipt, replayed=True)

            snapshot = self._snapshot_locked(command.table_id)
            if command.expected_revision != snapshot.revision:
                raise JournalRevisionConflictError("journal revision is stale")
            folders = {folder.folder_id: folder for folder in snapshot.folders}
            documents = {document.document_id: document for document in snapshot.documents}
            revision = snapshot.revision + 1
            event_base = {
                "table_id": command.table_id,
                "event_id": f"{command.table_id}:journal:{revision}",
                "sequence": revision,
                "revision": revision,
                "command_id": command.command_id,
            }
            event: JournalMutationEvent
            if isinstance(command, JournalPutFolderCommand):
                if command.folder.folder_id not in folders and len(folders) >= MAX_JOURNAL_FOLDERS:
                    raise JournalCapacityError("journal folder capacity reached")
                folders[command.folder.folder_id] = command.folder
                self._validate_folder_graph(folders)
                event = JournalFolderPutEvent(**event_base, folder=command.folder)
            elif isinstance(command, JournalDeleteFolderCommand):
                folder = folders.get(command.folder_id)
                if folder is None:
                    raise JournalRecordNotFoundError("folder is missing")
                if any(
                    item.parent_folder_id == folder.folder_id for item in folders.values()
                ) or any(item.folder_id == folder.folder_id for item in documents.values()):
                    raise JournalFolderNotEmptyError("folder is not empty")
                del folders[folder.folder_id]
                event = JournalFolderDeletedEvent(**event_base, folder=folder)
            elif isinstance(command, JournalPutDocumentCommand):
                if (
                    command.document.document_id not in documents
                    and len(documents) >= MAX_JOURNAL_DOCUMENTS
                ):
                    raise JournalCapacityError("journal document capacity reached")
                next_documents = {**documents, command.document.document_id: command.document}
                self._validate_documents(next_documents, folders)
                event = JournalDocumentPutEvent(**event_base, document=command.document)
            else:
                document = documents.get(command.document_id)
                if document is None:
                    raise JournalRecordNotFoundError("document is missing")
                if any(
                    document.document_id in _document_links(candidate)
                    for candidate in documents.values()
                    if candidate.document_id != document.document_id
                ):
                    raise JournalLinkedDocumentError("document is linked by another record")
                event = JournalDocumentDeletedEvent(**event_base, document=document)

            receipt = JournalMutationReceipt(
                table_id=command.table_id,
                command_id=command.command_id,
                revision=revision,
                event=event,
            )
            self._connection.execute(
                f"INSERT INTO {_EVENTS_TABLE} "
                "(store_schema_version, table_id, sequence, revision, command_id, command_json, receipt_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    JOURNAL_STORE_SCHEMA_VERSION,
                    command.table_id,
                    revision,
                    revision,
                    command.command_id,
                    command_json,
                    _canonical_json(receipt),
                ),
            )
            self._connection.commit()
            return JournalExecutionResult(receipt=receipt, replayed=False)
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def replay(self, command: JournalMutationCommand) -> JournalExecutionResult | None:
        """Return an exact durable replay without re-evaluating mutable policy."""

        command = parse_journal_command(command.model_dump(mode="json"))
        command_json = _canonical_json(command)
        if self._connection.in_transaction:
            raise JournalStoreError("replay cannot run inside an active transaction")
        row = self._connection.execute(
            f"SELECT store_schema_version, table_id, sequence, revision, command_id, "
            f"command_json, receipt_json FROM {_EVENTS_TABLE} "
            "WHERE table_id = ? AND command_id = ?",
            (command.table_id, command.command_id),
        ).fetchone()
        if row is None:
            return None
        self._parse_event_row(command.table_id, row)
        if str(row[5]) != command_json:
            raise JournalCommandConflictError("command ID has different content")
        return JournalExecutionResult(
            receipt=self._parse_receipt(str(row[6])),
            replayed=True,
        )

    def snapshot(self, table_id: str) -> JournalSnapshot:
        return self._snapshot_locked(table_id)

    def revision(self, table_id: str) -> int:
        return self.snapshot(table_id).revision

    def events_after(self, table_id: str, sequence: int) -> tuple[JournalMutationEvent, ...]:
        if type(sequence) is not int or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        rows = self._connection.execute(
            f"SELECT store_schema_version, table_id, sequence, revision, command_id, "
            f"command_json, receipt_json FROM {_EVENTS_TABLE} "
            "WHERE table_id = ? ORDER BY sequence ASC",
            (table_id,),
        ).fetchall()
        events = tuple(self._parse_event_row(table_id, row) for row in rows)
        folders: dict[str, JournalFolder] = {}
        documents: dict[str, JournalDocument] = {}
        for expected, event in enumerate(events, 1):
            if event.sequence != expected or event.revision != expected:
                raise JournalStoreCorruptionError("journal history has a gap")
            if isinstance(event, JournalFolderPutEvent):
                folders[event.folder.folder_id] = event.folder
            elif isinstance(event, JournalFolderDeletedEvent):
                if folders.pop(event.folder.folder_id, None) != event.folder:
                    raise JournalStoreCorruptionError("folder tombstone is inconsistent")
            elif isinstance(event, JournalDocumentPutEvent):
                documents[event.document.document_id] = event.document
            elif documents.pop(event.document.document_id, None) != event.document:
                raise JournalStoreCorruptionError("document tombstone is inconsistent")
        return tuple(event for event in events if event.sequence > sequence)

    def search(self, table_id: str, query: str) -> tuple[JournalDocument, ...]:
        if not isinstance(query, str) or not query or query != query.strip() or len(query) > 160:
            raise ValueError("query must be canonical text of 1-160 characters")
        tokens = unicodedata.normalize("NFKC", query).casefold().split()
        return tuple(
            document
            for document in self.snapshot(table_id).documents
            if all(token in _search_text(document) for token in tokens)
        )[:MAX_JOURNAL_SEARCH_RESULTS]

    def _snapshot_locked(self, table_id: str) -> JournalSnapshot:
        events = self.events_after(table_id, 0)
        folders: dict[str, JournalFolder] = {}
        documents: dict[str, JournalDocument] = {}
        for event in events:
            if isinstance(event, JournalFolderPutEvent):
                folders[event.folder.folder_id] = event.folder
            elif isinstance(event, JournalFolderDeletedEvent):
                if folders.pop(event.folder.folder_id, None) != event.folder:
                    raise JournalStoreCorruptionError("folder tombstone is inconsistent")
            elif isinstance(event, JournalDocumentPutEvent):
                documents[event.document.document_id] = event.document
            else:
                if documents.pop(event.document.document_id, None) != event.document:
                    raise JournalStoreCorruptionError("document tombstone is inconsistent")
        try:
            self._validate_folder_graph(folders)
            self._validate_documents(documents, folders)
        except JournalStoreError as exc:
            raise JournalStoreCorruptionError("journal state violates references") from exc
        return JournalSnapshot(
            revision=len(events),
            folders=tuple(sorted(folders.values(), key=journal_folder_sort_key)),
            documents=tuple(sorted(documents.values(), key=journal_document_sort_key)),
            events=events,
        )

    @staticmethod
    def _validate_folder_graph(folders: dict[str, JournalFolder]) -> None:
        for folder in folders.values():
            seen: set[str] = set()
            current = folder
            depth = 1
            while current.parent_folder_id is not None:
                if current.parent_folder_id not in folders:
                    raise JournalFolderReferenceError("parent folder is missing")
                if current.parent_folder_id in seen:
                    raise JournalFolderCycleError("folder graph is cyclic")
                seen.add(current.folder_id)
                current = folders[current.parent_folder_id]
                depth += 1
                if depth > MAX_JOURNAL_FOLDER_DEPTH:
                    raise JournalFolderCycleError("folder depth exceeds limit")

    @staticmethod
    def _validate_documents(
        documents: dict[str, JournalDocument], folders: dict[str, JournalFolder]
    ) -> None:
        for document in documents.values():
            if document.folder_id is not None and document.folder_id not in folders:
                raise JournalFolderReferenceError("document folder is missing")
            if not _document_links(document) <= set(documents):
                raise JournalDocumentLinkError("document link target is missing")

    @staticmethod
    def _parse_receipt(encoded: str) -> JournalMutationReceipt:
        try:
            decoded: Any = json.loads(
                encoded,
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            )
            receipt = JournalMutationReceipt.model_validate(decoded)
            parse_journal_event(receipt.event.model_dump(mode="json"))
            if _canonical_json(receipt) != encoded:
                raise ValueError("noncanonical")
            return receipt
        except (ValueError, TypeError, ValidationError, json.JSONDecodeError) as exc:
            raise JournalStoreCorruptionError("stored journal receipt is invalid") from exc

    @classmethod
    def _parse_event_row(
        cls,
        expected_table_id: str,
        row: tuple[Any, ...],
    ) -> JournalMutationEvent:
        try:
            (
                schema,
                table_id,
                sequence,
                revision,
                command_id,
                command_json,
                receipt_json,
            ) = row
            if str(schema) != JOURNAL_STORE_SCHEMA_VERSION:
                raise JournalStoreSchemaError("unsupported stored journal schema")
            if (
                str(table_id) != expected_table_id
                or type(sequence) is not int
                or type(revision) is not int
                or sequence < 1
                or revision != sequence
            ):
                raise ValueError("row identity")
            decoded_command: Any = json.loads(
                str(command_json),
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            )
            command = parse_journal_command(decoded_command)
            if _canonical_json(command) != str(command_json):
                raise ValueError("noncanonical command")
            receipt = cls._parse_receipt(str(receipt_json))
            if (
                command.table_id != table_id
                or command.command_id != str(command_id)
                or command.expected_revision != revision - 1
                or receipt.table_id != table_id
                or receipt.command_id != str(command_id)
                or receipt.revision != revision
                or receipt.event.sequence != sequence
                or receipt.event.revision != revision
                or receipt.event.event_id != f"{table_id}:journal:{sequence}"
                or not _command_matches_event(command, receipt.event)
            ):
                raise ValueError("row content identity")
            return receipt.event
        except JournalStoreSchemaError:
            raise
        except JournalStoreCorruptionError:
            raise
        except (ValueError, TypeError, ValidationError, json.JSONDecodeError) as exc:
            raise JournalStoreCorruptionError("stored journal event row is invalid") from exc


__all__ = [name for name in globals() if name.startswith("Journal") or name.startswith("SQLite")]
__all__ += ["MAX_JOURNAL_DOCUMENTS", "MAX_JOURNAL_FOLDER_DEPTH", "MAX_JOURNAL_FOLDERS"]
