from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dnd_sim.interactive import DndCombatEncounterDriver
from dnd_sim.interactive.dnd_encounter_driver import START_ENCOUNTER_COMMAND_KIND
from dnd_sim.vtt.access import TableAccessPolicy
from dnd_sim.vtt.board_calibration import BoardCalibration
from dnd_sim.vtt.event_store import SQLiteSessionEventStore
from dnd_sim.vtt.http_api import create_vtt_app
from dnd_sim.vtt.participants import (
    PARTICIPANT_SCHEMA_VERSION,
    ROSTER_SCHEMA_VERSION,
    TableParticipant,
    TableRoster,
)
from dnd_sim.vtt.scene import FeetPosition
from dnd_sim.vtt.scene_library_contracts import SceneCreateCommand, SceneMapMetadata, SceneRecord
from dnd_sim.vtt.scene_library_store import SQLiteSceneLibrary
from dnd_sim.vtt.session_service import VTTSessionService
from dnd_sim.vtt.solo_table import build_solo_table_fixture
from dnd_sim.vtt.token_contracts import TokenCreateCommand, TokenPose, TokenRecord
from dnd_sim.vtt.token_store import SQLiteTokenStore
from dnd_sim.vtt.visibility_api import (
    VTT_VISIBILITY_REQUEST_SCHEMA_VERSION,
    _render_signal,
)
from dnd_sim.vtt.visibility_contracts import (
    FogOperation,
    SceneEnvironment,
    SightBarrier,
    TokenVision,
    VisibilityPoint,
)
from dnd_sim.vtt.visibility_store import SQLiteVisibilityStore

SESSION_ID = "visibility-session"
TABLE_ID = "visibility-table"
TOKENS = {"gm": "gm-visibility-token-1234", "owner": "owner-visibility-token-1234"}


def _participant(
    participant_id: str,
    role: str,
    actor_ids: tuple[str, ...] = (),
) -> TableParticipant:
    return TableParticipant(
        schema_version=PARTICIPANT_SCHEMA_VERSION,
        participant_id=participant_id,
        display_name=participant_id.title(),
        role=role,
        owned_actor_ids=actor_ids,
    )


def _policy() -> TableAccessPolicy:
    return TableAccessPolicy(
        roster=TableRoster(
            schema_version=ROSTER_SCHEMA_VERSION,
            table_id=TABLE_ID,
            participants=(
                _participant("gm", "gm"),
                _participant("owner", "player", ("vela_quill",)),
            ),
        ),
        bearer_tokens=TOKENS,
    )


def _auth(participant_id: str) -> dict[str, str]:
    return {"authorization": f"Bearer {TOKENS[participant_id]}"}


def _point(x_ft: float, y_ft: float) -> VisibilityPoint:
    return VisibilityPoint(x_ft=x_ft, y_ft=y_ft)


def _token(token_id: str, actor_id: str, x_ft: float) -> TokenRecord:
    return TokenRecord(
        token_id=token_id,
        scene_id="echo-vault",
        actor_id=actor_id,
        name=token_id.title(),
        pose=TokenPose(
            position_ft=FeetPosition(x_ft=x_ft, y_ft=12.5, z_ft=0.0),
            width_ft=5.0,
            height_ft=5.0,
            rotation_degrees=0.0,
            layer=0,
        ),
        visibility="public",
        locked=False,
        nameplate="always",
        show_hp_bar=True,
        aura_radius_ft=0.0,
        aura_color="#4DD7B3",
        condition_labels=(),
    )


def _request(command: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": VTT_VISIBILITY_REQUEST_SCHEMA_VERSION,
        "session_id": SESSION_ID,
        "command": command,
    }


def _put(command_id: str, revision: int, record: Any) -> dict[str, Any]:
    return _request(
        {
            "schema_version": "vtt.visibility_command.v1",
            "command_type": "put",
            "table_id": TABLE_ID,
            "command_id": command_id,
            "expected_revision": revision,
            "record": record.model_dump(mode="json"),
        }
    )


