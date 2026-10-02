"""Live invitation authority and participant privacy at the world HTTP boundary."""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from dnd_sim.vtt import world_preparation
from dnd_sim.vtt.scene_library_contracts import SceneMapMetadata, SceneRecord
from dnd_sim.vtt.world_catalog_contracts import WorldArchiveCommand

from test_vtt_world_preparation import ROOT, launch, ready


@pytest.fixture
def workspace(tmp_path):
    app, client, admin, world = ready(tmp_path)
    opened = launch(client, admin, world).json()
    gm = {"Authorization": "Bearer " + opened["bearer_token"]}
    base = opened["workspace_api_path"] + "/api/v1"
    try:
        yield app, client, admin, world, opened, gm, base
    finally:
        client.close()
        app.state.close_owned_connections()


def issue(client, base, gm, *, command_id="invite", role="player"):
    response = client.post(
        base + "/invitations", headers=gm, json={"command_id": command_id, "role": role}
    )
    assert response.status_code == 201, response.text
    return response.json()


def join(client, issued, *, name="Guest"):
    response = client.post(
        ROOT + "/join",
        headers={"Authorization": "Bearer " + issued["invitation_token"]},
        json={"display_name": name},
    )
    assert response.status_code == 200, response.text
    opened = response.json()
    return opened, {"Authorization": "Bearer " + opened["bearer_token"]}


@pytest.mark.parametrize("role", ["player", "spectator"])
def test_invitation_join_is_world_bound_and_has_no_administration_authority(workspace, role):
    app, client, admin, world, opened, gm, base = workspace
    issued = issue(client, base, gm, role=role)
    assert issued["schema_version"] == "vtt.invitation_issued.v1"
    assert issued["replayed"] is False
    assert issued["invitation"]["participant"] is None
    replay = issue(client, base, gm, role=role)
    assert replay["replayed"] is True and replay["invitation_token"] is None
    guest, auth = join(client, issued)
    assert guest["world"] == world
    assert guest["session_id"] == opened["session_id"]
    assert guest["workspace_api_path"] == opened["workspace_api_path"]
    assert guest["table"]["current_participant"]["role"] == role
    assert guest["table"]["current_participant"]["owned_actor_ids"] == []
    assert client.get(base + "/table", headers=auth).json() == guest["table"]
    assert client.get(base + "/scenes", headers=auth).status_code == 200
    assert client.get(base + "/map-assets", headers=auth).status_code == 200
    assert client.get(ROOT + "/worlds", headers=auth).status_code == 401
    assert client.get(base + "/invitations", headers=auth).status_code == 403
    for endpoint in ["/invitations", "/scene-commands", "/map-assets"]:
        response = client.post(base + endpoint, headers=auth, content="not-json")
        assert response.status_code == 403, response.text
        assert response.json()["details"] == {}
        assert response.headers["cache-control"] == "no-store"
    assert (
        client.post(
            ROOT + "/join",
            headers={"Authorization": "Bearer " + issued["invitation_token"]},
            json={"display_name": "Another"},
        ).status_code
        == 401
    )
    listing = client.get(base + "/invitations", headers=gm).json()
    assert listing["schema_version"] == "vtt.world_invitations.v1"
    assert listing["invitations"][0]["participant"] == guest["table"]["current_participant"]
    assert issued["invitation_token"] not in str(listing)


def test_guest_survives_gm_return_and_logout_but_revoke_ends_access(workspace):
    app, client, admin, world, opened, gm, base = workspace
    issued = issue(client, base, gm)
    guest, auth = join(client, issued)
    assert (
        client.post(ROOT + "/worlds/" + world["world_id"] + "/return", headers=gm).status_code
        == 204
    )
    assert client.get(base + "/table", headers=auth).status_code == 200
    new_gm = launch(client, admin, world).json()
    gm = {"Authorization": "Bearer " + new_gm["bearer_token"]}
    revoke = base + "/invitations/" + issued["invitation"]["invitation_id"] + "/revoke"
    assert client.post(revoke, headers=gm).status_code == 204
    assert client.post(revoke, headers=gm).status_code == 204
    for endpoint in ["/table", "/scenes", "/map-assets", "/scene-events?after=invalid"]:
        response = client.get(base + endpoint, headers=auth)
        assert response.status_code == 401
        assert response.json()["details"] == {}


def test_invitation_authentication_precedes_bounded_body_validation(workspace):
    app, client, admin, world, opened, gm, base = workspace
    for headers in [{}, admin, gm, {"Authorization": "Bearer rejected"}]:
        response = client.post(ROOT + "/join", headers=headers, content="not-json")
        assert response.status_code == 401, response.text
        assert response.json()["details"] == {}
    issued = issue(client, base, gm)
    auth = {"Authorization": "Bearer " + issued["invitation_token"]}
    for body in [b"not-json", b"x" * 16385, b'{"display_name":""}', b'{"display_name":" Guest"}']:
        response = client.post(ROOT + "/join", headers=auth, content=body)
        assert response.status_code == 422
    join(client, issued)


