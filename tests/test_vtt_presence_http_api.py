from __future__ import annotations

import asyncio
import json
import random
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from dnd_sim.interactive import (
    EngineTransition,
    EngineVersionPins,
    PendingReaction,
    PreviewOutcome,
    SessionCommand,
)
from dnd_sim.vtt import presence_api
from dnd_sim.vtt.access import TableAccessPolicy
from dnd_sim.vtt.event_store import SQLiteSessionEventStore
from dnd_sim.vtt.http_api import VTT_ERROR_SCHEMA_VERSION, create_vtt_app
from dnd_sim.vtt.participants import TableParticipant, TableRoster
from dnd_sim.vtt.presence_api import (
    PRESENCE_CHANGE_SIGNAL_SCHEMA_VERSION,
    VTT_PRESENCE_HEARTBEAT_RESPONSE_SCHEMA_VERSION,
)
from dnd_sim.vtt.presence_contracts import PresenceHeartbeatCommand
from dnd_sim.vtt.presence_store import PresenceRevisionConflictError, SQLitePresenceStore
from dnd_sim.vtt.session_service import VTTSessionService

SESSION_ID = "presence-session"
TABLE_ID = "presence-table"
TOKENS = {
    "gm": "gm-presence-token-1234",
    "player": "player-presence-token-1234",
    "spectator": "spectator-presence-token-1234",
}


class _ProjectionDriver:
    version_pins = EngineVersionPins(
        engine_version="presence-http@1",
        rules_version="presence-rules@1",
        content_version="presence-content@1",
    )

    def encode_state(self, state: Any) -> Mapping[str, Any]:
        return {"value": int(state["value"])}

    def decode_state(self, payload: Mapping[str, Any]) -> dict[str, int]:
        return {"value": int(payload["value"])}

    def project_state(self, state: dict[str, int]) -> Mapping[str, Any]:
        return {"value": state["value"]}

    def preview(
        self,
        state: dict[str, int],
        command: SessionCommand,
        rng: random.Random,
    ) -> PreviewOutcome:
        return PreviewOutcome(projection=self.project_state(state), events=())

    def commit(
        self,
        state: dict[str, int],
        command: SessionCommand,
        rng: random.Random,
    ) -> EngineTransition:
        return EngineTransition(state=state, events=())

    def respond_to_reaction(
        self,
        state: dict[str, int],
        command: SessionCommand,
        pending_reaction: PendingReaction,
        rng: random.Random,
    ) -> EngineTransition:
        raise AssertionError("presence HTTP tests do not open reactions")


@dataclass
class _Clock:
    value: int = 1_000
    calls: int = 0

    def __call__(self) -> int:
        self.calls += 1
        return self.value


def _participant(participant_id: str, role: str) -> TableParticipant:
    return TableParticipant(
        schema_version="vtt.participant.v1",
        participant_id=participant_id,
        display_name=participant_id.title(),
        role=role,
        owned_actor_ids=(),
    )


def _roster() -> TableRoster:
    return TableRoster(
        schema_version="vtt.roster.v1",
        table_id=TABLE_ID,
        participants=(
            _participant("gm", "gm"),
            _participant("player", "player"),
            _participant("spectator", "spectator"),
        ),
    )


def _policy() -> TableAccessPolicy:
    return TableAccessPolicy(roster=_roster(), bearer_tokens=TOKENS)


def _authorization(participant_id: str) -> dict[str, str]:
    return {"authorization": f"Bearer {TOKENS[participant_id]}"}


def _heartbeat_request(
    command_id: str,
    *,
    participant_id: str = "player",
    client_id: str = "browser-a",
    expected_revision: int = 0,
    session_id: str = SESSION_ID,
    table_id: str = TABLE_ID,
) -> dict[str, Any]:
    return {
        "schema_version": "vtt.presence_heartbeat_request.v1",
        "session_id": session_id,
        "command": {
            "schema_version": "vtt.presence_command.v1",
            "command_type": "heartbeat",
            "table_id": table_id,
            "command_id": command_id,
            "expected_revision": expected_revision,
            "participant_id": participant_id,
            "client_id": client_id,
        },
    }