def _seed_visibility(client: TestClient) -> None:
    records = (
        SceneEnvironment(
            record_id="scene-environment",
            scene_id="echo-vault",
            darkness="bright",
            shared_vision="owned_only",
        ),
        TokenVision(
            record_id="vela-vision",
            scene_id="echo-vault",
            token_id="vela-token",
            enabled=True,
            normal_range_ft=100.0,
            darkvision_range_ft=0.0,
            emitted_bright_radius_ft=0.0,
            emitted_dim_radius_ft=0.0,
        ),
        FogOperation(
            record_id="fog-1",
            scene_id="echo-vault",
            operation_index=1,
            operation="reveal",
            polygon=(
                _point(0.0, 0.0),
                _point(40.0, 0.0),
                _point(40.0, 30.0),
                _point(0.0, 30.0),
            ),
        ),
        SightBarrier(
            record_id="vault-door",
            scene_id="echo-vault",
            start=_point(17.5, 0.0),
            end=_point(17.5, 30.0),
            behavior="door",
            blocks_sight=True,
            blocks_movement=True,
            portal_state="closed",
        ),
    )
    for revision, record in enumerate(records):
        response = client.post(
            "/api/v1/visibility-commands",
            headers=_auth("gm"),
            json=_put(f"seed-{revision}", revision, record),
        )
        assert response.status_code == 200, response.text


