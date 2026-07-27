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
from dnd_sim.vtt import annotation_api
from dnd_sim.vtt.access import TableAccessPolicy
from dnd_sim.vtt.annotation_api import (
    VTT_ANNOTATIONS_VIEW_SCHEMA_VERSION,
    VTT_ANNOTATION_REQUEST_SCHEMA_VERSION,
    VTT_ANNOTATION_RESPONSE_SCHEMA_VERSION,
)
from dnd_sim.vtt.annotation_store import (
    ANNOTATION_COMMAND_SCHEMA_VERSION,
    AnnotationPutCommand,
    AnnotationStoreCorruptionError,
    SQLiteAnnotationBoard,
)
from dnd_sim.vtt.annotations import ANNOTATION_SCHEMA_VERSION, PingAnnotation
from dnd_sim.vtt.event_store import SQLiteSessionEventStore
from dnd_sim.vtt.http_api import VTT_ERROR_SCHEMA_VERSION, create_vtt_app
from dnd_sim.vtt.participants import (
    PARTICIPANT_SCHEMA_VERSION,
    ROSTER_SCHEMA_VERSION,
    TableParticipant,
    TableRoster,
)
from dnd_sim.vtt.scene import SCENE_SCHEMA_VERSION, SquareGridScene
from dnd_sim.vtt.session_service import VTTSessionService

SESSION_ID = "annotation-session"
TABLE_ID = "annotation-table"
SCENE = SquareGridScene(
    schema_version=SCENE_SCHEMA_VERSION,
    scene_id="active-scene",
    name="Annotation Test Scene",
    cell_size_ft=5.0,
    columns=20,
    rows=20,
)
TOKENS = {
    "gm": "gm-annotation-token-1234",
    "player-1": "p1-annotation-token-1234",
    "player-2": "p2-annotation-token-1234",
    "spectator": "spec-annotation-token-1234",
}


def test_annotation_http_contracts_are_public_vtt_exports() -> None:
    import dnd_sim.vtt as vtt

    expected = {
        "OPEN_LOCAL_ANNOTATION_AUTHOR_ID",
        "VTT_ANNOTATIONS_VIEW_SCHEMA_VERSION",
        "VTT_ANNOTATION_REQUEST_SCHEMA_VERSION",
        "VTT_ANNOTATION_RESPONSE_SCHEMA_VERSION",
        "VTTAnnotationRequest",
        "VTTAnnotationResponse",
        "VTTAnnotationsView",
    }

    assert expected <= set(vtt.__all__)
    assert all(getattr(vtt, name) is not None for name in expected)


