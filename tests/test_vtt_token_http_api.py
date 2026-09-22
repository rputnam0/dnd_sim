from __future__ import annotations

import json
import random
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dnd_sim.interactive import (
    DndCombatEncounterDriver,
    EngineTransition,
    EngineVersionPins,
    EventDraft,
    PendingReaction,
    PreviewOutcome,
    SessionCommand,
)
from dnd_sim.interactive.dnd_encounter_driver import START_ENCOUNTER_COMMAND_KIND
from dnd_sim.vtt.access import TableAccessPolicy
from dnd_sim.vtt.annotation_store import SQLiteAnnotationBoard
from dnd_sim.vtt.board_calibration import BoardCalibration
from dnd_sim.vtt.event_store import SQLiteSessionEventStore
from dnd_sim.vtt.http_api import VTT_ERROR_SCHEMA_VERSION, create_vtt_app
from dnd_sim.vtt.participants import (
    PARTICIPANT_SCHEMA_VERSION,
    ROSTER_SCHEMA_VERSION,
    TableParticipant,
    TableRoster,
)
from dnd_sim.vtt.scene import FeetPosition, SquareGridScene
from dnd_sim.vtt.scene_library_contracts import (
    SceneActivateCommand,
    SceneCreateCommand,
    SceneMapMetadata,
    SceneRecord,
)
from dnd_sim.vtt.scene_library_store import SQLiteSceneLibrary
from dnd_sim.vtt.session_service import VTTSessionService
from dnd_sim.vtt.solo_table import build_solo_table_fixture
from dnd_sim.vtt.token_api import (
    VTT_TOKEN_REQUEST_SCHEMA_VERSION,
    VTT_TOKEN_RESPONSE_SCHEMA_VERSION,
)
from dnd_sim.vtt import token_api
from dnd_sim.vtt.token_contracts import TOKEN_COMMAND_SCHEMA_VERSION, TokenPose, TokenRecord
from dnd_sim.vtt.token_store import SQLiteTokenStore

SESSION_ID = "token-session"
TABLE_ID = "token-table"
TOKENS = {
    "gm": "gm-token-http-1234",
    "owner": "owner-token-http-1234",
    "other": "other-token-http-1234",
    "spectator": "spectator-token-http-1234",
}


