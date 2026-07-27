from __future__ import annotations

import asyncio
import json
import random
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from dnd_sim.interactive import (
    EngineTransition,
    EngineVersionPins,
    EventDraft,
    PendingReaction,
    PreviewOutcome,
    SessionCommand,
)
from dnd_sim.vtt.access import TableAccessPolicy
from dnd_sim.vtt.contracts import VTT_COMMAND_SCHEMA_VERSION
from dnd_sim.vtt.event_store import SQLiteSessionEventStore
from dnd_sim.vtt.http_api import VTT_ERROR_SCHEMA_VERSION, create_vtt_app
from dnd_sim.vtt.participants import (
    PARTICIPANT_SCHEMA_VERSION,
    ROSTER_SCHEMA_VERSION,
    TableParticipant,
    TableRoster,
)
from dnd_sim.vtt.session_service import VTTSessionService
from dnd_sim.vtt import http_api

TOKENS = {
    "gm": "gm-token-1234567890",
    "other": "other-token-1234567890",
    "player": "player-token-1234567890",
    "spectator": "spectator-token-1234567890",
}


def _participant(
    participant_id: str,
    *,
    role: str,
    owned_actor_ids: tuple[str, ...] = (),
) -> TableParticipant:
    return TableParticipant(
        schema_version=PARTICIPANT_SCHEMA_VERSION,
        participant_id=participant_id,
        display_name=participant_id,
        role=role,
        owned_actor_ids=owned_actor_ids,
    )


def _policy() -> TableAccessPolicy:
    roster = TableRoster(
        schema_version=ROSTER_SCHEMA_VERSION,
        table_id="access-table",
        participants=(
            _participant("gm", role="gm"),
            _participant("other", role="player", owned_actor_ids=("other_actor",)),
            _participant("player", role="player", owned_actor_ids=("hero",)),
            _participant("spectator", role="spectator"),
        ),
    )
    return TableAccessPolicy(roster=roster, bearer_tokens=TOKENS)


def _authorization(participant_id: str) -> dict[str, str]:
    return {"authorization": f"Bearer {TOKENS[participant_id]}"}


class AudienceDriver:
    version_pins = EngineVersionPins(
        engine_version="access-counter@1",
        rules_version="access-rules@1",
        content_version="access-content@1",
    )

    def encode_state(self, state: Any) -> Mapping[str, Any]:
        return {"value": state["value"]}

    def decode_state(self, payload: Mapping[str, Any]) -> dict[str, int]:
        return {"value": int(payload["value"])}

    def project_state(self, state: dict[str, int]) -> Mapping[str, Any]:
        return {"counter": {"value": state["value"]}}

    @staticmethod
    def _events(value: int) -> tuple[EventDraft, ...]:
        return (
            EventDraft(
                kind="counter.public",
                audience=("all",),
                payload={"label": "public", "value": value},
            ),
            EventDraft(
                kind="counter.gm",
                audience=("role:gm",),
                payload={"label": "gm", "value": value},
            ),
            EventDraft(
                kind="counter.owned",
                audience=("actor:hero",),
                payload={"label": "owned", "value": value},
            ),
            EventDraft(
                kind="counter.participant",
                audience=("participant:player",),
                payload={"label": "participant", "value": value},
            ),
            EventDraft(
                kind="counter.players",
                audience=("role:player",),
                payload={"label": "players", "value": value},
            ),
            EventDraft(
                kind="counter.spectators",
                audience=("role:spectator",),
                payload={"label": "spectators", "value": value},
            ),
            EventDraft(
                kind="counter.spectator-private",
                audience=("participant:spectator",),
                payload={"label": "spectator-private", "value": value},
            ),
            EventDraft(
                kind="counter.other",
                audience=("actor:other_actor",),
                payload={"label": "other", "value": value},
            ),
        )

    def preview(
        self,
        state: dict[str, int],
        command: SessionCommand,
        rng: random.Random,
    ) -> PreviewOutcome:
        next_value = state["value"] + int(command.payload["amount"])
        return PreviewOutcome(
            projection={"counter": {"value": next_value}},
            events=self._events(next_value),
        )

    def commit(
        self,
        state: dict[str, int],
        command: SessionCommand,
        rng: random.Random,
    ) -> EngineTransition:
        next_value = state["value"] + int(command.payload["amount"])
        return EngineTransition(
            state={"value": next_value},
            events=self._events(next_value),
        )

    def respond_to_reaction(
        self,
        state: dict[str, int],
        command: SessionCommand,
        pending_reaction: PendingReaction,
        rng: random.Random,
    ) -> EngineTransition:
        raise AssertionError("access tests do not open reactions")


def _command_payload(
    command_id: str,
    *,
    expected_revision: int = 0,
    actor_id: str | None = "hero",
    mode: str = "commit",
) -> dict[str, Any]:
    return {
        "schema_version": VTT_COMMAND_SCHEMA_VERSION,
        "command_id": command_id,
        "session_id": "access-table",
        "actor_id": actor_id,
        "expected_revision": expected_revision,
        "mode": mode,
        "kind": "counter.increment.v1",
        "payload": {"amount": 1},
        "intent_metadata": {},
    }


