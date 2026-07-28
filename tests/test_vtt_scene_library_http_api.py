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
    PendingReaction,
    PreviewOutcome,
    SessionCommand,
)
from dnd_sim.vtt import scene_library_api
from dnd_sim.vtt.access import TableAccessPolicy
from dnd_sim.vtt.event_store import SQLiteSessionEventStore
from dnd_sim.vtt.http_api import VTT_ERROR_SCHEMA_VERSION, create_vtt_app
from dnd_sim.vtt.participants import (
    PARTICIPANT_SCHEMA_VERSION,
    ROSTER_SCHEMA_VERSION,
    TableParticipant,
    TableRoster,
)
from dnd_sim.vtt.scene_library_api import (
    VTT_SCENE_LIBRARY_REQUEST_SCHEMA_VERSION,
    VTT_SCENE_LIBRARY_RESPONSE_SCHEMA_VERSION,
)
from dnd_sim.vtt.scene_library_contracts import (
    SCENE_COMMAND_SCHEMA_VERSION,
    SCENE_MAP_METADATA_SCHEMA_VERSION,
    SCENE_RECORD_SCHEMA_VERSION,
    SceneActivateCommand,
    SceneCreateCommand,
    SceneDuplicateCommand,
    SceneMapMetadata,
    SceneRecord,
)
from dnd_sim.vtt.scene_library_store import (
    SQLiteSceneLibrary,
    SceneLibraryStoreCorruptionError,
)
from dnd_sim.vtt.session_service import VTTSessionService

SESSION_ID = "scene-session"
TABLE_ID = "scene-table"
TOKENS = {
    "gm": "gm-scene-token-1234",
    "player": "player-scene-token-1234",
    "spectator": "spectator-scene-token-1234",
}