class _ActorProjectionDriver:
    version_pins = EngineVersionPins(
        engine_version="token-http@1",
        rules_version="token-rules@1",
        content_version="token-content@1",
    )

    def encode_state(self, state: Any) -> Mapping[str, Any]:
        return state

    def decode_state(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return dict(payload)

    def project_state(self, state: dict[str, Any]) -> Mapping[str, Any]:
        return state

    def preview(
        self,
        state: dict[str, Any],
        command: SessionCommand,
        rng: random.Random,
    ) -> PreviewOutcome:
        return PreviewOutcome(
            projection=state,
            events=(
                EventDraft(
                    kind="test.hidden_actor_observed",
                    payload={"actor_id": "sentry", "name": "Sentry"},
                ),
            ),
        )

    def commit(
        self,
        state: dict[str, Any],
        command: SessionCommand,
        rng: random.Random,
    ) -> EngineTransition:
        return EngineTransition(state=state, events=())

    def respond_to_reaction(
        self,
        state: dict[str, Any],
        command: SessionCommand,
        pending_reaction: PendingReaction,
        rng: random.Random,
    ) -> EngineTransition:
        raise AssertionError("token API tests do not open reactions")


def _participant(
    participant_id: str,
    role: str,
    owned_actor_ids: tuple[str, ...] = (),
) -> TableParticipant:
    return TableParticipant(
        schema_version=PARTICIPANT_SCHEMA_VERSION,
        participant_id=participant_id,
        display_name=participant_id.title(),
        role=role,
        owned_actor_ids=owned_actor_ids,
    )


def _policy() -> TableAccessPolicy:
    return TableAccessPolicy(
        roster=TableRoster(
            schema_version=ROSTER_SCHEMA_VERSION,
            table_id=TABLE_ID,
            participants=(
                _participant("gm", "gm"),
                _participant("other", "player"),
                _participant("owner", "player", ("vela",)),
                _participant("spectator", "spectator"),
            ),
        ),
        bearer_tokens=TOKENS,
    )


def _auth(participant_id: str) -> dict[str, str]:
    return {"authorization": f"Bearer {TOKENS[participant_id]}"}


def _token(
    token_id: str,
    *,
    actor_id: str | None = None,
    visibility: str = "public",
    x_ft: float = 12.5,
    rotation_degrees: float = 0.0,
) -> dict[str, Any]:
    return TokenRecord(
        token_id=token_id,
        scene_id="echo-vault",
        actor_id=actor_id,
        name=token_id.title(),
        pose=TokenPose(
            position_ft=FeetPosition(x_ft=x_ft, y_ft=12.5, z_ft=0.0),
            width_ft=5.0,
            height_ft=5.0,
            rotation_degrees=rotation_degrees,
            layer=0,
        ),
        visibility=visibility,
        locked=False,
        nameplate="hover",
        show_hp_bar=actor_id is not None,
        aura_radius_ft=0.0,
        aura_color="#4DD7B3",
        condition_labels=(),
    ).model_dump(mode="json")


def _request(
    command_id: str,
    token: dict[str, Any],
    *,
    expected_revision: int,
) -> dict[str, Any]:
    return {
        "schema_version": VTT_TOKEN_REQUEST_SCHEMA_VERSION,
        "session_id": SESSION_ID,
        "command": {
            "schema_version": TOKEN_COMMAND_SCHEMA_VERSION,
            "command_type": "create",
            "table_id": TABLE_ID,
            "command_id": command_id,
            "expected_revision": expected_revision,
            "token": token,
        },
    }


@pytest.fixture
def token_api_client(tmp_path: Path):
    path = tmp_path / "token-http.sqlite3"
    session_connection = sqlite3.connect(path, check_same_thread=False)
    scene_connection = sqlite3.connect(path, check_same_thread=False)
    token_connection = sqlite3.connect(path, check_same_thread=False)
    annotation_connection = sqlite3.connect(path, check_same_thread=False)
    service = VTTSessionService.open(
        session_id=SESSION_ID,
        initial_state={
            "actors": {
                "vela": {
                    "actor_id": "vela",
                    "position": [12.5, 12.5, 0.0],
                    "hp": 20,
                    "max_hp": 24,
                    "conditions": [],
                },
                "sentry": {
                    "actor_id": "sentry",
                    "position": [22.5, 12.5, 0.0],
                    "hp": 7,
                    "max_hp": 7,
                    "conditions": [],
                },
            }
        },
        driver=_ActorProjectionDriver(),
        seed=41,
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
                    width_px=800,
                    height_px=600,
                    grid_size_px=100.0,
                    gridless=False,
                ),
            ),
        )
    )
    store = SQLiteTokenStore(token_connection)
    annotation_board = SQLiteAnnotationBoard(annotation_connection)
    app = create_vtt_app(
        service,
        scene=SquareGridScene(
            schema_version="vtt.scene.v1",
            scene_id="echo-vault",
            name="Echo Vault",
            cell_size_ft=5.0,
            columns=8,
            rows=6,
        ),
        access_policy=_policy(),
        annotation_board=annotation_board,
        scene_library=scenes,
        token_store=store,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, store, service
    annotation_connection.close()
    token_connection.close()
    scene_connection.close()
    session_connection.close()


def _assert_error(response, *, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    assert response.json()["schema_version"] == VTT_ERROR_SCHEMA_VERSION
    assert response.json()["code"] == code
    assert "traceback" not in response.text.lower()


def test_token_contract_store_and_http_types_are_public_vtt_exports() -> None:
    import dnd_sim.vtt as vtt

    expected = {
        "TOKEN_COMMAND_SCHEMA_VERSION",
        "TOKEN_EVENT_SCHEMA_VERSION",
        "TOKEN_POSE_SCHEMA_VERSION",
        "TOKEN_RECORD_SCHEMA_VERSION",
        "TOKEN_STORE_SCHEMA_VERSION",
        "TOKEN_VIEW_SCHEMA_VERSION",
        "VTT_TOKEN_REQUEST_SCHEMA_VERSION",
        "VTT_TOKEN_RESPONSE_SCHEMA_VERSION",
        "SQLiteTokenStore",
        "TokenCreateCommand",
        "TokenPose",
        "TokenRecord",
        "TokenRequest",
        "TokenResponse",
        "TokenView",
        "project_token_view",
    }
    assert expected <= set(vtt.__all__)
    assert all(hasattr(vtt, name) for name in expected)


def test_token_routes_are_optional_and_require_a_scene_library(token_api_client) -> None:
    client, store, service = token_api_client
    optional = create_vtt_app(service, access_policy=_policy())
    with TestClient(optional, raise_server_exceptions=False) as optional_client:
        assert (
            optional_client.get(
                "/api/v1/tokens?scene_id=echo-vault", headers=_auth("gm")
            ).status_code
            == 404
        )
    with pytest.raises(ValueError, match="scene_library"):
        create_vtt_app(
            service,
            scene=SquareGridScene(
                schema_version="vtt.scene.v1",
                scene_id="echo-vault",
                name="Echo Vault",
                cell_size_ft=5.0,
                columns=8,
                rows=6,
            ),
            access_policy=_policy(),
            token_store=store,
        )


def test_token_routes_authenticate_before_query_or_body_validation(token_api_client) -> None:
    client, _store, _service = token_api_client

    _assert_error(
        client.get("/api/v1/tokens?scene_id=../secret"),
        status_code=401,
        code="authentication_required",
    )
    _assert_error(
        client.post("/api/v1/token-commands", json={"invalid": True}),
        status_code=401,
        code="authentication_required",
    )


def test_gm_mutations_and_server_projection_enforce_token_visibility(token_api_client) -> None:
    client, _store, _service = token_api_client
    payloads = (
        _request("create-public", _token("public"), expected_revision=0),
        _request(
            "create-owned",
            _token("owned", actor_id="vela", visibility="owners"),
            expected_revision=1,
        ),
        _request(
            "create-secret",
            _token("secret", actor_id="sentry", visibility="gm_only", x_ft=22.5),
            expected_revision=2,
        ),
    )
    for expected_revision, payload in enumerate(payloads, start=1):
        response = client.post("/api/v1/token-commands", json=payload, headers=_auth("gm"))
        assert response.status_code == 200
        assert response.json()["schema_version"] == VTT_TOKEN_RESPONSE_SCHEMA_VERSION
        assert response.json()["revision"] == expected_revision

    views = {
        identity: client.get(
            "/api/v1/tokens?scene_id=echo-vault",
            headers=_auth(identity),
        ).json()
        for identity in TOKENS
    }
    assert [token["token_id"] for token in views["gm"]["tokens"]] == [
        "owned",
        "public",
        "secret",
    ]
    assert [token["token_id"] for token in views["owner"]["tokens"]] == [
        "owned",
        "public",
    ]
    assert [token["token_id"] for token in views["other"]["tokens"]] == ["public"]
    assert [token["token_id"] for token in views["spectator"]["tokens"]] == ["public"]
    assert "secret" not in str(views["spectator"])
    assert "sentry" not in str(views["spectator"])

    session_views = {
        identity: client.get("/api/v1/session", headers=_auth(identity)).json()["projection"]
        for identity in ("gm", "owner", "other", "spectator")
    }
    assert set(session_views["gm"]["actors"]) == {"sentry", "vela"}
    assert set(session_views["owner"]["actors"]) == {"vela"}
    assert session_views["other"]["actors"] == {}
    assert session_views["spectator"]["actors"] == {}
    assert "sentry" not in str(session_views["owner"])
    assert "vela" not in str(session_views["other"])

    _assert_error(
        client.post("/api/v1/token-commands", json=payloads[0], headers=_auth("owner")),
        status_code=403,
        code="token_forbidden",
    )


def test_linked_actor_position_can_only_change_through_engine_authority(token_api_client) -> None:
    client, _store, _service = token_api_client
    created = client.post(
        "/api/v1/token-commands",
        json=_request(
            "create-vela",
            _token("vela-token", actor_id="vela", visibility="owners"),
            expected_revision=0,
        ),
        headers=_auth("gm"),
    )
    assert created.status_code == 200

    moved = created.json()["event"]["token"]
    moved["pose"]["position_ft"]["x_ft"] = 17.5
    update = {
        "schema_version": VTT_TOKEN_REQUEST_SCHEMA_VERSION,
        "session_id": SESSION_ID,
        "command": {
            "schema_version": TOKEN_COMMAND_SCHEMA_VERSION,
            "command_type": "update",
            "table_id": TABLE_ID,
            "command_id": "move-linked-token",
            "expected_revision": 1,
            "token": moved,
        },
    }
    _assert_error(
        client.post("/api/v1/token-commands", json=update, headers=_auth("gm")),
        status_code=409,
        code="token_actor_position_authoritative",
    )

    moved["pose"]["position_ft"]["x_ft"] = 12.5
    moved["pose"]["rotation_degrees"] = 90.0
    update["command"]["command_id"] = "rotate-linked-token"
    rotated = client.post("/api/v1/token-commands", json=update, headers=_auth("gm"))
    assert rotated.status_code == 200
    view = client.get(
        "/api/v1/tokens?scene_id=echo-vault",
        headers=_auth("owner"),
    ).json()
    assert view["tokens"][0]["pose"]["position_ft"] == {
        "x_ft": 12.5,
        "y_ft": 12.5,
        "z_ft": 0.0,
    }
    assert view["tokens"][0]["pose"]["rotation_degrees"] == 90.0


def test_player_preview_projection_cannot_reveal_hidden_token_actors(
    token_api_client,
) -> None:
    client, _store, _service = token_api_client
    for payload in (
        _request(
            "create-preview-owned",
            _token("preview-owned", actor_id="vela", visibility="owners"),
            expected_revision=0,
        ),
        _request(
            "create-preview-hidden",
            _token(
                "preview-hidden",
                actor_id="sentry",
                visibility="gm_only",
                x_ft=22.5,
            ),
            expected_revision=1,
        ),
    ):
        assert (
            client.post("/api/v1/token-commands", json=payload, headers=_auth("gm")).status_code
            == 200
        )

    preview = client.post(
        "/api/v1/commands",
        headers=_auth("owner"),
        json={
            "schema_version": "vtt.command.v1",
            "command_id": "owner-preview",
            "session_id": SESSION_ID,
            "actor_id": "vela",
            "expected_revision": 0,
            "mode": "preview",
            "kind": "test.preview",
            "payload": {},
            "intent_metadata": {},
        },
    )

    assert preview.status_code == 200
    assert set(preview.json()["projection"]["actors"]) == {"vela"}
    assert "sentry" not in preview.text
    assert preview.json()["events"] == []


def test_real_driver_rejects_hidden_actor_targets_before_preview_or_commit(
    tmp_path: Path,
) -> None:
    fixture = build_solo_table_fixture()
    path = tmp_path / "real-token-authority.sqlite3"
    session_connection = sqlite3.connect(path, check_same_thread=False)
    scene_connection = sqlite3.connect(path, check_same_thread=False)
    token_connection = sqlite3.connect(path, check_same_thread=False)
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
            command_id="seed-real-scene",
            expected_revision=0,
            scene=SceneRecord(
                scene_id=fixture.scene.scene_id,
                map_metadata=SceneMapMetadata(
                    name=fixture.scene.name,
                    width_px=800,
                    height_px=600,
                    grid_size_px=100.0,
                    gridless=False,
                ),
            ),
        )
    )
    store = SQLiteTokenStore(token_connection)
    policy = TableAccessPolicy(
        roster=TableRoster(
            schema_version=ROSTER_SCHEMA_VERSION,
            table_id=TABLE_ID,
            participants=(
                _participant("gm", "gm"),
                _participant("owner", "player", ("vela_quill",)),
            ),
        ),
        bearer_tokens={"gm": TOKENS["gm"], "owner": TOKENS["owner"]},
    )
    app = create_vtt_app(
        service,
        scene=fixture.scene,
        access_policy=policy,
        scene_library=scenes,
        token_store=store,
    )

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            for request in (
                _request(
                    "create-real-owner",
                    _token(
                        "real-owner",
                        actor_id="vela_quill",
                        visibility="owners",
                    ),
                    expected_revision=0,
                ),
                _request(
                    "create-real-hidden",
                    _token(
                        "real-hidden",
                        actor_id="hushglass_sentry",
                        visibility="gm_only",
                        x_ft=22.5,
                    ),
                    expected_revision=1,
                ),
            ):
                assert (
                    client.post(
                        "/api/v1/token-commands",
                        json=request,
                        headers=_auth("gm"),
                    ).status_code
                    == 200
                )

            started = client.post(
                "/api/v1/commands",
                headers=_auth("gm"),
                json={
                    "schema_version": "vtt.command.v1",
                    "command_id": "start-real-encounter",
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
            player_view = client.get("/api/v1/session", headers=_auth("owner"))
            assert player_view.status_code == 200
            assert set(player_view.json()["projection"]["actors"]) == {"vela_quill"}
            assert "hushglass_sentry" not in player_view.text

            before = service.read_view()
            hidden_target_payload = {
                "movement_path": [[12.5, 12.5, 0.0], [17.5, 12.5, 0.0]],
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
                rejected = client.post(
                    "/api/v1/commands",
                    headers=_auth("owner"),
                    json={
                        "schema_version": "vtt.command.v1",
                        "command_id": f"crafted-hidden-{mode}",
                        "session_id": SESSION_ID,
                        "actor_id": "vela_quill",
                        "expected_revision": 1,
                        "mode": mode,
                        "kind": "dnd.declare_turn.v1",
                        "payload": hidden_target_payload,
                        "intent_metadata": {},
                    },
                )
                _assert_error(
                    rejected,
                    status_code=403,
                    code="command_target_not_visible",
                )
                assert "hushglass_sentry" not in rejected.text
                assert service.read_view() == before
                assert service.revision == 1
                assert service.read_view().projection["actors"]["hushglass_sentry"]["hp"] == 7
    finally:
        token_connection.close()
        scene_connection.close()
        session_connection.close()


def test_token_change_signal_contains_only_scene_revision_and_sequence(
    token_api_client,
) -> None:
    client, store, _service = token_api_client
    created = client.post(
        "/api/v1/token-commands",
        json=_request("create-signal-token", _token("signal-secret"), expected_revision=0),
        headers=_auth("gm"),
    )
    assert created.status_code == 200
    event = store.events_after(TABLE_ID, 0)[0]

    block = token_api._render_signal(event, "echo-vault")
    lines = dict(line.split(": ", 1) for line in block.strip().splitlines() if ": " in line)
    assert lines["id"] == "1"
    assert lines["event"] == "vtt.tokens_changed"
    assert json.loads(lines["data"]) == {
        "revision": 1,
        "scene_id": "echo-vault",
        "schema_version": "vtt.token_change_signal.v1",
        "sequence": 1,
    }
    assert "signal-secret" not in block


@pytest.mark.parametrize(
    ("x_ft", "rotation_degrees"),
    ((-0.1, 0.0), (1.0, 45.0), (39.0, 0.0)),
)
def test_token_pose_must_fit_entirely_inside_the_configured_board(
    token_api_client,
    x_ft: float,
    rotation_degrees: float,
) -> None:
    client, store, _service = token_api_client
    response = client.post(
        "/api/v1/token-commands",
        json=_request(
            f"off-board-{str(x_ft).replace('.', '-')}-{int(rotation_degrees)}",
            _token(
                "off-board",
                x_ft=x_ft,
                rotation_degrees=rotation_degrees,
            ),
            expected_revision=0,
        ),
        headers=_auth("gm"),
    )

    _assert_error(response, status_code=409, code="token_pose_out_of_bounds")
    assert store.revision(TABLE_ID) == 0


def test_token_bounds_follow_the_target_scene_calibration_not_bootstrap_geometry(
    token_api_client,
) -> None:
    client, store, _service = token_api_client
    scenes = client.app.state.vtt_scene_library
    scenes.execute(
        SceneCreateCommand(
            table_id=TABLE_ID,
            command_id="create-hex-room",
            expected_revision=1,
            scene=SceneRecord(
                scene_id="hex-room",
                map_metadata=SceneMapMetadata(
                    name="Hex Room",
                    width_px=800,
                    height_px=600,
                    grid_size_px=100.0,
                    gridless=False,
                    calibration=BoardCalibration(
                        topology="hex_pointy",
                        origin_x_px=100.0,
                        origin_y_px=100.0,
                        cell_extent_px=100.0,
                        distance_ft=5.0,
                    ),
                ),
            ),
        )
    )
    valid_token = _token("hex-token", x_ft=12.5)
    valid_token["scene_id"] = "hex-room"
    valid_token["pose"]["occupied_hex_cells"] = [
        {"q": 1, "r": 2},
        {"q": 1, "r": 3},
    ]
    created = client.post(
        "/api/v1/token-commands",
        json=_request(
            "create-hex-token",
            valid_token,
            expected_revision=0,
        ),
        headers=_auth("gm"),
    )
    assert created.status_code == 200
    assert (
        client.get(
            "/api/v1/tokens?scene_id=hex-room",
            headers=_auth("gm"),
        ).status_code
        == 200
    )

    outside_token = _token("hex-edge-token", x_ft=37.5)
    outside_token["scene_id"] = "hex-room"
    outside_token["pose"]["occupied_hex_cells"] = [{"q": 6, "r": 2}]
    rejected = client.post(
        "/api/v1/token-commands",
        json=_request(
            "create-hex-edge-token",
            outside_token,
            expected_revision=1,
        ),
        headers=_auth("gm"),
    )
    _assert_error(rejected, status_code=409, code="token_pose_out_of_bounds")
    assert store.revision(TABLE_ID) == 1


def test_hex_footprint_ignores_rotation_but_requires_complete_connected_cells(
    token_api_client,
) -> None:
    client, store, _service = token_api_client
    scenes = client.app.state.vtt_scene_library
    scenes.execute(
        SceneCreateCommand(
            table_id=TABLE_ID,
            command_id="create-flat-hex-room",
            expected_revision=1,
            scene=SceneRecord(
                scene_id="flat-hex-room",
                map_metadata=SceneMapMetadata(
                    name="Flat Hex Room",
                    width_px=800,
                    height_px=600,
                    grid_size_px=100.0,
                    gridless=False,
                    calibration=BoardCalibration(
                        topology="hex_flat",
                        origin_x_px=100.0,
                        origin_y_px=100.0,
                        cell_extent_px=100.0,
                        distance_ft=5.0,
                    ),
                ),
            ),
        )
    )
    for revision, rotation in enumerate((0.0, 173.0)):
        token = _token(f"rotated-{revision}", x_ft=12.5, rotation_degrees=rotation)
        token["scene_id"] = "flat-hex-room"
        token["pose"]["occupied_hex_cells"] = [{"q": 2, "r": 1}]
        response = client.post(
            "/api/v1/token-commands",
            json=_request(
                f"create-rotated-{revision}",
                token,
                expected_revision=revision,
            ),
            headers=_auth("gm"),
        )
        assert response.status_code == 200

    disconnected = _token("disconnected", x_ft=12.5)
    disconnected["scene_id"] = "flat-hex-room"
    disconnected["pose"]["occupied_hex_cells"] = [
        {"q": 2, "r": 1},
        {"q": 4, "r": 1},
    ]
    rejected = client.post(
        "/api/v1/token-commands",
        json=_request("create-disconnected", disconnected, expected_revision=2),
        headers=_auth("gm"),
    )
    _assert_error(rejected, status_code=409, code="token_hex_footprint_invalid")
    assert store.revision(TABLE_ID) == 2


def test_active_scene_is_one_authority_for_session_tokens_annotations_and_privacy(
    token_api_client,
) -> None:
    client, store, _service = token_api_client
    scenes = client.app.state.vtt_scene_library
    old_hidden = _token(
        "old-hidden",
        actor_id="sentry",
        visibility="gm_only",
        x_ft=22.5,
    )
    assert (
        client.post(
            "/api/v1/token-commands",
            json=_request("create-old-hidden", old_hidden, expected_revision=0),
            headers=_auth("gm"),
        ).status_code
        == 200
    )
    scenes.execute(
        SceneCreateCommand(
            table_id=TABLE_ID,
            command_id="create-authoritative-hex",
            expected_revision=1,
            scene=SceneRecord(
                scene_id="authoritative-hex",
                map_metadata=SceneMapMetadata(
                    name="Authoritative Hex",
                    width_px=800,
                    height_px=600,
                    grid_size_px=100.0,
                    gridless=False,
                    calibration=BoardCalibration(
                        topology="hex_pointy",
                        origin_x_px=100.0,
                        origin_y_px=100.0,
                        cell_extent_px=100.0,
                        distance_ft=5.0,
                    ),
                ),
            ),
        )
    )
    hex_owner = _token("hex-owner", actor_id="vela", visibility="owners")
    hex_owner["scene_id"] = "authoritative-hex"
    hex_owner["pose"]["occupied_hex_cells"] = [{"q": 1, "r": 2}]
    assert (
        client.post(
            "/api/v1/token-commands",
            json=_request("create-hex-owner", hex_owner, expected_revision=1),
            headers=_auth("gm"),
        ).status_code
        == 200
    )
    scenes.execute(
        SceneActivateCommand(
            table_id=TABLE_ID,
            command_id="activate-authoritative-hex",
            expected_revision=2,
            scene_id="authoritative-hex",
        )
    )

    session = client.get("/api/v1/session", headers=_auth("owner"))
    assert session.status_code == 200
    payload = session.json()
    assert payload["scene"]["scene_id"] == "authoritative-hex"
    assert payload["active_board"]["scene_revision"] == 3
    assert payload["active_board"]["map_metadata"]["calibration"]["topology"] == "hex_pointy"
    assert set(payload["projection"]["actors"]) == {"vela"}
    assert "sentry" not in session.text

    tokens = client.get(
        "/api/v1/tokens?scene_id=authoritative-hex",
        headers=_auth("owner"),
    )
    assert tokens.status_code == 200
    assert [token["token_id"] for token in tokens.json()["tokens"]] == ["hex-owner"]
    assert (
        client.get(
            "/api/v1/tokens?scene_id=echo-vault",
            headers=_auth("owner"),
        ).status_code
        == 404
    )
    assert store.revision(TABLE_ID) == 2

    annotations = client.get("/api/v1/annotations", headers=_auth("owner"))
    assert annotations.status_code == 200
    assert annotations.json()["scene_id"] == "authoritative-hex"
    assert annotations.json()["annotations"] == []
    old_scene_put = {
        "schema_version": "vtt.annotation_request.v1",
        "session_id": SESSION_ID,
        "command": {
            "schema_version": "vtt.annotation_command.v1",
            "command_type": "put",
            "table_id": TABLE_ID,
            "command_id": "put-old-scene",
            "expected_revision": 0,
            "annotation": {
                "schema_version": "vtt.annotation.v1",
                "annotation_type": "ping",
                "annotation_id": "old-scene-ping",
                "scene_id": "echo-vault",
                "author_id": "owner",
                "audience": ["all"],
                "position": {"x_ft": 12.5, "y_ft": 12.5, "z_ft": 0.0},
                "duration_ms": 1500,
            },
        },
    }
    rejected = client.post(
        "/api/v1/annotation-commands",
        json=old_scene_put,
        headers=_auth("owner"),
    )
    assert rejected.status_code == 409
    assert rejected.json()["details"] == {"expected_scene_id": "authoritative-hex"}
    active_put = json.loads(json.dumps(old_scene_put))
    active_put["command"]["command_id"] = "put-active-scene"
    active_put["command"]["annotation"]["annotation_id"] = "active-scene-ping"
    active_put["command"]["annotation"]["scene_id"] = "authoritative-hex"
    accepted = client.post(
        "/api/v1/annotation-commands",
        json=active_put,
        headers=_auth("owner"),
    )
    assert accepted.status_code == 200
    refreshed = client.get("/api/v1/annotations", headers=_auth("owner")).json()
    assert [annotation["annotation_id"] for annotation in refreshed["annotations"]] == [
        "active-scene-ping"
    ]
