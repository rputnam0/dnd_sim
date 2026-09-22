from __future__ import annotations

import base64
import hashlib
import io
import random
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from dnd_sim.interactive import (
    EngineTransition,
    EngineVersionPins,
    PendingReaction,
    PreviewOutcome,
    SessionCommand,
)
from dnd_sim.vtt.access import TableAccessPolicy
from dnd_sim.vtt.event_store import SQLiteSessionEventStore
from dnd_sim.vtt.http_api import VTT_ERROR_SCHEMA_VERSION, create_vtt_app
from dnd_sim.vtt.map_asset_api import (
    VTT_MAP_ASSET_UPLOAD_REQUEST_SCHEMA_VERSION,
    VTT_MAP_ASSET_UPLOAD_RESPONSE_SCHEMA_VERSION,
)
from dnd_sim.vtt.map_asset_contracts import MAP_ASSET_UPLOAD_COMMAND_SCHEMA_VERSION
from dnd_sim.vtt.map_asset_store import SQLiteMapAssetStore
from dnd_sim.vtt.participants import (
    PARTICIPANT_SCHEMA_VERSION,
    ROSTER_SCHEMA_VERSION,
    TableParticipant,
    TableRoster,
)
from dnd_sim.vtt.scene_library_contracts import (
    SCENE_COMMAND_SCHEMA_VERSION,
    SCENE_EXPORT_SCHEMA_VERSION,
    SceneCreateCommand,
    SceneMapAssetReference,
    SceneMapMetadata,
    SceneRecord,
)
from dnd_sim.vtt.scene_library_api import VTT_SCENE_LIBRARY_REQUEST_SCHEMA_VERSION
from dnd_sim.vtt.scene_library_store import SQLiteSceneLibrary
from dnd_sim.vtt.session_service import VTTSessionService

SESSION_ID = "asset-session"
TABLE_ID = "asset-table"
TOKENS = {
    "gm": "gm-asset-token-1234",
    "player": "player-asset-token-1234",
    "spectator": "spectator-asset-token-1234",
}


class _ProjectionDriver:
    version_pins = EngineVersionPins(
        engine_version="asset-http@1",
        rules_version="asset-rules@1",
        content_version="asset-content@1",
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
        raise AssertionError("asset tests do not open reactions")


def _participant(participant_id: str, role: str) -> TableParticipant:
    return TableParticipant(
        schema_version=PARTICIPANT_SCHEMA_VERSION,
        participant_id=participant_id,
        display_name=participant_id.title(),
        role=role,
        owned_actor_ids=(),
    )


def _policy() -> TableAccessPolicy:
    return TableAccessPolicy(
        roster=TableRoster(
            schema_version=ROSTER_SCHEMA_VERSION,
            table_id=TABLE_ID,
            participants=(
                _participant("gm", "gm"),
                _participant("player", "player"),
                _participant("spectator", "spectator"),
            ),
        ),
        bearer_tokens=TOKENS,
    )


def _authorization(participant_id: str) -> dict[str, str]:
    return {"authorization": f"Bearer {TOKENS[participant_id]}"}


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (80, 60), color=(12, 40, 35)).save(output, format="PNG")
    return output.getvalue()


def _upload_request(
    *,
    command_id: str = "upload-map",
    asset_id: str = "moon-temple",
    expected_revision: int = 0,
    session_id: str = SESSION_ID,
    table_id: str = TABLE_ID,
    content: bytes | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": VTT_MAP_ASSET_UPLOAD_REQUEST_SCHEMA_VERSION,
        "session_id": session_id,
        "command": {
            "schema_version": MAP_ASSET_UPLOAD_COMMAND_SCHEMA_VERSION,
            "table_id": table_id,
            "command_id": command_id,
            "expected_revision": expected_revision,
            "asset_id": asset_id,
            "alt_text": "A top-down moon temple battle map.",
            "content_base64": base64.b64encode(_png_bytes() if content is None else content).decode(
                "ascii"
            ),
        },
    }


