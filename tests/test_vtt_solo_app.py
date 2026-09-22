from __future__ import annotations

import base64
import hashlib
import io
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from dnd_sim.interactive.dnd_contracts import DECLARATION_COMMAND_KIND
from dnd_sim.interactive.dnd_encounter_driver import START_ENCOUNTER_COMMAND_KIND
from dnd_sim.vtt import (
    VTT_COMMAND_SCHEMA_VERSION,
    VTT_COMMIT_RESPONSE_SCHEMA_VERSION,
    VTT_SESSION_VIEW_SCHEMA_VERSION,
    VTTCommand,
    create_solo_table_app,
)
from dnd_sim.vtt import solo_app


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def test_original_solo_map_asset_matches_the_published_integrity_digest() -> None:
    asset_path = (
        Path(__file__).parents[1]
        / "apps"
        / "vtt-web"
        / "public"
        / "assets"
        / "maps"
        / "echo-vault-original.png"
    )

    assert asset_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert hashlib.sha256(asset_path.read_bytes()).hexdigest() == (
        "90ece48257967087c27ac6ae2da497434526f88811242b9ae7a267cbee0d6b89"
    )


def _wire_command(
    *,
    command_id: str,
    session_id: str,
    actor_id: str | None,
    expected_revision: int,
    mode: str,
    kind: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return VTTCommand(
        schema_version=VTT_COMMAND_SCHEMA_VERSION,
        command_id=command_id,
        session_id=session_id,
        actor_id=actor_id,
        expected_revision=expected_revision,
        mode=mode,
        kind=kind,
        payload=payload,
        intent_metadata={},
    ).model_dump(mode="json")


def _winning_declaration_payload() -> dict[str, Any]:
    return {
        "movement_path": [
            [12.5, 12.5, 0.0],
            [17.5, 12.5, 0.0],
        ],
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


def _public_ping_request(
    *,
    session_id: str,
    command_id: str,
    annotation_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    return {
        "schema_version": "vtt.annotation_request.v1",
        "session_id": session_id,
        "command": {
            "schema_version": "vtt.annotation_command.v1",
            "table_id": session_id,
            "command_id": command_id,
            "expected_revision": expected_revision,
            "command_type": "put",
            "annotation": {
                "schema_version": "vtt.annotation.v1",
                "annotation_id": annotation_id,
                "scene_id": "echo-vault",
                "author_id": "untrusted-browser-author",
                "audience": ["all"],
                "annotation_type": "ping",
                # JSON.stringify emits whole-valued JavaScript numbers without
                # a decimal suffix. The HTTP boundary must still accept them.
                "position": {"x_ft": 20, "y_ft": 15, "z_ft": 0},
                "duration_ms": 1_500,
            },
        },
    }


def _public_text_drawing_request(
    *,
    session_id: str,
    command_id: str,
    annotation_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    return {
        "schema_version": "vtt.annotation_request.v1",
        "session_id": session_id,
        "command": {
            "schema_version": "vtt.annotation_command.v1",
            "table_id": session_id,
            "command_id": command_id,
            "expected_revision": expected_revision,
            "command_type": "put",
            "annotation": {
                "schema_version": "vtt.annotation.v1",
                "annotation_id": annotation_id,
                "scene_id": "echo-vault",
                "author_id": "untrusted-browser-author",
                "audience": ["all"],
                "annotation_type": "text_drawing",
                "layer": "over_tokens",
                "locked": True,
                "style": {
                    "stroke_color": "#5eead4",
                    "fill_color": None,
                    "opacity": 1,
                    "stroke_width_ft": 1,
                    "line_style": "solid",
                },
                "anchor": {"x_ft": 20, "y_ft": 15, "z_ft": 0},
                "text": "Hold <script>alert(1)</script>\nNorth",
                "font_size_ft": 3,
                "background_color": "#112233",
            },
        },
    }


def _public_chat_request(
    *,
    session_id: str,
    command_id: str,
    message_id: str,
    expected_revision: int,
    text: str,
) -> dict[str, Any]:
    return {
        "schema_version": "vtt.chat_request.v1",
        "session_id": session_id,
        "command": {
            "schema_version": "vtt.chat_command.v1",
            "table_id": session_id,
            "command_id": command_id,
            "expected_revision": expected_revision,
            "command_type": "post",
            "message": {
                "schema_version": "vtt.chat_message.v1",
                "message_id": message_id,
                "author_id": "untrusted-browser-author",
                "audience": ["all"],
                "text": text,
            },
        },
    }


def _public_scene_create_request(
    *,
    session_id: str,
    command_id: str,
    scene_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    return {
        "schema_version": "vtt.scene_library_request.v1",
        "session_id": session_id,
        "command": {
            "schema_version": "vtt.scene_command.v1",
            "command_type": "create",
            "table_id": session_id,
            "command_id": command_id,
            "expected_revision": expected_revision,
            "scene": {
                "schema_version": "vtt.scene_record.v1",
                "scene_id": scene_id,
                "map_metadata": {
                    "schema_version": "vtt.scene_map_metadata.v1",
                    "name": "Second Map",
                    "width_px": 1_600,
                    "height_px": 900,
                    "grid_size_px": 80.0,
                    "gridless": True,
                },
            },
        },
    }


def _public_presence_heartbeat_request(
    *,
    session_id: str,
    command_id: str,
    expected_revision: int,
    client_id: str = "solo-browser",
) -> dict[str, Any]:
    return {
        "schema_version": "vtt.presence_heartbeat_request.v1",
        "session_id": session_id,
        "command": {
            "schema_version": "vtt.presence_command.v1",
            "command_type": "heartbeat",
            "table_id": session_id,
            "command_id": command_id,
            "expected_revision": expected_revision,
            "participant_id": "local",
            "client_id": client_id,
        },
    }


def _public_map_asset_upload_request() -> tuple[dict[str, Any], bytes]:
    output = io.BytesIO()
    Image.new("RGB", (96, 72), color=(16, 46, 43)).save(output, format="PNG")
    content = output.getvalue()
    return (
        {
            "schema_version": "vtt.map_asset_upload_request.v1",
            "session_id": "echo-vault-session",
            "command": {
                "schema_version": "vtt.map_asset_upload_command.v1",
                "table_id": "echo-vault-session",
                "command_id": "upload-sunken-observatory",
                "expected_revision": 0,
                "asset_id": "sunken-observatory",
                "alt_text": "A top-down flooded observatory battle map.",
                "content_base64": base64.b64encode(content).decode("ascii"),
            },
        },
        content,
    )


def _stored_command_count(database_path: Path) -> int:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM vtt_committed_commands").fetchone()
    assert row is not None
    return int(row[0])


def _stored_chat_event_count(database_path: Path) -> int:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM _vtt_chat_event_log").fetchone()
    assert row is not None
    return int(row[0])


def _stored_scene_event_count(database_path: Path) -> int:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM _vtt_scene_library_event_log").fetchone()
    assert row is not None
    return int(row[0])


def _stored_presence_event_count(database_path: Path) -> int:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM _vtt_presence_event_log").fetchone()
    assert row is not None
    return int(row[0])


def _stored_map_asset_count(database_path: Path) -> int:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM _vtt_map_asset").fetchone()
    assert row is not None
    return int(row[0])


def _stored_token_event_count(database_path: Path) -> int:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM _vtt_token_event_log").fetchone()
    assert row is not None
    return int(row[0])


def _complete_fresh_solo_table(database_path: Path) -> dict[str, Any]:
    """Play the canonical encounter once and return its public terminal view."""

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as client:
        initial = client.get("/api/v1/session")
        assert initial.status_code == 200
        session_id = initial.json()["session_id"]

        started = client.post(
            "/api/v1/commands",
            json=_wire_command(
                command_id="fresh-replay-start",
                session_id=session_id,
                actor_id=None,
                expected_revision=0,
                mode="admin",
                kind=START_ENCOUNTER_COMMAND_KIND,
                payload={},
            ),
        )
        assert started.status_code == 200

        completed = client.post(
            "/api/v1/commands",
            json=_wire_command(
                command_id="fresh-replay-winning-turn",
                session_id=session_id,
                actor_id="vela_quill",
                expected_revision=1,
                mode="commit",
                kind=DECLARATION_COMMAND_KIND,
                payload=_winning_declaration_payload(),
            ),
        )
        assert completed.status_code == 200

        terminal = client.get("/api/v1/session")
        assert terminal.status_code == 200
        return terminal.json()


def test_solo_table_app_restarts_terminal_session_and_replays_exact_command(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "echo-vault.sqlite3"
    first_app = create_solo_table_app(database_path)

    with TestClient(first_app, raise_server_exceptions=False) as first_client:
        unstarted_response = first_client.get("/api/v1/session")
        assert unstarted_response.status_code == 200
        unstarted = unstarted_response.json()
        assert unstarted["schema_version"] == VTT_SESSION_VIEW_SCHEMA_VERSION
        assert unstarted["revision"] == 0
        assert unstarted["scene"]["scene_id"] == "echo-vault"
        assert unstarted["projection"]["phase"] == "unstarted"
        assert unstarted["projection"]["outcome"] is None
        session_id = unstarted["session_id"]

        start_command = _wire_command(
            command_id="start-echo-vault",
            session_id=session_id,
            actor_id=None,
            expected_revision=0,
            mode="admin",
            kind=START_ENCOUNTER_COMMAND_KIND,
            payload={},
        )
        started_response = first_client.post(
            "/api/v1/commands",
            json=start_command,
        )
        assert started_response.status_code == 200
        assert started_response.json()["schema_version"] == VTT_COMMIT_RESPONSE_SCHEMA_VERSION
        assert started_response.json()["revision"] == 1

        winning_command = _wire_command(
            command_id="vela-winning-turn",
            session_id=session_id,
            actor_id="vela_quill",
            expected_revision=1,
            mode="commit",
            kind=DECLARATION_COMMAND_KIND,
            payload=_winning_declaration_payload(),
        )
        winning_response = first_client.post(
            "/api/v1/commands",
            json=winning_command,
        )
        assert winning_response.status_code == 200
        assert winning_response.json()["schema_version"] == VTT_COMMIT_RESPONSE_SCHEMA_VERSION
        assert winning_response.json()["revision"] == 2
        assert winning_response.json()["events"][-1]["payload"]["outcome"] == "party_victory"

        terminal_response = first_client.get("/api/v1/session")
        assert terminal_response.status_code == 200
        terminal = terminal_response.json()
        assert terminal["revision"] == 2
        assert terminal["projection"]["phase"] == "terminal"
        assert terminal["projection"]["outcome"] == "party_victory"
        terminal_json = _canonical_json(terminal)

    assert _stored_command_count(database_path) == 2

    second_app = create_solo_table_app(database_path)
    with TestClient(second_app, raise_server_exceptions=False) as second_client:
        restored_response = second_client.get("/api/v1/session")
        assert restored_response.status_code == 200
        assert _canonical_json(restored_response.json()) == terminal_json

        replay_response = second_client.post(
            "/api/v1/commands",
            json=winning_command,
        )
        assert replay_response.status_code == 200
        assert replay_response.json()["replayed"] is True
        assert replay_response.json()["revision"] == 2

        after_retry_response = second_client.get("/api/v1/session")
        assert after_retry_response.status_code == 200
        assert _canonical_json(after_retry_response.json()) == terminal_json

    assert _stored_command_count(database_path) == 2


def test_solo_table_app_uses_a_fresh_fixture_for_a_separate_database(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "fresh-echo-vault.sqlite3"

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as client:
        response = client.get("/api/v1/session")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == VTT_SESSION_VIEW_SCHEMA_VERSION
    assert payload["revision"] == 0
    assert payload["projection"]["phase"] == "unstarted"
    assert payload["projection"]["outcome"] is None
    assert _stored_command_count(database_path) == 0


def test_solo_table_replay_matches_on_two_independent_fresh_databases(
    tmp_path: Path,
) -> None:
    first = _complete_fresh_solo_table(tmp_path / "first-replay.sqlite3")
    second = _complete_fresh_solo_table(tmp_path / "second-replay.sqlite3")

    assert first["projection"]["phase"] == "terminal"
    assert first["projection"]["outcome"] == "party_victory"
    assert _canonical_json(second) == _canonical_json(first)
    assert _stored_command_count(tmp_path / "first-replay.sqlite3") == 2
    assert _stored_command_count(tmp_path / "second-replay.sqlite3") == 2


def test_solo_table_persists_browser_ping_across_restart_and_exact_retry(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "solo-annotations.sqlite3"
    request = _public_ping_request(
        session_id="echo-vault-session",
        command_id="browser-ping-once",
        annotation_id="browser-ping",
        expected_revision=0,
    )

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as first_client:
        empty = first_client.get("/api/v1/annotations")
        assert empty.status_code == 200
        assert empty.json() == {
            "schema_version": "vtt.annotations_view.v1",
            "session_id": "echo-vault-session",
            "table_id": "echo-vault-session",
            "scene_id": "echo-vault",
            "revision": 0,
            "annotations": [],
        }

        created = first_client.post("/api/v1/annotation-commands", json=request)
        assert created.status_code == 200
        assert created.json()["replayed"] is False
        assert created.json()["receipt"]["revision"] == 1
        stored_annotation = created.json()["receipt"]["event"]["annotation"]
        assert stored_annotation["author_id"] == "local"
        assert stored_annotation["position"] == {
            "x_ft": 20.0,
            "y_ft": 15.0,
            "z_ft": 0.0,
        }

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as restored_client:
        restored = restored_client.get("/api/v1/annotations")
        assert restored.status_code == 200
        assert restored.json()["revision"] == 1
        assert restored.json()["annotations"] == [stored_annotation]

        replayed = restored_client.post("/api/v1/annotation-commands", json=request)
        assert replayed.status_code == 200
        assert replayed.json()["replayed"] is True
        assert replayed.json()["receipt"] == created.json()["receipt"]


def test_solo_table_persists_inert_layered_drawing_across_restart_and_retry(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "solo-drawing.sqlite3"
    request = _public_text_drawing_request(
        session_id="echo-vault-session",
        command_id="browser-drawing-once",
        annotation_id="browser-drawing",
        expected_revision=0,
    )

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as first_client:
        created = first_client.post("/api/v1/annotation-commands", json=request)
        assert created.status_code == 200
        stored = created.json()["receipt"]["event"]["annotation"]
        assert stored["author_id"] == "local"
        assert stored["layer"] == "over_tokens"
        assert stored["locked"] is True
        assert stored["text"] == "Hold <script>alert(1)</script>\nNorth"
        assert stored["style"]["opacity"] == 1.0

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as restored_client:
        restored = restored_client.get("/api/v1/annotations")
        replayed = restored_client.post("/api/v1/annotation-commands", json=request)

    assert restored.status_code == 200
    assert restored.json()["revision"] == 1
    assert restored.json()["annotations"] == [stored]
    assert replayed.status_code == 200
    assert replayed.json()["replayed"] is True
    assert replayed.json()["receipt"] == created.json()["receipt"]


def test_solo_table_persists_open_local_plain_text_chat_across_restart_and_retry(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "solo-chat.sqlite3"
    literal_text = "<b>literal HTML</b> & <script>alert('still text')</script>\n**plain text**"
    request = _public_chat_request(
        session_id="echo-vault-session",
        command_id="local-chat-once",
        message_id="local-message",
        expected_revision=0,
        text=literal_text,
    )

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as first_client:
        empty = first_client.get("/api/v1/chat")
        session_before = first_client.get("/api/v1/session")

        assert empty.status_code == 200
        assert empty.json() == {
            "schema_version": "vtt.chat_view.v1",
            "session_id": "echo-vault-session",
            "table_id": "echo-vault-session",
            "revision": 0,
            "messages": [],
        }
        assert session_before.status_code == 200
        assert session_before.json()["revision"] == 0

        created = first_client.post("/api/v1/chat-commands", json=request)

        assert created.status_code == 200
        created_payload = created.json()
        assert created_payload["schema_version"] == "vtt.chat_response.v1"
        assert created_payload["revision"] == 1
        assert created_payload["replayed"] is False
        assert created_payload["event"]["message"]["author_id"] == "local"
        assert created_payload["event"]["message"]["audience"] == ["all"]
        assert created_payload["event"]["message"]["text"] == literal_text
        assert first_client.get("/api/v1/session").json()["revision"] == 0

    assert _stored_chat_event_count(database_path) == 1

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as restored_client:
        restored = restored_client.get("/api/v1/chat")

        assert restored.status_code == 200
        restored_payload = restored.json()
        assert restored_payload["revision"] == 1
        assert restored_payload["messages"] == [created_payload["event"]["message"]]
        assert restored_payload["messages"][0]["author_id"] == "local"
        assert restored_payload["messages"][0]["text"] == literal_text
        assert restored_client.get("/api/v1/session").json()["revision"] == 0

        replayed = restored_client.post("/api/v1/chat-commands", json=request)

        assert replayed.status_code == 200
        assert replayed.json()["replayed"] is True
        assert replayed.json()["revision"] == 1
        after_retry = restored_client.get("/api/v1/chat").json()
        assert after_retry["revision"] == 1
        assert after_retry["messages"] == restored_payload["messages"]

    assert _stored_chat_event_count(database_path) == 1


def test_solo_table_seeds_and_persists_scene_library_across_restart_and_retry(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "solo-scenes.sqlite3"
    request = _public_scene_create_request(
        session_id="echo-vault-session",
        command_id="create-second-map",
        scene_id="second-map",
        # Revision one is the deterministic Echo Vault bootstrap event.
        expected_revision=1,
    )

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as first_client:
        initial = first_client.get("/api/v1/scenes")
        assert initial.status_code == 200
        assert initial.json()["revision"] == 1
        assert initial.json()["active_scene_id"] == "echo-vault"
        assert initial.json()["scenes"] == [
            {
                "scene": {
                    "schema_version": "vtt.scene_record.v1",
                    "scene_id": "echo-vault",
                    "map_metadata": {
                        "schema_version": "vtt.scene_map_metadata.v1",
                        "name": "Echo Vault",
                        "width_px": 1_448,
                        "height_px": 1_086,
                        "grid_size_px": 181.0,
                        "gridless": False,
                        "calibration": {
                            "schema_version": "vtt.board_calibration.v1",
                            "topology": "square",
                            "origin_x_px": 90.5,
                            "origin_y_px": 90.5,
                            "cell_extent_px": 181.0,
                            "distance_ft": 5.0,
                        },
                        "asset": {
                            "schema_version": "vtt.scene_map_asset.v1",
                            "asset_id": "echo-vault-original",
                            "media_type": "image/png",
                            "content_path": "/assets/maps/echo-vault-original.png",
                            "sha256": (
                                "90ece48257967087c27ac6ae2da497434526f88811242b9ae"
                                "7a267cbee0d6b89"
                            ),
                            "alt_text": (
                                "A top-down arcane vault chamber with a fractured "
                                "central resonator and broken stone colonnades."
                            ),
                        },
                    },
                },
                "archived": False,
            }
        ]

        created = first_client.post("/api/v1/scene-commands", json=request)
        assert created.status_code == 200
        assert created.json()["revision"] == 2
        assert created.json()["replayed"] is False
        activated = first_client.post(
            "/api/v1/scene-commands",
            json={
                "schema_version": "vtt.scene_library_request.v1",
                "session_id": "echo-vault-session",
                "command": {
                    "schema_version": "vtt.scene_command.v1",
                    "command_type": "activate",
                    "table_id": "echo-vault-session",
                    "command_id": "activate-second-map",
                    "expected_revision": 2,
                    "scene_id": "second-map",
                },
            },
        )
        assert activated.status_code == 200
        active_session = first_client.get("/api/v1/session").json()
        assert active_session["scene"]["scene_id"] == "second-map"
        assert active_session["active_board"]["scene_revision"] == 3

    assert _stored_scene_event_count(database_path) == 3

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as restored_client:
        restored = restored_client.get("/api/v1/scenes")
        assert restored.status_code == 200
        assert restored.json()["revision"] == 3
        assert restored.json()["active_scene_id"] == "second-map"
        assert [entry["scene"]["scene_id"] for entry in restored.json()["scenes"]] == [
            "echo-vault",
            "second-map",
        ]

        replayed = restored_client.post("/api/v1/scene-commands", json=request)
        assert replayed.status_code == 200
        assert replayed.json()["replayed"] is True
        assert replayed.json()["revision"] == 2
        restored_session = restored_client.get("/api/v1/session").json()
        assert restored_session["scene"]["scene_id"] == "second-map"
        assert restored_session["active_board"]["scene_revision"] == 3

    assert _stored_scene_event_count(database_path) == 3


def test_solo_table_persists_open_local_presence_across_restart_and_exact_retry(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "solo-presence.sqlite3"
    request = _public_presence_heartbeat_request(
        session_id="echo-vault-session",
        command_id="local-heartbeat-once",
        expected_revision=0,
    )

    with TestClient(
        create_solo_table_app(database_path, epoch_ms_clock=lambda: 1_000),
        raise_server_exceptions=False,
    ) as first_client:
        initial = first_client.get("/api/v1/presence")
        assert initial.status_code == 200
        assert initial.json()["records"] == [
            {
                "schema_version": "vtt.presence_record.v1",
                "participant_id": "local",
                "display_name": "Local GM",
                "role": "gm",
                "status": "offline",
            }
        ]

        created = first_client.post("/api/v1/presence-heartbeats", json=request)
        assert created.status_code == 200
        assert created.json()["replayed"] is False
        assert created.json()["signal"] == {
            "schema_version": "vtt.presence_change_signal.v1",
            "sequence": 1,
            "revision": 1,
            "participant_id": "local",
        }
        assert "client_id" not in created.text
        assert "observed_at" not in created.text

    assert _stored_presence_event_count(database_path) == 1

    with TestClient(
        create_solo_table_app(database_path, epoch_ms_clock=lambda: 1_001),
        raise_server_exceptions=False,
    ) as restored_client:
        restored = restored_client.get("/api/v1/presence")
        assert restored.status_code == 200
        assert restored.json()["records"][0]["status"] == "online"

        replayed = restored_client.post("/api/v1/presence-heartbeats", json=request)
        assert replayed.status_code == 200
        assert replayed.json()["replayed"] is True
        assert replayed.json()["signal"] == created.json()["signal"]

    assert _stored_presence_event_count(database_path) == 1


def test_solo_table_persists_uploaded_map_asset_bytes_across_restart_and_retry(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "solo-map-assets.sqlite3"
    request, content = _public_map_asset_upload_request()

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as first_client:
        initial = first_client.get("/api/v1/map-assets")
        assert initial.status_code == 200
        assert initial.json()["revision"] == 0
        assert initial.json()["assets"] == []

        created = first_client.post("/api/v1/map-assets", json=request)
        assert created.status_code == 200
        assert created.json()["replayed"] is False
        assert created.json()["asset"]["width_px"] == 96
        content_path = created.json()["asset"]["reference"]["content_path"]
        served = first_client.get(content_path)
        assert served.status_code == 200
        assert served.content == content

    assert _stored_map_asset_count(database_path) == 1

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as restored_client:
        restored = restored_client.get("/api/v1/map-assets")
        assert restored.status_code == 200
        assert restored.json()["revision"] == 1
        assert [asset["reference"]["asset_id"] for asset in restored.json()["assets"]] == [
            "sunken-observatory"
        ]

        replayed = restored_client.post("/api/v1/map-assets", json=request)
        assert replayed.status_code == 200
        assert replayed.json()["replayed"] is True
        assert replayed.json()["revision"] == 1

    assert _stored_map_asset_count(database_path) == 1


def test_solo_table_seeds_and_persists_linked_token_presentation_across_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "solo-tokens.sqlite3"

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as first_client:
        initial = first_client.get("/api/v1/tokens?scene_id=echo-vault")
        assert initial.status_code == 200
        assert initial.json()["revision"] == 2
        assert [token["token_id"] for token in initial.json()["tokens"]] == [
            "hushglass_sentry-token",
            "vela_quill-token",
        ]
        vela = next(
            token for token in initial.json()["tokens"] if token["actor_id"] == "vela_quill"
        )
        assert vela["pose"]["position_ft"] == {
            "x_ft": 12.5,
            "y_ft": 12.5,
            "z_ft": 0.0,
        }
        vela["pose"]["rotation_degrees"] = 45.0
        request = {
            "schema_version": "vtt.token_request.v1",
            "session_id": "echo-vault-session",
            "command": {
                "schema_version": "vtt.token_command.v1",
                "command_type": "update",
                "table_id": "echo-vault-session",
                "command_id": "rotate-vela-token",
                "expected_revision": 2,
                "token": vela,
            },
        }
        updated = first_client.post("/api/v1/token-commands", json=request)
        assert updated.status_code == 200
        assert updated.json()["replayed"] is False

    assert _stored_token_event_count(database_path) == 3

    with TestClient(
        create_solo_table_app(database_path),
        raise_server_exceptions=False,
    ) as restored_client:
        restored = restored_client.get("/api/v1/tokens?scene_id=echo-vault")
        assert restored.status_code == 200
        restored_vela = next(
            token for token in restored.json()["tokens"] if token["actor_id"] == "vela_quill"
        )
        assert restored_vela["pose"]["rotation_degrees"] == 45.0
        replayed = restored_client.post("/api/v1/token-commands", json=request)
        assert replayed.status_code == 200
        assert replayed.json()["replayed"] is True

    assert _stored_token_event_count(database_path) == 3


def test_solo_table_persists_journal_handout_pin_and_exact_retry_across_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "solo-journal.sqlite3"
    request = {
        "schema_version": "vtt.journal_request.v1",
        "session_id": "echo-vault-session",
        "command": {
            "schema_version": "vtt.journal_command.v1",
            "command_type": "put_document",
            "table_id": "echo-vault-session",
            "command_id": "create-vault-handout",
            "expected_revision": 0,
            "document": {
                "schema_version": "vtt.journal_document.v1",
                "document_id": "vault-handout",
                "document_type": "handout",
                "folder_id": None,
                "title": "Vault Handout",
                "audience": ["all"],
                "tags": ["lore"],
                "favorite": True,
                "blocks": [
                    {
                        "schema_version": "vtt.journal_block.v1",
                        "block_type": "paragraph",
                        "text": "The resonator answers a whispered chord.",
                    }
                ],
                "map_pin": {
                    "schema_version": "vtt.journal_map_pin.v1",
                    "scene_id": "echo-vault",
                    "position": {"x_ft": 7.5, "y_ft": 7.5, "z_ft": 0.0},
                    "color": "#5eead4",
                },
            },
        },
    }

    with TestClient(create_solo_table_app(database_path), raise_server_exceptions=False) as client:
        created = client.post("/api/v1/journal-commands", json=request)
        assert created.status_code == 200
        assert created.json()["replayed"] is False

    with TestClient(create_solo_table_app(database_path), raise_server_exceptions=False) as client:
        restored = client.get("/api/v1/journal")
        assert restored.status_code == 200
        assert restored.json()["revision"] == 1
        assert restored.json()["documents"][0]["document_id"] == "vault-handout"
        assert restored.json()["documents"][0]["map_pin"]["scene_id"] == "echo-vault"
        replayed = client.post("/api/v1/journal-commands", json=request)
        assert replayed.status_code == 200
        assert replayed.json()["replayed"] is True
        assert replayed.json()["receipt"] == created.json()["receipt"]


def test_solo_table_persists_sound_and_shared_camera_across_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "solo-presentation.sqlite3"
    payload = b"\x00\x00\x01\x00"
    body = (
        b"WAVEfmt "
        + (16).to_bytes(4, "little")
        + b"\x01\x00\x01\x00"
        + (8_000).to_bytes(4, "little")
        + (16_000).to_bytes(4, "little")
        + b"\x02\x00\x10\x00data"
        + len(payload).to_bytes(4, "little")
        + payload
    )
    content = b"RIFF" + len(body).to_bytes(4, "little") + body

    def request(command: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "vtt.presentation_request.v1",
            "session_id": "echo-vault-session",
            "command": {
                "schema_version": "vtt.presentation_command.v1",
                "table_id": "echo-vault-session",
                **command,
            },
        }

    with TestClient(create_solo_table_app(database_path), raise_server_exceptions=False) as client:
        uploaded = client.post(
            "/api/v1/presentation-commands",
            json=request(
                {
                    "command_type": "upload_track",
                    "command_id": "upload-solo-hum",
                    "expected_revision": 0,
                    "track_id": "solo-hum",
                    "name": "Solo hum",
                    "content_base64": base64.b64encode(content).decode("ascii"),
                }
            ),
        )
        assert uploaded.status_code == 200
        shared = client.post(
            "/api/v1/presentation-commands",
            json=request(
                {
                    "command_type": "share_camera",
                    "command_id": "share-solo-camera",
                    "expected_revision": 1,
                    "scene_id": "echo-vault",
                    "center_x_ft": 20.0,
                    "center_y_ft": 15.0,
                    "zoom": 1.5,
                }
            ),
        )
        assert shared.status_code == 200

    with TestClient(create_solo_table_app(database_path), raise_server_exceptions=False) as client:
        restored = client.get("/api/v1/presentation")
        assert restored.status_code == 200
        assert restored.json()["revision"] == 2
        assert restored.json()["tracks"][0]["track_id"] == "solo-hum"
        assert restored.json()["camera"]["scene_id"] == "echo-vault"
        assert client.get("/api/v1/sound-assets/solo-hum/content.wav").content == content


def test_solo_table_owns_ten_independent_sqlite_connections_and_closes_them(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured_connections: list[sqlite3.Connection] = []

    def capture_composition(
        service,
        *,
        annotation_board,
        chat_log,
        scene_library,
        map_asset_store,
        token_store,
        visibility_store,
        journal_store,
        presence_store,
        presentation_store,
        **_kwargs,
    ):
        captured_connections.extend(
            [
                service._event_store._connection,
                annotation_board._connection,
                chat_log._connection,
                scene_library._connection,
                map_asset_store._connection,
                token_store._connection,
                presence_store._connection,
                visibility_store._connection,
                journal_store._connection,
                presentation_store._connection,
            ]
        )
        return FastAPI()

    monkeypatch.setattr(solo_app, "create_vtt_app", capture_composition)

    app = create_solo_table_app(tmp_path / "owned-connections.sqlite3")

    assert len(captured_connections) == 10
    assert len({id(connection) for connection in captured_connections}) == 10
    assert [
        connection.execute("PRAGMA busy_timeout").fetchone()[0]
        for connection in captured_connections
    ] == [30_000] * 10

    with TestClient(app):
        pass

    for connection in captured_connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def test_solo_table_closes_all_connections_when_http_composition_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured_connections: list[sqlite3.Connection] = []

    def fail_composition(
        service,
        *,
        annotation_board,
        chat_log,
        scene_library,
        map_asset_store,
        token_store,
        visibility_store,
        journal_store,
        presence_store,
        presentation_store,
        **_kwargs,
    ):
        captured_connections.extend(
            [
                service._event_store._connection,
                annotation_board._connection,
                chat_log._connection,
                scene_library._connection,
                map_asset_store._connection,
                token_store._connection,
                presence_store._connection,
                visibility_store._connection,
                journal_store._connection,
                presentation_store._connection,
            ]
        )
        raise RuntimeError("HTTP composition failed")

    monkeypatch.setattr(solo_app, "create_vtt_app", fail_composition)

    with pytest.raises(RuntimeError, match="HTTP composition failed"):
        create_solo_table_app(tmp_path / "failed-composition.sqlite3")

    assert len(captured_connections) == 10
    for connection in captured_connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def test_solo_table_main_passes_explicit_server_options(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "cli.sqlite3"
    sentinel_app = object()
    observed: dict[str, Any] = {}

    def fake_factory(path: Path) -> object:
        observed["database"] = path
        return sentinel_app

    monkeypatch.setattr(solo_app, "create_solo_table_app", fake_factory)

    def fake_run(app: object, *, host: str, port: int) -> None:
        observed.update({"app": app, "host": host, "port": port})

    monkeypatch.setattr(solo_app.uvicorn, "run", fake_run)

    solo_app.main(
        [
            "--database",
            str(database_path),
            "--host",
            "0.0.0.0",
            "--port",
            "9123",
        ]
    )

    assert observed == {
        "database": database_path,
        "app": sentinel_app,
        "host": "0.0.0.0",
        "port": 9123,
    }
    assert not hasattr(solo_app, "app")
