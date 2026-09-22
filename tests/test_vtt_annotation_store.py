from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from dnd_sim.vtt.annotation_store import (
    ANNOTATION_COMMAND_SCHEMA_VERSION,
    ANNOTATION_EVENT_SCHEMA_VERSION,
    ANNOTATION_RECEIPT_SCHEMA_VERSION,
    AnnotationCommandConflictError,
    AnnotationCapacityError,
    AnnotationDeleteCommand,
    AnnotationDeleteEvent,
    AnnotationNotFoundError,
    AnnotationPutCommand,
    AnnotationPutEvent,
    AnnotationRevisionConflictError,
    AnnotationStoreCorruptionError,
    AnnotationStoreSchemaError,
    SQLiteAnnotationBoard,
    parse_annotation_command,
    parse_annotation_command_json,
)
from dnd_sim.vtt.annotations import (
    AnnotationPoint,
    CircleTemplateAnnotation,
    ConeTemplateAnnotation,
    PingAnnotation,
)


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _circle(
    annotation_id: str,
    *,
    scene_id: str = "scene-a",
    author_id: str = "gm",
    audience: tuple[str, ...] = ("all",),
    radius_ft: float = 10.0,
) -> CircleTemplateAnnotation:
    return CircleTemplateAnnotation(
        annotation_id=annotation_id,
        scene_id=scene_id,
        author_id=author_id,
        audience=audience,
        center=AnnotationPoint(x_ft=5.0, y_ft=10.0, z_ft=0.0),
        radius_ft=radius_ft,
    )


def _put(
    command_id: str,
    *,
    expected_revision: int,
    annotation: CircleTemplateAnnotation | ConeTemplateAnnotation | PingAnnotation,
    table_id: str = "table-a",
) -> AnnotationPutCommand:
    return AnnotationPutCommand(
        table_id=table_id,
        command_id=command_id,
        expected_revision=expected_revision,
        annotation=annotation,
    )


def test_command_contracts_are_strict_versioned_and_never_accept_pixels() -> None:
    command = _put("put-1", expected_revision=0, annotation=_circle("blast"))

    assert command.schema_version == ANNOTATION_COMMAND_SCHEMA_VERSION
    assert parse_annotation_command(command.model_dump(mode="json")) == command
    assert parse_annotation_command_json(command.model_dump_json()) == command

    wire = command.model_dump(mode="json")
    with pytest.raises(ValidationError):
        parse_annotation_command({**wire, "expected_revision": "0"})

    annotation = dict(wire["annotation"])
    annotation["center"] = {**annotation["center"], "x_px": 100.0}
    with pytest.raises(ValidationError):
        parse_annotation_command({**wire, "annotation": annotation})

    with pytest.raises(ValidationError):
        parse_annotation_command({**wire, "schema_version": "vtt.annotation_command.v999"})


def test_put_update_delete_form_an_append_only_monotonic_history() -> None:
    with _connection() as connection:
        board = SQLiteAnnotationBoard(connection)
        created = board.execute(_put("put-1", expected_revision=0, annotation=_circle("blast")))
        replacement = ConeTemplateAnnotation(
            annotation_id="blast",
            scene_id="scene-b",
            author_id="gm",
            audience=("player-1",),
            origin=AnnotationPoint(x_ft=0.0, y_ft=0.0, z_ft=0.0),
            direction_degrees=90.0,
            length_ft=30.0,
            angle_degrees=60.0,
        )
        updated = board.execute(_put("put-2", expected_revision=1, annotation=replacement))
        assert board.annotations("table-a") == (replacement,)
        deleted = board.execute(
            AnnotationDeleteCommand(
                table_id="table-a",
                command_id="delete-1",
                expected_revision=2,
                annotation_id="blast",
            )
        )

        assert created.replayed is False
        assert created.receipt.schema_version == ANNOTATION_RECEIPT_SCHEMA_VERSION
        assert isinstance(created.receipt.event, AnnotationPutEvent)
        assert isinstance(created.receipt.event.annotation, CircleTemplateAnnotation)
        assert isinstance(updated.receipt.event, AnnotationPutEvent)
        assert updated.receipt.event.annotation == replacement
        assert isinstance(deleted.receipt.event, AnnotationDeleteEvent)
        assert deleted.receipt.event.scene_id == "scene-b"
        assert deleted.receipt.event.audience == ("player-1",)

        events = board.events_after("table-a", 0)
        assert [event.schema_version for event in events] == [
            ANNOTATION_EVENT_SCHEMA_VERSION,
            ANNOTATION_EVENT_SCHEMA_VERSION,
            ANNOTATION_EVENT_SCHEMA_VERSION,
        ]
        assert [event.sequence for event in events] == [1, 2, 3]
        assert [event.revision for event in events] == [1, 2, 3]
        assert [event.sequence for event in board.events_after("table-a", 1)] == [2, 3]
        assert board.events_after("table-a", 3) == ()
        with pytest.raises(ValueError, match="non-negative integer"):
            board.events_after("table-a", True)
        assert board.revision("table-a") == 3
        assert board.annotations("table-a") == ()