@pytest.fixture
def asset_api(tmp_path: Path):
    database_path = tmp_path / "asset-http.sqlite3"
    session_connection = sqlite3.connect(database_path, check_same_thread=False)
    scene_connection = sqlite3.connect(database_path, check_same_thread=False)
    asset_connection = sqlite3.connect(database_path, check_same_thread=False)
    service = VTTSessionService.open(
        session_id=SESSION_ID,
        initial_state={"value": 0},
        driver=_ProjectionDriver(),
        seed=19,
        event_store=SQLiteSessionEventStore(session_connection),
    )
    scenes = SQLiteSceneLibrary(scene_connection)
    assets = SQLiteMapAssetStore(asset_connection)
    app = create_vtt_app(
        service,
        access_policy=_policy(),
        scene_library=scenes,
        map_asset_store=assets,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, assets, scenes, service
    asset_connection.close()
    scene_connection.close()
    session_connection.close()


def _assert_error(response, *, status_code: int, code: str) -> dict[str, Any]:
    assert response.status_code == status_code
    payload = response.json()
    assert payload["schema_version"] == VTT_ERROR_SCHEMA_VERSION
    assert payload["code"] == code
    assert payload["message"]
    assert isinstance(payload["details"], dict)
    assert "traceback" not in response.text.lower()
    return payload


def test_asset_routes_are_optional_and_require_scene_library_for_protected_views(
    asset_api,
) -> None:
    _client, assets, _scenes, service = asset_api
    with TestClient(create_vtt_app(service), raise_server_exceptions=False) as no_assets:
        assert no_assets.get("/api/v1/map-assets").status_code == 404
        assert no_assets.post("/api/v1/map-assets", json={}).status_code == 404

    with pytest.raises(ValueError, match="map_asset_store"):
        create_vtt_app(service, map_asset_table_id=TABLE_ID)
    with pytest.raises(ValueError, match="scene_library"):
        create_vtt_app(service, access_policy=_policy(), map_asset_store=assets)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    (
        ("get", "/api/v1/map-assets", None),
        ("post", "/api/v1/map-assets", "{not-json"),
        ("get", "/api/v1/map-assets/anything/content.png", None),
    ),
)
def test_asset_routes_authenticate_before_body_or_dynamic_content_lookup(
    asset_api,
    method: str,
    path: str,
    body: str | None,
) -> None:
    client, _assets, _scenes, _service = asset_api
    response = client.request(
        method,
        path,
        content=body,
        headers={"content-type": "application/json"} if body is not None else None,
    )

    _assert_error(response, status_code=401, code="authentication_required")


def test_gm_uploads_idempotently_while_other_roles_cannot_mutate(asset_api) -> None:
    client, assets, _scenes, _service = asset_api
    request = _upload_request()

    uploaded = client.post(
        "/api/v1/map-assets",
        headers=_authorization("gm"),
        json=request,
    )
    replayed = client.post(
        "/api/v1/map-assets",
        headers=_authorization("gm"),
        json=request,
    )

    assert uploaded.status_code == replayed.status_code == 200
    assert uploaded.json()["schema_version"] == VTT_MAP_ASSET_UPLOAD_RESPONSE_SCHEMA_VERSION
    assert uploaded.json()["replayed"] is False
    assert replayed.json()["replayed"] is True
    assert replayed.json()["asset"] == uploaded.json()["asset"]
    assert uploaded.json()["asset"]["reference"]["content_path"] == (
        "/api/v1/map-assets/moon-temple/content.png"
    )
    for participant_id in ("player", "spectator"):
        forbidden = client.post(
            "/api/v1/map-assets",
            headers=_authorization(participant_id),
            json=_upload_request(
                command_id=f"{participant_id}-upload",
                asset_id=f"{participant_id}-map",
                expected_revision=1,
            ),
        )
        _assert_error(forbidden, status_code=403, code="map_asset_forbidden")
    assert assets.revision(TABLE_ID) == 1


