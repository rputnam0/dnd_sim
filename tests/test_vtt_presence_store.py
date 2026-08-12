from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from dnd_sim.vtt.participants import (
    PARTICIPANT_SCHEMA_VERSION,
    ROSTER_SCHEMA_VERSION,
    TableParticipant,
    TableRoster,
)
from dnd_sim.vtt.presence_contracts import (
    PRESENCE_COMMAND_SCHEMA_VERSION,
    PresenceHeartbeatCommand,
    PresenceHeartbeatEvent,
    PresenceView,
)
from dnd_sim.vtt.presence_store import (
    PRESENCE_STORE_SCHEMA_VERSION,
    PresenceCommandConflictError,
    PresenceParticipantNotFoundError,
    PresenceRevisionConflictError,
    PresenceStoreCorruptionError,
    PresenceStoreSchemaError,
    PresenceTableMismatchError,
    PresenceTimeRegressionError,
    SQLitePresenceStore,
)

TABLE_ID = "presence-table"


def _participant(participant_id: str, *, display_name: str, role: str) -> TableParticipant:
    return TableParticipant(
        schema_version=PARTICIPANT_SCHEMA_VERSION,
        participant_id=participant_id,
        display_name=display_name,
        role=role,
        owned_actor_ids=(),
    )


def _roster() -> TableRoster:
    return TableRoster(
        schema_version=ROSTER_SCHEMA_VERSION,
        table_id=TABLE_ID,
        participants=(
            _participant("gm", display_name="Game Master", role="gm"),
            _participant("player-1", display_name="Vela", role="player"),
            _participant("spectator", display_name="Observer", role="spectator"),
        ),
    )


def _heartbeat(
    command_id: str,
    *,
    participant_id: str = "player-1",
    client_id: str = "client-a",
    expected_revision: int = 0,
    table_id: str = TABLE_ID,
) -> PresenceHeartbeatCommand:
    return PresenceHeartbeatCommand(
        schema_version=PRESENCE_COMMAND_SCHEMA_VERSION,
        table_id=table_id,
        command_id=command_id,
        expected_revision=expected_revision,
        participant_id=participant_id,
        client_id=client_id,
    )


def _store(connection: sqlite3.Connection) -> SQLitePresenceStore:
    return SQLitePresenceStore(
        connection,
        roster=_roster(),
        away_after_ms=10,
        offline_after_ms=30,
    )


def test_presence_contracts_are_strict_and_safe() -> None:
    command = _heartbeat("heartbeat-1")
    with pytest.raises(ValidationError):
        PresenceHeartbeatCommand.model_validate(
            {**command.model_dump(mode="json"), "bearer_token": "forbidden"}
        )
    with pytest.raises(ValidationError):
        PresenceHeartbeatCommand.model_validate(
            {**command.model_dump(mode="json"), "expected_revision": True}
        )
    event = PresenceHeartbeatEvent(
        table_id=TABLE_ID,
        event_id=f"{TABLE_ID}:presence:1",
        sequence=1,
        revision=1,
        command_id=command.command_id,
        participant_id=command.participant_id,
        client_id=command.client_id,
        observed_at_ms=100,
    )
    with pytest.raises(ValidationError, match="sequence must match revision"):
        PresenceHeartbeatEvent.model_validate({**event.model_dump(mode="json"), "revision": 2})


def test_view_derives_online_away_and_offline_across_multiple_clients() -> None:
    connection = sqlite3.connect(":memory:")
    store = _store(connection)
    assert [
        record.status for record in store.view(viewer_id="gm", evaluated_at_ms=100).records
    ] == [
        "offline",
        "offline",
        "offline",
    ]
    store.heartbeat(_heartbeat("player-a"), observed_at_ms=100)
    store.heartbeat(
        _heartbeat("player-b", client_id="client-b", expected_revision=1),
        observed_at_ms=120,
    )

    assert store.view(viewer_id="spectator", evaluated_at_ms=129).records[1].status == "online"
    assert store.view(viewer_id="spectator", evaluated_at_ms=130).records[1].status == "away"
    assert store.view(viewer_id="spectator", evaluated_at_ms=150).records[1].status == "offline"
    encoded = json.dumps(store.view(viewer_id="gm", evaluated_at_ms=129).model_dump(mode="json"))
    assert "client-a" not in encoded
    assert "client-b" not in encoded
    assert "observed_at" not in encoded
    assert "owned_actor_ids" not in encoded
    connection.close()