class _ProjectionDriver:
    version_pins = EngineVersionPins(
        engine_version="annotation-http@1",
        rules_version="annotation-rules@1",
        content_version="annotation-content@1",
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
        raise AssertionError("annotation HTTP tests do not open reactions")


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
    return TableAccessPolicy(
        roster=TableRoster(
            schema_version=ROSTER_SCHEMA_VERSION,
            table_id=TABLE_ID,
            participants=(
                _participant("gm", role="gm"),
                _participant("player-1", role="player", owned_actor_ids=("hero",)),
                _participant("player-2", role="player", owned_actor_ids=("rogue",)),
                _participant("spectator", role="spectator"),
            ),
        ),
        bearer_tokens=TOKENS,
    )


def _authorization(participant_id: str) -> dict[str, str]:
    return {"authorization": f"Bearer {TOKENS[participant_id]}"}


def _annotation(
    annotation_id: str,
    *,
    author_id: str = "gm",
    audience: tuple[str, ...] = ("all",),
    scene_id: str = SCENE.scene_id,
    x_ft: float = 5.0,
) -> PingAnnotation:
    return PingAnnotation(
        schema_version=ANNOTATION_SCHEMA_VERSION,
        annotation_id=annotation_id,
        scene_id=scene_id,
        author_id=author_id,
        audience=audience,
        position={"x_ft": x_ft, "y_ft": 5.0, "z_ft": 0.0},
    )


def _request(command: dict[str, Any], *, session_id: str = SESSION_ID) -> dict[str, Any]:
    return {
        "schema_version": VTT_ANNOTATION_REQUEST_SCHEMA_VERSION,
        "session_id": session_id,
        "command": command,
    }


def _put_request(
    command_id: str,
    *,
    expected_revision: int,
    annotation_id: str,
    author_id: str = "untrusted-client-author",
    audience: tuple[str, ...] = ("all",),
    scene_id: str = SCENE.scene_id,
    table_id: str = TABLE_ID,
    x_ft: float = 5.0,
) -> dict[str, Any]:
    return _request(
        {
            "schema_version": ANNOTATION_COMMAND_SCHEMA_VERSION,
            "table_id": table_id,
            "command_id": command_id,
            "expected_revision": expected_revision,
            "command_type": "put",
            "annotation": _annotation(
                annotation_id,
                author_id=author_id,
                audience=audience,
                scene_id=scene_id,
                x_ft=x_ft,
            ).model_dump(mode="json"),
        }
    )


def _delete_request(
    command_id: str,
    *,
    expected_revision: int,
    annotation_id: str,
    table_id: str = TABLE_ID,
) -> dict[str, Any]:
    return _request(
        {
            "schema_version": ANNOTATION_COMMAND_SCHEMA_VERSION,
            "table_id": table_id,
            "command_id": command_id,
            "expected_revision": expected_revision,
            "command_type": "delete",
            "annotation_id": annotation_id,
        }
    )


@pytest.fixture
def annotation_api_client(tmp_path: Path):
    connection = sqlite3.connect(
        tmp_path / "annotation-http.sqlite3",
        check_same_thread=False,
    )
    service = VTTSessionService.open(
        session_id=SESSION_ID,
        initial_state={"value": 0},
        driver=_ProjectionDriver(),
        seed=41,
        event_store=SQLiteSessionEventStore(connection),
    )
    board = SQLiteAnnotationBoard(connection)
    app = create_vtt_app(
        service,
        scene=SCENE,
        access_policy=_policy(),
        annotation_board=board,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, board, service
    connection.close()


def _assert_error(response, *, status_code: int, code: str) -> dict[str, Any]:
    assert response.status_code == status_code
    payload = response.json()
    assert payload["schema_version"] == VTT_ERROR_SCHEMA_VERSION
    assert payload["code"] == code
    assert isinstance(payload["message"], str) and payload["message"]
    assert isinstance(payload["details"], dict)
    assert "traceback" not in response.text.lower()
    return payload


def test_annotation_routes_are_optional_require_a_scene_and_preserve_open_local_mode(
    annotation_api_client,
) -> None:
    _client, board, service = annotation_api_client

    with TestClient(create_vtt_app(service), raise_server_exceptions=False) as open_client:
        assert open_client.get("/api/v1/annotations").status_code == 404
        assert open_client.post("/api/v1/annotation-commands", json={}).status_code == 404

    with pytest.raises(ValueError, match="scene"):
        create_vtt_app(service, annotation_board=board)

    with TestClient(
        create_vtt_app(
            service,
            scene=SCENE,
            annotation_board=board,
            annotation_table_id=TABLE_ID,
        ),
        raise_server_exceptions=False,
    ) as open_annotation_client:
        created = open_annotation_client.post(
            "/api/v1/annotation-commands",
            json=_put_request(
                "open-create",
                expected_revision=0,
                annotation_id="open-private",
                author_id="local-author",
                audience=("participant:any-local-id",),
            ),
        )
        current = open_annotation_client.get("/api/v1/annotations")

    assert created.status_code == 200
    assert created.json()["receipt"]["event"]["annotation"]["author_id"] == "local"
    assert [item["annotation_id"] for item in current.json()["annotations"]] == ["open-private"]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/v1/annotations", None),
        ("get", "/api/v1/annotation-events", None),
        ("post", "/api/v1/annotation-commands", "{not-json"),
    ],
)
def test_annotation_routes_authenticate_before_reading_mutation_bodies(
    annotation_api_client,
    method: str,
    path: str,
    body: str | None,
) -> None:
    client, _board, _service = annotation_api_client

    response = client.request(
        method.upper(),
        path,
        content=body,
        headers={"content-type": "application/json"} if body is not None else None,
    )

    payload = _assert_error(response, status_code=401, code="authentication_required")
    assert payload["details"] == {}
    assert response.headers["www-authenticate"] == "Bearer"


