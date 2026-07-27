from __future__ import annotations

import json
import sqlite3

import pytest

from dnd_sim.vtt import (
    EVENT_STORE_SCHEMA_VERSION,
    CommandConflictError,
    EventStoreSchemaError,
    SQLiteSessionEventStore,
)


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _command(command_id: str, *, amount: int = 1) -> dict[str, object]:
    return {
        "schema_version": "vtt.command.v1",
        "command_id": command_id,
        "kind": "counter.add",
        "payload": {"z": 2, "amount": amount},
    }


def _receipt(command_id: str, *, revision: int) -> dict[str, object]:
    return {
        "schema_version": "vtt.receipt.v1",
        "command_id": command_id,
        "revision": revision,
        "events": [{"sequence": revision, "kind": "counter.changed"}],
    }


def _snapshot(*, revision: int, total: int) -> dict[str, object]:
    return {
        "schema_version": "engine.snapshot.v1",
        "revision": revision,
        "state": {"total": total, "a": 1},
    }


def test_append_commit_persists_canonical_snapshot_and_command_atomically() -> None:
    with _connection() as connection:
        store = SQLiteSessionEventStore(connection)

        result = store.append_commit(
            session_id="session-1",
            command_id="command-1",
            command=_command("command-1"),
            receipt=_receipt("command-1", revision=1),
            snapshot=_snapshot(revision=1, total=4),
        )

        assert result.replayed is False
        assert result.record.schema_version == EVENT_STORE_SCHEMA_VERSION
        assert result.record.sequence == 1

        latest = store.load_latest_snapshot("session-1")
        assert latest is not None
        assert latest.schema_version == EVENT_STORE_SCHEMA_VERSION
        assert latest.last_command_sequence == 1
        assert latest.snapshot == _snapshot(revision=1, total=4)

        records = store.load_commands("session-1")
        assert len(records) == 1
        assert records[0].command == _command("command-1")
        assert records[0].receipt == _receipt("command-1", revision=1)

        stored_command_json = connection.execute(
            "SELECT command_json FROM vtt_committed_commands"
        ).fetchone()[0]
        assert stored_command_json == (
            '{"command_id":"command-1","kind":"counter.add",'
            '"payload":{"amount":1,"z":2},"schema_version":"vtt.command.v1"}'
        )


def test_commands_are_ordered_per_session_and_sessions_are_isolated() -> None:
    with _connection() as connection:
        store = SQLiteSessionEventStore(connection)

        store.append_commit(
            session_id="session-1",
            command_id="command-2",
            command=_command("command-2", amount=2),
            receipt=_receipt("command-2", revision=1),
            snapshot=_snapshot(revision=1, total=2),
        )
        store.append_commit(
            session_id="session-2",
            command_id="command-a",
            command=_command("command-a", amount=7),
            receipt=_receipt("command-a", revision=1),
            snapshot=_snapshot(revision=1, total=7),
        )
        store.append_commit(
            session_id="session-1",
            command_id="command-1",
            command=_command("command-1", amount=1),
            receipt=_receipt("command-1", revision=2),
            snapshot=_snapshot(revision=2, total=3),
        )

        session_one = store.load_commands("session-1")
        session_two = store.load_commands("session-2")

        assert [(row.sequence, row.command_id) for row in session_one] == [
            (1, "command-2"),
            (2, "command-1"),
        ]
        assert [(row.sequence, row.command_id) for row in session_two] == [(1, "command-a")]

        stored_snapshots = connection.execute(
            """
            SELECT sequence, snapshot_json
            FROM vtt_committed_commands
            WHERE session_id = ?
            ORDER BY sequence ASC
            """,
            ("session-1",),
        ).fetchall()
        assert [(row[0], json.loads(row[1])) for row in stored_snapshots] == [
            (1, _snapshot(revision=1, total=2)),
            (2, _snapshot(revision=2, total=3)),
        ]


