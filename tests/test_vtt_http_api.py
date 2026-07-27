from __future__ import annotations

import random
import sqlite3
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dnd_sim.interactive import (
    EngineSessionError,
    EngineTransition,
    EngineVersionPins,
    EventDraft,
    PendingReaction,
    PreviewOutcome,
    SessionCommand,
)
from dnd_sim.vtt import (
    CommandConflictError,
    SCENE_SCHEMA_VERSION,
    VTT_COMMAND_SCHEMA_VERSION,
    VTT_COMMIT_RESPONSE_SCHEMA_VERSION,
    VTT_ERROR_SCHEMA_VERSION,
    VTT_PREVIEW_RESPONSE_SCHEMA_VERSION,
    VTT_SESSION_VIEW_SCHEMA_VERSION,
    SQLiteSessionEventStore,
    SquareGridScene,
    VTTSessionService,
    VTTCommand,
    create_vtt_app,
)

SCENE = SquareGridScene(
    schema_version=SCENE_SCHEMA_VERSION,
    scene_id="scene-http",
    name="HTTP Test Arena",
    cell_size_ft=5.0,
    columns=20,
    rows=20,
)


class ProjectingCounterDriver:
    version_pins = EngineVersionPins(
        engine_version="http-counter@1",
        rules_version="http-counter-rules@1",
        content_version="http-counter-content@1",
    )

    def encode_state(self, state: Any) -> Mapping[str, Any]:
        return {
            "value": state["value"],
            "canonical_secret": state["canonical_secret"],
            "internal_cursor": state["internal_cursor"],
        }

    def decode_state(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "value": int(payload["value"]),
            "canonical_secret": str(payload["canonical_secret"]),
            "internal_cursor": int(payload["internal_cursor"]),
        }

    def project_state(self, state: dict[str, Any]) -> Mapping[str, Any]:
        return {"counter": {"value": state["value"]}}

    def preview(
        self,
        state: dict[str, Any],
        command: SessionCommand,
        rng: random.Random,
    ) -> PreviewOutcome:
        next_value = state["value"] + int(command.payload["amount"])
        return PreviewOutcome(
            projection={"counter": {"value": next_value}},
            events=(EventDraft(kind="counter.previewed", payload={}),),
        )

    def commit(
        self,
        state: dict[str, Any],
        command: SessionCommand,
        rng: random.Random,
    ) -> EngineTransition:
        next_state = {
            **state,
            "value": state["value"] + int(command.payload["amount"]),
            "internal_cursor": state["internal_cursor"] + 1,
        }
        return EngineTransition(
            state=next_state,
            events=(
                EventDraft(
                    kind="counter.changed",
                    payload={"value": next_state["value"]},
                ),
            ),
        )

    def respond_to_reaction(
        self,
        state: dict[str, Any],
        command: SessionCommand,
        pending_reaction: PendingReaction,
        rng: random.Random,
    ) -> EngineTransition:
        raise AssertionError("HTTP counter tests do not open reactions")


def _command_payload(
    *,
    command_id: str,
    expected_revision: int | str,
    mode: str = "commit",
    session_id: str = "table-http",
    amount: int = 1,
) -> dict[str, Any]:
    return {
        "schema_version": VTT_COMMAND_SCHEMA_VERSION,
        "command_id": command_id,
        "session_id": session_id,
        "actor_id": "hero",
        "expected_revision": expected_revision,
        "mode": mode,
        "kind": "counter.increment.v1",
        "payload": {"amount": amount},
        "intent_metadata": {},
    }


@pytest.fixture
def api_client(tmp_path: Path):
    connection = sqlite3.connect(
        tmp_path / "http-session.sqlite3",
        check_same_thread=False,
    )
    service = VTTSessionService.open(
        session_id="table-http",
        initial_state={
            "value": 0,
            "canonical_secret": "must-never-cross-http",
            "internal_cursor": 0,
        },
        driver=ProjectingCounterDriver(),
        seed=11,
        event_store=SQLiteSessionEventStore(connection),
    )
    with TestClient(
        create_vtt_app(service, scene=SCENE),
        raise_server_exceptions=False,
    ) as client:
        yield client, service
    connection.close()


def _assert_vtt_error(response, *, status_code: int, code: str) -> dict[str, Any]:
    assert response.status_code == status_code
    payload = response.json()
    assert payload["schema_version"] == VTT_ERROR_SCHEMA_VERSION
    assert payload["code"] == code
    assert isinstance(payload["message"], str) and payload["message"]
    assert isinstance(payload["details"], dict)
    assert "traceback" not in response.text.lower()
    return payload