def test_current_annotations_are_exact_scene_bound_and_audience_filtered(
    annotation_api_client,
) -> None:
    client, board, _service = annotation_api_client
    annotations = (
        _annotation("public", audience=("all",)),
        _annotation("player-one", audience=("participant:player-1",)),
        _annotation("player-two", audience=("participant:player-2",)),
        _annotation("players", audience=("role:player",)),
        _annotation("spectators", audience=("role:spectator",)),
        _annotation("other-scene", audience=("all",), scene_id="other-scene"),
    )
    for revision, annotation in enumerate(annotations):
        board.execute(
            AnnotationPutCommand(
                table_id=TABLE_ID,
                command_id=f"seed-{annotation.annotation_id}",
                expected_revision=revision,
                annotation=annotation,
            )
        )

    expected = {
        "gm": ["player-one", "player-two", "players", "public", "spectators"],
        "player-1": ["player-one", "players", "public"],
        "player-2": ["player-two", "players", "public"],
        "spectator": ["public", "spectators"],
    }
    for participant_id, annotation_ids in expected.items():
        response = client.get(
            "/api/v1/annotations",
            headers=_authorization(participant_id),
        )
        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {
            "schema_version",
            "session_id",
            "table_id",
            "scene_id",
            "revision",
            "annotations",
        }
        assert payload["schema_version"] == VTT_ANNOTATIONS_VIEW_SCHEMA_VERSION
        assert payload["session_id"] == SESSION_ID
        assert payload["table_id"] == TABLE_ID
        assert payload["scene_id"] == SCENE.scene_id
        assert payload["revision"] == len(annotations)
        assert [item["annotation_id"] for item in payload["annotations"]] == annotation_ids


def test_player_put_is_server_authored_and_strictly_bound_to_table_session_scene_and_audience(
    annotation_api_client,
) -> None:
    client, board, _service = annotation_api_client
    created = client.post(
        "/api/v1/annotation-commands",
        json=_put_request(
            "player-create",
            expected_revision=0,
            annotation_id="player-mark",
            author_id="gm",
            audience=("participant:player-1",),
        ),
        headers=_authorization("player-1"),
    )

    assert created.status_code == 200
    payload = created.json()
    assert payload["schema_version"] == VTT_ANNOTATION_RESPONSE_SCHEMA_VERSION
    assert payload["session_id"] == SESSION_ID
    assert payload["replayed"] is False
    assert payload["receipt"]["revision"] == 1
    assert payload["receipt"]["event"]["annotation"]["author_id"] == "player-1"
    assert board.annotations(TABLE_ID)[0].author_id == "player-1"

    wrong_session = _put_request(
        "wrong-session",
        expected_revision=1,
        annotation_id="wrong-session",
    )
    wrong_session["session_id"] = "somewhere-else"
    cases = (
        (wrong_session, 409, "annotation_binding_mismatch"),
        (
            _put_request(
                "wrong-table",
                expected_revision=1,
                annotation_id="wrong-table",
                table_id="somewhere-else",
            ),
            409,
            "annotation_binding_mismatch",
        ),
        (
            _put_request(
                "wrong-scene",
                expected_revision=1,
                annotation_id="wrong-scene",
                scene_id="somewhere-else",
            ),
            409,
            "annotation_scene_mismatch",
        ),
        (
            _put_request(
                "unknown-audience",
                expected_revision=1,
                annotation_id="unknown-audience",
                audience=("participant:missing",),
            ),
            422,
            "invalid_annotation_audience",
        ),
    )
    for request_payload, status_code, code in cases:
        response = client.post(
            "/api/v1/annotation-commands",
            json=request_payload,
            headers=_authorization("player-1"),
        )
        _assert_error(response, status_code=status_code, code=code)

    extra = _put_request(
        "extra",
        expected_revision=1,
        annotation_id="extra",
    )
    extra["unexpected"] = True
    _assert_error(
        client.post(
            "/api/v1/annotation-commands",
            json=extra,
            headers=_authorization("player-1"),
        ),
        status_code=422,
        code="invalid_request",
    )
    duplicate_audience = _put_request(
        "duplicate-audience",
        expected_revision=1,
        annotation_id="duplicate-audience",
    )
    duplicate_audience["command"]["annotation"]["audience"] = ["all", "all"]
    _assert_error(
        client.post(
            "/api/v1/annotation-commands",
            json=duplicate_audience,
            headers=_authorization("player-1"),
        ),
        status_code=422,
        code="invalid_request",
    )
    assert board.revision(TABLE_ID) == 1