def test_content_and_catalog_hide_inactive_assets_from_non_gms(asset_api) -> None:
    client, _assets, scenes, _service = asset_api
    uploaded = client.post(
        "/api/v1/map-assets",
        headers=_authorization("gm"),
        json=_upload_request(),
    ).json()
    reference = SceneMapAssetReference.model_validate(uploaded["asset"]["reference"])

    hidden = client.get(reference.content_path, headers=_authorization("player"))
    _assert_error(hidden, status_code=404, code="map_asset_not_found")
    assert client.get("/api/v1/map-assets", headers=_authorization("player")).json()["assets"] == []

    scenes.execute(
        SceneCreateCommand(
            table_id=TABLE_ID,
            command_id="create-active-scene",
            expected_revision=0,
            scene=SceneRecord(
                scene_id="moon-temple-scene",
                map_metadata=SceneMapMetadata(
                    name="Moon Temple",
                    width_px=80,
                    height_px=60,
                    grid_size_px=10.0,
                    gridless=False,
                    asset=reference,
                ),
            ),
        )
    )

    for participant_id in ("gm", "player", "spectator"):
        content = client.get(
            reference.content_path,
            headers=_authorization(participant_id),
        )
        assert content.status_code == 200
        assert content.content == _png_bytes()
        assert content.headers["content-type"] == "image/png"
        assert content.headers["etag"] == f'"{reference.sha256}"'
        assert content.headers["cache-control"].startswith("private")
        assert content.headers["x-content-type-options"] == "nosniff"
    player_assets = client.get("/api/v1/map-assets", headers=_authorization("player")).json()[
        "assets"
    ]
    assert [asset["reference"]["asset_id"] for asset in player_assets] == ["moon-temple"]


def test_upload_binding_validation_media_failure_and_stale_revision_are_stable(
    asset_api,
) -> None:
    client, assets, _scenes, _service = asset_api
    for request in (
        _upload_request(session_id="wrong-session"),
        _upload_request(table_id="wrong-table"),
    ):
        response = client.post(
            "/api/v1/map-assets",
            headers=_authorization("gm"),
            json=request,
        )
        _assert_error(response, status_code=409, code="map_asset_binding_mismatch")

    invalid = client.post(
        "/api/v1/map-assets",
        headers=_authorization("gm"),
        json=_upload_request(content=b"not-an-image"),
    )
    _assert_error(invalid, status_code=422, code="map_asset_invalid_image")
    assert assets.revision(TABLE_ID) == 0

    created = client.post(
        "/api/v1/map-assets",
        headers=_authorization("gm"),
        json=_upload_request(),
    )
    assert created.status_code == 200
    stale = client.post(
        "/api/v1/map-assets",
        headers=_authorization("gm"),
        json=_upload_request(
            command_id="stale-upload",
            asset_id="stale-map",
            expected_revision=0,
        ),
    )
    details = _assert_error(stale, status_code=409, code="map_asset_stale_revision")["details"]
    assert details == {"current_revision": 1}