class _ProjectionDriver:
    version_pins = EngineVersionPins(
        engine_version="scene-http@1",
        rules_version="scene-rules@1",
        content_version="scene-content@1",
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
        raise AssertionError("scene HTTP tests do not open reactions")


def _participant(participant_id: str, *, role: str) -> TableParticipant:
    return TableParticipant(
        schema_version=PARTICIPANT_SCHEMA_VERSION,
        participant_id=participant_id,
        display_name=participant_id,
        role=role,
        owned_actor_ids=(),
    )


def _policy() -> TableAccessPolicy:
    return TableAccessPolicy(
        roster=TableRoster(
            schema_version=ROSTER_SCHEMA_VERSION,
            table_id=TABLE_ID,
            participants=(
                _participant("gm", role="gm"),
                _participant("player", role="player"),
                _participant("spectator", role="spectator"),
            ),
        ),
        bearer_tokens=TOKENS,
    )


def _authorization(participant_id: str) -> dict[str, str]:
    return {"authorization": f"Bearer {TOKENS[participant_id]}"}


def _scene(scene_id: str, *, name: str | None = None) -> SceneRecord:
    return SceneRecord(
        schema_version=SCENE_RECORD_SCHEMA_VERSION,
        scene_id=scene_id,
        map_metadata=SceneMapMetadata(
            schema_version=SCENE_MAP_METADATA_SCHEMA_VERSION,
            name=name or scene_id.title(),
            width_px=1_280,
            height_px=720,
            grid_size_px=64.0,
            gridless=False,
        ),
    )


def _create_request(
    command_id: str,
    scene_id: str,
    *,
    expected_revision: int,
    session_id: str = SESSION_ID,
    table_id: str = TABLE_ID,
) -> dict[str, Any]:
    return {
        "schema_version": VTT_SCENE_LIBRARY_REQUEST_SCHEMA_VERSION,
        "session_id": session_id,
        "command": {
            "schema_version": SCENE_COMMAND_SCHEMA_VERSION,
            "command_type": "create",
            "table_id": table_id,
            "command_id": command_id,
            "expected_revision": expected_revision,
            "scene": _scene(scene_id).model_dump(mode="json"),
        },
    }


@pytest.fixture
def scene_api_client(tmp_path: Path):
    database_path = tmp_path / "scene-http.sqlite3"
    session_connection = sqlite3.connect(database_path, check_same_thread=False)
    scene_connection = sqlite3.connect(database_path, check_same_thread=False)
    service = VTTSessionService.open(
        session_id=SESSION_ID,
        initial_state={"value": 0},
        driver=_ProjectionDriver(),
        seed=91,
        event_store=SQLiteSessionEventStore(session_connection),
    )
    library = SQLiteSceneLibrary(scene_connection)
    app = create_vtt_app(service, access_policy=_policy(), scene_library=library)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, library, service
    scene_connection.close()
    session_connection.close()


def _assert_error(response, *, status_code: int, code: str) -> dict[str, Any]:
    assert response.status_code == status_code
    payload = response.json()
    assert payload["schema_version"] == VTT_ERROR_SCHEMA_VERSION
    assert payload["code"] == code
    assert isinstance(payload["message"], str) and payload["message"]
    assert isinstance(payload["details"], dict)
    assert "traceback" not in response.text.lower()
    return payload


def test_scene_library_http_contracts_and_store_are_public_vtt_exports() -> None:
    import dnd_sim.vtt as vtt

    expected = {
        "SCENE_COMMAND_SCHEMA_VERSION",
        "SCENE_EXPORT_SCHEMA_VERSION",
        "SCENE_LIBRARY_STORE_SCHEMA_VERSION",
        "SCENE_LIBRARY_VIEW_SCHEMA_VERSION",
        "SCENE_MAP_METADATA_SCHEMA_VERSION",
        "SCENE_RECORD_SCHEMA_VERSION",
        "VTT_SCENE_LIBRARY_REQUEST_SCHEMA_VERSION",
        "VTT_SCENE_LIBRARY_RESPONSE_SCHEMA_VERSION",
        "SceneCreateCommand",
        "SceneLibraryRequest",
        "SceneLibraryResponse",
        "SceneLibraryView",
        "SceneMapMetadata",
        "SceneRecord",
        "SQLiteSceneLibrary",
    }

    assert expected <= set(vtt.__all__)
    assert all(getattr(vtt, name) is not None for name in expected)


def test_scene_routes_are_optional_and_validate_table_binding(scene_api_client) -> None:
    _client, library, service = scene_api_client
    with TestClient(create_vtt_app(service), raise_server_exceptions=False) as no_scenes:
        assert no_scenes.get("/api/v1/scenes").status_code == 404
        assert no_scenes.post("/api/v1/scene-commands", json={}).status_code == 404

    with pytest.raises(ValueError, match="scene_library"):
        create_vtt_app(service, scene_library_table_id=TABLE_ID)
    with pytest.raises(ValueError, match="access-policy table"):
        create_vtt_app(
            service,
            access_policy=_policy(),
            scene_library=library,
            scene_library_table_id="other-table",
        )

    with TestClient(
        create_vtt_app(
            service,
            scene_library=library,
            scene_library_table_id=TABLE_ID,
        ),
        raise_server_exceptions=False,
    ) as open_local:
        created = open_local.post(
            "/api/v1/scene-commands",
            json=_create_request("open-create", "open-scene", expected_revision=0),
        )
        assert created.status_code == 200
        assert created.json()["schema_version"] == VTT_SCENE_LIBRARY_RESPONSE_SCHEMA_VERSION
        assert created.json()["replayed"] is False


@pytest.mark.parametrize(
    ("method", "path", "body"),
    (
        ("get", "/api/v1/scenes", None),
        ("get", "/api/v1/scene-events?after=01", None),
        ("post", "/api/v1/scene-commands", "{not-json"),
    ),
)
def test_scene_routes_authenticate_before_cursor_or_body_validation(
    scene_api_client,
    method: str,
    path: str,
    body: str | None,
) -> None:
    client, _library, _service = scene_api_client
    response = client.request(
        method,
        path,
        content=body,
        headers={"content-type": "application/json"} if body is not None else None,
    )

    _assert_error(response, status_code=401, code="authentication_required")


def test_gm_mutates_while_player_and_spectator_receive_only_active_metadata(
    scene_api_client,
) -> None:
    client, library, _service = scene_api_client
    first = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json=_create_request("create-one", "one", expected_revision=0),
    )
    second = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json=_create_request("create-secret", "secret", expected_revision=1),
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["event"]["became_active"] is True
    assert second.json()["event"]["became_active"] is False

    gm_view = client.get("/api/v1/scenes", headers=_authorization("gm")).json()
    player_view = client.get("/api/v1/scenes", headers=_authorization("player")).json()
    spectator_view = client.get("/api/v1/scenes", headers=_authorization("spectator")).json()
    assert [entry["scene"]["scene_id"] for entry in gm_view["scenes"]] == [
        "one",
        "secret",
    ]
    assert [entry["scene"]["scene_id"] for entry in player_view["scenes"]] == ["one"]
    assert spectator_view == player_view
    assert player_view["revision"] == 2

    forbidden = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("player"),
        json=_create_request("player-create", "forbidden", expected_revision=2),
    )
    spectator_forbidden = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("spectator"),
        json=_create_request("spectator-create", "forbidden", expected_revision=2),
    )
    _assert_error(forbidden, status_code=403, code="scene_forbidden")
    _assert_error(spectator_forbidden, status_code=403, code="scene_forbidden")
    assert library.revision(TABLE_ID) == 2

    activated = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json={
            "schema_version": VTT_SCENE_LIBRARY_REQUEST_SCHEMA_VERSION,
            "session_id": SESSION_ID,
            "command": {
                "schema_version": SCENE_COMMAND_SCHEMA_VERSION,
                "command_type": "activate",
                "table_id": TABLE_ID,
                "command_id": "activate-secret",
                "expected_revision": 2,
                "scene_id": "secret",
            },
        },
    )
    assert activated.status_code == 200
    active_view = client.get("/api/v1/scenes", headers=_authorization("player")).json()
    assert active_view["active_scene_id"] == "secret"
    assert [entry["scene"]["scene_id"] for entry in active_view["scenes"]] == ["secret"]