def test_stale_revision_and_missing_delete_reject_without_mutation() -> None:
    with _connection() as connection:
        board = SQLiteAnnotationBoard(connection)
        board.execute(_put("put-1", expected_revision=0, annotation=_circle("blast")))

        with pytest.raises(AnnotationRevisionConflictError, match="expected revision 1"):
            board.execute(
                _put(
                    "put-stale",
                    expected_revision=0,
                    annotation=_circle("other"),
                )
            )
        with pytest.raises(AnnotationNotFoundError, match="missing"):
            board.execute(
                AnnotationDeleteCommand(
                    table_id="table-a",
                    command_id="delete-missing",
                    expected_revision=1,
                    annotation_id="missing",
                )
            )

        assert board.revision("table-a") == 1
        assert [item.annotation_id for item in board.annotations("table-a")] == ["blast"]
        assert [event.command_id for event in board.events_after("table-a", 0)] == ["put-1"]


def test_active_annotation_capacity_is_bounded_without_blocking_update_delete_or_retry() -> None:
    with _connection() as connection:
        board = SQLiteAnnotationBoard(connection, max_active_annotations=2)
        first = _put("put-1", expected_revision=0, annotation=_circle("first"))
        board.execute(first)
        board.execute(_put("put-2", expected_revision=1, annotation=_circle("second")))

        with pytest.raises(AnnotationCapacityError, match="active annotation capacity"):
            board.execute(_put("put-3", expected_revision=2, annotation=_circle("third")))

        assert board.execute(first).replayed is True
        board.execute(
            _put(
                "update-2",
                expected_revision=2,
                annotation=_circle("second", radius_ft=15.0),
            )
        )
        board.execute(
            AnnotationDeleteCommand(
                table_id="table-a",
                command_id="delete-1",
                expected_revision=3,
                annotation_id="first",
            )
        )
        board.execute(_put("put-4", expected_revision=4, annotation=_circle("third")))

        assert board.revision("table-a") == 5
        assert [item.annotation_id for item in board.annotations("table-a")] == [
            "second",
            "third",
        ]


def test_exact_retry_returns_original_receipt_and_conflicting_reuse_is_rejected() -> None:
    with _connection() as connection:
        board = SQLiteAnnotationBoard(connection)
        command = _put("put-1", expected_revision=0, annotation=_circle("blast"))

        original = board.execute(command)
        retried = board.execute(parse_annotation_command(command.model_dump(mode="json")))

        assert retried.replayed is True
        assert retried.receipt == original.receipt
        assert len(board.events_after("table-a", 0)) == 1

        with pytest.raises(AnnotationCommandConflictError, match="put-1"):
            board.execute(
                _put(
                    "put-1",
                    expected_revision=0,
                    annotation=_circle("blast", radius_ft=15.0),
                )
            )

        assert board.revision("table-a") == 1
        assert board.annotations("table-a") == (_circle("blast"),)