def test_scene_attachment_resolves_exact_durable_asset_before_mutation(asset_api) -> None:
    client, _assets, scenes, _service = asset_api
    uploaded = client.post(
        "/api/v1/map-assets",
        headers=_authorization("gm"),
        json=_upload_request(),
    ).json()["asset"]
    created = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json={
            "schema_version": VTT_SCENE_LIBRARY_REQUEST_SCHEMA_VERSION,
            "session_id": SESSION_ID,
            "command": {
                "schema_version": SCENE_COMMAND_SCHEMA_VERSION,
                "command_type": "create",
                "table_id": TABLE_ID,
                "command_id": "create-asset-scene",
                "expected_revision": 0,
                "scene": SceneRecord(
                    scene_id="asset-scene",
                    map_metadata=SceneMapMetadata(
                        name="Asset Scene",
                        width_px=80,
                        height_px=60,
                        grid_size_px=10.0,
                        gridless=False,
                    ),
                ).model_dump(mode="json"),
            },
        },
    )
    assert created.status_code == 200

    def update(reference: dict[str, Any], command_id: str) -> dict[str, Any]:
        return {
            "schema_version": VTT_SCENE_LIBRARY_REQUEST_SCHEMA_VERSION,
            "session_id": SESSION_ID,
            "command": {
                "schema_version": SCENE_COMMAND_SCHEMA_VERSION,
                "command_type": "update",
                "table_id": TABLE_ID,
                "command_id": command_id,
                "expected_revision": 1,
                "scene_id": "asset-scene",
                "map_metadata": {
                    "schema_version": "vtt.scene_map_metadata.v1",
                    "name": "Asset Scene",
                    "width_px": uploaded["width_px"],
                    "height_px": uploaded["height_px"],
                    "grid_size_px": 10.0,
                    "gridless": False,
                    "asset": reference,
                },
            },
        }

    missing = dict(uploaded["reference"])
    missing.update(
        {
            "asset_id": "missing-map",
            "content_path": "/api/v1/map-assets/missing-map/content.png",
        }
    )
    response = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json=update(missing, "attach-missing"),
    )
    _assert_error(response, status_code=404, code="scene_asset_not_found")
    assert scenes.revision(TABLE_ID) == 1

    mismatched = dict(uploaded["reference"])
    mismatched["sha256"] = "f" * 64
    response = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json=update(mismatched, "attach-mismatch"),
    )
    _assert_error(response, status_code=409, code="scene_asset_mismatch")
    assert scenes.revision(TABLE_ID) == 1

    wrong_dimensions = update(uploaded["reference"], "attach-wrong-dimensions")
    wrong_dimensions["command"]["map_metadata"]["width_px"] = uploaded["width_px"] + 1
    response = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json=wrong_dimensions,
    )
    _assert_error(
        response,
        status_code=409,
        code="scene_asset_dimensions_mismatch",
    )
    assert scenes.revision(TABLE_ID) == 1

    exact = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json=update(uploaded["reference"], "attach-exact"),
    )
    assert exact.status_code == 200
    assert scenes.revision(TABLE_ID) == 2
    content_path = exact.json()["event"]["scene"]["map_metadata"]["asset"]["content_path"]
    player_content = client.get(content_path, headers=_authorization("player"))
    assert player_content.status_code == 200
    assert hashlib.sha256(player_content.content).hexdigest() == uploaded["reference"]["sha256"]


