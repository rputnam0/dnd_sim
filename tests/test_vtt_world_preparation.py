"""Preparation-only world lifetime, durable provisioning, and access boundaries."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from dnd_sim.vtt.standalone_app import create_standalone_app
from dnd_sim.vtt import world_preparation
from dnd_sim.vtt.scene_library_contracts import SceneMapMetadata, SceneRecord

ROOT = "/api/v1/installation"
ADMIN = {
    "username": "operator",
    "display_name": "World Author",
    "password": "a private long password",
}


def ready(tmp_path: Path):
    claims = []
    app = create_standalone_app(
        tmp_path / "installation.sqlite", bootstrap_claim_delivery=claims.append
    )
    client = TestClient(app)
    assert (
        client.post(
            ROOT + "/setup", headers={"X-VTT-Setup-Claim": claims[0]}, json=ADMIN
        ).status_code
        == 201
    )
    login = client.post(
        ROOT + "/login", json={"username": ADMIN["username"], "password": ADMIN["password"]}
    ).json()
    headers = {"Authorization": "Bearer " + login["bearer_token"]}
    world = client.post(
        ROOT + "/worlds/create",
        headers=headers,
        json={"command_id": "create", "expected_revision": 0, "name": "Empty world"},
    ).json()["receipt"]["event"]["world"]
    return app, client, headers, world


def launch(client, headers, world):
    return client.post(ROOT + "/worlds/" + world["world_id"] + "/launch", headers=headers)


def test_explicit_prepare_creates_empty_world_and_return_releases_connection(
    tmp_path: Path,
) -> None:
    app, client, headers, world = ready(tmp_path)
    try:
        assert not list(tmp_path.glob("*.worlds/*.sqlite"))
        assert client.get(ROOT + "/worlds", headers=headers).json()["launch_supported"] is True
        response = launch(client, headers, world)
        assert response.status_code == 200, response.text
        opened = response.json()
        assert set(opened) == {
            "schema_version",
            "world",
            "session_id",
            "table",
            "workspace_api_path",
            "bearer_token",
        }
        assert opened["schema_version"] == "vtt.world_launch.v1"
        assert opened["world"] == world
        assert opened["table"]["access_mode"] == "protected"
        assert opened["table"]["current_participant"]["role"] == "gm"
        assert opened["table"]["current_participant"]["display_name"] == "World Author"
        auth = {"Authorization": "Bearer " + opened["bearer_token"]}
        base = opened["workspace_api_path"] + "/api/v1"
        assert client.get(base + "/table", headers=auth).json() == opened["table"]
        scenes = client.get(base + "/scenes", headers=auth).json()
        assert (
            scenes["revision"] == 0 and scenes["scenes"] == [] and scenes["active_scene_id"] is None
        )
        assert client.get(base + "/map-assets", headers=auth).json()["assets"] == []
        assert client.get(base + "/session", headers=auth).status_code == 404
        assert client.get(base + "/scenes", headers=headers).status_code == 401
        assert (
            client.post(ROOT + "/worlds/" + world["world_id"] + "/return", headers=auth).status_code
            == 204
        )
        assert client.get(base + "/scenes", headers=auth).status_code == 401
        assert app.state.world_manager.open_resource_count == 0
        reopened = launch(client, headers, world).json()
        assert reopened["session_id"] == opened["session_id"]
        assert reopened["table"] == opened["table"]
        assert reopened["bearer_token"] != opened["bearer_token"]
    finally:
        client.close()
        app.state.close_owned_connections()


@pytest.mark.parametrize(
    "damage", ["missing_file", "missing_scene_table", "missing_metadata", "receipt", "partial_file"]
)
def test_damaged_or_partial_world_is_never_recreated(tmp_path: Path, damage: str) -> None:
    app, client, headers, world = ready(tmp_path)
    try:
        path = app.state.world_manager.database_path(world["world_id"])
        if damage == "partial_file":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        else:
            opened = launch(client, headers, world).json()
            auth = {"Authorization": "Bearer " + opened["bearer_token"]}
            client.post(ROOT + "/worlds/" + world["world_id"] + "/return", headers=auth)
            if damage == "missing_file":
                path.unlink()
            else:
                with sqlite3.connect(path) as connection:
                    if damage == "missing_scene_table":
                        connection.execute("DROP TABLE _vtt_scene_library_event_log")
                    elif damage == "missing_metadata":
                        connection.execute("DELETE FROM _vtt_map_asset_store_metadata")
                    else:
                        connection.execute("DELETE FROM _vtt_world_preparation_receipt")
        before = path.read_bytes() if path.exists() else None
        response = launch(client, headers, world)
        assert response.status_code == 503, response.text
        assert response.json()["details"] == {}
        assert (path.read_bytes() if path.exists() else None) == before
        assert app.state.world_manager.open_resource_count == 0
    finally:
        client.close()
        app.state.close_owned_connections()


def test_world_authentication_precedes_body_and_duplicate_headers_are_rejected(
    tmp_path: Path,
) -> None:
    app, client, headers, world = ready(tmp_path)
    try:
        opened = launch(client, headers, world).json()
        base = opened["workspace_api_path"] + "/api/v1"
        for endpoint in ["/scene-commands", "/map-assets"]:
            for bad_headers in [
                {},
                headers,
                [("Authorization", "Bearer " + opened["bearer_token"])] * 2,
            ]:
                response = client.post(base + endpoint, headers=bad_headers, content="not json")
                assert response.status_code == 401, response.text
                assert response.json()["details"] == {}
        assert client.post(ROOT + "/logout", headers=headers).status_code == 204
        auth = {"Authorization": "Bearer " + opened["bearer_token"]}
        assert client.get(base + "/table", headers=auth).status_code == 401
        assert app.state.world_manager.open_resource_count == 0
    finally:
        client.close()
        app.state.close_owned_connections()


def test_return_only_releases_one_launch_and_sessions_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client, headers, world = ready(tmp_path)
    monkeypatch.setattr(world_preparation, "MAX_WORLD_LAUNCHES", 2)
    try:
        first, second = [launch(client, headers, world).json() for _ in range(2)]
        assert app.state.world_manager.open_resource_count == 1
        assert launch(client, headers, world).status_code == 503
        assert (
            client.post(
                ROOT + "/worlds/" + world["world_id"] + "/return",
                headers={"Authorization": "Bearer " + first["bearer_token"]},
            ).status_code
            == 204
        )
        assert app.state.world_manager.open_resource_count == 1
        assert (
            client.get(
                second["workspace_api_path"] + "/api/v1/table",
                headers={"Authorization": "Bearer " + second["bearer_token"]},
            ).status_code
            == 200
        )
        assert launch(client, headers, world).status_code == 200
    finally:
        client.close()
        app.state.close_owned_connections()
    assert app.state.world_manager.open_resource_count == 0


@pytest.mark.parametrize("cause", ["archive", "expiry"])
def test_archive_and_original_admin_expiry_revoke_world_capability(
    tmp_path: Path, cause: str
) -> None:
    app, client, headers, world = ready(tmp_path)
    try:
        opened = launch(client, headers, world).json()
        if cause == "archive":
            response = client.post(
                ROOT + "/worlds/archive",
                headers=headers,
                json={
                    "command_id": "archive",
                    "expected_revision": 1,
                    "world_id": world["world_id"],
                },
            )
            assert response.status_code == 200, response.text
            assert launch(client, headers, world).status_code == 409
        else:
            authority = app.state.world_manager._installation
            now = authority._clock()
            authority._clock = lambda: now + 100_000
        for endpoint in [
            "/table",
            "/scenes",
            "/scene-events?after=not-a-number",
            "/map-assets/secret/content.png",
        ]:
            response = client.get(
                opened["workspace_api_path"] + "/api/v1" + endpoint,
                headers={"Authorization": "Bearer " + opened["bearer_token"]},
            )
            assert response.status_code == 401, response.text
            assert response.json()["details"] == {}
        assert app.state.world_manager.open_resource_count == 0
    finally:
        client.close()
        app.state.close_owned_connections()


def test_failed_store_provisioning_closes_connection_and_never_retries_partial_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client, headers, world = ready(tmp_path)
    opened_connections = []

    def failing_store(connection, **kwargs):
        opened_connections.append(connection)
        raise sqlite3.DatabaseError("injected provisioning failure")

    monkeypatch.setattr(world_preparation, "SQLiteMapAssetStore", failing_store)
    try:
        for _ in range(2):
            response = launch(client, headers, world)
            assert response.status_code == 503, response.text
        assert len(opened_connections) == 1
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            opened_connections[0].execute("SELECT 1")
        assert app.state.world_manager.open_resource_count == 0
    finally:
        client.close()
        app.state.close_owned_connections()


@pytest.mark.parametrize("endpoint", ["scene-commands", "map-assets"])
@pytest.mark.parametrize("malformed", [False, True])
def test_revocation_while_reading_chunked_body_still_returns_authentication_error(
    tmp_path: Path, endpoint: str, malformed: bool
) -> None:
    app, client, headers, world = ready(tmp_path)
    manager = app.state.world_manager
    try:
        opened = launch(client, headers, world).json()
        token = opened["bearer_token"]
        command = {
            "command_id": "in-flight-command",
            "expected_revision": 0,
            "table_id": world["table_id"],
        }
        if endpoint == "scene-commands":
            command.update(
                {
                    "command_type": "create",
                    "scene": SceneRecord(
                        scene_id="in-flight-scene",
                        map_metadata=SceneMapMetadata(
                            name="Private scene",
                            width_px=128,
                            height_px=128,
                            grid_size_px=32.0,
                            gridless=False,
                        ),
                    ).model_dump(mode="json"),
                }
            )
        else:
            image = io.BytesIO()
            Image.new("RGB", (8, 8)).save(image, "PNG")
            command.update(
                {
                    "asset_id": "in-flight-map",
                    "alt_text": "Private map",
                    "content_base64": base64.b64encode(image.getvalue()).decode(),
                }
            )
        body = (
            b"{malformed-private-input"
            if malformed
            else json.dumps({"session_id": opened["session_id"], "command": command}).encode()
        )
        midpoint = len(body) // 2

        async def post():
            sent = []
            first_chunk = True

            async def receive():
                nonlocal first_chunk
                if first_chunk:
                    first_chunk = False
                    return {"type": "http.request", "body": body[:midpoint], "more_body": True}
                manager._installation.revoke_session(
                    headers["Authorization"].removeprefix("Bearer ")
                )
                return {"type": "http.request", "body": body[midpoint:], "more_body": False}

            async def send(message):
                sent.append(message)

            scope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.4"},
                "method": "POST",
                "scheme": "http",
                "path": "/api/v1/" + endpoint,
                "raw_path": ("/api/v1/" + endpoint).encode(),
                "query_string": b"",
                "root_path": "",
                "headers": [
                    (b"authorization", ("Bearer " + token).encode()),
                    (b"content-type", b"application/json"),
                ],
                "server": ("test", 80),
                "client": ("test", 1234),
                "path_params": {"world_id": world["world_id"]},
            }
            await manager(scope, receive, send)
            return sent

        sent = asyncio.run(post())
        assert sent[0]["status"] == 401
        response = json.loads(sent[1]["body"])
        assert response["code"] == "authentication_required"
        assert response["details"] == {}
        assert manager.open_resource_count == 0
        with sqlite3.connect(manager.database_path(world["world_id"])) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM _vtt_scene_library_event_log"
            ).fetchone() == (0,)
            assert connection.execute("SELECT COUNT(*) FROM _vtt_map_asset").fetchone() == (0,)
    finally:
        client.close()
        app.state.close_owned_connections()


@pytest.mark.parametrize("cause", ["return", "logout", "archive", "expiry"])
def test_live_stream_rechecks_authority_between_already_queued_events(
    tmp_path: Path, cause: str
) -> None:
    app, client, headers, world = ready(tmp_path)
    manager = app.state.world_manager
    try:
        opened = launch(client, headers, world).json()
        token = opened["bearer_token"]
        for index in range(2):
            scene = SceneRecord(
                schema_version="vtt.scene_record.v1",
                scene_id=f"scene-{index}",
                map_metadata=SceneMapMetadata(
                    schema_version="vtt.scene_map_metadata.v1",
                    name=f"Secret scene {index}",
                    width_px=128,
                    height_px=128,
                    grid_size_px=32.0,
                    gridless=False,
                ),
            )
            response = client.post(
                opened["workspace_api_path"] + "/api/v1/scene-commands",
                headers={"Authorization": "Bearer " + token},
                json={
                    "session_id": opened["session_id"],
                    "command": {
                        "schema_version": "vtt.scene_command.v1",
                        "command_type": "create",
                        "command_id": f"create-{index}",
                        "table_id": world["table_id"],
                        "expected_revision": index,
                        "scene": scene.model_dump(mode="json"),
                    },
                },
            )
            assert response.status_code == 200, response.text

        async def stream():
            sent = []
            requested = False

            async def receive():
                nonlocal requested
                if not requested:
                    requested = True
                    return {"type": "http.request", "body": b"", "more_body": False}
                await asyncio.Event().wait()

            async def send(message):
                sent.append(message)
                if message["type"] == "http.response.body" and b"id: 1\n" in message.get(
                    "body", b""
                ):
                    assert manager.open_resource_count == 1
                    if cause == "return":
                        manager.return_world(world["world_id"], token)
                    elif cause == "logout":
                        manager._installation.revoke_session(
                            headers["Authorization"].removeprefix("Bearer ")
                        )
                    elif cause == "archive":
                        from dnd_sim.vtt.world_catalog_contracts import WorldArchiveCommand

                        manager._catalog.execute(
                            WorldArchiveCommand(
                                command_id="archive-stream",
                                expected_revision=1,
                                world_id=world["world_id"],
                            )
                        )
                    else:
                        now = manager._installation._clock()
                        manager._installation._clock = lambda: now + 100_000
                    # A live generator keeps its connection until ASGI unwinds.
                    assert manager.open_resource_count == 1

            scope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.4"},
                "method": "GET",
                "scheme": "http",
                "path": "/api/v1/scene-events",
                "raw_path": b"/api/v1/scene-events",
                "query_string": b"",
                "root_path": "",
                "headers": [(b"authorization", ("Bearer " + token).encode())],
                "server": ("test", 80),
                "client": ("test", 1234),
                "path_params": {"world_id": world["world_id"]},
            }
            await asyncio.wait_for(manager(scope, receive, send), timeout=2)
            return b"".join(message.get("body", b"") for message in sent)

        output = asyncio.run(stream())
        assert b"id: 1\n" in output
        assert b"id: 2\n" not in output
        assert manager.open_resource_count == 0
    finally:
        client.close()
        app.state.close_owned_connections()