def test_tables_are_isolated_and_puts_bind_annotations_to_the_command_table() -> None:
    with _connection() as connection:
        board = SQLiteAnnotationBoard(connection)
        board.execute(
            _put(
                "put-shared",
                table_id="table-a",
                expected_revision=0,
                annotation=_circle("shared", radius_ft=5.0),
            )
        )
        board.execute(
            _put(
                "put-shared",
                table_id="table-b",
                expected_revision=0,
                annotation=_circle("shared", radius_ft=20.0),
            )
        )

        assert board.revision("table-a") == 1
        assert board.revision("table-b") == 1
        assert board.annotations("table-a")[0].radius_ft == 5.0
        assert board.annotations("table-b")[0].radius_ft == 20.0
        assert board.events_after("table-a", 0)[0].table_id == "table-a"
        assert board.events_after("table-b", 0)[0].table_id == "table-b"


def test_restart_recovers_latest_projection_and_audience_filtering(tmp_path: Path) -> None:
    database_path = str(tmp_path / "annotations.sqlite3")
    first_connection = sqlite3.connect(database_path)
    first = SQLiteAnnotationBoard(first_connection)
    first.execute(_put("put-public", expected_revision=0, annotation=_circle("public")))
    first.execute(
        _put(
            "put-private",
            expected_revision=1,
            annotation=_circle(
                "private",
                audience=("player-1",),
                author_id="player-1",
            ),
        )
    )
    first.execute(
        _put(
            "put-other-scene",
            expected_revision=2,
            annotation=_circle("other-scene", scene_id="scene-b"),
        )
    )
    first_connection.close()

    second_connection = sqlite3.connect(database_path)
    try:
        recovered = SQLiteAnnotationBoard(second_connection)

        assert recovered.revision("table-a") == 3
        assert [
            item.annotation_id
            for item in recovered.project("table-a", scene_id="scene-a", recipient_id=None)
        ] == ["public"]
        assert [
            item.annotation_id
            for item in recovered.project("table-a", scene_id="scene-a", recipient_id="player-1")
        ] == ["private", "public"]
        assert [
            item.annotation_id
            for item in recovered.project("table-a", scene_id="scene-b", recipient_id="player-1")
        ] == ["other-scene"]
    finally:
        second_connection.close()


def test_tampered_stored_payload_is_rejected_instead_of_becoming_projection() -> None:
    with _connection() as connection:
        board = SQLiteAnnotationBoard(connection)
        board.execute(_put("put-1", expected_revision=0, annotation=_circle("blast")))
        encoded = connection.execute(
            "SELECT receipt_json FROM _vtt_annotation_event_log"
        ).fetchone()[0]
        receipt = json.loads(encoded)
        receipt["event"]["annotation"]["radius_ft"] = 15.0
        connection.execute(
            "UPDATE _vtt_annotation_event_log SET receipt_json = ?",
            (json.dumps(receipt),),
        )
        connection.commit()

        with pytest.raises(AnnotationStoreCorruptionError, match="annotation does not match"):
            board.annotations("table-a")


def test_unknown_schema_aborts_transactional_initialization() -> None:
    with _connection() as connection:
        connection.execute("""
            CREATE TABLE _vtt_annotation_store_metadata (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                schema_version TEXT NOT NULL
            )
            """)
        connection.execute(
            """
            INSERT INTO _vtt_annotation_store_metadata (singleton, schema_version)
            VALUES (1, ?)
            """,
            ("vtt.annotation_store.v999",),
        )
        connection.commit()

        with pytest.raises(AnnotationStoreSchemaError, match="v999"):
            SQLiteAnnotationBoard(connection)

        event_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("_vtt_annotation_event_log",),
        ).fetchone()
        assert event_table is None


def test_insert_failure_rolls_back_revision_event_and_projection() -> None:
    with _connection() as connection:
        board = SQLiteAnnotationBoard(connection)
        connection.execute("""
            CREATE TRIGGER reject_annotation_test_command
            BEFORE INSERT ON _vtt_annotation_event_log
            WHEN NEW.command_id = 'reject-me'
            BEGIN
                SELECT RAISE(ABORT, 'forced annotation failure');
            END
            """)
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError, match="forced annotation failure"):
            board.execute(_put("reject-me", expected_revision=0, annotation=_circle("blast")))

        assert board.revision("table-a") == 0
        assert board.events_after("table-a", 0) == ()
        assert board.annotations("table-a") == ()
