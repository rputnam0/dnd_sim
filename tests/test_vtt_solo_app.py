from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

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


def _stored_command_count(database_path: Path) -> int:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM vtt_committed_commands").fetchone()
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
