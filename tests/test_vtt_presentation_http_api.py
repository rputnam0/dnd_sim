from __future__ import annotations

import base64
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dnd_sim.interactive import DndCombatEncounterDriver
from dnd_sim.vtt.access import TableAccessPolicy
from dnd_sim.vtt.board_calibration import BoardCalibration
from dnd_sim.vtt.event_store import SQLiteSessionEventStore
from dnd_sim.vtt.http_api import VTT_ERROR_SCHEMA_VERSION, create_vtt_app
from dnd_sim.vtt.participants import (
    PARTICIPANT_SCHEMA_VERSION,
    ROSTER_SCHEMA_VERSION,
    TableParticipant,
    TableRoster,
)
from dnd_sim.vtt.presentation_store import SQLitePresentationStore
from dnd_sim.vtt.scene_library_contracts import (
    SceneActivateCommand,
    SceneCreateCommand,
    SceneMapMetadata,
    SceneRecord,
)
from dnd_sim.vtt.scene_library_store import SQLiteSceneLibrary
from dnd_sim.vtt.session_service import VTTSessionService
from dnd_sim.vtt.solo_table import build_solo_table_fixture

SESSION_ID = "presentation-session"
TABLE_ID = "presentation-table"
TOKENS = {
    "gm": "presentation-gm-token-0001",
    "player": "presentation-player-token-0001",
    "spectator": "presentation-spectator-token-0001",
}


def _wav_bytes(seed: int = 0) -> bytes:
    payload = bytes((seed, 0, seed, 0))
    body = (
        b"WAVEfmt "
        + (16).to_bytes(4, "little")
        + b"\x01\x00\x01\x00"
        + (8_000).to_bytes(4, "little")
        + (16_000).to_bytes(4, "little")
        + b"\x02\x00\x10\x00"
        + b"data"
        + len(payload).to_bytes(4, "little")
        + payload
    )
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def _policy() -> TableAccessPolicy:
    def participant(participant_id: str, role: str) -> TableParticipant:
        return TableParticipant(
            schema_version=PARTICIPANT_SCHEMA_VERSION,
            participant_id=participant_id,
            display_name=participant_id.title(),
            role=role,
            owned_actor_ids=(),
        )

    return TableAccessPolicy(
        roster=TableRoster(
            schema_version=ROSTER_SCHEMA_VERSION,
            table_id=TABLE_ID,
            participants=(
                participant("gm", "gm"),
                participant("player", "player"),
                participant("spectator", "spectator"),
            ),
        ),
        bearer_tokens=TOKENS,
    )


def _headers(participant_id: str) -> dict[str, str]:
    return {"authorization": f"Bearer {TOKENS[participant_id]}"}


def _request(command: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "vtt.presentation_request.v1",
        "session_id": SESSION_ID,
        "command": {
            "schema_version": "vtt.presentation_command.v1",
            "table_id": TABLE_ID,
            **command,
        },
    }


