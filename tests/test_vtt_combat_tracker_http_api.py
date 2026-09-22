from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from dnd_sim.interactive import DndCombatEncounterDriver
from dnd_sim.interactive.dnd_encounter_driver import (
    COMBAT_CONTROL_COMMAND_KIND,
    START_ENCOUNTER_COMMAND_KIND,
)
from dnd_sim.vtt.access import TableAccessPolicy
from dnd_sim.vtt.contracts import VTTCommand
from dnd_sim.vtt.event_store import SQLiteSessionEventStore
from dnd_sim.vtt.http_api import _project_event_for_participant, create_vtt_app
from dnd_sim.vtt.participants import (
    PARTICIPANT_SCHEMA_VERSION,
    ROSTER_SCHEMA_VERSION,
    TableParticipant,
    TableRoster,
)
from dnd_sim.vtt.session_service import VTTSessionService
from dnd_sim.vtt.solo_table import build_solo_table_fixture


def _policy() -> TableAccessPolicy:
    return TableAccessPolicy(
        roster=TableRoster(
            schema_version=ROSTER_SCHEMA_VERSION,
            table_id="tracker-table",
            participants=(
                TableParticipant(
                    schema_version=PARTICIPANT_SCHEMA_VERSION,
                    participant_id="gm",
                    display_name="GM",
                    role="gm",
                ),
                TableParticipant(
                    schema_version=PARTICIPANT_SCHEMA_VERSION,
                    participant_id="player",
                    display_name="Player",
                    role="player",
                    owned_actor_ids=("vela_quill",),
                ),
            ),
        ),
        bearer_tokens={
            "gm": "gm-tracker-token-1234",
            "player": "player-tracker-token-1234",
        },
    )


def _headers(participant_id: str) -> dict[str, str]:
    return {
        "authorization": (
            "Bearer gm-tracker-token-1234"
            if participant_id == "gm"
            else "Bearer player-tracker-token-1234"
        )
    }


def _command(
    *,
    command_id: str,
    expected_revision: int,
    kind: str,
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": "vtt.command.v1",
        "command_id": command_id,
        "session_id": "tracker-session",
        "actor_id": None,
        "expected_revision": expected_revision,
        "mode": "admin",
        "kind": kind,
        "payload": payload,
        "intent_metadata": {},
    }


def _open_service(database: Path) -> tuple[sqlite3.Connection, VTTSessionService]:
    fixture = build_solo_table_fixture()
    connection = sqlite3.connect(database, check_same_thread=False)
    return connection, VTTSessionService.open(
        session_id="tracker-session",
        initial_state=fixture.encounter_state,
        driver=DndCombatEncounterDriver(version_pins=fixture.version_pins),
        seed=fixture.seed,
        event_store=SQLiteSessionEventStore(connection),
    )


def test_protected_tracker_is_gm_only_restart_safe_and_exactly_replayable(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tracker.sqlite3"
    connection, service = _open_service(database)
    app = create_vtt_app(service, access_policy=_policy())
    start = _command(
        command_id="start",
        expected_revision=0,
        kind=START_ENCOUNTER_COMMAND_KIND,
        payload={},
    )
    advance = _command(
        command_id="advance",
        expected_revision=1,
        kind=COMBAT_CONTROL_COMMAND_KIND,
        payload={
            "operation": "advance",
            "direction": "next",
            "reason": "Correct the physical table cursor.",
        },
    )

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            unauthenticated = client.post(
                "/api/v1/commands",
                content="{not-json",
                headers={"content-type": "application/json"},
            )
            assert unauthenticated.status_code == 401
            assert unauthenticated.json()["code"] == "authentication_required"

            assert (
                client.post("/api/v1/commands", json=start, headers=_headers("gm")).status_code
                == 200
            )
            before = service.read_view()
            forbidden = client.post("/api/v1/commands", json=advance, headers=_headers("player"))
            assert forbidden.status_code == 403
            assert forbidden.json()["code"] == "command_forbidden"
            assert service.read_view() == before

            accepted = client.post("/api/v1/commands", json=advance, headers=_headers("gm"))
            assert accepted.status_code == 200
            assert accepted.json()["events"][0]["kind"] == ("dnd.encounter.cursor_overridden")
            replayed = client.post("/api/v1/commands", json=advance, headers=_headers("gm"))
            assert replayed.status_code == 200
            assert replayed.json()["replayed"] is True
            assert service.revision == 2
    finally:
        connection.close()

    restored_connection, restored = _open_service(database)
    try:
        projection = restored.read_view().projection
        assert restored.revision == 2
        assert projection["active_actor_id"] == "hushglass_sentry"
        assert projection["round_number"] == 1
        assert [event.kind for event in restored.events_after(2)] == [
            "dnd.encounter.cursor_overridden",
            "dnd.turn.prepared",
        ]
        assert restored.events_after(2)[0].payload["reason"] == (
            "Correct the physical table cursor."
        )
    finally:
        restored_connection.close()


def test_hidden_tracker_audit_projects_as_identity_free_refresh_signal(
    tmp_path: Path,
) -> None:
    connection, service = _open_service(tmp_path / "tracker-projection.sqlite3")
    player = _policy().roster.participant("player")
    assert player is not None
    try:
        service.execute(
            VTTCommand.model_validate(
                _command(
                    command_id="start",
                    expected_revision=0,
                    kind=START_ENCOUNTER_COMMAND_KIND,
                    payload={},
                )
            )
        )
        service.execute(
            VTTCommand.model_validate(
                _command(
                    command_id="advance",
                    expected_revision=1,
                    kind=COMBAT_CONTROL_COMMAND_KIND,
                    payload={
                        "operation": "advance",
                        "direction": "next",
                        "reason": "Hidden enemy is now active.",
                    },
                )
            )
        )
        audit = service.events_after(2)[0]
        projected = _project_event_for_participant(
            audit,
            participant=player,
            hidden_actor_values=frozenset({"hushglass_sentry"}),
        )
        assert projected is not None
        assert projected.kind == "vtt.encounter.changed.v1"
        assert projected.payload == {}
        assert "hushglass_sentry" not in projected.model_dump_json()
        assert "Hidden enemy" not in projected.model_dump_json()
    finally:
        connection.close()