def test_health_and_session_view_use_only_the_public_projection(api_client) -> None:
    client, service = api_client

    health = client.get("/healthz")
    response = client.get("/api/v1/session")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "schema_version",
        "session_id",
        "revision",
        "versions",
        "scene",
        "projection",
    }
    assert payload["schema_version"] == VTT_SESSION_VIEW_SCHEMA_VERSION
    assert payload["session_id"] == "table-http"
    assert payload["revision"] == 0
    assert payload["scene"] == SCENE.model_dump(mode="json")
    assert payload["projection"] == {"counter": {"value": 0}}
    assert payload["versions"]["schema_version"].startswith("vtt.")
    assert service.state["canonical_secret"] == "must-never-cross-http"
    assert "canonical_secret" not in response.text
    assert "internal_cursor" not in response.text
    assert "pixels_per_cell" not in response.text


def test_session_view_uses_null_when_no_scene_is_configured(api_client) -> None:
    _client, service = api_client

    with TestClient(create_vtt_app(service), raise_server_exceptions=False) as client:
        response = client.get("/api/v1/session")

    assert response.status_code == 200
    assert response.json()["scene"] is None


def test_cors_allows_only_configured_exact_origins(api_client) -> None:
    client, service = api_client

    allowed = client.get(
        "/api/v1/session",
        headers={"origin": "http://127.0.0.1:3000"},
    )
    denied = client.get(
        "/api/v1/session",
        headers={"origin": "http://attacker.example"},
    )
    preflight = client.options(
        "/api/v1/commands",
        headers={
            "origin": "http://localhost:3000",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type",
        },
    )

    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
    assert allowed.headers["access-control-allow-origin"] != "*"
    assert "access-control-allow-credentials" not in allowed.headers
    assert "access-control-allow-origin" not in denied.headers
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert set(preflight.headers["access-control-allow-methods"].split(", ")) == {
        "GET",
        "POST",
    }
    assert "content-type" in preflight.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in preflight.headers
    with pytest.raises(ValueError, match="wildcard"):
        create_vtt_app(service, allowed_origins=("*",))


def test_preview_and_commit_return_vtt_schemas_and_advance_the_session(api_client) -> None:
    client, _service = api_client

    preview = client.post(
        "/api/v1/commands",
        json=_command_payload(
            command_id="preview-1",
            expected_revision=0,
            mode="preview",
            amount=3,
        ),
    )

    assert preview.status_code == 200
    assert preview.json()["schema_version"] == VTT_PREVIEW_RESPONSE_SCHEMA_VERSION
    assert preview.json()["projection"] == {"counter": {"value": 3}}
    after_preview = client.get("/api/v1/session").json()
    assert after_preview["revision"] == 0
    assert after_preview["projection"] == {"counter": {"value": 0}}

    commit = client.post(
        "/api/v1/commands",
        json=_command_payload(
            command_id="commit-1",
            expected_revision=0,
            amount=3,
        ),
    )

    assert commit.status_code == 200
    assert commit.json()["schema_version"] == VTT_COMMIT_RESPONSE_SCHEMA_VERSION
    assert commit.json()["revision"] == 1
    assert commit.json()["events"][0]["kind"] == "counter.changed"
    after_commit = client.get("/api/v1/session").json()
    assert after_commit["revision"] == 1
    assert after_commit["projection"] == {"counter": {"value": 3}}


@pytest.mark.parametrize(
    "payload",
    [
        {**_command_payload(command_id="extra-1", expected_revision=0), "unexpected": True},
        _command_payload(command_id="coercive-1", expected_revision="0"),
        {
            **_command_payload(command_id="schema-1", expected_revision=0),
            "schema_version": "vtt.command.v2",
        },
    ],
)
def test_invalid_command_payloads_return_strict_vtt_errors(api_client, payload) -> None:
    client, _service = api_client

    response = client.post("/api/v1/commands", json=payload)

    error = _assert_vtt_error(response, status_code=422, code="invalid_request")
    assert error["details"]["issues"]


def test_malformed_json_returns_a_strict_vtt_error(api_client) -> None:
    client, _service = api_client

    response = client.post(
        "/api/v1/commands",
        content="{not-json",
        headers={"content-type": "application/json"},
    )

    _assert_vtt_error(response, status_code=422, code="invalid_request")