def test_browser_integral_annotation_numbers_are_canonicalized_at_the_http_boundary(
    annotation_api_client,
) -> None:
    client, board, _service = annotation_api_client
    request_payload = _put_request(
        "browser-numbers",
        expected_revision=0,
        annotation_id="browser-ping",
    )
    annotation = request_payload["command"]["annotation"]
    annotation["position"] = {"x_ft": 5, "y_ft": 10, "z_ft": 0}

    response = client.post(
        "/api/v1/annotation-commands",
        json=request_payload,
        headers=_authorization("player-1"),
    )

    assert response.status_code == 200
    stored = board.annotations(TABLE_ID)[0]
    assert type(stored.position.x_ft) is float
    assert type(stored.position.y_ft) is float
    assert type(stored.position.z_ft) is float


@pytest.mark.parametrize(
    ("annotation_type", "geometry", "float_paths"),
    [
        (
            "circle_template",
            {"center": {"x_ft": 10, "y_ft": 15, "z_ft": 0}, "radius_ft": 10},
            (("center", "x_ft"), ("center", "y_ft"), ("radius_ft",)),
        ),
        (
            "cone_template",
            {
                "origin": {"x_ft": 10, "y_ft": 15, "z_ft": 0},
                "direction_degrees": 45,
                "length_ft": 15,
                "angle_degrees": 90,
            },
            (
                ("origin", "x_ft"),
                ("direction_degrees",),
                ("length_ft",),
                ("angle_degrees",),
            ),
        ),
        (
            "line_template",
            {
                "start": {"x_ft": 5, "y_ft": 5, "z_ft": 0},
                "end": {"x_ft": 20, "y_ft": 15, "z_ft": 0},
                "width_ft": 5,
            },
            (("start", "x_ft"), ("end", "y_ft"), ("width_ft",)),
        ),
        (
            "cube_template",
            {"center": {"x_ft": 10, "y_ft": 15, "z_ft": 0}, "size_ft": 10},
            (("center", "x_ft"), ("center", "y_ft"), ("size_ft",)),
        ),
    ],
)
def test_browser_integral_template_geometry_is_normalized_without_schema_drift(
    annotation_api_client,
    annotation_type: str,
    geometry: dict[str, Any],
    float_paths: tuple[tuple[str, ...], ...],
) -> None:
    client, _board, _service = annotation_api_client
    request_payload = _put_request(
        f"browser-{annotation_type}",
        expected_revision=0,
        annotation_id=f"browser-{annotation_type}",
    )
    annotation = request_payload["command"]["annotation"]
    annotation.pop("position")
    annotation.pop("duration_ms")
    annotation["annotation_type"] = annotation_type
    annotation.update(geometry)

    response = client.post(
        "/api/v1/annotation-commands",
        json=request_payload,
        headers=_authorization("player-1"),
    )

    assert response.status_code == 200
    stored = response.json()["receipt"]["event"]["annotation"]
    assert set(stored) == {
        "schema_version",
        "annotation_id",
        "scene_id",
        "author_id",
        "audience",
        "annotation_type",
        *geometry,
    }
    for path in float_paths:
        value: Any = stored
        for part in path:
            value = value[part]
        assert type(value) is float


def test_annotation_mutations_enforce_ownership_roles_and_preserve_author(
    annotation_api_client,
) -> None:
    client, board, _service = annotation_api_client
    gm_created = client.post(
        "/api/v1/annotation-commands",
        json=_put_request("gm-create", expected_revision=0, annotation_id="gm-mark"),
        headers=_authorization("gm"),
    )
    player_created = client.post(
        "/api/v1/annotation-commands",
        json=_put_request("p1-create", expected_revision=1, annotation_id="p1-mark"),
        headers=_authorization("player-1"),
    )
    assert gm_created.status_code == player_created.status_code == 200

    forbidden_requests = (
        (
            "player-1",
            _put_request(
                "overwrite-gm",
                expected_revision=2,
                annotation_id="gm-mark",
                x_ft=10.0,
            ),
        ),
        (
            "player-2",
            _delete_request(
                "delete-p1",
                expected_revision=2,
                annotation_id="p1-mark",
            ),
        ),
        (
            "spectator",
            _put_request(
                "spectator-put",
                expected_revision=2,
                annotation_id="spectator-mark",
            ),
        ),
    )
    for participant_id, request_payload in forbidden_requests:
        response = client.post(
            "/api/v1/annotation-commands",
            json=request_payload,
            headers=_authorization(participant_id),
        )
        _assert_error(response, status_code=403, code="annotation_forbidden")

    player_update = client.post(
        "/api/v1/annotation-commands",
        json=_put_request(
            "p1-update",
            expected_revision=2,
            annotation_id="p1-mark",
            author_id="player-2",
            x_ft=15.0,
        ),
        headers=_authorization("player-1"),
    )
    gm_update = client.post(
        "/api/v1/annotation-commands",
        json=_put_request(
            "gm-update-p1",
            expected_revision=3,
            annotation_id="p1-mark",
            author_id="gm",
            x_ft=20.0,
        ),
        headers=_authorization("gm"),
    )
    assert player_update.status_code == gm_update.status_code == 200
    stored = {item.annotation_id: item for item in board.annotations(TABLE_ID)}
    assert stored["p1-mark"].author_id == "player-1"
    assert stored["p1-mark"].position.x_ft == 20.0