@pytest.fixture
def protected_api(tmp_path: Path):
    connection = sqlite3.connect(
        tmp_path / "access.sqlite3",
        check_same_thread=False,
    )
    service = VTTSessionService.open(
        session_id="access-table",
        initial_state={"value": 0},
        driver=AudienceDriver(),
        seed=23,
        event_store=SQLiteSessionEventStore(connection),
    )
    app = create_vtt_app(service, access_policy=_policy())
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, service
    connection.close()


def _assert_access_error(response, *, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    assert response.json() == {
        "schema_version": VTT_ERROR_SCHEMA_VERSION,
        "code": code,
        "message": (
            "Authentication is required for this table."
            if status_code == 401
            else "This participant is not permitted to issue the command."
        ),
        "details": {},
    }
    if status_code == 401:
        assert response.headers["www-authenticate"] == "Bearer"
    else:
        assert "www-authenticate" not in response.headers
    assert "token-1234567890" not in response.text


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"authorization": "Basic player-token-1234567890"},
        {"authorization": "bearer player-token-1234567890"},
        {"authorization": "Bearer unknown-token-1234567890"},
    ],
)
def test_protected_routes_require_one_canonical_bearer_credential(
    protected_api,
    headers: dict[str, str],
) -> None:
    client, service = protected_api

    session = client.get("/api/v1/session", headers=headers)
    events = client.get("/api/v1/events", headers=headers)
    command = client.post(
        "/api/v1/commands",
        content="{not-json",
        headers={"content-type": "application/json", **headers},
    )

    _assert_access_error(session, status_code=401, code="authentication_required")
    _assert_access_error(events, status_code=401, code="authentication_required")
    _assert_access_error(command, status_code=401, code="authentication_required")
    assert service.revision == 0


def test_health_remains_public_and_open_apps_keep_existing_behavior(
    protected_api,
) -> None:
    client, service = protected_api

    assert client.get("/healthz").json() == {"status": "ok"}
    for participant_id in TOKENS:
        response = client.get(
            "/api/v1/session",
            headers=_authorization(participant_id),
        )
        assert response.status_code == 200

    with TestClient(create_vtt_app(service), raise_server_exceptions=False) as open_client:
        assert open_client.get("/api/v1/session").status_code == 200


def test_duplicate_authorization_headers_are_rejected(protected_api) -> None:
    client, _service = protected_api

    response = client.get(
        "/api/v1/session",
        headers=[
            ("authorization", f"Bearer {TOKENS['player']}"),
            ("authorization", f"Bearer {TOKENS['gm']}"),
        ],
    )

    _assert_access_error(response, status_code=401, code="authentication_required")


@pytest.mark.parametrize(
    ("participant_id", "patch"),
    [
        ("player", {"actor_id": "other_actor"}),
        ("player", {"actor_id": None}),
        ("player", {"mode": "admin"}),
        ("spectator", {}),
    ],
)
def test_role_and_actor_ownership_are_authorized_before_mutation(
    protected_api,
    participant_id: str,
    patch: dict[str, Any],
) -> None:
    client, service = protected_api
    payload = _command_payload(f"forbidden-{participant_id}")
    payload.update(patch)

    response = client.post(
        "/api/v1/commands",
        json=payload,
        headers=_authorization(participant_id),
    )

    _assert_access_error(response, status_code=403, code="command_forbidden")
    assert service.revision == 0
    assert service.state == {"value": 0}
    assert service.events_after(0) == ()


def test_gm_may_administer_and_player_may_act_only_as_owned_actor(protected_api) -> None:
    client, service = protected_api

    player = client.post(
        "/api/v1/commands",
        json=_command_payload("player-preview", mode="preview"),
        headers=_authorization("player"),
    )
    gm = client.post(
        "/api/v1/commands",
        json=_command_payload(
            "gm-admin",
            expected_revision=0,
            actor_id=None,
            mode="admin",
        ),
        headers=_authorization("gm"),
    )

    assert player.status_code == 200
    assert gm.status_code == 200
    assert service.revision == 1


def test_direct_command_events_are_filtered_and_bounds_describe_visible_events(
    protected_api,
) -> None:
    client, _service = protected_api

    preview = client.post(
        "/api/v1/commands",
        json=_command_payload("player-preview", mode="preview"),
        headers=_authorization("player"),
    )
    commit = client.post(
        "/api/v1/commands",
        json=_command_payload("player-commit"),
        headers=_authorization("player"),
    )

    assert [event["payload"]["label"] for event in preview.json()["events"]] == [
        "public",
        "owned",
        "participant",
        "players",
    ]
    payload = commit.json()
    assert [event["sequence"] for event in payload["events"]] == [1, 3, 4, 5]
    assert payload["first_sequence"] == 1
    assert payload["last_sequence"] == 5
    labels = [event["payload"]["label"] for event in payload["events"]]
    assert "spectator-private" not in labels
    assert "other" not in labels