def test_browser_integral_grid_size_is_canonicalized_at_the_http_boundary(
    scene_api_client,
) -> None:
    client, library, _service = scene_api_client
    request = _create_request("browser-create", "browser-map", expected_revision=0)
    request["command"]["scene"]["map_metadata"]["grid_size_px"] = 64

    response = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json=request,
    )

    assert response.status_code == 200
    assert response.json()["event"]["scene"]["map_metadata"]["grid_size_px"] == 64.0
    stored = library.snapshot(TABLE_ID).scene("browser-map")
    assert stored is not None
    assert stored.scene.map_metadata.grid_size_px == 64.0


def test_scene_binding_idempotency_and_store_conflicts_use_stable_errors(
    scene_api_client,
) -> None:
    client, _library, _service = scene_api_client
    request = _create_request("create-once", "one", expected_revision=0)
    first = client.post("/api/v1/scene-commands", headers=_authorization("gm"), json=request)
    retry = client.post("/api/v1/scene-commands", headers=_authorization("gm"), json=request)
    assert first.status_code == retry.status_code == 200
    assert retry.json()["replayed"] is True
    assert retry.json()["event"] == first.json()["event"]

    stale = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json=_create_request("stale", "stale", expected_revision=0),
    )
    assert _assert_error(stale, status_code=409, code="scene_stale_revision")["details"] == {
        "current_revision": 1
    }

    conflict = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json=_create_request("create-once", "different", expected_revision=0),
    )
    _assert_error(conflict, status_code=409, code="scene_command_id_conflict")

    binding = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json=_create_request(
            "wrong-binding",
            "wrong",
            expected_revision=1,
            session_id="wrong-session",
        ),
    )
    payload = _assert_error(binding, status_code=409, code="scene_binding_mismatch")
    assert payload["details"] == {
        "expected_session_id": SESSION_ID,
        "expected_table_id": TABLE_ID,
    }

    missing = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json={
            "schema_version": VTT_SCENE_LIBRARY_REQUEST_SCHEMA_VERSION,
            "session_id": SESSION_ID,
            "command": {
                "schema_version": SCENE_COMMAND_SCHEMA_VERSION,
                "command_type": "activate",
                "table_id": TABLE_ID,
                "command_id": "missing",
                "expected_revision": 1,
                "scene_id": "missing",
            },
        },
    )
    _assert_error(missing, status_code=404, code="scene_not_found")