def test_scene_create_and_import_resolve_assets_before_mutation(asset_api) -> None:
    client, _assets, scenes, _service = asset_api
    uploaded = client.post(
        "/api/v1/map-assets",
        headers=_authorization("gm"),
        json=_upload_request(),
    ).json()["asset"]

    def scene(scene_id: str, reference: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "vtt.scene_record.v1",
            "scene_id": scene_id,
            "map_metadata": {
                "schema_version": "vtt.scene_map_metadata.v1",
                "name": scene_id.replace("-", " ").title(),
                "width_px": uploaded["width_px"],
                "height_px": uploaded["height_px"],
                "grid_size_px": 10.0,
                "gridless": False,
                "asset": reference,
            },
        }

    def request(command: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": VTT_SCENE_LIBRARY_REQUEST_SCHEMA_VERSION,
            "session_id": SESSION_ID,
            "command": command,
        }

    missing = dict(uploaded["reference"])
    missing.update(
        {
            "asset_id": "missing-create-map",
            "content_path": "/api/v1/map-assets/missing-create-map/content.png",
        }
    )
    rejected_create = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json=request(
            {
                "schema_version": SCENE_COMMAND_SCHEMA_VERSION,
                "command_type": "create",
                "table_id": TABLE_ID,
                "command_id": "create-missing-asset-scene",
                "expected_revision": 0,
                "scene": scene("missing-asset-scene", missing),
            }
        ),
    )
    _assert_error(rejected_create, status_code=404, code="scene_asset_not_found")
    assert scenes.revision(TABLE_ID) == 0

    accepted_create = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json=request(
            {
                "schema_version": SCENE_COMMAND_SCHEMA_VERSION,
                "command_type": "create",
                "table_id": TABLE_ID,
                "command_id": "create-exact-asset-scene",
                "expected_revision": 0,
                "scene": scene("exact-asset-scene", uploaded["reference"]),
            }
        ),
    )
    assert accepted_create.status_code == 200
    assert scenes.revision(TABLE_ID) == 1

    forged = dict(uploaded["reference"])
    forged["alt_text"] = "A forged description for the uploaded map."
    rejected_import = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json=request(
            {
                "schema_version": SCENE_COMMAND_SCHEMA_VERSION,
                "command_type": "import",
                "table_id": TABLE_ID,
                "command_id": "import-forged-asset-scene",
                "expected_revision": 1,
                "bundle": {
                    "schema_version": SCENE_EXPORT_SCHEMA_VERSION,
                    "scene": scene("forged-import-scene", forged),
                },
            }
        ),
    )
    _assert_error(rejected_import, status_code=409, code="scene_asset_mismatch")
    assert scenes.revision(TABLE_ID) == 1

    accepted_import = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json=request(
            {
                "schema_version": SCENE_COMMAND_SCHEMA_VERSION,
                "command_type": "import",
                "table_id": TABLE_ID,
                "command_id": "import-exact-asset-scene",
                "expected_revision": 1,
                "bundle": {
                    "schema_version": SCENE_EXPORT_SCHEMA_VERSION,
                    "scene": scene("exact-import-scene", uploaded["reference"]),
                },
            }
        ),
    )
    assert accepted_import.status_code == 200
    assert scenes.revision(TABLE_ID) == 2


def test_existing_bundled_static_asset_can_be_reused_but_not_forged(asset_api) -> None:
    client, _assets, scenes, _service = asset_api
    trusted_reference = SceneMapAssetReference(
        asset_id="bundled-map",
        media_type="image/png",
        content_path="/assets/maps/bundled-map.png",
        sha256="a" * 64,
        alt_text="A bundled map.",
    )
    metadata = SceneMapMetadata(
        name="Bundled Scene",
        width_px=80,
        height_px=60,
        grid_size_px=10.0,
        gridless=False,
        asset=trusted_reference,
    )
    scenes.execute(
        SceneCreateCommand(
            table_id=TABLE_ID,
            command_id="seed-bundled-scene",
            expected_revision=0,
            scene=SceneRecord(scene_id="bundled-scene", map_metadata=metadata),
        )
    )

    def update(reference: SceneMapAssetReference, command_id: str) -> dict[str, Any]:
        return {
            "schema_version": VTT_SCENE_LIBRARY_REQUEST_SCHEMA_VERSION,
            "session_id": SESSION_ID,
            "command": {
                "schema_version": SCENE_COMMAND_SCHEMA_VERSION,
                "command_type": "update",
                "table_id": TABLE_ID,
                "command_id": command_id,
                "expected_revision": 1,
                "scene_id": "bundled-scene",
                "map_metadata": metadata.model_copy(update={"asset": reference}).model_dump(
                    mode="json"
                ),
            },
        }

    reused = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json=update(trusted_reference, "reuse-bundled-reference"),
    )
    assert reused.status_code == 200
    assert scenes.revision(TABLE_ID) == 2

    forged_reference = trusted_reference.model_copy(update={"sha256": "b" * 64})
    forged_request = update(forged_reference, "forge-bundled-reference")
    forged_request["command"]["expected_revision"] = 2
    forged = client.post(
        "/api/v1/scene-commands",
        headers=_authorization("gm"),
        json=forged_request,
    )
    _assert_error(forged, status_code=409, code="scene_asset_unmanaged")
    assert scenes.revision(TABLE_ID) == 2
