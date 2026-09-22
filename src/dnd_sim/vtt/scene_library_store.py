"""Restart-safe append-only SQLite storage for VTT scene libraries."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from .scene_library_contracts import (
    SCENE_LIBRARY_VIEW_SCHEMA_VERSION,
    SceneActivateCommand,
    SceneActivatedEvent,
    SceneArchiveCommand,
    SceneArchivedEvent,
    SceneCreateCommand,
    SceneCreatedEvent,
    SceneDuplicateCommand,
    SceneDuplicatedEvent,
    SceneExportBundle,
    SceneImportCommand,
    SceneImportedEvent,
    SceneLibraryEntry,
    SceneLibraryView,
    SceneMapMetadata,
    SceneMutationCommand,
    SceneMutationEvent,
    SceneMutationReceipt,
    SceneRecord,
    SceneUpdateCommand,
    SceneUpdatedEvent,
    parse_scene_command,
)

SCENE_LIBRARY_STORE_SCHEMA_VERSION = "vtt.scene_library_store.v1"
_METADATA_TABLE = "_vtt_scene_library_store_metadata"
_EVENTS_TABLE = "_vtt_scene_library_event_log"


class SceneLibraryStoreError(RuntimeError):
    """Base failure for durable scene-library operations."""


class SceneLibraryStoreSchemaError(SceneLibraryStoreError):
    pass


class SceneLibraryStoreCorruptionError(SceneLibraryStoreError):
    pass


class SceneCommandConflictError(SceneLibraryStoreError):
    pass


class SceneRevisionConflictError(SceneLibraryStoreError):
    def __init__(self, *, current_revision: int, expected_revision: int) -> None:
        super().__init__(f"expected revision {current_revision}, received {expected_revision}")
        self.current_revision = current_revision
        self.expected_revision = expected_revision


class SceneIdConflictError(SceneLibraryStoreError):
    pass


class SceneImportConflictError(SceneIdConflictError):
    pass


class SceneNotFoundError(SceneLibraryStoreError):
    pass


class SceneArchivedError(SceneLibraryStoreError):
    pass


class SceneAlreadyActiveError(SceneLibraryStoreError):
    pass


class SceneActiveArchiveError(SceneLibraryStoreError):
    pass


class SceneSuccessorError(SceneLibraryStoreError):
    pass


@dataclass(frozen=True, slots=True)
class SceneExecutionResult:
    receipt: SceneMutationReceipt
    replayed: bool


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


def _without_migrated_calibration(value: Any) -> Any:
    """Return the canonical pre-calibration representation when it is lossless."""

    if isinstance(value, list):
        return [_without_migrated_calibration(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized = {key: _without_migrated_calibration(item) for key, item in value.items()}
    if normalized.get("schema_version") != "vtt.scene_map_metadata.v1":
        return normalized
    calibration = normalized.get("calibration")
    grid_size = normalized.get("grid_size_px")
    gridless = normalized.get("gridless")
    if (
        type(grid_size) is float
        and isinstance(gridless, bool)
        and calibration
        == {
            "schema_version": "vtt.board_calibration.v1",
            "topology": "gridless" if gridless else "square",
            "origin_x_px": grid_size / 2.0,
            "origin_y_px": grid_size / 2.0,
            "cell_extent_px": grid_size,
            "distance_ft": 5.0,
        }
    ):
        normalized.pop("calibration")
    return normalized


def _matches_stored_canonical_json(model: BaseModel, encoded: str) -> bool:
    if _canonical_json(model) == encoded:
        return True
    legacy = _without_migrated_calibration(model.model_dump(mode="json"))
    return (
        json.dumps(
            legacy,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        == encoded
    )


def _decode_json(encoded: str, *, field_name: str) -> Any:
    try:
        return json.loads(
            encoded,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SceneLibraryStoreCorruptionError(f"stored {field_name} is not valid JSON") from exc


def _stored_positive_int(value: Any, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise SceneLibraryStoreCorruptionError(f"stored {field_name} is not a positive integer")
    return value


class SQLiteSceneLibrary:
    """One connection-owned event log supporting isolated table scene libraries."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        if connection.in_transaction:
            raise SceneLibraryStoreError(
                "cannot initialize scene storage inside an active transaction"
            )
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
                    (SCENE_LIBRARY_STORE_SCHEMA_VERSION,),
                )
            elif str(row[0]) != SCENE_LIBRARY_STORE_SCHEMA_VERSION:
                raise SceneLibraryStoreSchemaError("unsupported scene-library store schema")
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

    def execute(self, command: SceneMutationCommand) -> SceneExecutionResult:
        if not isinstance(
            command,
            (
                SceneCreateCommand,
                SceneDuplicateCommand,
                SceneUpdateCommand,
                SceneActivateCommand,
                SceneArchiveCommand,
                SceneImportCommand,
            ),
        ):
            raise TypeError("command must be a scene mutation command")
        command = parse_scene_command(command.model_dump(mode="json"))
        command_json = _canonical_json(command)
        if self._connection.in_transaction:
            raise SceneLibraryStoreError("execute cannot run inside an active transaction")

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
                if stored_command != command:
                    raise SceneCommandConflictError(
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
                return SceneExecutionResult(receipt=receipt, replayed=True)

            snapshot = self._snapshot_locked(command.table_id)
            if command.expected_revision != snapshot.revision:
                raise SceneRevisionConflictError(
                    current_revision=snapshot.revision,
                    expected_revision=command.expected_revision,
                )
            revision = snapshot.revision + 1
            event_id = f"{command.table_id}:scene:{revision}"
            scene_ids = {entry.scene.scene_id for entry in snapshot.scenes}
            event = self._build_event(
                command,
                snapshot=snapshot,
                scene_ids=scene_ids,
                revision=revision,
                event_id=event_id,
            )
            receipt = SceneMutationReceipt(
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
                    SCENE_LIBRARY_STORE_SCHEMA_VERSION,
                    command.table_id,
                    revision,
                    revision,
                    command.command_id,
                    command_json,
                    _canonical_json(receipt),
                ),
            )
            self._connection.commit()
            return SceneExecutionResult(receipt=receipt, replayed=False)
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def _build_event(
        self,
        command: SceneMutationCommand,
        *,
        snapshot: SceneLibraryView,
        scene_ids: set[str],
        revision: int,
        event_id: str,
    ) -> SceneMutationEvent:
        common = {
            "table_id": command.table_id,
            "event_id": event_id,
            "sequence": revision,
            "revision": revision,
            "command_id": command.command_id,
        }
        if isinstance(command, SceneCreateCommand):
            if command.scene.scene_id in scene_ids:
                raise SceneIdConflictError(f"scene_id '{command.scene.scene_id}' was already used")
            return SceneCreatedEvent(
                **common,
                scene=command.scene,
                became_active=snapshot.active_scene_id is None,
            )
        if isinstance(command, SceneImportCommand):
            scene = command.bundle.scene
            if scene.scene_id in scene_ids:
                raise SceneImportConflictError(
                    f"imported scene_id '{scene.scene_id}' was already used"
                )
            return SceneImportedEvent(
                **common,
                scene=scene,
                became_active=snapshot.active_scene_id is None,
            )
        if isinstance(command, SceneDuplicateCommand):
            source = snapshot.scene(command.source_scene_id)
            if source is None:
                raise SceneNotFoundError(f"source scene_id '{command.source_scene_id}' is missing")
            if command.new_scene_id in scene_ids:
                raise SceneIdConflictError(f"scene_id '{command.new_scene_id}' was already used")
            map_metadata = SceneMapMetadata.model_validate(
                {
                    **source.scene.map_metadata.model_dump(mode="json"),
                    "name": command.new_name,
                }
            )
            scene = SceneRecord(
                scene_id=command.new_scene_id,
                map_metadata=map_metadata,
            )
            return SceneDuplicatedEvent(
                **common,
                source_scene_id=command.source_scene_id,
                scene=scene,
                became_active=False,
            )
        if isinstance(command, SceneUpdateCommand):
            target = snapshot.scene(command.scene_id)
            if target is None:
                raise SceneNotFoundError(f"scene_id '{command.scene_id}' is missing")
            if target.archived:
                raise SceneArchivedError(f"scene_id '{command.scene_id}' is archived")
            return SceneUpdatedEvent(
                **common,
                scene=SceneRecord(
                    scene_id=command.scene_id,
                    map_metadata=command.map_metadata,
                ),
                active=snapshot.active_scene_id == command.scene_id,
            )
        if isinstance(command, SceneActivateCommand):
            target = snapshot.scene(command.scene_id)
            if target is None:
                raise SceneNotFoundError(f"scene_id '{command.scene_id}' is missing")
            if target.archived:
                raise SceneArchivedError(f"scene_id '{command.scene_id}' is archived")
            if snapshot.active_scene_id == command.scene_id:
                raise SceneAlreadyActiveError(f"scene_id '{command.scene_id}' is already active")
            if snapshot.active_scene_id is None:
                raise SceneLibraryStoreCorruptionError(
                    "a non-empty scene library has no active scene"
                )
            return SceneActivatedEvent(
                **common,
                scene_id=command.scene_id,
                previous_scene_id=snapshot.active_scene_id,
            )

        target = snapshot.scene(command.scene_id)
        if target is None:
            raise SceneNotFoundError(f"scene_id '{command.scene_id}' is missing")
        if target.archived:
            raise SceneArchivedError(f"scene_id '{command.scene_id}' is already archived")
        if snapshot.active_scene_id == command.scene_id:
            if command.successor_scene_id is None:
                raise SceneActiveArchiveError(
                    "the active scene requires an explicit available successor"
                )
            successor = snapshot.scene(command.successor_scene_id)
            if successor is None or successor.archived:
                raise SceneSuccessorError("successor_scene_id must identify an available scene")
            active_scene_id = successor.scene.scene_id
        else:
            if command.successor_scene_id is not None:
                raise SceneSuccessorError(
                    "successor_scene_id is only valid when archiving the active scene"
                )
            if snapshot.active_scene_id is None:
                raise SceneLibraryStoreCorruptionError(
                    "a non-empty scene library has no active scene"
                )
            active_scene_id = snapshot.active_scene_id
        return SceneArchivedEvent(
            **common,
            scene_id=command.scene_id,
            successor_scene_id=command.successor_scene_id,
            active_scene_id=active_scene_id,
        )

    def snapshot(self, table_id: str) -> SceneLibraryView:
        return self._snapshot_locked(_canonical_text(table_id, field_name="table_id"))

    def revision(self, table_id: str) -> int:
        return self.snapshot(table_id).revision

    def export_scene(self, table_id: str, scene_id: str) -> SceneExportBundle:
        view = self.snapshot(table_id)
        entry = view.scene(_canonical_text(scene_id, field_name="scene_id"))
        if entry is None:
            raise SceneNotFoundError(f"scene_id '{scene_id}' is missing")
        return SceneExportBundle(scene=entry.scene)

    def events_after(self, table_id: str, sequence: int) -> tuple[SceneMutationEvent, ...]:
        normalized = _canonical_text(table_id, field_name="table_id")
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
            (normalized, sequence),
        ).fetchall()
        return self._parse_event_rows(normalized, rows)

    def _events_locked(self, table_id: str) -> tuple[SceneMutationEvent, ...]:
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
        return self._parse_event_rows(table_id, rows)

    def _parse_event_rows(
        self,
        table_id: str,
        rows: list[tuple[Any, ...]],
    ) -> tuple[SceneMutationEvent, ...]:
        events: list[SceneMutationEvent] = []
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

    def _snapshot_locked(self, table_id: str) -> SceneLibraryView:
        events = self._events_locked(table_id)
        entries: dict[str, SceneLibraryEntry] = {}
        active_scene_id: str | None = None
        expected_revision = 1
        for event in events:
            if event.sequence != expected_revision or event.revision != expected_revision:
                raise SceneLibraryStoreCorruptionError(
                    "scene history has a sequence or revision gap"
                )
            if isinstance(event, (SceneCreatedEvent, SceneImportedEvent)):
                scene_id = event.scene.scene_id
                if scene_id in entries:
                    raise SceneLibraryStoreCorruptionError("scene history reuses a scene ID")
                expected_active = active_scene_id is None
                if event.became_active is not expected_active:
                    raise SceneLibraryStoreCorruptionError(
                        "scene creation has inconsistent activation state"
                    )
                entries[scene_id] = SceneLibraryEntry(scene=event.scene, archived=False)
                if event.became_active:
                    active_scene_id = scene_id
            elif isinstance(event, SceneDuplicatedEvent):
                source = entries.get(event.source_scene_id)
                if source is None:
                    raise SceneLibraryStoreCorruptionError(
                        "scene duplicate targets a missing source"
                    )
                scene_id = event.scene.scene_id
                if scene_id in entries:
                    raise SceneLibraryStoreCorruptionError("scene history reuses a scene ID")
                expected_metadata = source.scene.map_metadata.model_copy(
                    update={"name": event.scene.map_metadata.name}
                )
                if event.scene.map_metadata != expected_metadata or event.became_active:
                    raise SceneLibraryStoreCorruptionError(
                        "scene duplicate does not match its source"
                    )
                entries[scene_id] = SceneLibraryEntry(scene=event.scene, archived=False)
            elif isinstance(event, SceneUpdatedEvent):
                scene_id = event.scene.scene_id
                target = entries.get(scene_id)
                if target is None or target.archived:
                    raise SceneLibraryStoreCorruptionError(
                        "scene update targets an unavailable scene"
                    )
                if event.active is not (active_scene_id == scene_id):
                    raise SceneLibraryStoreCorruptionError(
                        "scene update has inconsistent active state"
                    )
                entries[scene_id] = SceneLibraryEntry(
                    scene=event.scene,
                    archived=False,
                )
            elif isinstance(event, SceneActivatedEvent):
                target = entries.get(event.scene_id)
                if target is None or target.archived:
                    raise SceneLibraryStoreCorruptionError(
                        "scene activation targets an unavailable scene"
                    )
                if event.previous_scene_id != active_scene_id or event.scene_id == active_scene_id:
                    raise SceneLibraryStoreCorruptionError(
                        "scene activation has inconsistent previous state"
                    )
                active_scene_id = event.scene_id
            else:
                target = entries.get(event.scene_id)
                if target is None or target.archived:
                    raise SceneLibraryStoreCorruptionError(
                        "scene archive targets an unavailable scene"
                    )
                if event.scene_id == active_scene_id:
                    successor = (
                        entries.get(event.successor_scene_id)
                        if event.successor_scene_id is not None
                        else None
                    )
                    if (
                        successor is None
                        or successor.archived
                        or event.active_scene_id != event.successor_scene_id
                    ):
                        raise SceneLibraryStoreCorruptionError(
                            "active scene archive has an invalid successor"
                        )
                    active_scene_id = event.successor_scene_id
                elif (
                    event.successor_scene_id is not None or event.active_scene_id != active_scene_id
                ):
                    raise SceneLibraryStoreCorruptionError(
                        "inactive scene archive changes active state"
                    )
                entries[event.scene_id] = SceneLibraryEntry(
                    scene=target.scene,
                    archived=True,
                )
            expected_revision += 1

        try:
            return SceneLibraryView(
                schema_version=SCENE_LIBRARY_VIEW_SCHEMA_VERSION,
                table_id=table_id,
                revision=expected_revision - 1,
                active_scene_id=active_scene_id,
                scenes=tuple(entries[key] for key in sorted(entries)),
            )
        except ValidationError as exc:
            raise SceneLibraryStoreCorruptionError(
                "scene history produces an invalid library view"
            ) from exc

    @staticmethod
    def _parse_stored_command(
        encoded: str,
        *,
        table_id: str,
        command_id: str,
        revision: int,
    ) -> SceneMutationCommand:
        try:
            command = parse_scene_command(_decode_json(encoded, field_name="command"))
        except ValidationError as exc:
            raise SceneLibraryStoreCorruptionError(
                "stored scene command violates its contract"
            ) from exc
        if (
            command.table_id != table_id
            or command.command_id != command_id
            or command.expected_revision != revision - 1
            or not _matches_stored_canonical_json(command, encoded)
        ):
            raise SceneLibraryStoreCorruptionError("stored scene command identity is inconsistent")
        return command

    @staticmethod
    def _parse_stored_receipt(
        encoded: str,
        *,
        table_id: str,
        command_id: str,
        sequence: int,
        revision: int,
    ) -> SceneMutationReceipt:
        try:
            receipt = SceneMutationReceipt.model_validate(
                _decode_json(encoded, field_name="receipt")
            )
        except ValidationError as exc:
            raise SceneLibraryStoreCorruptionError(
                "stored scene receipt violates its contract"
            ) from exc
        if (
            receipt.table_id != table_id
            or receipt.command_id != command_id
            or receipt.revision != revision
            or receipt.event.sequence != sequence
            or receipt.event.event_id != f"{table_id}:scene:{sequence}"
            or not _matches_stored_canonical_json(receipt, encoded)
        ):
            raise SceneLibraryStoreCorruptionError("stored scene receipt identity is inconsistent")
        return receipt

    @staticmethod
    def _validate_command_receipt(
        command: SceneMutationCommand,
        receipt: SceneMutationReceipt,
    ) -> None:
        event = receipt.event
        valid = False
        if isinstance(command, SceneCreateCommand):
            valid = isinstance(event, SceneCreatedEvent) and event.scene == command.scene
        elif isinstance(command, SceneImportCommand):
            valid = isinstance(event, SceneImportedEvent) and event.scene == command.bundle.scene
        elif isinstance(command, SceneDuplicateCommand):
            valid = (
                isinstance(event, SceneDuplicatedEvent)
                and event.source_scene_id == command.source_scene_id
                and event.scene.scene_id == command.new_scene_id
                and event.scene.map_metadata.name == command.new_name
            )
        elif isinstance(command, SceneUpdateCommand):
            valid = (
                isinstance(event, SceneUpdatedEvent)
                and event.scene.scene_id == command.scene_id
                and event.scene.map_metadata == command.map_metadata
            )
        elif isinstance(command, SceneActivateCommand):
            valid = isinstance(event, SceneActivatedEvent) and event.scene_id == command.scene_id
        elif isinstance(command, SceneArchiveCommand):
            valid = (
                isinstance(event, SceneArchivedEvent)
                and event.scene_id == command.scene_id
                and event.successor_scene_id == command.successor_scene_id
            )
        if not valid:
            raise SceneLibraryStoreCorruptionError(
                "stored scene command and receipt are inconsistent"
            )

    @staticmethod
    def _validate_store_schema(value: str) -> None:
        if value != SCENE_LIBRARY_STORE_SCHEMA_VERSION:
            raise SceneLibraryStoreSchemaError("stored scene row uses an unsupported schema")


__all__ = [
    "SCENE_LIBRARY_STORE_SCHEMA_VERSION",
    "SQLiteSceneLibrary",
    "SceneActiveArchiveError",
    "SceneAlreadyActiveError",
    "SceneArchivedError",
    "SceneCommandConflictError",
    "SceneExecutionResult",
    "SceneIdConflictError",
    "SceneImportConflictError",
    "SceneLibraryStoreCorruptionError",
    "SceneLibraryStoreError",
    "SceneLibraryStoreSchemaError",
    "SceneNotFoundError",
    "SceneRevisionConflictError",
    "SceneSuccessorError",
]