def test_heartbeat_is_optimistic_idempotent_and_principal_scoped() -> None:
    connection = sqlite3.connect(":memory:")
    store = _store(connection)
    command = _heartbeat("heartbeat-1")
    first = store.heartbeat(command, observed_at_ms=100)
    replay = store.heartbeat(command, observed_at_ms=999)

    assert replay.replayed is True
    assert replay.receipt == first.receipt
    assert replay.receipt.event.observed_at_ms == 100
    with pytest.raises(PresenceCommandConflictError):
        store.heartbeat(
            command.model_copy(update={"client_id": "different"}),
            observed_at_ms=101,
        )
    with pytest.raises(PresenceRevisionConflictError) as stale_error:
        store.heartbeat(
            _heartbeat("stale", expected_revision=0),
            observed_at_ms=101,
        )
    assert stale_error.value.current_revision == 1
    assert stale_error.value.expected_revision == 0
    with pytest.raises(PresenceTableMismatchError):
        store.heartbeat(_heartbeat("wrong-table", table_id="other"), observed_at_ms=101)
    with pytest.raises(PresenceParticipantNotFoundError):
        store.heartbeat(
            _heartbeat("unknown", participant_id="unknown", expected_revision=1),
            observed_at_ms=101,
        )
    connection.close()


def test_presence_rejects_time_regression_and_accepts_equal_server_time() -> None:
    connection = sqlite3.connect(":memory:")
    store = _store(connection)
    store.heartbeat(_heartbeat("first"), observed_at_ms=100)
    with pytest.raises(PresenceTimeRegressionError):
        store.heartbeat(_heartbeat("regressed", expected_revision=1), observed_at_ms=99)
    with pytest.raises(PresenceTimeRegressionError):
        store.view(viewer_id="gm", evaluated_at_ms=99)
    store.heartbeat(_heartbeat("same-time", expected_revision=1), observed_at_ms=100)
    assert store.revision == 2
    connection.close()


def test_presence_history_survives_restart_and_exact_retry(tmp_path: Path) -> None:
    database_path = tmp_path / "presence.sqlite3"
    command = _heartbeat("durable-heartbeat")
    first_connection = sqlite3.connect(database_path)
    original = _store(first_connection).heartbeat(command, observed_at_ms=1_000)
    first_connection.close()

    restored_connection = sqlite3.connect(database_path)
    restored_store = _store(restored_connection)
    assert restored_store.view(viewer_id="gm", evaluated_at_ms=1_009).records[1].status == "online"
    replay = restored_store.heartbeat(command, observed_at_ms=2_000)
    assert replay.replayed is True
    assert replay.receipt == original.receipt
    assert restored_store.events_after(viewer_id="gm", sequence=0) == (original.receipt.event,)
    restored_connection.close()


def test_presence_event_delta_queries_only_the_requested_sqlite_tail() -> None:
    connection = sqlite3.connect(":memory:")
    store = _store(connection)
    store.heartbeat(_heartbeat("first"), observed_at_ms=100)
    store.heartbeat(_heartbeat("second", expected_revision=1), observed_at_ms=101)
    traced: list[str] = []
    connection.set_trace_callback(traced.append)
    events = store.events_after(viewer_id="gm", sequence=1)
    connection.set_trace_callback(None)

    assert [event.sequence for event in events] == [2]
    queries = [
        " ".join(statement.split()).lower()
        for statement in traced
        if "_vtt_presence_event_log" in statement.lower()
        and statement.lstrip().upper().startswith("SELECT")
    ]
    assert len(queries) == 1
    assert "sequence > 1" in queries[0]
    connection.close()


def test_presence_store_detects_schema_and_history_corruption() -> None:
    connection = sqlite3.connect(":memory:")
    store = _store(connection)
    connection.execute("UPDATE _vtt_presence_store_metadata SET schema_version = 'future'")
    connection.commit()
    with pytest.raises(PresenceStoreSchemaError):
        store.view(viewer_id="gm", evaluated_at_ms=0)
    connection.close()

    corrupt_connection = sqlite3.connect(":memory:")
    corrupt_store = _store(corrupt_connection)
    corrupt_store.heartbeat(_heartbeat("first"), observed_at_ms=100)
    receipt_row = corrupt_connection.execute(
        "SELECT receipt_json FROM _vtt_presence_event_log"
    ).fetchone()
    assert receipt_row is not None
    receipt = json.loads(str(receipt_row[0]))
    receipt["event"]["client_id"] = "forged-client"
    corrupt_connection.execute(
        "UPDATE _vtt_presence_event_log SET receipt_json = ?",
        (json.dumps(receipt),),
    )
    corrupt_connection.commit()
    with pytest.raises(PresenceStoreCorruptionError):
        corrupt_store.view(viewer_id="gm", evaluated_at_ms=100)
    corrupt_connection.close()


def test_presence_view_contract_rejects_internal_fields() -> None:
    connection = sqlite3.connect(":memory:")
    view = _store(connection).view(viewer_id="gm", evaluated_at_ms=0)
    with pytest.raises(ValidationError):
        PresenceView.model_validate({**view.model_dump(mode="json"), "client_id": "not-public"})
    assert PRESENCE_STORE_SCHEMA_VERSION == "vtt.presence_store.v1"
    connection.close()