def test_board_revision_idempotency_conflict_missing_and_delete_retry_are_preserved(
    annotation_api_client,
) -> None:
    client, board, _service = annotation_api_client
    create_request = _put_request(
        "create-once",
        expected_revision=0,
        annotation_id="owned",
    )
    first = client.post(
        "/api/v1/annotation-commands",
        json=create_request,
        headers=_authorization("player-1"),
    )
    replay = client.post(
        "/api/v1/annotation-commands",
        json=create_request,
        headers=_authorization("player-1"),
    )
    assert first.status_code == replay.status_code == 200
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert replay.json()["receipt"] == first.json()["receipt"]

    stale = client.post(
        "/api/v1/annotation-commands",
        json=_put_request("stale", expected_revision=0, annotation_id="stale"),
        headers=_authorization("player-1"),
    )
    stale_payload = _assert_error(
        stale,
        status_code=409,
        code="annotation_stale_revision",
    )
    assert stale_payload["details"] == {"current_revision": 1}

    conflict_request = _put_request(
        "create-once",
        expected_revision=0,
        annotation_id="different",
    )
    _assert_error(
        client.post(
            "/api/v1/annotation-commands",
            json=conflict_request,
            headers=_authorization("player-1"),
        ),
        status_code=409,
        code="annotation_command_id_conflict",
    )
    _assert_error(
        client.post(
            "/api/v1/annotation-commands",
            json=_delete_request(
                "missing",
                expected_revision=1,
                annotation_id="missing",
            ),
            headers=_authorization("gm"),
        ),
        status_code=404,
        code="annotation_not_found",
    )

    delete_request = _delete_request(
        "delete-once",
        expected_revision=1,
        annotation_id="owned",
    )
    deleted = client.post(
        "/api/v1/annotation-commands",
        json=delete_request,
        headers=_authorization("player-1"),
    )
    delete_replay = client.post(
        "/api/v1/annotation-commands",
        json=delete_request,
        headers=_authorization("player-1"),
    )
    assert deleted.status_code == delete_replay.status_code == 200
    assert delete_replay.json()["replayed"] is True
    assert board.revision(TABLE_ID) == 2


def test_historical_player_retries_survive_later_state_without_transferring_authority(
    annotation_api_client,
) -> None:
    client, board, _service = annotation_api_client
    original_put = _put_request(
        "historical-put",
        expected_revision=0,
        annotation_id="historical-mark",
        x_ft=5.0,
    )
    assert (
        client.post(
            "/api/v1/annotation-commands",
            json=original_put,
            headers=_authorization("player-1"),
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/annotation-commands",
            json=_put_request(
                "later-update",
                expected_revision=1,
                annotation_id="historical-mark",
                x_ft=15.0,
            ),
            headers=_authorization("player-1"),
        ).status_code
        == 200
    )

    _assert_error(
        client.post(
            "/api/v1/annotation-commands",
            json=original_put,
            headers=_authorization("player-2"),
        ),
        status_code=403,
        code="annotation_forbidden",
    )
    put_replay = client.post(
        "/api/v1/annotation-commands",
        json=original_put,
        headers=_authorization("player-1"),
    )
    assert put_replay.status_code == 200
    assert put_replay.json()["replayed"] is True
    assert board.revision(TABLE_ID) == 2
    assert board.annotations(TABLE_ID)[0].position.x_ft == 15.0

    original_delete = _delete_request(
        "historical-delete",
        expected_revision=2,
        annotation_id="historical-mark",
    )
    assert (
        client.post(
            "/api/v1/annotation-commands",
            json=original_delete,
            headers=_authorization("player-1"),
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/annotation-commands",
            json=_put_request(
                "gm-recreate",
                expected_revision=3,
                annotation_id="historical-mark",
                x_ft=25.0,
            ),
            headers=_authorization("gm"),
        ).status_code
        == 200
    )

    _assert_error(
        client.post(
            "/api/v1/annotation-commands",
            json=original_delete,
            headers=_authorization("player-2"),
        ),
        status_code=403,
        code="annotation_forbidden",
    )
    delete_replay = client.post(
        "/api/v1/annotation-commands",
        json=original_delete,
        headers=_authorization("player-1"),
    )
    assert delete_replay.status_code == 200
    assert delete_replay.json()["replayed"] is True
    assert board.revision(TABLE_ID) == 4
    replacement = board.annotations(TABLE_ID)[0]
    assert replacement.author_id == "gm"
    assert replacement.position.x_ft == 25.0