def test_stale_revision_and_wrong_session_are_stable_conflict_errors(api_client) -> None:
    client, _service = api_client
    committed = client.post(
        "/api/v1/commands",
        json=_command_payload(command_id="commit-1", expected_revision=0),
    )
    assert committed.status_code == 200

    stale = client.post(
        "/api/v1/commands",
        json=_command_payload(command_id="stale-1", expected_revision=0),
    )
    stale_error = _assert_vtt_error(stale, status_code=409, code="stale_revision")
    assert stale_error["details"] == {
        "expected_revision": 1,
        "received_revision": 0,
    }

    wrong_session = client.post(
        "/api/v1/commands",
        json=_command_payload(
            command_id="wrong-session-1",
            expected_revision=1,
            session_id="another-table",
        ),
    )
    mismatch = _assert_vtt_error(
        wrong_session,
        status_code=409,
        code="session_mismatch",
    )
    assert mismatch["details"] == {"expected_session_id": "table-http"}


def test_reusing_a_command_id_with_different_content_is_a_conflict(api_client) -> None:
    client, _service = api_client
    original = client.post(
        "/api/v1/commands",
        json=_command_payload(command_id="same-id", expected_revision=0, amount=1),
    )
    assert original.status_code == 200

    conflict = client.post(
        "/api/v1/commands",
        json=_command_payload(command_id="same-id", expected_revision=0, amount=2),
    )

    _assert_vtt_error(conflict, status_code=409, code="command_id_conflict")


def test_store_command_conflicts_use_the_same_public_error_code(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, service = api_client

    def raise_conflict(_command: VTTCommand) -> None:
        raise CommandConflictError("private persistence detail")

    monkeypatch.setattr(service, "execute", raise_conflict)

    response = client.post(
        "/api/v1/commands",
        json=_command_payload(command_id="conflict-1", expected_revision=0),
    )

    error = _assert_vtt_error(
        response,
        status_code=409,
        code="command_id_conflict",
    )
    assert "private persistence detail" not in error["message"]


@pytest.mark.parametrize(
    "code",
    [
        "encounter_complete",
        "encounter_already_started",
        "turn_not_prepared",
        "actor_mismatch",
    ],
)
def test_engine_turn_state_conflicts_return_409(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
) -> None:
    client, service = api_client

    def raise_conflict(_command: VTTCommand) -> None:
        raise EngineSessionError(code, "The command conflicts with the active turn state.")

    monkeypatch.setattr(service, "execute", raise_conflict)

    response = client.post(
        "/api/v1/commands",
        json=_command_payload(command_id=f"{code}-1", expected_revision=0),
    )

    _assert_vtt_error(response, status_code=409, code=code)


def test_atomic_service_read_cannot_interleave_with_a_commit(tmp_path: Path) -> None:
    connection = sqlite3.connect(
        tmp_path / "atomic-read.sqlite3",
        check_same_thread=False,
    )
    driver = ProjectingCounterDriver()
    service = VTTSessionService.open(
        session_id="table-http",
        initial_state={
            "value": 0,
            "canonical_secret": "hidden",
            "internal_cursor": 0,
        },
        driver=driver,
        seed=19,
        event_store=SQLiteSessionEventStore(connection),
    )
    projection_started = threading.Event()
    release_projection = threading.Event()
    commit_started = threading.Event()
    commit_finished = threading.Event()
    original_project_state = driver.project_state
    read_results = []
    commit_results = []

    def blocking_project_state(state: dict[str, Any]) -> Mapping[str, Any]:
        projection_started.set()
        assert release_projection.wait(timeout=1.0)
        return original_project_state(state)

    driver.project_state = blocking_project_state  # type: ignore[method-assign]

    def read_session() -> None:
        read_results.append(service.read_view())

    def commit_command() -> None:
        commit_started.set()
        commit_results.append(
            service.execute(
                VTTCommand.model_validate(
                    _command_payload(command_id="atomic-commit", expected_revision=0)
                )
            )
        )
        commit_finished.set()

    read_thread = threading.Thread(target=read_session)
    commit_thread = threading.Thread(target=commit_command)
    read_thread.start()
    assert projection_started.wait(timeout=1.0)
    commit_thread.start()
    assert commit_started.wait(timeout=1.0)
    assert not commit_finished.wait(timeout=0.05)

    release_projection.set()
    read_thread.join(timeout=1.0)
    commit_thread.join(timeout=1.0)

    assert not read_thread.is_alive()
    assert not commit_thread.is_alive()
    assert read_results[0].revision == 0
    assert read_results[0].projection == {"counter": {"value": 0}}
    assert commit_results[0].revision == 1
    assert service.read_view().projection == {"counter": {"value": 1}}
    connection.close()