@pytest.fixture
def presence_api_client(tmp_path: Path):
    database_path = tmp_path / "presence-http.sqlite3"
    session_connection = sqlite3.connect(database_path, check_same_thread=False)
    presence_connection = sqlite3.connect(database_path, check_same_thread=False)
    service = VTTSessionService.open(
        session_id=SESSION_ID,
        initial_state={"value": 0},
        driver=_ProjectionDriver(),
        seed=91,
        event_store=SQLiteSessionEventStore(session_connection),
    )
    store = SQLitePresenceStore(
        presence_connection,
        roster=_roster(),
        away_after_ms=10,
        offline_after_ms=30,
    )
    clock = _Clock()
    app = create_vtt_app(
        service,
        access_policy=_policy(),
        presence_store=store,
        presence_epoch_ms_clock=clock,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, store, service, clock
    presence_connection.close()
    session_connection.close()


def _assert_error(response, *, status_code: int, code: str) -> dict[str, Any]:
    assert response.status_code == status_code
    payload = response.json()
    assert payload["schema_version"] == VTT_ERROR_SCHEMA_VERSION
    assert payload["code"] == code
    assert isinstance(payload["details"], dict)
    assert "traceback" not in response.text.lower()
    return payload


def test_presence_routes_are_optional_and_authenticate_before_validation(
    presence_api_client,
) -> None:
    client, _store, service, _clock = presence_api_client
    with TestClient(create_vtt_app(service), raise_server_exceptions=False) as absent:
        assert absent.get("/api/v1/presence").status_code == 404
    for method, path, body in (
        ("GET", "/api/v1/presence", None),
        ("GET", "/api/v1/presence-events?after=01", None),
        ("POST", "/api/v1/presence-heartbeats", "{not-json"),
    ):
        response = client.request(
            method,
            path,
            content=body,
            headers={"content-type": "application/json"} if body else None,
        )
        _assert_error(response, status_code=401, code="authentication_required")


def test_presence_view_and_heartbeat_are_safe_and_principal_bound(
    presence_api_client,
) -> None:
    client, store, _service, clock = presence_api_client
    initial = client.get("/api/v1/presence", headers=_authorization("spectator"))
    assert initial.status_code == 200
    assert [record["status"] for record in initial.json()["records"]] == [
        "offline",
        "offline",
        "offline",
    ]
    created = client.post(
        "/api/v1/presence-heartbeats",
        headers=_authorization("player"),
        json=_heartbeat_request("heartbeat-once"),
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["schema_version"] == VTT_PRESENCE_HEARTBEAT_RESPONSE_SCHEMA_VERSION
    assert payload["signal"] == {
        "schema_version": PRESENCE_CHANGE_SIGNAL_SCHEMA_VERSION,
        "sequence": 1,
        "revision": 1,
        "participant_id": "player",
    }
    assert "browser-a" not in created.text
    assert "client_id" not in created.text
    assert "observed_at" not in created.text
    assert store.events_after(viewer_id="gm", sequence=0)[0].observed_at_ms == 1_000
    assert clock.calls == 2

    forbidden = client.post(
        "/api/v1/presence-heartbeats",
        headers=_authorization("gm"),
        json=_heartbeat_request(
            "impersonate",
            participant_id="player",
            expected_revision=1,
        ),
    )
    _assert_error(forbidden, status_code=403, code="presence_impersonation_forbidden")
    assert store.revision == 1


def test_heartbeat_rejects_client_time_and_preserves_exact_retry(
    presence_api_client,
) -> None:
    client, store, _service, clock = presence_api_client
    invalid = _heartbeat_request("client-time")
    invalid["command"]["observed_at_ms"] = 1
    rejected = client.post(
        "/api/v1/presence-heartbeats",
        headers=_authorization("player"),
        json=invalid,
    )
    _assert_error(rejected, status_code=422, code="invalid_request")
    assert clock.calls == 0

    request = _heartbeat_request("heartbeat-once")
    first = client.post(
        "/api/v1/presence-heartbeats",
        headers=_authorization("player"),
        json=request,
    )
    clock.value = 2_000
    replay = client.post(
        "/api/v1/presence-heartbeats",
        headers=_authorization("player"),
        json=request,
    )
    assert first.status_code == replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["signal"] == first.json()["signal"]
    stale = client.post(
        "/api/v1/presence-heartbeats",
        headers=_authorization("spectator"),
        json=_heartbeat_request("stale", participant_id="spectator"),
    )
    assert _assert_error(stale, status_code=409, code="presence_stale_revision")["details"] == {
        "current_revision": 1
    }
    assert store.revision == 1


def test_presence_binding_and_transaction_race_errors_are_stable(
    presence_api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store, _service, _clock = presence_api_client
    wrong = client.post(
        "/api/v1/presence-heartbeats",
        headers=_authorization("player"),
        json=_heartbeat_request("wrong", session_id="other"),
    )
    _assert_error(wrong, status_code=409, code="presence_binding_mismatch")

    def lose_cross_process_race(
        _command: PresenceHeartbeatCommand,
        *,
        observed_at_ms: int,
    ):
        assert observed_at_ms == 1_000
        raise PresenceRevisionConflictError(current_revision=7, expected_revision=0)

    monkeypatch.setattr(store, "heartbeat", lose_cross_process_race)
    raced = client.post(
        "/api/v1/presence-heartbeats",
        headers=_authorization("player"),
        json=_heartbeat_request("raced"),
    )
    assert _assert_error(raced, status_code=409, code="presence_stale_revision")["details"] == {
        "current_revision": 7
    }


async def _capture_sse(app, path: str, *, headers: dict[str, str]) -> tuple[int, str]:
    parsed = urlsplit(path)
    request_sent = False
    disconnected = asyncio.Event()
    response_start: dict[str, Any] | None = None
    response_body: list[str] = []
    encoded_headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in headers.items()
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": parsed.path,
        "raw_path": parsed.path.encode("ascii"),
        "query_string": parsed.query.encode("ascii"),
        "headers": encoded_headers,
        "client": ("127.0.0.1", 43123),
        "server": ("testserver", 80),
        "root_path": "",
    }

    async def receive() -> dict[str, Any]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        nonlocal response_start
        if message["type"] == "http.response.start":
            response_start = message
        elif message["type"] == "http.response.body":
            response_body.append(bytes(message.get("body", b"")).decode("utf-8"))
            if "data: " in "".join(response_body):
                disconnected.set()

    await asyncio.wait_for(app(scope, receive, send), timeout=1.0)
    assert response_start is not None
    return int(response_start["status"]), "".join(response_body)


def test_presence_sse_is_reconnectable_and_contains_only_sanitized_signals(
    presence_api_client,
) -> None:
    client, _store, _service, _clock = presence_api_client
    created = client.post(
        "/api/v1/presence-heartbeats",
        headers=_authorization("player"),
        json=_heartbeat_request("streamed"),
    )
    assert created.status_code == 200
    status, payload = asyncio.run(
        _capture_sse(
            client.app,
            "/api/v1/presence-events?after=0",
            headers=_authorization("spectator"),
        )
    )
    assert status == 200
    assert "event: vtt.presence_changed" in payload
    data_line = next(line for line in payload.splitlines() if line.startswith("data: "))
    signal = json.loads(data_line.removeprefix("data: "))
    assert signal == created.json()["signal"]
    assert "client_id" not in payload
    assert "browser-a" not in payload
    assert "observed_at" not in payload


def test_presence_clock_regression_is_nonleaking_server_error(
    presence_api_client,
) -> None:
    client, _store, _service, clock = presence_api_client
    assert (
        client.post(
            "/api/v1/presence-heartbeats",
            headers=_authorization("player"),
            json=_heartbeat_request("anchor"),
        ).status_code
        == 200
    )
    clock.value = 999
    regressed = client.get("/api/v1/presence", headers=_authorization("gm"))
    _assert_error(regressed, status_code=500, code="presence_clock_regressed")