def test_scene_store_failures_use_stable_nonleaking_errors(
    scene_api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, library, _service = scene_api_client

    def corrupt_snapshot(_table_id: str):
        raise SceneLibraryStoreCorruptionError("private corruption detail")

    monkeypatch.setattr(library, "snapshot", corrupt_snapshot)
    corrupt = client.get("/api/v1/scenes", headers=_authorization("gm"))
    payload = _assert_error(corrupt, status_code=500, code="scene_store_corrupt")
    assert "private corruption detail" not in payload["message"]

    def unavailable_snapshot(_table_id: str):
        raise sqlite3.OperationalError("private database path")

    monkeypatch.setattr(library, "snapshot", unavailable_snapshot)
    unavailable = client.get("/api/v1/scenes", headers=_authorization("gm"))
    payload = _assert_error(
        unavailable,
        status_code=503,
        code="scene_storage_unavailable",
    )
    assert "private database path" not in payload["message"]


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


def _sse_events(payload: str) -> list[tuple[int, dict[str, Any]]]:
    parsed: list[tuple[int, dict[str, Any]]] = []
    for block in payload.split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if ": " in line:
                name, value = line.split(": ", 1)
                fields[name] = value
        if "id" in fields and "data" in fields:
            assert fields["event"] == "vtt.scene_event"
            parsed.append((int(fields["id"]), json.loads(fields["data"])))
    return parsed


def test_scene_sse_hides_staged_metadata_and_advances_across_hidden_events(
    scene_api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, library, _service = scene_api_client
    library.execute(
        SceneCreateCommand(
            table_id=TABLE_ID,
            command_id="create-public",
            expected_revision=0,
            scene=_scene("public"),
        )
    )
    library.execute(
        SceneCreateCommand(
            table_id=TABLE_ID,
            command_id="create-secret",
            expected_revision=1,
            scene=_scene("secret"),
        )
    )
    library.execute(
        SceneDuplicateCommand(
            table_id=TABLE_ID,
            command_id="duplicate-secret",
            expected_revision=2,
            source_scene_id="secret",
            new_scene_id="secret-copy",
            new_name="Secret Copy",
        )
    )
    library.execute(
        SceneActivateCommand(
            table_id=TABLE_ID,
            command_id="activate-secret",
            expected_revision=3,
            scene_id="secret",
        )
    )

    seen_cursors: list[int] = []
    original_events_after = library.events_after

    def recording_events_after(table_id: str, sequence: int):
        seen_cursors.append(sequence)
        return original_events_after(table_id, sequence)

    monkeypatch.setattr(library, "events_after", recording_events_after)
    monkeypatch.setattr(scene_library_api, "SSE_POLL_INTERVAL_SECONDS", 0.001)
    monkeypatch.setattr(scene_library_api, "SSE_HEARTBEAT_INTERVAL_SECONDS", 0.01)

    status, headers, payload = asyncio.run(
        _capture_sse(
            client.app,
            "/api/v1/scene-events?after=0",
            headers=_authorization("player"),
            data_event_count=2,
        )
    )
    assert status == 200
    assert headers["content-type"].startswith("text/event-stream")
    assert [event_id for event_id, _event in _sse_events(payload)] == [1, 4]
    assert "Secret Copy" not in payload

    status, _headers, payload = asyncio.run(
        _capture_sse(
            client.app,
            "/api/v1/scene-events?after=1",
            headers={**_authorization("player"), "last-event-id": "4"},
            stop_on_heartbeat=True,
        )
    )
    assert status == 200
    assert _sse_events(payload) == []
    assert ": heartbeat\n\n" in payload
    assert 4 in seen_cursors

    invalid = client.get("/api/v1/scene-events?after=01", headers=_authorization("player"))
    _assert_error(invalid, status_code=400, code="invalid_scene_event_cursor")