def test_guest_return_releases_last_resource_and_prevents_reuse(workspace):
    app, client, admin, world, opened, gm, base = workspace
    guest, auth = join(client, issue(client, base, gm))
    return_path = ROOT + "/worlds/" + world["world_id"] + "/return"
    assert client.post(return_path, headers=gm).status_code == 204
    assert app.state.world_manager.open_resource_count == 1
    assert client.post(return_path, headers=auth).status_code == 204
    assert app.state.world_manager.open_resource_count == 0
    assert client.get(base + "/table", headers=auth).status_code == 401


def test_guest_capacity_failure_does_not_consume_invitation(workspace, monkeypatch):
    app, client, admin, world, opened, gm, base = workspace
    issued = issue(client, base, gm)
    monkeypatch.setattr(world_preparation, "MAX_WORLD_LAUNCHES", 1)
    response = client.post(
        ROOT + "/join",
        headers={"Authorization": "Bearer " + issued["invitation_token"]},
        json={"display_name": "Waiting guest"},
    )
    assert response.status_code == 503
    assert (
        client.get(base + "/invitations", headers=gm).json()["invitations"][0]["status"]
        == "pending"
    )
    assert (
        client.post(ROOT + "/worlds/" + world["world_id"] + "/return", headers=gm).status_code
        == 204
    )
    guest, auth = join(client, issued)
    assert client.get(base + "/table", headers=auth).status_code == 200


@pytest.mark.parametrize("cause", ["expiry", "archive", "durable_revocation", "durable_corruption"])
def test_guest_request_revalidates_canonical_durable_authority(workspace, cause):
    app, client, admin, world, opened, gm, base = workspace
    manager = app.state.world_manager
    issued = issue(client, base, gm)
    guest, auth = join(client, issued)
    client.post(ROOT + "/worlds/" + world["world_id"] + "/return", headers=gm)
    if cause == "expiry":
        now = manager._clock()
        manager._clock = lambda: now + world_preparation.GUEST_SESSION_SECONDS
    elif cause == "archive":
        manager._catalog.execute(
            WorldArchiveCommand(
                command_id="archive", expected_revision=1, world_id=world["world_id"]
            )
        )
    elif cause == "durable_revocation":
        manager._invitations.revoke(
            world["world_id"], world["table_id"], issued["invitation"]["invitation_id"]
        )
    else:
        manager._registry.execute("DELETE FROM _vtt_world_invitations")
        manager._registry.commit()
    response = client.get(base + "/table", headers=auth)
    assert response.status_code == 401
    assert response.json()["details"] == {}
    assert manager.open_resource_count == 0


@pytest.mark.parametrize("damage", ["missing_file", "missing_receipt", "unprepared"])
def test_guest_never_provisions_or_repairs_world_and_does_not_consume_on_failure(workspace, damage):
    app, client, admin, world, opened, gm, base = workspace
    manager = app.state.world_manager
    issued = issue(client, base, gm)
    client.post(ROOT + "/worlds/" + world["world_id"] + "/return", headers=gm)
    path = manager.database_path(world["world_id"])
    if damage in {"missing_file", "unprepared"}:
        path.unlink()
        if damage == "unprepared":
            manager._registry.execute("DELETE FROM _vtt_world_preparation_registry")
            manager._registry.commit()
    else:
        with sqlite3.connect(path) as connection:
            connection.execute("DELETE FROM _vtt_world_preparation_receipt")
    before = path.read_bytes() if path.exists() else None
    response = client.post(
        ROOT + "/join",
        headers={"Authorization": "Bearer " + issued["invitation_token"]},
        json={"display_name": "Guest"},
    )
    assert response.status_code in {401, 503}
    assert manager.open_resource_count == 0
    assert (path.read_bytes() if path.exists() else None) == before
    assert manager._invitations.list(world["world_id"], world["table_id"])[0].status == "pending"


@pytest.mark.parametrize("role", ["gm", "admin", "PLAYER", None, True])
def test_invitation_creation_rejects_roles_outside_player_or_spectator(workspace, role):
    app, client, admin, world, opened, gm, base = workspace
    response = client.post(
        base + "/invitations", headers=gm, json={"command_id": "bad-role", "role": role}
    )
    assert response.status_code == 422
    assert client.get(base + "/invitations", headers=gm).json()["invitations"] == []


def test_invitation_retry_change_conflicts_and_oversized_payload_is_bounded(workspace):
    app, client, admin, world, opened, gm, base = workspace
    issue(client, base, gm)
    response = client.post(
        base + "/invitations", headers=gm, json={"command_id": "invite", "role": "spectator"}
    )
    assert response.status_code == 409
    response = client.post(base + "/invitations", headers=gm, content=b"x" * 16385)
    assert response.status_code == 422