def test_gm_direct_response_can_inspect_every_explicit_audience(protected_api) -> None:
    client, _service = protected_api

    response = client.post(
        "/api/v1/commands",
        json=_command_payload("gm-commit", actor_id="other_actor"),
        headers=_authorization("gm"),
    )

    assert response.status_code == 200
    assert [event["sequence"] for event in response.json()["events"]] == list(range(1, 9))


async def _capture_sse(
    app,
    path: str,
    *,
    headers: dict[str, str],
    data_event_count: int | None = None,
    stop_on_heartbeat: bool = False,
) -> tuple[int, dict[str, str], str]:
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
            return
        if message["type"] != "http.response.body":
            return
        response_body.append(bytes(message.get("body", b"")).decode("utf-8"))
        rendered = "".join(response_body)
        if data_event_count is not None and rendered.count("data: ") >= data_event_count:
            disconnected.set()
        if stop_on_heartbeat and ": heartbeat\n\n" in rendered:
            disconnected.set()

    await asyncio.wait_for(app(scope, receive, send), timeout=1.0)
    assert response_start is not None
    response_headers = {
        bytes(name).decode("latin-1").lower(): bytes(value).decode("latin-1")
        for name, value in response_start["headers"]
    }
    return int(response_start["status"]), response_headers, "".join(response_body)


def _sse_data_events(payload: str) -> list[tuple[int, dict[str, Any]]]:
    events: list[tuple[int, dict[str, Any]]] = []
    for block in payload.split("\n\n"):
        fields = {}
        for line in block.splitlines():
            if ": " in line:
                name, value = line.split(": ", 1)
                fields[name] = value
        if "id" in fields and "data" in fields:
            events.append((int(fields["id"]), json.loads(fields["data"])))
    return events


@pytest.mark.parametrize(
    ("participant_id", "visible_sequences"),
    [
        ("gm", list(range(1, 9))),
        ("player", [1, 3, 4, 5]),
        ("other", [1, 5, 8]),
        ("spectator", [1, 6]),
    ],
)
def test_sse_projects_only_the_principals_explicit_audiences(
    protected_api,
    participant_id: str,
    visible_sequences: list[int],
) -> None:
    client, _service = protected_api
    committed = client.post(
        "/api/v1/commands",
        json=_command_payload("gm-commit", actor_id=None, mode="admin"),
        headers=_authorization("gm"),
    )
    assert committed.status_code == 200

    status, _headers, payload = asyncio.run(
        _capture_sse(
            client.app,
            "/api/v1/events?after=0",
            headers=_authorization(participant_id),
            data_event_count=len(visible_sequences),
        )
    )

    assert status == 200
    events = _sse_data_events(payload)
    assert [event_id for event_id, _event in events] == visible_sequences
    assert [event["sequence"] for _event_id, event in events] == visible_sequences
    if participant_id == "spectator":
        assert "spectator-private" not in payload


def test_hidden_sse_events_advance_only_the_private_scan_cursor(
    protected_api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, service = protected_api
    committed = client.post(
        "/api/v1/commands",
        json=_command_payload("gm-commit", actor_id=None, mode="admin"),
        headers=_authorization("gm"),
    )
    assert committed.status_code == 200

    seen_cursors: list[int] = []
    original_events_after = service.events_after

    def recording_events_after(sequence: int):
        seen_cursors.append(sequence)
        return original_events_after(sequence)

    monkeypatch.setattr(service, "events_after", recording_events_after)
    monkeypatch.setattr(http_api, "SSE_POLL_INTERVAL_SECONDS", 0.001)
    monkeypatch.setattr(http_api, "SSE_HEARTBEAT_INTERVAL_SECONDS", 0.01)

    status, _headers, payload = asyncio.run(
        _capture_sse(
            client.app,
            "/api/v1/events?after=6",
            headers=_authorization("spectator"),
            stop_on_heartbeat=True,
        )
    )

    assert status == 200
    assert _sse_data_events(payload) == []
    assert ": heartbeat\n\n" in payload
    assert seen_cursors[0] == 6
    assert 8 in seen_cursors[1:]
    assert "cursor" not in payload
    assert "counter.other" not in payload


def test_cors_preflight_permits_authorization_without_requiring_auth(
    protected_api,
) -> None:
    client, _service = protected_api

    unauthorized = client.get(
        "/api/v1/session",
        headers={"origin": "http://localhost:3000"},
    )
    response = client.options(
        "/api/v1/commands",
        headers={
            "origin": "http://localhost:3000",
            "access-control-request-method": "POST",
            "access-control-request-headers": "authorization,content-type",
        },
    )

    _assert_access_error(unauthorized, status_code=401, code="authentication_required")
    assert unauthorized.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.status_code == 200
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed
    assert "content-type" in allowed
