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
from dnd_sim.vtt import chat_api
from dnd_sim.vtt.access import TableAccessPolicy
from dnd_sim.vtt.chat_contracts import (
    CHAT_COMMAND_SCHEMA_VERSION,
    CHAT_MESSAGE_SCHEMA_VERSION,
    CHAT_REQUEST_SCHEMA_VERSION,
    CHAT_RESPONSE_SCHEMA_VERSION,
    CHAT_VIEW_SCHEMA_VERSION,
    ChatMessage,
    ChatPostCommand,
)
from dnd_sim.vtt.chat_store import ChatStoreCorruptionError, SQLiteChatLog
from dnd_sim.vtt.event_store import SQLiteSessionEventStore
from dnd_sim.vtt.http_api import VTT_ERROR_SCHEMA_VERSION, create_vtt_app
from dnd_sim.vtt.participants import (
    PARTICIPANT_SCHEMA_VERSION,
    ROSTER_SCHEMA_VERSION,
    TableParticipant,
    TableRoster,
)
from dnd_sim.vtt.session_service import VTTSessionService

SESSION_ID = "chat-session"
TABLE_ID = "chat-table"
TOKENS = {
    "gm": "gm-chat-token-1234",
    "player-1": "p1-chat-token-1234",
    "player-2": "p2-chat-token-1234",
    "spectator": "spectator-token-1234",
}


def test_chat_contracts_and_store_are_public_vtt_exports() -> None:
    import dnd_sim.vtt as vtt

    expected = {
        "CHAT_COMMAND_SCHEMA_VERSION",
        "CHAT_EVENT_SCHEMA_VERSION",
        "CHAT_MESSAGE_SCHEMA_VERSION",
        "CHAT_RECEIPT_SCHEMA_VERSION",
        "CHAT_REQUEST_SCHEMA_VERSION",
        "CHAT_RESPONSE_SCHEMA_VERSION",
        "CHAT_STORE_SCHEMA_VERSION",
        "CHAT_VIEW_SCHEMA_VERSION",
        "OPEN_LOCAL_CHAT_AUTHOR_ID",
        "ChatDeleteCommand",
        "ChatMessage",
        "ChatPostCommand",
        "ChatRequest",
        "ChatResponse",
        "ChatView",
        "SQLiteChatLog",
    }

    assert expected <= set(vtt.__all__)
    assert all(getattr(vtt, name) is not None for name in expected)