@pytest.mark.parametrize("cause", ["revoke", "expiry", "archive", "return"])
def test_guest_scene_stream_never_replays_inactive_history_and_rechecks_authority(workspace, cause):
    app, client, admin, world, opened, gm, base = workspace
    manager = app.state.world_manager
    for index in range(2):
        scene = SceneRecord(
            scene_id=f"private-scene-{index}",
            map_metadata=SceneMapMetadata(
                name=f"Private history {index}",
                width_px=128,
                height_px=128,
                grid_size_px=32.0,
                gridless=False,
            ),
        )
        response = client.post(
            base + "/scene-commands",
            headers=gm,
            json={
                "session_id": opened["session_id"],
                "command": {
                    "command_type": "create",
                    "command_id": f"scene-{index}",
                    "expected_revision": index,
                    "table_id": world["table_id"],
                    "scene": scene.model_dump(mode="json"),
                },
            },
        )
        assert response.status_code == 200, response.text
    response = client.post(
        base + "/scene-commands",
        headers=gm,
        json={
            "session_id": opened["session_id"],
            "command": {
                "command_type": "activate",
                "command_id": "activate",
                "expected_revision": 2,
                "table_id": world["table_id"],
                "scene_id": "private-scene-1",
            },
        },
    )
    assert response.status_code == 200, response.text
    issued = issue(client, base, gm)
    guest, auth = join(client, issued)
    view = client.get(base + "/scenes", headers=auth).json()
    assert "Private history 0" not in str(view)
    assert "Private history 1" in str(view)
    client.post(ROOT + "/worlds/" + world["world_id"] + "/return", headers=gm)

    async def stream():
        sent = []

        async def receive():
            await asyncio.Event().wait()

        async def send(message):
            sent.append(message)
            if b"vtt.scene_refresh" in message.get("body", b""):
                assert manager.open_resource_count == 1
                if cause == "revoke":
                    manager._invitations.revoke(
                        world["world_id"], world["table_id"], issued["invitation"]["invitation_id"]
                    )
                elif cause == "expiry":
                    now = manager._clock()
                    manager._clock = lambda: now + world_preparation.GUEST_SESSION_SECONDS
                elif cause == "archive":
                    manager._catalog.execute(
                        WorldArchiveCommand(
                            command_id="archive", expected_revision=1, world_id=world["world_id"]
                        )
                    )
                else:
                    manager.return_world(world["world_id"], guest["bearer_token"])

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/scene-events",
            "raw_path": b"/api/v1/scene-events",
            "query_string": b"after=0",
            "root_path": "",
            "headers": [(b"authorization", auth["Authorization"].encode())],
            "server": ("test", 80),
            "client": ("test", 1234),
            "path_params": {"world_id": world["world_id"]},
        }
        await asyncio.wait_for(manager(scope, receive, send), timeout=2)
        return b"".join(message.get("body", b"") for message in sent)

    output = asyncio.run(stream())
    assert b'event: vtt.scene_refresh\ndata: {"revision":3}' in output
    assert b"Private history" not in output and b"private-scene" not in output
    assert issued["invitation_token"].encode() not in output
    assert guest["bearer_token"].encode() not in output
    assert manager.open_resource_count == 0


@pytest.mark.parametrize("malformed", [False, True])
def test_join_revalidates_invitation_after_chunked_body_before_payload_validation(
    workspace, malformed
):
    app, client, admin, world, opened, gm, base = workspace
    manager = app.state.world_manager
    issued = issue(client, base, gm)
    body = b"not-json" if malformed else b'{"display_name":"Guest"}'

    async def post():
        sent = []
        chunks = 0

        async def receive():
            nonlocal chunks
            chunks += 1
            if chunks == 1:
                return {"type": "http.request", "body": body[:4], "more_body": True}
            if chunks == 2:
                manager._invitations.revoke(
                    world["world_id"], world["table_id"], issued["invitation"]["invitation_id"]
                )
                return {"type": "http.request", "body": body[4:], "more_body": False}
            await asyncio.Event().wait()

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "method": "POST",
            "scheme": "http",
            "path": ROOT + "/join",
            "raw_path": (ROOT + "/join").encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"authorization", ("Bearer " + issued["invitation_token"]).encode()),
                (b"content-type", b"application/json"),
            ],
            "server": ("test", 80),
            "client": ("test", 1234),
        }
        await asyncio.wait_for(app(scope, receive, send), timeout=2)
        return sent

    sent = asyncio.run(post())
    assert sent[0]["status"] == 401
    payload = json.loads(b"".join(message.get("body", b"") for message in sent))
    assert payload["code"] == "authentication_required" and payload["details"] == {}
    assert manager._invitations.list(world["world_id"], world["table_id"])[0].participant is None