def test_annotation_store_failures_map_to_stable_vtt_envelopes(
    annotation_api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, board, _service = annotation_api_client

    def corrupt_events(_table_id: str, _sequence: int):
        raise AnnotationStoreCorruptionError("do not expose this detail")

    monkeypatch.setattr(board, "events_after", corrupt_events)
    corrupt = client.get(
        "/api/v1/annotations",
        headers=_authorization("gm"),
    )
    payload = _assert_error(
        corrupt,
        status_code=500,
        code="annotation_store_corrupt",
    )
    assert "do not expose" not in payload["message"]

    def unavailable_events(_table_id: str, _sequence: int):
        raise sqlite3.OperationalError("database path is secret")

    monkeypatch.setattr(board, "events_after", unavailable_events)
    unavailable = client.get(
        "/api/v1/annotations",
        headers=_authorization("gm"),
    )
    payload = _assert_error(
        unavailable,
        status_code=503,
        code="annotation_storage_unavailable",
    )
    assert "database path" not in payload["message"]


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
            assert fields["event"] == "vtt.annotation_event"
            parsed.append((int(fields["id"]), json.loads(fields["data"])))
    return parsed


def test_annotation_sse_is_exclusive_reconnectable_and_advances_hidden_events(
    annotation_api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, board, _service = annotation_api_client
    for revision, annotation in enumerate(
        (
            _annotation("public", audience=("all",)),
            _annotation("other", audience=("participant:player-2",)),
            _annotation("private", audience=("participant:player-1",)),
        )
    ):
        board.execute(
            AnnotationPutCommand(
                table_id=TABLE_ID,
                command_id=f"sse-{annotation.annotation_id}",
                expected_revision=revision,
                annotation=annotation,
            )
        )

    seen_cursors: list[int] = []
    original_events_after = board.events_after

    def recording_events_after(table_id: str, sequence: int):
        seen_cursors.append(sequence)
        return original_events_after(table_id, sequence)

    monkeypatch.setattr(board, "events_after", recording_events_after)
    monkeypatch.setattr(annotation_api, "SSE_POLL_INTERVAL_SECONDS", 0.001)
    monkeypatch.setattr(annotation_api, "SSE_HEARTBEAT_INTERVAL_SECONDS", 0.01)

    status, headers, payload = asyncio.run(
        _capture_sse(
            client.app,
            "/api/v1/annotation-events?after=0",
            headers=_authorization("player-1"),
            data_event_count=2,
        )
    )
    assert status == 200
    assert headers["content-type"].startswith("text/event-stream")
    assert [event_id for event_id, _event in _sse_events(payload)] == [1, 3]

    status, _headers, payload = asyncio.run(
        _capture_sse(
            client.app,
            "/api/v1/annotation-events?after=1",
            headers={**_authorization("player-1"), "last-event-id": "3"},
            stop_on_heartbeat=True,
        )
    )
    assert status == 200
    assert _sse_events(payload) == []
    assert ": heartbeat\n\n" in payload
    assert 3 in seen_cursors

    invalid = client.get(
        "/api/v1/annotation-events?after=01",
        headers=_authorization("player-1"),
    )
    _assert_error(
        invalid,
        status_code=400,
        code="invalid_annotation_event_cursor",
    )