class _ProjectionDriver:
    version_pins = EngineVersionPins(
        engine_version="chat-http@1",
        rules_version="chat-rules@1",
        content_version="chat-content@1",
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
        raise AssertionError("chat HTTP tests do not open reactions")


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


def _message(
    message_id: str,
    *,
    author_id: str = "untrusted-client-author",
    audience: tuple[str, ...] = ("all",),
    text: str = "hello",
) -> dict[str, Any]:
    return {
        "schema_version": CHAT_MESSAGE_SCHEMA_VERSION,
        "message_id": message_id,
        "author_id": author_id,
        "audience": list(audience),
        "text": text,
    }


def _post_request(
    command_id: str,
    *,
    expected_revision: int,
    message_id: str,
    session_id: str = SESSION_ID,
    table_id: str = TABLE_ID,
    author_id: str = "untrusted-client-author",
    audience: tuple[str, ...] = ("all",),
    text: str = "hello",
) -> dict[str, Any]:
    return {
        "schema_version": CHAT_REQUEST_SCHEMA_VERSION,
        "session_id": session_id,
        "command": {
            "schema_version": CHAT_COMMAND_SCHEMA_VERSION,
            "command_type": "post",
            "table_id": table_id,
            "command_id": command_id,
            "expected_revision": expected_revision,
            "message": _message(
                message_id,
                author_id=author_id,
                audience=audience,
                text=text,
            ),
        },
    }


def _delete_request(
    command_id: str,
    *,
    expected_revision: int,
    message_id: str,
    session_id: str = SESSION_ID,
    table_id: str = TABLE_ID,
) -> dict[str, Any]:
    return {
        "schema_version": CHAT_REQUEST_SCHEMA_VERSION,
        "session_id": session_id,
        "command": {
            "schema_version": CHAT_COMMAND_SCHEMA_VERSION,
            "command_type": "delete",
            "table_id": table_id,
            "command_id": command_id,
            "expected_revision": expected_revision,
            "message_id": message_id,
        },
    }


@pytest.fixture
def chat_api_client(tmp_path: Path):
    connection = sqlite3.connect(tmp_path / "chat-http.sqlite3", check_same_thread=False)
    service = VTTSessionService.open(
        session_id=SESSION_ID,
        initial_state={"value": 0},
        driver=_ProjectionDriver(),
        seed=91,
        event_store=SQLiteSessionEventStore(connection),
    )
    log = SQLiteChatLog(connection)
    app = create_vtt_app(service, access_policy=_policy(), chat_log=log)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, log, service
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


def test_chat_routes_are_optional_and_open_local_mode_is_server_authored(
    chat_api_client,
) -> None:
    _client, log, service = chat_api_client
    with TestClient(create_vtt_app(service), raise_server_exceptions=False) as no_chat:
        assert no_chat.get("/api/v1/chat").status_code == 404
        assert no_chat.post("/api/v1/chat-commands", json={}).status_code == 404

    with pytest.raises(ValueError, match="chat_log"):
        create_vtt_app(service, chat_table_id=TABLE_ID)
    with pytest.raises(ValueError, match="access-policy table"):
        create_vtt_app(
            service,
            access_policy=_policy(),
            chat_log=log,
            chat_table_id="other-table",
        )

    with TestClient(
        create_vtt_app(service, chat_log=log, chat_table_id=TABLE_ID),
        raise_server_exceptions=False,
    ) as open_chat:
        response = open_chat.post(
            "/api/v1/chat-commands",
            json=_post_request(
                "open-post",
                expected_revision=0,
                message_id="open-message",
                audience=("participant:any-local-id",),
                text="<b>literal</b> and **plain**",
            ),
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["schema_version"] == CHAT_RESPONSE_SCHEMA_VERSION
        assert payload["event"]["message"]["author_id"] == "local"
        assert payload["event"]["message"]["text"] == "<b>literal</b> and **plain**"

        view = open_chat.get("/api/v1/chat")
        assert view.status_code == 200
        assert view.json()["schema_version"] == CHAT_VIEW_SCHEMA_VERSION
        assert view.json()["messages"] == [payload["event"]["message"]]
        assert "timestamp" not in view.text.lower()
        assert "html" not in view.text.lower()


def test_protected_chat_authenticates_before_validation_and_spectators_are_read_only(
    chat_api_client,
) -> None:
    client, _log, _service = chat_api_client
    for method, path, body in (
        ("get", "/api/v1/chat", None),
        ("post", "/api/v1/chat-commands", {"malformed": True}),
        ("get", "/api/v1/chat-events", None),
    ):
        response = (
            getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
        )
        _assert_error(response, status_code=401, code="authentication_required")

    view = client.get("/api/v1/chat", headers=_authorization("spectator"))
    assert view.status_code == 200
    forbidden = client.post(
        "/api/v1/chat-commands",
        headers=_authorization("spectator"),
        json=_post_request("spectator-post", expected_revision=0, message_id="blocked"),
    )
    _assert_error(forbidden, status_code=403, code="chat_forbidden")


def test_chat_authority_audience_filtering_and_gm_moderation(chat_api_client) -> None:
    client, _log, _service = chat_api_client
    private_request = _post_request(
        "private-post",
        expected_revision=0,
        message_id="private-message",
        audience=("participant:player-2",),
        text="secret for player two",
    )
    posted = client.post(
        "/api/v1/chat-commands",
        headers=_authorization("player-1"),
        json=private_request,
    )
    assert posted.status_code == 200
    posted_payload = posted.json()
    assert posted_payload["event"]["message"]["author_id"] == "player-1"
    assert posted_payload["event"]["message"]["text"] == "secret for player two"

    player_one_view = client.get("/api/v1/chat", headers=_authorization("player-1"))
    player_two_view = client.get("/api/v1/chat", headers=_authorization("player-2"))
    spectator_view = client.get("/api/v1/chat", headers=_authorization("spectator"))
    assert [item["message_id"] for item in player_one_view.json()["messages"]] == [
        "private-message"
    ]
    assert [item["message_id"] for item in player_two_view.json()["messages"]] == [
        "private-message"
    ]
    assert spectator_view.json()["messages"] == []
    assert {player_one_view.json()["revision"], player_two_view.json()["revision"]} == {1}

    forbidden_delete = client.post(
        "/api/v1/chat-commands",
        headers=_authorization("player-2"),
        json=_delete_request(
            "player-two-delete",
            expected_revision=1,
            message_id="private-message",
        ),
    )
    _assert_error(forbidden_delete, status_code=403, code="chat_forbidden")

    invalid_audience = client.post(
        "/api/v1/chat-commands",
        headers=_authorization("player-1"),
        json=_post_request(
            "invalid-audience",
            expected_revision=1,
            message_id="invalid",
            audience=("participant:missing",),
        ),
    )
    _assert_error(invalid_audience, status_code=422, code="invalid_chat_audience")

    deleted = client.post(
        "/api/v1/chat-commands",
        headers=_authorization("gm"),
        json=_delete_request("gm-delete", expected_revision=1, message_id="private-message"),
    )
    assert deleted.status_code == 200
    assert deleted.json()["event"]["event_type"] == "deleted"
    assert client.get("/api/v1/chat", headers=_authorization("player-2")).json() == {
        "schema_version": CHAT_VIEW_SCHEMA_VERSION,
        "session_id": SESSION_ID,
        "table_id": TABLE_ID,
        "revision": 2,
        "messages": [],
    }


def test_chat_binding_idempotency_ownership_and_conflicts_are_stable(chat_api_client) -> None:
    client, _log, _service = chat_api_client
    request = _post_request(
        "post-once",
        expected_revision=0,
        message_id="immutable-id",
        author_id="spoofed",
    )
    first = client.post("/api/v1/chat-commands", headers=_authorization("player-1"), json=request)
    retry = client.post("/api/v1/chat-commands", headers=_authorization("player-1"), json=request)
    assert first.status_code == retry.status_code == 200
    assert first.json()["replayed"] is False
    assert retry.json()["replayed"] is True
    assert retry.json()["event"] == first.json()["event"]

    hijack = client.post("/api/v1/chat-commands", headers=_authorization("player-2"), json=request)
    _assert_error(hijack, status_code=403, code="chat_forbidden")

    delete_request = _delete_request("delete-once", expected_revision=1, message_id="immutable-id")
    deleted = client.post(
        "/api/v1/chat-commands",
        headers=_authorization("player-1"),
        json=delete_request,
    )
    delete_retry = client.post(
        "/api/v1/chat-commands",
        headers=_authorization("player-1"),
        json=delete_request,
    )
    assert deleted.status_code == delete_retry.status_code == 200
    assert delete_retry.json()["replayed"] is True
    late_post_retry = client.post(
        "/api/v1/chat-commands",
        headers=_authorization("player-1"),
        json=request,
    )
    assert late_post_retry.status_code == 200
    assert late_post_retry.json()["replayed"] is True
    assert late_post_retry.json()["revision"] == 1

    conflicting_command = client.post(
        "/api/v1/chat-commands",
        headers=_authorization("player-1"),
        json=_post_request(
            "post-once",
            expected_revision=0,
            message_id="different-id",
            text="different command content",
        ),
    )
    _assert_error(
        conflicting_command,
        status_code=409,
        code="chat_command_id_conflict",
    )

    reused = client.post(
        "/api/v1/chat-commands",
        headers=_authorization("player-1"),
        json=_post_request(
            "reuse-id", expected_revision=2, message_id="immutable-id", text="new text"
        ),
    )
    _assert_error(reused, status_code=409, code="chat_message_id_conflict")
    stale = client.post(
        "/api/v1/chat-commands",
        headers=_authorization("player-1"),
        json=_post_request("stale", expected_revision=1, message_id="later"),
    )
    payload = _assert_error(stale, status_code=409, code="chat_stale_revision")
    assert payload["details"] == {"current_revision": 2}
    missing = client.post(
        "/api/v1/chat-commands",
        headers=_authorization("gm"),
        json=_delete_request("missing", expected_revision=2, message_id="missing"),
    )
    _assert_error(missing, status_code=404, code="chat_message_not_found")

    binding = client.post(
        "/api/v1/chat-commands",
        headers=_authorization("gm"),
        json=_post_request(
            "wrong-binding",
            expected_revision=2,
            message_id="binding",
            session_id="other-session",
        ),
    )
    payload = _assert_error(binding, status_code=409, code="chat_binding_mismatch")
    assert payload["details"] == {
        "expected_session_id": SESSION_ID,
        "expected_table_id": TABLE_ID,
    }

    extra = _post_request("extra", expected_revision=2, message_id="extra")
    extra["command"]["unexpected"] = True
    _assert_error(
        client.post("/api/v1/chat-commands", headers=_authorization("gm"), json=extra),
        status_code=422,
        code="invalid_request",
    )


def test_chat_store_failures_use_stable_error_envelopes(
    chat_api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, log, _service = chat_api_client

    def corrupt_snapshot(_table_id: str):
        raise ChatStoreCorruptionError("private corruption detail")

    monkeypatch.setattr(log, "snapshot", corrupt_snapshot)
    payload = _assert_error(
        client.get("/api/v1/chat", headers=_authorization("gm")),
        status_code=500,
        code="chat_store_corrupt",
    )
    assert "private corruption" not in payload["message"]

    def unavailable_snapshot(_table_id: str):
        raise sqlite3.OperationalError("private database path")

    monkeypatch.setattr(log, "snapshot", unavailable_snapshot)
    payload = _assert_error(
        client.get("/api/v1/chat", headers=_authorization("gm")),
        status_code=503,
        code="chat_storage_unavailable",
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
            assert fields["event"] == "vtt.chat_event"
            parsed.append((int(fields["id"]), json.loads(fields["data"])))
    return parsed


def test_chat_sse_is_separate_exclusive_and_advances_across_hidden_events(
    chat_api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, log, _service = chat_api_client
    for revision, (message_id, author_id, audience) in enumerate(
        (
            ("public", "gm", ("all",)),
            ("other", "gm", ("participant:player-2",)),
            ("outbound", "player-1", ("participant:player-2",)),
            ("private", "gm", ("participant:player-1",)),
        )
    ):
        log.execute(
            ChatPostCommand(
                table_id=TABLE_ID,
                command_id=f"sse-{message_id}",
                expected_revision=revision,
                message=ChatMessage(
                    message_id=message_id,
                    author_id=author_id,
                    audience=audience,
                    text=message_id,
                ),
            )
        )

    seen_cursors: list[int] = []
    original_events_after = log.events_after

    def recording_events_after(table_id: str, sequence: int):
        seen_cursors.append(sequence)
        return original_events_after(table_id, sequence)

    monkeypatch.setattr(log, "events_after", recording_events_after)
    monkeypatch.setattr(chat_api, "SSE_POLL_INTERVAL_SECONDS", 0.001)
    monkeypatch.setattr(chat_api, "SSE_HEARTBEAT_INTERVAL_SECONDS", 0.01)

    status, headers, payload = asyncio.run(
        _capture_sse(
            client.app,
            "/api/v1/chat-events?after=0",
            headers=_authorization("player-1"),
            data_event_count=3,
        )
    )
    assert status == 200
    assert headers["content-type"].startswith("text/event-stream")
    assert [event_id for event_id, _event in _sse_events(payload)] == [1, 3, 4]

    status, _headers, payload = asyncio.run(
        _capture_sse(
            client.app,
            "/api/v1/chat-events?after=1",
            headers={**_authorization("player-1"), "last-event-id": "4"},
            stop_on_heartbeat=True,
        )
    )
    assert status == 200
    assert _sse_events(payload) == []
    assert ": heartbeat\n\n" in payload
    assert 4 in seen_cursors

    invalid = client.get("/api/v1/chat-events?after=01", headers=_authorization("player-1"))
    _assert_error(invalid, status_code=400, code="invalid_chat_event_cursor")