@pytest.fixture
def presentation_api(tmp_path: Path):
    database = tmp_path / "presentation-api.sqlite3"
    session_connection = sqlite3.connect(database, check_same_thread=False)
    scene_connection = sqlite3.connect(database, check_same_thread=False)
    presentation_connection = sqlite3.connect(database, check_same_thread=False)
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
            command_id="create-scene",
            expected_revision=0,
            scene=SceneRecord(
                scene_id=fixture.scene.scene_id,
                map_metadata=SceneMapMetadata(
                    name=fixture.scene.name,
                    width_px=500,
                    height_px=400,
                    grid_size_px=50.0,
                    gridless=False,
                    calibration=BoardCalibration(
                        topology="square",
                        origin_x_px=25.0,
                        origin_y_px=25.0,
                        cell_extent_px=50.0,
                        distance_ft=5.0,
                    ),
                ),
            ),
        )
    )
    store = SQLitePresentationStore(presentation_connection)
    clock = [1_000]
    app = create_vtt_app(
        service,
        scene=fixture.scene,
        access_policy=_policy(),
        scene_library=scenes,
        presentation_store=store,
        presentation_epoch_ms_clock=lambda: clock[0],
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, store, clock, fixture.scene.scene_id, scenes
    presentation_connection.close()
    scene_connection.close()
    session_connection.close()


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    payload = response.json()
    assert payload["schema_version"] == VTT_ERROR_SCHEMA_VERSION
    assert payload["code"] == code
    assert "traceback" not in response.text.lower()


def test_presentation_authenticates_before_validation_and_requires_gm(presentation_api) -> None:
    client, _store, _clock, _scene_id, _scenes = presentation_api
    _assert_error(
        client.post(
            "/api/v1/presentation-commands",
            content="{not-json",
            headers={"content-type": "application/json"},
        ),
        401,
        "authentication_required",
    )
    _assert_error(
        client.post(
            "/api/v1/presentation-commands",
            headers=_headers("player"),
            json=_request(
                {
                    "command_type": "stop",
                    "command_id": "player-stop",
                    "expected_revision": 0,
                }
            ),
        ),
        403,
        "presentation_forbidden",
    )
    _assert_error(
        client.get("/api/v1/presentation-events?after=01"),
        401,
        "authentication_required",
    )
    _assert_error(
        client.get("/api/v1/presentation-events?after=01", headers=_headers("player")),
        400,
        "presentation_invalid_cursor",
    )
    _assert_error(
        client.get("/api/v1/sound-assets/secret/content.wav"),
        401,
        "authentication_required",
    )


def test_sound_and_camera_are_audience_projected_and_privately_served(presentation_api) -> None:
    client, store, clock, scene_id, scenes = presentation_api
    for revision, track_id in enumerate(("vault-hum", "gm-secret")):
        response = client.post(
            "/api/v1/presentation-commands",
            headers=_headers("gm"),
            json=_request(
                {
                    "command_type": "upload_track",
                    "command_id": f"upload-{track_id}",
                    "expected_revision": revision,
                    "track_id": track_id,
                    "name": track_id.replace("-", " ").title(),
                    "content_base64": base64.b64encode(_wav_bytes(revision)).decode("ascii"),
                }
            ),
        )
        assert response.status_code == 200
    playlist = client.post(
        "/api/v1/presentation-commands",
        headers=_headers("gm"),
        json=_request(
            {
                "command_type": "put_playlist",
                "command_id": "put-ambience",
                "expected_revision": 2,
                "playlist": {
                    "schema_version": "vtt.sound_playlist.v1",
                    "playlist_id": "ambience",
                    "name": "Ambience",
                    "track_ids": ["vault-hum"],
                },
            }
        ),
    )
    assert playlist.status_code == 200
    play_request = _request(
        {
            "command_type": "play",
            "command_id": "play-vault-hum",
            "expected_revision": 3,
            "track_id": "vault-hum",
            "playlist_id": "ambience",
            "position_ms": 250,
            "loop": True,
            "audience": ["role:player"],
        }
    )
    played = client.post("/api/v1/presentation-commands", headers=_headers("gm"), json=play_request)
    replayed = client.post(
        "/api/v1/presentation-commands", headers=_headers("gm"), json=play_request
    )
    assert played.status_code == replayed.status_code == 200
    assert played.json()["replayed"] is False
    assert replayed.json()["replayed"] is True

    player = client.get("/api/v1/presentation", headers=_headers("player")).json()
    assert [track["track_id"] for track in player["tracks"]] == ["vault-hum"]
    assert player["playlists"] == []
    assert player["playback"]["audience"] == ["all"]
    spectator = client.get("/api/v1/presentation", headers=_headers("spectator")).json()
    assert spectator["tracks"] == []
    assert spectator["playback"]["status"] == "stopped"
    assert client.get(
        "/api/v1/sound-assets/vault-hum/content.wav", headers=_headers("player")
    ).content == _wav_bytes(0)
    hidden = client.get("/api/v1/sound-assets/gm-secret/content.wav", headers=_headers("player"))
    _assert_error(hidden, 404, "sound_asset_not_found")

    clock[0] = 2_000
    shared = client.post(
        "/api/v1/presentation-commands",
        headers=_headers("gm"),
        json=_request(
            {
                "command_type": "share_camera",
                "command_id": "share-camera",
                "expected_revision": 4,
                "scene_id": scene_id,
                "center_x_ft": 20.0,
                "center_y_ft": 15.0,
                "zoom": 2.0,
            }
        ),
    )
    assert shared.status_code == 200
    camera = client.get("/api/v1/presentation", headers=_headers("player")).json()["camera"]
    assert camera == {
        "schema_version": "vtt.presentation_camera.v1",
        "enabled": True,
        "epoch": 1,
        "scene_id": scene_id,
        "center_x_ft": 20.0,
        "center_y_ft": 15.0,
        "zoom": 2.0,
    }
    assert [signal.model_dump(mode="json") for signal in store.events_after(TABLE_ID, 3)] == [
        {"schema_version": "vtt.presentation_signal.v1", "sequence": 4, "revision": 4},
        {"schema_version": "vtt.presentation_signal.v1", "sequence": 5, "revision": 5},
    ]

    first_entry = scenes.snapshot(TABLE_ID).scene(scene_id)
    assert first_entry is not None
    scenes.execute(
        SceneCreateCommand(
            table_id=TABLE_ID,
            command_id="create-second-scene",
            expected_revision=1,
            scene=SceneRecord(
                scene_id="second-room",
                map_metadata=first_entry.scene.map_metadata.model_copy(
                    update={"name": "Second room"}
                ),
            ),
        )
    )
    scenes.execute(
        SceneActivateCommand(
            table_id=TABLE_ID,
            command_id="activate-second-scene",
            expected_revision=2,
            scene_id="second-room",
        )
    )
    after_activation = client.get("/api/v1/presentation", headers=_headers("player")).json()
    assert after_activation["camera"]["enabled"] is False
    exact_retry = client.post(
        "/api/v1/presentation-commands",
        headers=_headers("gm"),
        json=_request(
            {
                "command_type": "share_camera",
                "command_id": "share-camera",
                "expected_revision": 4,
                "scene_id": scene_id,
                "center_x_ft": 20.0,
                "center_y_ft": 15.0,
                "zoom": 2.0,
            }
        ),
    )
    assert exact_retry.status_code == 200
    assert exact_retry.json()["replayed"] is True


def test_camera_rejects_wrong_scene_and_out_of_bounds_without_mutation(presentation_api) -> None:
    client, store, _clock, scene_id, _scenes = presentation_api
    for command_id, target_scene, x_ft, expected_code in (
        ("wrong-scene", "other", 5.0, "presentation_scene_mismatch"),
        ("outside", scene_id, 1_000.0, "presentation_camera_out_of_bounds"),
    ):
        response = client.post(
            "/api/v1/presentation-commands",
            headers=_headers("gm"),
            json=_request(
                {
                    "command_type": "share_camera",
                    "command_id": command_id,
                    "expected_revision": 0,
                    "scene_id": target_scene,
                    "center_x_ft": x_ft,
                    "center_y_ft": 5.0,
                    "zoom": 1.0,
                }
            ),
        )
        _assert_error(response, 409 if target_scene == "other" else 422, expected_code)
        assert store.revision(TABLE_ID) == 0


def test_playback_rejects_unknown_audience_before_store_mutation(presentation_api) -> None:
    client, store, _clock, _scene_id, _scenes = presentation_api
    response = client.post(
        "/api/v1/presentation-commands",
        headers=_headers("gm"),
        json=_request(
            {
                "command_type": "play",
                "command_id": "unknown-audience",
                "expected_revision": 0,
                "track_id": "hidden",
                "playlist_id": None,
                "position_ms": 0,
                "loop": False,
                "audience": ["participant:missing"],
            }
        ),
    )
    _assert_error(response, 422, "presentation_invalid_audience")
    assert store.revision(TABLE_ID) == 0
