from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dnd_sim.interactive.dnd_contracts import DECLARATION_COMMAND_KIND
from dnd_sim.interactive.dnd_encounter_driver import START_ENCOUNTER_COMMAND_KIND
from dnd_sim.vtt import (
    VTT_COMMAND_SCHEMA_VERSION,
    VTT_COMMIT_RESPONSE_SCHEMA_VERSION,
    VTT_SESSION_VIEW_SCHEMA_VERSION,
    VTTCommand,
    create_solo_table_app,
)
from dnd_sim.vtt import solo_app


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _wire_command(
    *,
    command_id: str,
    session_id: str,
    actor_id: str | None,
    expected_revision: int,
    mode: str,
    kind: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return VTTCommand(
        schema_version=VTT_COMMAND_SCHEMA_VERSION,
        command_id=command_id,
        session_id=session_id,
        actor_id=actor_id,
        expected_revision=expected_revision,
        mode=mode,
        kind=kind,
        payload=payload,
        intent_metadata={},
    ).model_dump(mode="json")


def _winning_declaration_payload() -> dict[str, Any]:
    return {
        "movement_path": [
            [12.5, 12.5, 0.0],
            [17.5, 12.5, 0.0],
        ],
        "action": {
            "action_name": "Lattice Lance",
            "targets": [{"actor_id": "hushglass_sentry"}],
            "resource_spend": {"amounts": {}},
            "spell_slot_level": None,
            "rationale": {},
        },
        "bonus_action": None,
        "reaction_policy": {"mode": "auto", "rationale": {}},
        "ready": None,
        "rationale": {},
    }


def _public_ping_request(
    *,
    session_id: str,
    command_id: str,
    annotation_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    return {
        "schema_version": "vtt.annotation_request.v1",
        "session_id": session_id,
        "command": {
            "schema_version": "vtt.annotation_command.v1",
            "table_id": session_id,
            "command_id": command_id,
            "expected_revision": expected_revision,
            "command_type": "put",
            "annotation": {
                "schema_version": "vtt.annotation.v1",
                "annotation_id": annotation_id,
                "scene_id": "echo-vault",
                "author_id": "untrusted-browser-author",
                "audience": ["all"],
                "annotation_type": "ping",
                # JSON.stringify emits whole-valued JavaScript numbers without
                # a decimal suffix. The HTTP boundary must still accept them.
                "position": {"x_ft": 20, "y_ft": 15, "z_ft": 0},
                "duration_ms": 1_500,
            },
        },
    }


def _public_chat_request(
    *,
    session_id: str,
    command_id: str,
    message_id: str,
    expected_revision: int,
    text: str,
) -> dict[str, Any]:
    return {
        "schema_version": "vtt.chat_request.v1",
        "session_id": session_id,
        "command": {
            "schema_version": "vtt.chat_command.v1",
            "table_id": session_id,
            "command_id": command_id,
            "expected_revision": expected_revision,
            "command_type": "post",
            "message": {
                "schema_version": "vtt.chat_message.v1",
                "message_id": message_id,
                "author_id": "untrusted-browser-author",
                "audience": ["all"],
                "text": text,
            },
        },
    }


def _stored_command_count(database_path: Path) -> int:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM vtt_committed_commands").fetchone()
    assert row is not None
    return int(row[0])


def _stored_chat_event_count(database_path: Path) -> int:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM _vtt_chat_event_log").fetchone()
    assert row is not None
    return int(row[0])


def _complete_fresh_solo_table(database_path: Path) -> dict[str, Any]:
    """Play the canonical encounter once and return its public terminal view."""

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as client:
        initial = client.get("/api/v1/session")
        assert initial.status_code == 200
        session_id = initial.json()["session_id"]

        started = client.post(
            "/api/v1/commands",
            json=_wire_command(
                command_id="fresh-replay-start",
                session_id=session_id,
                actor_id=None,
                expected_revision=0,
                mode="admin",
                kind=START_ENCOUNTER_COMMAND_KIND,
                payload={},
            ),
        )
        assert started.status_code == 200

        completed = client.post(
            "/api/v1/commands",
            json=_wire_command(
                command_id="fresh-replay-winning-turn",
                session_id=session_id,
                actor_id="vela_quill",
                expected_revision=1,
                mode="commit",
                kind=DECLARATION_COMMAND_KIND,
                payload=_winning_declaration_payload(),
            ),
        )
        assert completed.status_code == 200

        terminal = client.get("/api/v1/session")
        assert terminal.status_code == 200
        return terminal.json()


def test_solo_table_app_restarts_terminal_session_and_replays_exact_command(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "echo-vault.sqlite3"
    first_app = create_solo_table_app(database_path)

    with TestClient(first_app, raise_server_exceptions=False) as first_client:
        unstarted_response = first_client.get("/api/v1/session")
        assert unstarted_response.status_code == 200
        unstarted = unstarted_response.json()
        assert unstarted["schema_version"] == VTT_SESSION_VIEW_SCHEMA_VERSION
        assert unstarted["revision"] == 0
        assert unstarted["scene"]["scene_id"] == "echo-vault"
        assert unstarted["projection"]["phase"] == "unstarted"
        assert unstarted["projection"]["outcome"] is None
        session_id = unstarted["session_id"]

        start_command = _wire_command(
            command_id="start-echo-vault",
            session_id=session_id,
            actor_id=None,
            expected_revision=0,
            mode="admin",
            kind=START_ENCOUNTER_COMMAND_KIND,
            payload={},
        )
        started_response = first_client.post(
            "/api/v1/commands",
            json=start_command,
        )
        assert started_response.status_code == 200
        assert started_response.json()["schema_version"] == VTT_COMMIT_RESPONSE_SCHEMA_VERSION
        assert started_response.json()["revision"] == 1

        winning_command = _wire_command(
            command_id="vela-winning-turn",
            session_id=session_id,
            actor_id="vela_quill",
            expected_revision=1,
            mode="commit",
            kind=DECLARATION_COMMAND_KIND,
            payload=_winning_declaration_payload(),
        )
        winning_response = first_client.post(
            "/api/v1/commands",
            json=winning_command,
        )
        assert winning_response.status_code == 200
        assert winning_response.json()["schema_version"] == VTT_COMMIT_RESPONSE_SCHEMA_VERSION
        assert winning_response.json()["revision"] == 2
        assert winning_response.json()["events"][-1]["payload"]["outcome"] == "party_victory"

        terminal_response = first_client.get("/api/v1/session")
        assert terminal_response.status_code == 200
        terminal = terminal_response.json()
        assert terminal["revision"] == 2
        assert terminal["projection"]["phase"] == "terminal"
        assert terminal["projection"]["outcome"] == "party_victory"
        terminal_json = _canonical_json(terminal)

    assert _stored_command_count(database_path) == 2

    second_app = create_solo_table_app(database_path)
    with TestClient(second_app, raise_server_exceptions=False) as second_client:
        restored_response = second_client.get("/api/v1/session")
        assert restored_response.status_code == 200
        assert _canonical_json(restored_response.json()) == terminal_json

        replay_response = second_client.post(
            "/api/v1/commands",
            json=winning_command,
        )
        assert replay_response.status_code == 200
        assert replay_response.json()["replayed"] is True
        assert replay_response.json()["revision"] == 2

        after_retry_response = second_client.get("/api/v1/session")
        assert after_retry_response.status_code == 200
        assert _canonical_json(after_retry_response.json()) == terminal_json

    assert _stored_command_count(database_path) == 2


def test_solo_table_app_uses_a_fresh_fixture_for_a_separate_database(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "fresh-echo-vault.sqlite3"

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as client:
        response = client.get("/api/v1/session")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == VTT_SESSION_VIEW_SCHEMA_VERSION
    assert payload["revision"] == 0
    assert payload["projection"]["phase"] == "unstarted"
    assert payload["projection"]["outcome"] is None
    assert _stored_command_count(database_path) == 0


def test_solo_table_replay_matches_on_two_independent_fresh_databases(
    tmp_path: Path,
) -> None:
    first = _complete_fresh_solo_table(tmp_path / "first-replay.sqlite3")
    second = _complete_fresh_solo_table(tmp_path / "second-replay.sqlite3")

    assert first["projection"]["phase"] == "terminal"
    assert first["projection"]["outcome"] == "party_victory"
    assert _canonical_json(second) == _canonical_json(first)
    assert _stored_command_count(tmp_path / "first-replay.sqlite3") == 2
    assert _stored_command_count(tmp_path / "second-replay.sqlite3") == 2


def test_solo_table_persists_browser_ping_across_restart_and_exact_retry(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "solo-annotations.sqlite3"
    request = _public_ping_request(
        session_id="echo-vault-session",
        command_id="browser-ping-once",
        annotation_id="browser-ping",
        expected_revision=0,
    )

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as first_client:
        empty = first_client.get("/api/v1/annotations")
        assert empty.status_code == 200
        assert empty.json() == {
            "schema_version": "vtt.annotations_view.v1",
            "session_id": "echo-vault-session",
            "table_id": "echo-vault-session",
            "scene_id": "echo-vault",
            "revision": 0,
            "annotations": [],
        }

        created = first_client.post("/api/v1/annotation-commands", json=request)
        assert created.status_code == 200
        assert created.json()["replayed"] is False
        assert created.json()["receipt"]["revision"] == 1
        stored_annotation = created.json()["receipt"]["event"]["annotation"]
        assert stored_annotation["author_id"] == "local"
        assert stored_annotation["position"] == {
            "x_ft": 20.0,
            "y_ft": 15.0,
            "z_ft": 0.0,
        }

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as restored_client:
        restored = restored_client.get("/api/v1/annotations")
        assert restored.status_code == 200
        assert restored.json()["revision"] == 1
        assert restored.json()["annotations"] == [stored_annotation]

        replayed = restored_client.post("/api/v1/annotation-commands", json=request)
        assert replayed.status_code == 200
        assert replayed.json()["replayed"] is True
        assert replayed.json()["receipt"] == created.json()["receipt"]


def test_solo_table_persists_open_local_plain_text_chat_across_restart_and_retry(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "solo-chat.sqlite3"
    literal_text = "<b>literal HTML</b> & <script>alert('still text')</script>\n**plain text**"
    request = _public_chat_request(
        session_id="echo-vault-session",
        command_id="local-chat-once",
        message_id="local-message",
        expected_revision=0,
        text=literal_text,
    )

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as first_client:
        empty = first_client.get("/api/v1/chat")
        session_before = first_client.get("/api/v1/session")

        assert empty.status_code == 200
        assert empty.json() == {
            "schema_version": "vtt.chat_view.v1",
            "session_id": "echo-vault-session",
            "table_id": "echo-vault-session",
            "revision": 0,
            "messages": [],
        }
        assert session_before.status_code == 200
        assert session_before.json()["revision"] == 0

        created = first_client.post("/api/v1/chat-commands", json=request)

        assert created.status_code == 200
        created_payload = created.json()
        assert created_payload["schema_version"] == "vtt.chat_response.v1"
        assert created_payload["revision"] == 1
        assert created_payload["replayed"] is False
        assert created_payload["event"]["message"]["author_id"] == "local"
        assert created_payload["event"]["message"]["audience"] == ["all"]
        assert created_payload["event"]["message"]["text"] == literal_text
        assert first_client.get("/api/v1/session").json()["revision"] == 0

    assert _stored_chat_event_count(database_path) == 1

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as restored_client:
        restored = restored_client.get("/api/v1/chat")

        assert restored.status_code == 200
        restored_payload = restored.json()
        assert restored_payload["revision"] == 1
        assert restored_payload["messages"] == [created_payload["event"]["message"]]
        assert restored_payload["messages"][0]["author_id"] == "local"
        assert restored_payload["messages"][0]["text"] == literal_text
        assert restored_client.get("/api/v1/session").json()["revision"] == 0

        replayed = restored_client.post("/api/v1/chat-commands", json=request)

        assert replayed.status_code == 200
        assert replayed.json()["replayed"] is True
        assert replayed.json()["revision"] == 1
        after_retry = restored_client.get("/api/v1/chat").json()
        assert after_retry["revision"] == 1
        assert after_retry["messages"] == restored_payload["messages"]

    assert _stored_chat_event_count(database_path) == 1


def test_solo_table_owns_three_independent_sqlite_connections_and_closes_them(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured_connections: list[sqlite3.Connection] = []

    def capture_composition(service, *, annotation_board, chat_log, **_kwargs):
        captured_connections.extend(
            [
                service._event_store._connection,
                annotation_board._connection,
                chat_log._connection,
            ]
        )
        return FastAPI()

    monkeypatch.setattr(solo_app, "create_vtt_app", capture_composition)

    app = create_solo_table_app(tmp_path / "owned-connections.sqlite3")

    assert len(captured_connections) == 3
    assert len({id(connection) for connection in captured_connections}) == 3
    assert [
        connection.execute("PRAGMA busy_timeout").fetchone()[0]
        for connection in captured_connections
    ] == [30_000, 30_000, 30_000]

    with TestClient(app):
        pass

    for connection in captured_connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def test_solo_table_closes_all_connections_when_http_composition_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured_connections: list[sqlite3.Connection] = []

    def fail_composition(service, *, annotation_board, chat_log, **_kwargs):
        captured_connections.extend(
            [
                service._event_store._connection,
                annotation_board._connection,
                chat_log._connection,
            ]
        )
        raise RuntimeError("HTTP composition failed")

    monkeypatch.setattr(solo_app, "create_vtt_app", fail_composition)

    with pytest.raises(RuntimeError, match="HTTP composition failed"):
        create_solo_table_app(tmp_path / "failed-composition.sqlite3")

    assert len(captured_connections) == 3
    for connection in captured_connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def test_solo_table_main_passes_explicit_server_options(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "cli.sqlite3"
    sentinel_app = object()
    observed: dict[str, Any] = {}

    def fake_factory(path: Path) -> object:
        observed["database"] = path
        return sentinel_app

    monkeypatch.setattr(solo_app, "create_solo_table_app", fake_factory)

    def fake_run(app: object, *, host: str, port: int) -> None:
        observed.update({"app": app, "host": host, "port": port})

    monkeypatch.setattr(solo_app.uvicorn, "run", fake_run)

    solo_app.main(
        [
            "--database",
            str(database_path),
            "--host",
            "0.0.0.0",
            "--port",
            "9123",
        ]
    )

    assert observed == {
        "database": database_path,
        "app": sentinel_app,
        "host": "0.0.0.0",
        "port": 9123,
    }
    assert not hasattr(solo_app, "app")
