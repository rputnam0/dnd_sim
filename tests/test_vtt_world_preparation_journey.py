"""Black-box acceptance journeys for real worlds, without a demo or engine fixture."""

from __future__ import annotations

import base64
import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from dnd_sim.vtt.map_asset_api import VTT_MAP_ASSET_UPLOAD_REQUEST_SCHEMA_VERSION
from dnd_sim.vtt.map_asset_contracts import MAP_ASSET_UPLOAD_COMMAND_SCHEMA_VERSION
from dnd_sim.vtt.scene_library_api import VTT_SCENE_LIBRARY_REQUEST_SCHEMA_VERSION
from dnd_sim.vtt.scene_library_contracts import (
    SCENE_COMMAND_SCHEMA_VERSION,
    SCENE_MAP_METADATA_SCHEMA_VERSION,
    SCENE_RECORD_SCHEMA_VERSION,
    SceneMapMetadata,
    SceneRecord,
)
from dnd_sim.vtt.standalone_app import create_standalone_app

ROOT = "/api/v1/installation"
ADMIN = {
    "username": "journey-gm",
    "display_name": "Preparation GM",
    "password": "synthetic preparation journey password",
}


def _headers(issuance: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {issuance['bearer_token']}"}


def _login(client: TestClient) -> dict:
    response = client.post(
        ROOT + "/login", json={"username": ADMIN["username"], "password": ADMIN["password"]}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _world(client: TestClient, admin: dict, name: str, revision: int) -> dict:
    response = client.post(
        ROOT + "/worlds/create",
        headers=_headers(admin),
        json={"command_id": f"world-{revision}", "expected_revision": revision, "name": name},
    )
    assert response.status_code == 200, response.text
    return response.json()["receipt"]["event"]["world"]


def _launch(client: TestClient, admin: dict, world: dict) -> dict:
    response = client.post(f"{ROOT}/worlds/{world['world_id']}/launch", headers=_headers(admin))
    assert response.status_code == 200, response.text
    launch = response.json()
    assert set(launch) == {
        "schema_version",
        "world",
        "session_id",
        "table",
        "workspace_api_path",
        "bearer_token",
    }
    assert launch["schema_version"] == "vtt.world_launch.v1"
    assert launch["world"] == world
    assert launch["workspace_api_path"] == f"/api/v1/worlds/{world['world_id']}"
    assert launch["table"]["table_id"] == world["table_id"]
    assert launch["table"]["access_mode"] == "protected"
    assert launch["table"]["current_participant"]["role"] == "gm"
    assert launch["table"]["current_participant"]["owned_actor_ids"] == []
    assert launch["bearer_token"] != admin["bearer_token"]
    return launch


def _get(client: TestClient, launch: dict, suffix: str):
    return client.get(launch["workspace_api_path"] + "/api/v1/" + suffix, headers=_headers(launch))


def _author_map_scene(client: TestClient, launch: dict, *, color: str, name: str) -> bytes:
    image = io.BytesIO()
    Image.new("RGB", (128, 128), color=color).save(image, "PNG")
    content = image.getvalue()
    upload = {
        "schema_version": VTT_MAP_ASSET_UPLOAD_REQUEST_SCHEMA_VERSION,
        "session_id": launch["session_id"],
        "command": {
            "schema_version": MAP_ASSET_UPLOAD_COMMAND_SCHEMA_VERSION,
            "command_id": "same-upload-id",
            "expected_revision": 0,
            "table_id": launch["world"]["table_id"],
            "asset_id": "same-map-id",
            "alt_text": name,
            "content_base64": base64.b64encode(content).decode("ascii"),
        },
    }
    path = launch["workspace_api_path"] + "/api/v1/map-assets"
    response = client.post(path, headers=_headers(launch), json=upload)
    assert response.status_code == 200, response.text
    reference = response.json()["asset"]["reference"]
    replay = client.post(path, headers=_headers(launch), json=upload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True
    scene = SceneRecord(
        schema_version=SCENE_RECORD_SCHEMA_VERSION,
        scene_id="same-scene-id",
        map_metadata=SceneMapMetadata(
            schema_version=SCENE_MAP_METADATA_SCHEMA_VERSION,
            name=name,
            width_px=128,
            height_px=128,
            grid_size_px=32.0,
            gridless=False,
            asset=reference,
        ),
    )
    command = {
        "schema_version": VTT_SCENE_LIBRARY_REQUEST_SCHEMA_VERSION,
        "session_id": launch["session_id"],
        "command": {
            "schema_version": SCENE_COMMAND_SCHEMA_VERSION,
            "command_type": "create",
            "table_id": launch["world"]["table_id"],
            "command_id": "same-scene-command-id",
            "expected_revision": 0,
            "scene": scene.model_dump(mode="json"),
        },
    }
    response = client.post(
        launch["workspace_api_path"] + "/api/v1/scene-commands",
        headers=_headers(launch),
        json=command,
    )
    assert response.status_code == 200, response.text
    return content


def test_empty_world_authoring_return_restart_and_isolated_identical_ids(tmp_path: Path) -> None:
    database = tmp_path / "installation.sqlite"
    claims: list[str] = []
    with TestClient(
        create_standalone_app(database, bootstrap_claim_delivery=claims.append)
    ) as client:
        assert (
            client.post(
                ROOT + "/setup", headers={"X-VTT-Setup-Claim": claims[0]}, json=ADMIN
            ).status_code
            == 201
        )
        admin = _login(client)
        worlds = [
            _world(client, admin, name, index) for index, name in enumerate(("Forest", "Sea"))
        ]
        launches = [_launch(client, admin, world) for world in worlds]
        for launch in launches:
            scenes = _get(client, launch, "scenes").json()
            assert scenes["scenes"] == []
            assert scenes["active_scene_id"] is None
            assert scenes["revision"] == 0
            assert _get(client, launch, "map-assets").json()["assets"] == []
            assert _get(client, launch, "session").status_code == 404
        contents = [
            _author_map_scene(client, launches[0], color="green", name="Private forest"),
            _author_map_scene(client, launches[1], color="blue", name="Private sea"),
        ]
        views = [_get(client, launch, "scenes").json() for launch in launches]
        for index, launch in enumerate(launches):
            assert views[index]["revision"] == 1
            assert views[index]["active_scene_id"] == "same-scene-id"
            assert len(views[index]["scenes"]) == 1
            reference = views[index]["scenes"][0]["scene"]["map_metadata"]["asset"]
            asset_path = launch["workspace_api_path"] + reference["content_path"]
            response = client.get(asset_path, headers=_headers(launch))
            assert response.content == contents[index]
            assert client.get(asset_path, headers=_headers(launches[1 - index])).status_code == 401
            response = client.post(
                f"{ROOT}/worlds/{launch['world']['world_id']}/return", headers=_headers(launch)
            )
            assert response.status_code == 204, response.text
            assert _get(client, launch, "scenes").status_code == 401
        reopened = _launch(client, admin, worlds[0])
        assert _get(client, reopened, "scenes").json() == views[0]

    with TestClient(create_standalone_app(database)) as client:
        admin = _login(client)
        for index, world in enumerate(worlds):
            reopened = _launch(client, admin, world)
            assert reopened["session_id"] == launches[index]["session_id"]
            assert reopened["table"] == launches[index]["table"]
            assert _get(client, reopened, "scenes").json() == views[index]
            reference = views[index]["scenes"][0]["scene"]["map_metadata"]["asset"]
            assert (
                client.get(
                    reopened["workspace_api_path"] + reference["content_path"],
                    headers=_headers(reopened),
                ).content
                == contents[index]
            )
            assert _get(client, launches[index], "table").status_code == 401


def test_world_boundary_rejects_wrong_credentials_before_payload_and_revokes_on_logout(
    tmp_path: Path,
) -> None:
    claims: list[str] = []
    with TestClient(
        create_standalone_app(
            tmp_path / "installation.sqlite", bootstrap_claim_delivery=claims.append
        )
    ) as client:
        assert (
            client.post(
                ROOT + "/setup", headers={"X-VTT-Setup-Claim": claims[0]}, json=ADMIN
            ).status_code
            == 201
        )
        admin = _login(client)
        world = _world(client, admin, "Private world", 0)
        launch = _launch(client, admin, world)
        path = launch["workspace_api_path"] + "/api/v1/scene-commands"
        for headers in (
            {},
            _headers(admin),
            [("Authorization", _headers(launch)["Authorization"])] * 2,
        ):
            response = client.post(path, content=b'{"secret-input":', headers=headers)
            assert response.status_code == 401, response.text
            assert response.json()["details"] == {}
            assert "secret-input" not in response.text
        assert client.post(ROOT + "/logout", headers=_headers(admin)).status_code == 204
        for suffix in ("table", "scenes", "map-assets", "scene-events?after=0"):
            response = _get(client, launch, suffix)
            assert response.status_code == 401, response.text
            assert response.json()["details"] == {}