def test_identical_retry_returns_original_result_without_replacing_latest_snapshot() -> None:
    with _connection() as connection:
        store = SQLiteSessionEventStore(connection)
        first_command = _command("command-1")
        first_receipt = _receipt("command-1", revision=1)
        first_snapshot = _snapshot(revision=1, total=4)

        original = store.append_commit(
            session_id="session-1",
            command_id="command-1",
            command=first_command,
            receipt=first_receipt,
            snapshot=first_snapshot,
        )
        store.append_commit(
            session_id="session-1",
            command_id="command-2",
            command=_command("command-2"),
            receipt=_receipt("command-2", revision=2),
            snapshot=_snapshot(revision=2, total=8),
        )

        retried = store.append_commit(
            session_id="session-1",
            command_id="command-1",
            command={
                "payload": {"amount": 1, "z": 2},
                "kind": "counter.add",
                "command_id": "command-1",
                "schema_version": "vtt.command.v1",
            },
            receipt=_receipt("command-1", revision=999),
            snapshot=_snapshot(revision=999, total=999),
        )

        assert retried.replayed is True
        assert retried.record == original.record
        assert len(store.load_commands("session-1")) == 2
        latest = store.load_latest_snapshot("session-1")
        assert latest is not None
        assert latest.snapshot == _snapshot(revision=2, total=8)


def test_same_command_id_with_different_command_is_rejected_without_mutation() -> None:
    with _connection() as connection:
        store = SQLiteSessionEventStore(connection)
        store.append_commit(
            session_id="session-1",
            command_id="command-1",
            command=_command("command-1", amount=1),
            receipt=_receipt("command-1", revision=1),
            snapshot=_snapshot(revision=1, total=4),
        )

        with pytest.raises(CommandConflictError, match="command-1"):
            store.append_commit(
                session_id="session-1",
                command_id="command-1",
                command=_command("command-1", amount=99),
                receipt=_receipt("command-1", revision=2),
                snapshot=_snapshot(revision=2, total=103),
            )

        assert len(store.load_commands("session-1")) == 1
        latest = store.load_latest_snapshot("session-1")
        assert latest is not None
        assert latest.snapshot == _snapshot(revision=1, total=4)


def test_command_insert_failure_rolls_back_the_session_snapshot() -> None:
    with _connection() as connection:
        store = SQLiteSessionEventStore(connection)
        connection.execute("""
            CREATE TRIGGER reject_test_command
            BEFORE INSERT ON vtt_committed_commands
            WHEN NEW.command_id = 'reject-me'
            BEGIN
                SELECT RAISE(ABORT, 'forced command failure');
            END
            """)
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError, match="forced command failure"):
            store.append_commit(
                session_id="session-1",
                command_id="reject-me",
                command=_command("reject-me"),
                receipt=_receipt("reject-me", revision=1),
                snapshot=_snapshot(revision=1, total=4),
            )

        assert store.load_latest_snapshot("session-1") is None
        assert store.load_commands("session-1") == ()


def test_store_rejects_unknown_on_disk_schema_version() -> None:
    with _connection() as connection:
        connection.execute("""
            CREATE TABLE vtt_event_store_metadata (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                schema_version TEXT NOT NULL
            )
            """)
        connection.execute(
            "INSERT INTO vtt_event_store_metadata (singleton, schema_version) VALUES (1, ?)",
            ("vtt.event_store.v999",),
        )
        connection.commit()

        with pytest.raises(EventStoreSchemaError, match="vtt.event_store.v999"):
            SQLiteSessionEventStore(connection)


def test_non_json_commit_payload_is_rejected_before_any_write() -> None:
    with _connection() as connection:
        store = SQLiteSessionEventStore(connection)

        with pytest.raises(ValueError, match="snapshot"):
            store.append_commit(
                session_id="session-1",
                command_id="command-1",
                command=_command("command-1"),
                receipt=_receipt("command-1", revision=1),
                snapshot={"not_json": {"a", "set"}},
            )

        assert store.load_latest_snapshot("session-1") is None
        assert store.load_commands("session-1") == ()


def test_embedded_session_and_command_identity_must_match_store_keys() -> None:
    with _connection() as connection:
        store = SQLiteSessionEventStore(connection)
        command = {**_command("command-1"), "session_id": "session-1"}
        receipt = {
            **_receipt("wrong-command", revision=1),
            "session_id": "session-1",
        }
        snapshot = {
            **_snapshot(revision=1, total=4),
            "session_id": "session-1",
        }

        with pytest.raises(ValueError, match="receipt.command_id"):
            store.append_commit(
                session_id="session-1",
                command_id="command-1",
                command=command,
                receipt=receipt,
                snapshot=snapshot,
            )

        assert store.load_commands("session-1") == ()