@pytest.fixture
def visibility_api_client(tmp_path: Path):
    database = tmp_path / "visibility-http.sqlite3"
    session_connection = sqlite3.connect(database, check_same_thread=False)
    scene_connection = sqlite3.connect(database, check_same_thread=False)
    token_connection = sqlite3.connect(database, check_same_thread=False)
    visibility_connection = sqlite3.connect(database, check_same_thread=False)
    fixture = build_solo_table_fixture()
    service = VTTSessionService.open(
        session_id=SESSION_ID,
        initial_state=fixture.encounter_state,
        driver=DndCombatEncounterDriver(version_pins=fixture.version_pins),
        seed=fixture.seed,
        event_store=SQLiteSessionEventStore(session_connection),
    )
    scenes = SQLiteSceneLibrary(scene_connection)
    scenes.execute(
        SceneCreateCommand(
            table_id=TABLE_ID,
            command_id="seed-scene",
            expected_revision=0,
            scene=SceneRecord(
                scene_id="echo-vault",
                map_metadata=SceneMapMetadata(
                    name="Echo Vault",
                    width_px=40,
                    height_px=30,
                    grid_size_px=5.0,
                    gridless=False,
                    calibration=BoardCalibration(
                        topology="square",
                        origin_x_px=2.5,
                        origin_y_px=2.5,
                        cell_extent_px=5.0,
                        distance_ft=5.0,
                    ),
                ),
            ),
        )
    )
    token_store = SQLiteTokenStore(token_connection)
    token_store.execute(
        TokenCreateCommand(
            table_id=TABLE_ID,
            command_id="seed-vela",
            expected_revision=0,
            token=_token("vela-token", "vela_quill", 12.5),
        )
    )
    token_store.execute(
        TokenCreateCommand(
            table_id=TABLE_ID,
            command_id="seed-sentry",
            expected_revision=1,
            token=_token("sentry-token", "hushglass_sentry", 22.5),
        )
    )
    visibility_store = SQLiteVisibilityStore(visibility_connection)
    app = create_vtt_app(
        service,
        scene=fixture.scene,
        access_policy=_policy(),
        scene_library=scenes,
        token_store=token_store,
        visibility_store=visibility_store,
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, visibility_store, service
    finally:
        visibility_connection.close()
        token_connection.close()
        scene_connection.close()
        session_connection.close()


def _assert_error(response, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    assert response.json()["schema_version"] == "vtt.error.v1"
    assert response.json()["code"] == code
    assert "traceback" not in response.text.lower()


def test_visibility_routes_authenticate_before_query_and_body_validation(
    visibility_api_client,
) -> None:
    client, _store, _service = visibility_api_client

    _assert_error(
        client.get("/api/v1/visibility?scene_id=../private"), 401, "authentication_required"
    )
    _assert_error(
        client.post("/api/v1/visibility-commands", json={"invalid": True}),
        401,
        "authentication_required",
    )


def test_player_projection_and_session_hide_raw_geometry_and_occluded_actor(
    visibility_api_client,
) -> None:
    client, _store, service = visibility_api_client
    _seed_visibility(client)
    started = client.post(
        "/api/v1/commands",
        headers=_auth("gm"),
        json={
            "schema_version": "vtt.command.v1",
            "command_id": "start-visibility",
            "session_id": SESSION_ID,
            "actor_id": None,
            "expected_revision": 0,
            "mode": "admin",
            "kind": START_ENCOUNTER_COMMAND_KIND,
            "payload": {},
            "intent_metadata": {},
        },
    )
    assert started.status_code == 200

    projected = client.get("/api/v1/visibility", headers=_auth("owner"))
    assert projected.status_code == 200
    assert projected.json()["schema_version"] == "vtt.visibility_projection.v1"
    assert [token["token_id"] for token in projected.json()["tokens"]] == ["vela-token"]
    for secret in ("vault-door", "vela-vision", "fog-1", "sentry-token"):
        assert secret not in projected.text

    tokens = client.get(
        "/api/v1/tokens?scene_id=echo-vault",
        headers=_auth("owner"),
    )
    assert tokens.status_code == 200
    assert [token["token_id"] for token in tokens.json()["tokens"]] == ["vela-token"]
    assert "sentry-token" not in tokens.text

    session = client.get("/api/v1/session", headers=_auth("owner"))
    assert session.status_code == 200
    assert set(session.json()["projection"]["actors"]) == {"vela_quill"}
    assert "hushglass_sentry" not in session.text

    blocked_path = {
        "movement_path": [[12.5, 12.5, 0.0], [22.5, 12.5, 0.0]],
        "action": None,
        "bonus_action": None,
        "reaction_policy": {"mode": "auto", "rationale": {}},
        "ready": None,
        "rationale": {},
    }
    before = service.read_view()
    for participant_id in ("owner", "gm"):
        for mode in ("preview", "commit"):
            blocked = client.post(
                "/api/v1/commands",
                headers=_auth(participant_id),
                json={
                    "schema_version": "vtt.command.v1",
                    "command_id": f"blocked-door-{participant_id}-{mode}",
                    "session_id": SESSION_ID,
                    "actor_id": "vela_quill",
                    "expected_revision": 1,
                    "mode": mode,
                    "kind": "dnd.declare_turn.v1",
                    "payload": blocked_path,
                    "intent_metadata": {},
                },
            )
            _assert_error(blocked, 409, "board_movement_blocked")
            assert "vault-door" not in blocked.text
            assert service.read_view() == before

    crafted = {
        "movement_path": [[12.5, 12.5, 0.0]],
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
    for mode in ("preview", "commit"):
        response = client.post(
            "/api/v1/commands",
            headers=_auth("owner"),
            json={
                "schema_version": "vtt.command.v1",
                "command_id": f"occluded-{mode}",
                "session_id": SESSION_ID,
                "actor_id": "vela_quill",
                "expected_revision": 1,
                "mode": mode,
                "kind": "dnd.declare_turn.v1",
                "payload": crafted,
                "intent_metadata": {},
            },
        )
        _assert_error(response, 403, "command_target_not_visible")
        assert "hushglass_sentry" not in response.text
        assert service.read_view() == before


def test_gm_editor_preview_door_toggle_and_sanitized_signal(
    visibility_api_client,
) -> None:
    client, store, _service = visibility_api_client
    _seed_visibility(client)

    editor = client.get("/api/v1/visibility", headers=_auth("gm"))
    assert editor.status_code == 200
    assert editor.json()["schema_version"] == "vtt.visibility_catalog_view.v1"
    assert {record["record_id"] for record in editor.json()["records"]} == {
        "fog-1",
        "scene-environment",
        "vault-door",
        "vela-vision",
    }
    preview = client.get(
        "/api/v1/visibility-preview?participant_id=owner",
        headers=_auth("gm"),
    )
    assert preview.status_code == 200
    closed_count = sum(run["length"] for run in preview.json()["visible_runs"])

    opened = client.post(
        "/api/v1/visibility-commands",
        headers=_auth("gm"),
        json=_request(
            {
                "schema_version": "vtt.visibility_command.v1",
                "command_type": "set_door_state",
                "table_id": TABLE_ID,
                "command_id": "open-door",
                "expected_revision": 4,
                "scene_id": "echo-vault",
                "barrier_id": "vault-door",
                "portal_state": "open",
            }
        ),
    )
    assert opened.status_code == 200
    open_preview = client.get(
        "/api/v1/visibility-preview?participant_id=owner",
        headers=_auth("gm"),
    )
    assert sum(run["length"] for run in open_preview.json()["visible_runs"]) > closed_count
    signal = _render_signal(store.events_after(TABLE_ID, 4)[0])
    lines = dict(line.split(": ", 1) for line in signal.strip().splitlines() if ": " in line)
    assert lines["event"] == "vtt.visibility_changed"
    assert json.loads(lines["data"]) == {
        "revision": 5,
        "scene_id": "echo-vault",
        "schema_version": "vtt.visibility_change_signal.v1",
        "sequence": 5,
    }
    assert "vault-door" not in signal


def test_visibility_mutations_are_gm_only_replay_safe_and_prevalidated(
    visibility_api_client,
) -> None:
    client, store, _service = visibility_api_client
    environment = SceneEnvironment(
        record_id="scene-environment",
        scene_id="echo-vault",
        darkness="bright",
        shared_vision="owned_only",
    )
    request = _put("environment", 0, environment)
    _assert_error(
        client.post("/api/v1/visibility-commands", headers=_auth("owner"), json=request),
        403,
        "visibility_forbidden",
    )
    first = client.post("/api/v1/visibility-commands", headers=_auth("gm"), json=request)
    replay = client.post("/api/v1/visibility-commands", headers=_auth("gm"), json=request)
    assert first.status_code == replay.status_code == 200
    assert {key: value for key, value in first.json().items() if key != "replayed"} == {
        key: value for key, value in replay.json().items() if key != "replayed"
    }
    assert replay.json()["replayed"] is True

    outside = SightBarrier(
        record_id="outside",
        scene_id="echo-vault",
        start=_point(10.0, 10.0),
        end=_point(100.0, 10.0),
        behavior="wall",
        blocks_sight=True,
        blocks_movement=True,
    )
    _assert_error(
        client.post(
            "/api/v1/visibility-commands",
            headers=_auth("gm"),
            json=_put("outside", 1, outside),
        ),
        409,
        "visibility_geometry_out_of_bounds",
    )
    missing_vision = TokenVision(
        record_id="missing-vision",
        scene_id="echo-vault",
        token_id="private-missing-token",
        enabled=True,
        normal_range_ft=60.0,
        darkvision_range_ft=0.0,
        emitted_bright_radius_ft=0.0,
        emitted_dim_radius_ft=0.0,
    )
    missing = client.post(
        "/api/v1/visibility-commands",
        headers=_auth("gm"),
        json=_put("missing", 1, missing_vision),
    )
    _assert_error(missing, 404, "visibility_token_unavailable")
    assert "private-missing-token" not in missing.text
    assert store.revision(TABLE_ID) == 1


def test_visibility_routes_are_optional_and_require_scene_and_token_sources(
    visibility_api_client,
) -> None:
    client, store, service = visibility_api_client
    optional = create_vtt_app(service, access_policy=_policy())
    with TestClient(optional, raise_server_exceptions=False) as optional_client:
        assert optional_client.get("/api/v1/visibility", headers=_auth("gm")).status_code == 404
    with pytest.raises(ValueError, match="visibility_store"):
        create_vtt_app(service, access_policy=_policy(), visibility_store=store)
