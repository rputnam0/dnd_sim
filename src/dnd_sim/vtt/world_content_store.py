"""Tamper-evident append-only SQLite storage for reusable VTT world content."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from .world_content_contracts import (
    MAX_ACTIVE_ACTORS,
    MAX_ACTIVE_ITEMS,
    MAX_RETAINED_ACTORS,
    MAX_RETAINED_ITEMS,
    MAX_SEARCH_RESULTS,
    DocumentKind,
    WorldActorDocument,
    WorldContentArchiveCommand,
    WorldContentArchivedEvent,
    WorldContentCreateCommand,
    WorldContentCreatedEvent,
    WorldContentEntry,
    WorldContentMutationCommand,
    WorldContentMutationEvent,
    WorldContentMutationReceipt,
    WorldContentPrincipalRole,
    WorldContentProjection,
    WorldContentProjectionEntry,
    WorldContentSearchHit,
    WorldContentUpdateCommand,
    WorldContentUpdatedEvent,
    WorldContentView,
    WorldDocument,
    WorldItemDocument,
    WorldProjectedActorDocument,
    WorldProjectedItemDocument,
    document_digest,
    document_name_key,
    parse_world_content_command,
    parse_world_content_event,
)

WORLD_CONTENT_STORE_SCHEMA_VERSION = "vtt.world_content_store.v1"
logger = logging.getLogger(__name__)
_METADATA_TABLE = "_vtt_world_content_metadata"
_HEAD_TABLE = "_vtt_world_content_head"
_EVENTS_TABLE = "_vtt_world_content_events"
_EMPTY_HEAD_HASH = "0" * 64


class WorldContentStoreError(RuntimeError):
    """Base failure for reusable world-content persistence."""


class WorldContentStoreSchemaError(WorldContentStoreError):
    pass


class WorldContentCorruptionError(WorldContentStoreError):
    pass


class WorldContentCommandConflictError(WorldContentStoreError):
    pass


class WorldContentRevisionConflictError(WorldContentStoreError):
    def __init__(self, *, current_revision: int, expected_revision: int) -> None:
        super().__init__(f"expected revision {current_revision}, received {expected_revision}")
        self.current_revision = current_revision
        self.expected_revision = expected_revision


class WorldContentDocumentConflictError(WorldContentStoreError):
    pass


class WorldContentDocumentRevisionError(WorldContentStoreError):
    pass


class WorldContentNameConflictError(WorldContentStoreError):
    pass


class WorldContentNotFoundError(WorldContentStoreError):
    pass


class WorldContentArchivedError(WorldContentStoreError):
    pass


class WorldContentReferencedError(WorldContentStoreError):
    pass


class WorldContentLimitError(WorldContentStoreError):
    pass


@dataclass(frozen=True, slots=True)
class WorldContentExecutionResult:
    receipt: WorldContentMutationReceipt
    replayed: bool


@dataclass(frozen=True, slots=True)
class _StoredHistoryEntry:
    command: WorldContentMutationCommand
    receipt: WorldContentMutationReceipt
    entry_hash: str


@dataclass(frozen=True, slots=True)
class _ContentHistoryView:
    revision: int
    documents: tuple[WorldContentEntry, ...]


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
        raise WorldContentCorruptionError(f"stored {field_name} is not valid JSON") from exc


def _stored_non_negative_int(value: Any, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise WorldContentCorruptionError(f"stored {field_name} is not a non-negative integer")
    return value


def _stored_positive_int(value: Any, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise WorldContentCorruptionError(f"stored {field_name} is not a positive integer")
    return value


def _stored_hash(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise WorldContentCorruptionError(f"stored {field_name} is not a lowercase SHA-256 digest")
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
            "store_schema_version": WORLD_CONTENT_STORE_SCHEMA_VERSION,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _document_key(document: WorldDocument) -> tuple[DocumentKind, str]:
    return (document.document_kind, document.document_id)


def _content_without_revision(document: WorldDocument) -> dict[str, Any]:
    return document.model_dump(mode="json", exclude={"document_revision"})


def _active_name_owner(
    entries: dict[tuple[DocumentKind, str], WorldContentEntry],
    document: WorldDocument,
    *,
    excluding_key: tuple[DocumentKind, str] | None = None,
) -> str | None:
    key = document_name_key(document.name)
    return next(
        (
            entry.document_id
            for entry_key, entry in entries.items()
            if entry_key != excluding_key
            and not entry.archived
            and entry.document.table_id == document.table_id
            and entry.document_kind == document.document_kind
            and document_name_key(entry.document.name) == key
        ),
        None,
    )


def _require_inventory_integrity(
    entries: dict[tuple[DocumentKind, str], WorldContentEntry],
    actor: WorldActorDocument,
) -> None:
    for inventory_entry in actor.inventory:
        item_entry = entries.get(("item", inventory_entry.item_id))
        if (
            item_entry is None
            or item_entry.archived
            or item_entry.document.table_id != actor.table_id
        ):
            raise WorldContentReferencedError(
                f"actor '{actor.actor_id}' references missing active item "
                f"'{inventory_entry.item_id}' in its table"
            )
        if not isinstance(item_entry.document, WorldItemDocument):
            raise WorldContentReferencedError(
                f"actor '{actor.actor_id}' references a non-item document"
            )
        if inventory_entry.attuned and not item_entry.document.data.requires_attunement:
            raise WorldContentReferencedError(
                f"actor '{actor.actor_id}' attunes item '{inventory_entry.item_id}' "
                "which does not require attunement"
            )


def _active_item_referrers(
    entries: dict[tuple[DocumentKind, str], WorldContentEntry],
    *,
    table_id: str,
    item_id: str,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            entry.document.actor_id
            for entry in entries.values()
            if not entry.archived
            and isinstance(entry.document, WorldActorDocument)
            and entry.document.table_id == table_id
            and any(row.item_id == item_id for row in entry.document.inventory)
        )
    )


class WorldContentTransaction:
    """One caller-composable content transaction with an explicit lifetime."""

    def __init__(self, store: "SQLiteWorldContentStore") -> None:
        self._store = store
        self._active = True

    def _require_active(self) -> None:
        if not self._active:
            raise WorldContentStoreError("world content transaction is closed")
        if not self._store._connection.in_transaction:
            raise WorldContentStoreError("world content transaction was finalized externally")

    def execute(self, command: WorldContentMutationCommand) -> WorldContentExecutionResult:
        self._require_active()
        return self._store._execute_locked(command)

    def snapshot(self, table_id: str) -> WorldContentView:
        self._require_active()
        view, _ = self._store._read_history_locked()
        return self._store._table_view(view=view, table_id=table_id)

    def receipts_after(self, sequence: int) -> tuple[WorldContentMutationReceipt, ...]:
        self._require_active()
        return self._store._receipts_after_locked(sequence)

    def _close(self) -> None:
        self._active = False


class SQLiteWorldContentStore:
    """Append-only actor/item document storage spanning independently scoped tables."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        if connection.in_transaction:
            raise WorldContentStoreError(
                "cannot initialize world content store inside an active transaction"
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
                raise WorldContentStoreSchemaError("world content store schema is incomplete")
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
                    raise WorldContentCorruptionError("world content metadata row is missing")
                self._connection.execute(
                    f"INSERT INTO {_METADATA_TABLE} (singleton, schema_version) VALUES (1, ?)",
                    (WORLD_CONTENT_STORE_SCHEMA_VERSION,),
                )
            elif metadata[0] != WORLD_CONTENT_STORE_SCHEMA_VERSION:
                raise WorldContentStoreSchemaError("unsupported world content store schema")

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
                    raise WorldContentCorruptionError("world content head is missing")
                self._connection.execute(
                    f"INSERT INTO {_HEAD_TABLE} (singleton, revision, head_hash) "
                    "VALUES (1, 0, ?)",
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
    def transaction(self) -> Iterator[WorldContentTransaction]:
        if self._connection.in_transaction:
            raise WorldContentStoreError(
                "cannot start world content transaction inside an active transaction"
            )
        transaction = WorldContentTransaction(self)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield transaction
            if not self._connection.in_transaction:
                raise WorldContentStoreError("world content transaction was finalized externally")
            self._read_history_locked()
            self._connection.commit()
        except BaseException:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise
        finally:
            transaction._close()

    def execute(self, command: WorldContentMutationCommand) -> WorldContentExecutionResult:
        with self.transaction() as transaction:
            return transaction.execute(command)

    def snapshot(self, table_id: str) -> WorldContentView:
        view, _ = self._read_public()
        return self._table_view(view=view, table_id=table_id)

    def revision(self) -> int:
        view, _ = self._read_public()
        return view.revision

    def receipts_after(self, sequence: int) -> tuple[WorldContentMutationReceipt, ...]:
        self._validate_sequence(sequence)
        _, history = self._read_public()
        return tuple(entry.receipt for entry in history if entry.receipt.revision > sequence)

    def events_after(self, sequence: int) -> tuple[WorldContentMutationEvent, ...]:
        return tuple(receipt.event for receipt in self.receipts_after(sequence))

    def search(
        self,
        *,
        table_id: str,
        query: str,
        principal_id: str | None,
        principal_role: WorldContentPrincipalRole,
        document_kind: DocumentKind | None = None,
        limit: int = MAX_SEARCH_RESULTS,
    ) -> tuple[WorldContentSearchHit, ...]:
        projection = self.project(
            table_id=table_id,
            principal_id=principal_id,
            principal_role=principal_role,
        )
        if not isinstance(query, str) or not query or query != query.strip():
            raise ValueError("query must be non-empty without surrounding whitespace")
        if len(query) > 160:
            raise ValueError("query must be at most 160 characters")
        if (
            type(limit) is not int
            or isinstance(limit, bool)
            or not 1 <= limit <= MAX_SEARCH_RESULTS
        ):
            raise ValueError(f"limit must be an integer from 1 through {MAX_SEARCH_RESULTS}")
        query_key = unicodedata.normalize("NFKC", query).casefold()
        hits: list[WorldContentSearchHit] = []
        for entry in projection.documents:
            if entry.archived:
                continue
            document = entry.document
            if document_kind is not None and document.document_kind != document_kind:
                continue
            # Only safe, explicitly displayed metadata participates.  Descriptions,
            # sheets, provenance, ownership, and references are never indexed.
            searchable = (document.name, *(document.tags))
            if not any(
                query_key in unicodedata.normalize("NFKC", text).casefold() for text in searchable
            ):
                continue
            hits.append(
                WorldContentSearchHit(
                    table_id=document.table_id,
                    document_kind=document.document_kind,
                    document_id=document.document_id,
                    name=document.name,
                    folder_id=document.folder_id,
                    tags=document.tags,
                    can_control=document.can_control,
                )
            )
            if len(hits) >= limit:
                break
        return tuple(hits)

    def project(
        self,
        *,
        table_id: str,
        principal_id: str | None,
        principal_role: WorldContentPrincipalRole,
    ) -> WorldContentProjection:
        """Return only documents and relationships authorized for one principal."""

        if principal_role not in {"gm", "player", "spectator"}:
            raise ValueError("principal_role must be gm, player, or spectator")
        if principal_role == "player" and principal_id is None:
            raise ValueError("player projections require principal_id")
        view = self.snapshot(table_id)
        active_entries = tuple(entry for entry in view.documents if not entry.archived)

        assigned_actors: set[str] = set()
        visible_actor_entries: list[WorldContentEntry] = []
        for entry in active_entries:
            document = entry.document
            if not isinstance(document, WorldActorDocument):
                continue
            is_assigned = (
                principal_role == "player"
                and principal_id is not None
                and principal_id in document.permissions.assigned_participant_ids
            )
            if is_assigned:
                assigned_actors.add(document.actor_id)
            if is_assigned or document.permissions.can_view(
                principal_id=principal_id,
                principal_role=principal_role,
            ):
                visible_actor_entries.append(entry)

        linked_item_ids = {
            row.item_id
            for entry in visible_actor_entries
            if entry.document.document_id in assigned_actors
            and isinstance(entry.document, WorldActorDocument)
            for row in entry.document.inventory
        }
        visible_item_entries = [
            entry
            for entry in active_entries
            if isinstance(entry.document, WorldItemDocument)
            and (
                entry.document.item_id in linked_item_ids
                or entry.document.permissions.can_view(
                    principal_id=principal_id,
                    principal_role=principal_role,
                )
            )
        ]

        if principal_role == "gm":
            selected = list(view.documents)
        else:
            selected = visible_actor_entries + visible_item_entries
        visible_item_ids = {
            entry.document.item_id
            for entry in selected
            if isinstance(entry.document, WorldItemDocument) and not entry.archived
        }

        projected: list[WorldContentProjectionEntry] = []
        for entry in sorted(
            selected,
            key=lambda row: (row.document_kind, row.document_id),
        ):
            document = entry.document
            can_control = document.permissions.can_control(
                principal_id=principal_id,
                principal_role=principal_role,
            )
            if isinstance(document, WorldActorDocument):
                safe_inventory = tuple(
                    row for row in document.inventory if row.item_id in visible_item_ids
                )
                projected_document = WorldProjectedActorDocument(
                    actor_id=document.actor_id,
                    table_id=document.table_id,
                    document_revision=document.document_revision,
                    name=document.name,
                    folder_id=document.folder_id,
                    tags=document.tags,
                    sheet=document.sheet,
                    inventory=safe_inventory,
                    can_control=can_control,
                )
            else:
                projected_document = WorldProjectedItemDocument(
                    item_id=document.item_id,
                    table_id=document.table_id,
                    document_revision=document.document_revision,
                    name=document.name,
                    folder_id=document.folder_id,
                    tags=document.tags,
                    data=document.data,
                    can_control=can_control,
                )
            projected.append(
                WorldContentProjectionEntry(
                    document=projected_document,
                    archived=entry.archived,
                )
            )
        return WorldContentProjection(
            table_id=view.table_id,
            revision=view.revision,
            documents=tuple(projected),
        )

    def _read_public(
        self,
    ) -> tuple[_ContentHistoryView, tuple[_StoredHistoryEntry, ...]]:
        if self._connection.in_transaction:
            raise WorldContentStoreError(
                "cannot read world content store inside an active transaction"
            )
        try:
            self._connection.execute("BEGIN")
            result = self._read_history_locked()
            self._connection.commit()
            return result
        except BaseException:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    @staticmethod
    def _table_view(*, view: _ContentHistoryView, table_id: str) -> WorldContentView:
        # Validate using the projection contract rather than duplicating identity rules.
        return WorldContentView(
            table_id=table_id,
            revision=view.revision,
            documents=tuple(
                entry for entry in view.documents if entry.document.table_id == table_id
            ),
        )

    def _execute_locked(self, command: WorldContentMutationCommand) -> WorldContentExecutionResult:
        if not isinstance(
            command,
            (
                WorldContentCreateCommand,
                WorldContentUpdateCommand,
                WorldContentArchiveCommand,
            ),
        ):
            raise TypeError("command must be a world content mutation command")
        command = parse_world_content_command(command.model_dump(mode="json"))
        command_json = _canonical_json(command)

        snapshot, history = self._read_history_locked()
        existing = next(
            (entry for entry in history if entry.command.command_id == command.command_id),
            None,
        )
        if existing is not None:
            if existing.command != command:
                raise WorldContentCommandConflictError(
                    f"command_id '{command.command_id}' has different content"
                )
            return WorldContentExecutionResult(receipt=existing.receipt, replayed=True)

        if command.expected_revision != snapshot.revision:
            raise WorldContentRevisionConflictError(
                current_revision=snapshot.revision,
                expected_revision=command.expected_revision,
            )
        entries = {(entry.document_kind, entry.document_id): entry for entry in snapshot.documents}
        revision = snapshot.revision + 1
        event = self._build_event(command, entries=entries, revision=revision)
        receipt = WorldContentMutationReceipt(
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
                WORLD_CONTENT_STORE_SCHEMA_VERSION,
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
            raise WorldContentCorruptionError("world content head changed unexpectedly")
        return WorldContentExecutionResult(receipt=receipt, replayed=False)

    def _build_event(
        self,
        command: WorldContentMutationCommand,
        *,
        entries: dict[tuple[DocumentKind, str], WorldContentEntry],
        revision: int,
    ) -> WorldContentMutationEvent:
        common = {
            "event_id": f"content-{revision}",
            "sequence": revision,
            "revision": revision,
            "command_id": command.command_id,
        }
        if isinstance(command, WorldContentCreateCommand):
            document = command.document
            key = _document_key(document)
            if key in entries:
                raise WorldContentDocumentConflictError(
                    f"{document.document_kind}_id '{document.document_id}' is permanently used"
                )
            self._validate_create_limits(entries, document=document)
            owner = _active_name_owner(entries, document)
            if owner is not None:
                raise WorldContentNameConflictError(
                    f"active {document.document_kind} name is already used by '{owner}'"
                )
            if isinstance(document, WorldActorDocument):
                _require_inventory_integrity(entries, document)
            return WorldContentCreatedEvent(**common, document=document)

        if isinstance(command, WorldContentUpdateCommand):
            document = command.document
            key = _document_key(document)
            target = entries.get(key)
            if target is None:
                raise WorldContentNotFoundError(
                    f"{document.document_kind}_id '{document.document_id}' is missing"
                )
            if target.archived:
                raise WorldContentArchivedError(
                    f"{document.document_kind}_id '{document.document_id}' is archived"
                )
            prior = target.document
            if document.table_id != prior.table_id:
                raise WorldContentDocumentConflictError("document table_id is immutable")
            expected_document_revision = prior.document_revision + 1
            if document.document_revision != expected_document_revision:
                raise WorldContentDocumentRevisionError(
                    f"expected document revision {expected_document_revision}, "
                    f"received {document.document_revision}"
                )
            if _content_without_revision(document) == _content_without_revision(prior):
                raise WorldContentDocumentConflictError(
                    "document update must change document content"
                )
            owner = _active_name_owner(entries, document, excluding_key=key)
            if owner is not None:
                raise WorldContentNameConflictError(
                    f"active {document.document_kind} name is already used by '{owner}'"
                )
            if isinstance(document, WorldActorDocument):
                _require_inventory_integrity(entries, document)
            return WorldContentUpdatedEvent(
                **common,
                previous_document_digest=document_digest(prior),
                document=document,
            )

        key = (command.document_kind, command.document_id)
        target = entries.get(key)
        if target is None or target.document.table_id != command.table_id:
            raise WorldContentNotFoundError(
                f"{command.document_kind}_id '{command.document_id}' is missing"
            )
        if target.archived:
            raise WorldContentArchivedError(
                f"{command.document_kind}_id '{command.document_id}' is archived"
            )
        if command.document_kind == "item":
            referrers = _active_item_referrers(
                entries,
                table_id=command.table_id,
                item_id=command.document_id,
            )
            if referrers:
                raise WorldContentReferencedError(
                    f"item '{command.document_id}' is referenced by active actor(s): "
                    + ", ".join(referrers)
                )
        return WorldContentArchivedEvent(
            **common,
            table_id=command.table_id,
            document_kind=command.document_kind,
            document_id=command.document_id,
            prior_document_digest=document_digest(target.document),
        )

    @staticmethod
    def _validate_create_limits(
        entries: dict[tuple[DocumentKind, str], WorldContentEntry],
        *,
        document: WorldDocument,
    ) -> None:
        retained = tuple(
            entry
            for entry in entries.values()
            if entry.document.table_id == document.table_id
            and entry.document_kind == document.document_kind
        )
        active = tuple(entry for entry in retained if not entry.archived)
        if document.document_kind == "actor":
            if len(retained) >= MAX_RETAINED_ACTORS:
                raise WorldContentLimitError("table reached its retained actor limit")
            if len(active) >= MAX_ACTIVE_ACTORS:
                raise WorldContentLimitError("table reached its active actor limit")
        else:
            if len(retained) >= MAX_RETAINED_ITEMS:
                raise WorldContentLimitError("table reached its retained item limit")
            if len(active) >= MAX_ACTIVE_ITEMS:
                raise WorldContentLimitError("table reached its active item limit")

    def _read_history_locked(
        self,
    ) -> tuple[_ContentHistoryView, tuple[_StoredHistoryEntry, ...]]:
        metadata_row = self._connection.execute(
            f"SELECT schema_version FROM {_METADATA_TABLE} WHERE singleton = 1"
        ).fetchone()
        if metadata_row is None:
            raise WorldContentCorruptionError("world content metadata row is missing")
        if metadata_row[0] != WORLD_CONTENT_STORE_SCHEMA_VERSION:
            raise WorldContentStoreSchemaError("unsupported world content store schema")
        head_row = self._connection.execute(
            f"SELECT revision, head_hash FROM {_HEAD_TABLE} WHERE singleton = 1"
        ).fetchone()
        if head_row is None:
            raise WorldContentCorruptionError("world content head is missing")
        head_revision = _stored_non_negative_int(head_row[0], field_name="head revision")
        head_hash = _stored_hash(head_row[1], field_name="head hash")

        rows = self._connection.execute(f"""
            SELECT store_schema_version, revision, command_id, command_json,
                   receipt_json, previous_hash, entry_hash
            FROM {_EVENTS_TABLE}
            ORDER BY revision ASC
            """).fetchall()
        entries: dict[tuple[DocumentKind, str], WorldContentEntry] = {}
        history: list[_StoredHistoryEntry] = []
        expected_revision = 1
        previous_hash = _EMPTY_HEAD_HASH
        for row in rows:
            self._validate_store_schema(row[0])
            revision = _stored_positive_int(row[1], field_name="revision")
            if revision != expected_revision:
                raise WorldContentCorruptionError("world content history has a revision gap")
            command_id = row[2]
            command_json = row[3]
            receipt_json = row[4]
            if not all(
                isinstance(value, str) for value in (command_id, command_json, receipt_json)
            ):
                raise WorldContentCorruptionError("world content row contains non-text JSON")
            stored_previous_hash = _stored_hash(row[5], field_name="previous hash")
            stored_entry_hash = _stored_hash(row[6], field_name="entry hash")
            if stored_previous_hash != previous_hash:
                raise WorldContentCorruptionError("world content hash chain is broken")
            calculated_hash = _entry_hash(
                revision=revision,
                command_json=command_json,
                receipt_json=receipt_json,
                previous_hash=stored_previous_hash,
            )
            if stored_entry_hash != calculated_hash:
                raise WorldContentCorruptionError("world content entry hash is inconsistent")

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
            raise WorldContentCorruptionError(
                "world content head does not match its append-only history"
            )
        try:
            view = _ContentHistoryView(
                revision=revision,
                documents=tuple(entries[key] for key in sorted(entries)),
            )
            for table_id in sorted({entry.document.table_id for entry in entries.values()}):
                self._table_view(view=view, table_id=table_id)
        except ValidationError as exc:
            raise WorldContentCorruptionError(
                "world content history produces an invalid projection"
            ) from exc
        return view, tuple(history)

    @staticmethod
    def _apply_event(
        entries: dict[tuple[DocumentKind, str], WorldContentEntry],
        event: WorldContentMutationEvent,
    ) -> None:
        if isinstance(event, WorldContentCreatedEvent):
            document = event.document
            key = _document_key(document)
            if key in entries:
                raise WorldContentCorruptionError("world content history reuses a document ID")
            try:
                SQLiteWorldContentStore._validate_create_limits(entries, document=document)
                if _active_name_owner(entries, document) is not None:
                    raise WorldContentCorruptionError(
                        "world content history reuses an active document name"
                    )
                if isinstance(document, WorldActorDocument):
                    _require_inventory_integrity(entries, document)
            except WorldContentStoreError as exc:
                raise WorldContentCorruptionError(
                    "world content history violates create invariants"
                ) from exc
            entries[key] = WorldContentEntry(document=document, archived=False)
            return

        if isinstance(event, WorldContentUpdatedEvent):
            document = event.document
            key = _document_key(document)
            target = entries.get(key)
            if target is None or target.archived:
                raise WorldContentCorruptionError(
                    "world content history updates a missing or archived document"
                )
            prior = target.document
            if (
                prior.table_id != document.table_id
                or document.document_revision != prior.document_revision + 1
                or event.previous_document_digest != document_digest(prior)
                or _content_without_revision(document) == _content_without_revision(prior)
                or _active_name_owner(entries, document, excluding_key=key) is not None
            ):
                raise WorldContentCorruptionError(
                    "world content update violates document invariants"
                )
            try:
                if isinstance(document, WorldActorDocument):
                    _require_inventory_integrity(entries, document)
            except WorldContentStoreError as exc:
                raise WorldContentCorruptionError(
                    "world content update violates inventory integrity"
                ) from exc
            entries[key] = WorldContentEntry(document=document, archived=False)
            return

        key = (event.document_kind, event.document_id)
        target = entries.get(key)
        if (
            target is None
            or target.archived
            or target.document.table_id != event.table_id
            or event.prior_document_digest != document_digest(target.document)
        ):
            raise WorldContentCorruptionError("world content history archives an invalid document")
        if event.document_kind == "item" and _active_item_referrers(
            entries,
            table_id=event.table_id,
            item_id=event.document_id,
        ):
            raise WorldContentCorruptionError("world content history archives a referenced item")
        entries[key] = WorldContentEntry(document=target.document, archived=True)

    @staticmethod
    def _parse_stored_command(
        encoded: str,
        *,
        command_id: str,
        revision: int,
    ) -> WorldContentMutationCommand:
        try:
            _decode_json(encoded, field_name="command")
            command = parse_world_content_command(encoded)
        except ValidationError as exc:
            raise WorldContentCorruptionError(
                "stored world content command violates its contract"
            ) from exc
        if (
            command.command_id != command_id
            or command.expected_revision != revision - 1
            or _canonical_json(command) != encoded
        ):
            raise WorldContentCorruptionError(
                "stored world content command identity is inconsistent"
            )
        return command

    @staticmethod
    def _parse_stored_receipt(
        encoded: str,
        *,
        command_id: str,
        revision: int,
    ) -> WorldContentMutationReceipt:
        try:
            _decode_json(encoded, field_name="receipt")
            receipt = WorldContentMutationReceipt.model_validate_json(encoded)
        except ValidationError as exc:
            raise WorldContentCorruptionError(
                "stored world content receipt violates its contract"
            ) from exc
        if (
            receipt.command_id != command_id
            or receipt.revision != revision
            or receipt.event.sequence != revision
            or receipt.event.event_id != f"content-{revision}"
            or _canonical_json(receipt) != encoded
        ):
            raise WorldContentCorruptionError(
                "stored world content receipt identity is inconsistent"
            )
        return receipt

    @staticmethod
    def _validate_command_receipt(
        command: WorldContentMutationCommand,
        receipt: WorldContentMutationReceipt,
    ) -> None:
        event = receipt.event
        valid = False
        if isinstance(command, WorldContentCreateCommand):
            valid = (
                isinstance(event, WorldContentCreatedEvent) and event.document == command.document
            )
        elif isinstance(command, WorldContentUpdateCommand):
            valid = (
                isinstance(event, WorldContentUpdatedEvent) and event.document == command.document
            )
        elif isinstance(command, WorldContentArchiveCommand):
            valid = (
                isinstance(event, WorldContentArchivedEvent)
                and event.table_id == command.table_id
                and event.document_kind == command.document_kind
                and event.document_id == command.document_id
            )
        if not valid:
            raise WorldContentCorruptionError(
                "stored world content command and receipt are inconsistent"
            )

    def _receipts_after_locked(self, sequence: int) -> tuple[WorldContentMutationReceipt, ...]:
        self._validate_sequence(sequence)
        _, history = self._read_history_locked()
        return tuple(entry.receipt for entry in history if entry.receipt.revision > sequence)

    @staticmethod
    def _validate_sequence(sequence: int) -> None:
        if type(sequence) is not int or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")

    @staticmethod
    def _validate_store_schema(value: Any) -> None:
        if value != WORLD_CONTENT_STORE_SCHEMA_VERSION:
            raise WorldContentStoreSchemaError(
                "stored world content row uses an unsupported schema"
            )


__all__ = [
    "WORLD_CONTENT_STORE_SCHEMA_VERSION",
    "SQLiteWorldContentStore",
    "WorldContentArchivedError",
    "WorldContentCommandConflictError",
    "WorldContentCorruptionError",
    "WorldContentDocumentConflictError",
    "WorldContentDocumentRevisionError",
    "WorldContentExecutionResult",
    "WorldContentLimitError",
    "WorldContentNameConflictError",
    "WorldContentNotFoundError",
    "WorldContentReferencedError",
    "WorldContentRevisionConflictError",
    "WorldContentStoreError",
    "WorldContentStoreSchemaError",
    "WorldContentTransaction",
]
