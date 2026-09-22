from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from dnd_sim.interactive import DndCombatEncounterDriver
from dnd_sim.vtt.access import TableAccessPolicy
from dnd_sim.vtt.event_store import SQLiteSessionEventStore
from dnd_sim.vtt.http_api import create_vtt_app
from dnd_sim.vtt import journal_api
from dnd_sim.vtt.journal_contracts import (
    JournalDeleteDocumentCommand,
    JournalDeleteFolderCommand,
    JournalDocument,
    JournalPutDocumentCommand,
    JournalPutFolderCommand,
    JournalFolder,
)
from dnd_sim.vtt.journal_store import JournalStoreCorruptionError, SQLiteJournalStore
from dnd_sim.vtt.participants import TableParticipant, TableRoster
from dnd_sim.vtt.participants import PARTICIPANT_SCHEMA_VERSION, ROSTER_SCHEMA_VERSION
from dnd_sim.vtt.session_service import VTTSessionService
from dnd_sim.vtt.solo_table import build_solo_table_fixture
from dnd_sim.vtt.scene_library_store import SQLiteSceneLibrary
from dnd_sim.vtt.scene_library_contracts import (
    SceneArchiveCommand,
    SceneCreateCommand,
    SceneMapMetadata,
    SceneRecord,
)

TOKENS = {
    "gm": "journal-gm-token-0001",
    "other": "journal-other-token-0001",
    "player": "journal-player-token-0001",
}


class _ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


def test_journal_http_contracts_are_public_vtt_exports() -> None:
    import dnd_sim.vtt as vtt

    expected = {
        "JOURNAL_PROTECTED_ROUTES",
        "JOURNAL_VIEW_SCHEMA_VERSION",
        "JournalDocument",
        "JournalRequest",
        "JournalResponse",
        "JournalView",
        "SQLiteJournalStore",
        "install_journal_routes",
    }
    assert expected <= set(vtt.__all__)
    assert all(getattr(vtt, name) is not None for name in expected)


def test_journal_and_scene_library_must_share_one_table_identity(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "identity-session.sqlite3")
    journal_connection = sqlite3.connect(tmp_path / "identity-journal.sqlite3")
    scene_connection = sqlite3.connect(tmp_path / "identity-scenes.sqlite3")
    fixture = build_solo_table_fixture()
    service = VTTSessionService.open(
        session_id="session-a",
        initial_state=fixture.encounter_state,
        driver=DndCombatEncounterDriver(version_pins=fixture.version_pins),
        seed=fixture.seed,
        event_store=SQLiteSessionEventStore(connection),
    )
    try:
        with pytest.raises(ValueError, match="journal and scene-library table IDs"):
            create_vtt_app(
                service,
                scene=fixture.scene,
                journal_store=SQLiteJournalStore(journal_connection),
                journal_table_id="journal-table",
                scene_library=SQLiteSceneLibrary(scene_connection),
                scene_library_table_id="scene-table",
            )
    finally:
        scene_connection.close()
        journal_connection.close()
        connection.close()


def _policy() -> TableAccessPolicy:
    return TableAccessPolicy(
        roster=TableRoster(
            schema_version=ROSTER_SCHEMA_VERSION,
            table_id="table-a",
            participants=(
                TableParticipant(
                    schema_version=PARTICIPANT_SCHEMA_VERSION,
                    participant_id="gm",
                    display_name="GM",
                    role="gm",
                    owned_actor_ids=(),
                ),
                TableParticipant(
                    schema_version=PARTICIPANT_SCHEMA_VERSION,
                    participant_id="other",
                    display_name="Other",
                    role="player",
                    owned_actor_ids=(),
                ),
                TableParticipant(
                    schema_version=PARTICIPANT_SCHEMA_VERSION,
                    participant_id="player",
                    display_name="Player",
                    role="player",
                    owned_actor_ids=("vela_quill",),
                ),
            ),
        ),
        bearer_tokens=TOKENS,
    )


def _headers(participant: str) -> dict[str, str]:
    return {"authorization": f"Bearer {TOKENS[participant]}"}


def _put(command_id: str, revision: int, audience: list[str]) -> dict[str, object]:
    return {
        "schema_version": "vtt.journal_request.v1",
        "session_id": "session-a",
        "command": {
            "schema_version": "vtt.journal_command.v1",
            "command_type": "put_document",
            "table_id": "table-a",
            "command_id": command_id,
            "expected_revision": revision,
            "document": {
                "schema_version": "vtt.journal_document.v1",
                "document_id": "handout-a",
                "document_type": "handout",
                "folder_id": None,
                "title": "Vault Key",
                "audience": audience,
                "tags": ["lore"],
                "favorite": False,
                "blocks": [
                    {
                        "schema_version": "vtt.journal_block.v1",
                        "block_type": "paragraph",
                        "text": "The glass key opens the northern seal.",
                    }
                ],
                "map_pin": None,
            },
        },
    }


async def _capture_sse(
    app,
    path: str,
    *,
    headers: dict[str, str],
    data_event_count: int | None = None,
) -> tuple[int, str]:
    parsed = urlsplit(path)
    request_sent = False
    disconnected = asyncio.Event()
    response_start: dict[str, Any] | None = None
    response_body: list[str] = []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": parsed.path,
        "raw_path": parsed.path.encode("ascii"),
        "query_string": parsed.query.encode("ascii"),
        "headers": [
            (name.lower().encode("latin-1"), value.encode("latin-1"))
            for name, value in headers.items()
        ],
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
        elif message["type"] == "http.response.body":
            response_body.append(bytes(message.get("body", b"")).decode("utf-8"))
            if (
                data_event_count is not None
                and "".join(response_body).count("data: ") >= data_event_count
            ):
                disconnected.set()

    await asyncio.wait_for(app(scope, receive, send), timeout=1.0)
    assert response_start is not None
    return int(response_start["status"]), "".join(response_body)


def _document(
    document_id: str,
    *,
    audience: tuple[str, ...],
    folder_id: str | None = None,
    link: str | None = None,
) -> JournalDocument:
    blocks: list[dict[str, object]] = [
        {
            "schema_version": "vtt.journal_block.v1",
            "block_type": "paragraph",
            "text": f"Text for {document_id}",
        }
    ]
    if link is not None:
        blocks.append(
            {
                "schema_version": "vtt.journal_block.v1",
                "block_type": "document_link",
                "document_id": link,
                "label": "Hidden target label",
            }
        )
    return JournalDocument.model_validate(
        {
            "schema_version": "vtt.journal_document.v1",
            "document_id": document_id,
            "document_type": "handout",
            "folder_id": folder_id,
            "title": document_id,
            "audience": list(audience),
            "tags": [],
            "favorite": False,
            "blocks": blocks,
            "map_pin": None,
        }
    )


def test_journal_http_projects_search_and_enforces_gm_only_writes(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "session.sqlite3", check_same_thread=False)
    journal_connection = sqlite3.connect(tmp_path / "journal.sqlite3", check_same_thread=False)
    fixture = build_solo_table_fixture()
    service = VTTSessionService.open(
        session_id="session-a",
        initial_state=fixture.encounter_state,
        driver=DndCombatEncounterDriver(version_pins=fixture.version_pins),
        seed=fixture.seed,
        event_store=SQLiteSessionEventStore(connection),
    )
    store = SQLiteJournalStore(journal_connection)
    app = create_vtt_app(
        service,
        scene=fixture.scene,
        access_policy=_policy(),
        journal_store=store,
        journal_table_id="table-a",
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            unauthorized = client.post("/api/v1/journal-commands", json={"bad": True})
            assert unauthorized.status_code == 401
            unauthorized_query = client.get("/api/v1/journal?query=")
            assert unauthorized_query.status_code == 401
            unauthorized_cursor = client.get("/api/v1/journal-events?after=01")
            assert unauthorized_cursor.status_code == 401
            forbidden = client.post(
                "/api/v1/journal-commands",
                json=_put("forbidden", 0, ["all"]),
                headers=_headers("player"),
            )
            assert forbidden.status_code == 403
            created = client.post(
                "/api/v1/journal-commands",
                json=_put("public", 0, ["all"]),
                headers=_headers("gm"),
            )
            assert created.status_code == 200
            narrowed = client.post(
                "/api/v1/journal-commands",
                json=_put("private", 1, ["participant:player"]),
                headers=_headers("gm"),
            )
            assert narrowed.status_code == 200
            player = client.get("/api/v1/journal?query=glass%20key", headers=_headers("player"))
            other = client.get("/api/v1/journal", headers=_headers("other"))
            gm = client.get("/api/v1/journal", headers=_headers("gm"))
            off_board = _put("off-board", 2, ["all"])
            off_board["command"]["document"]["map_pin"] = {
                "schema_version": "vtt.journal_map_pin.v1",
                "scene_id": fixture.scene.scene_id,
                "position": {"x_ft": 1_000_000.0, "y_ft": 0.0, "z_ft": 0.0},
                "color": "#5eead4",
            }
            rejected_pin = client.post(
                "/api/v1/journal-commands",
                json=off_board,
                headers=_headers("gm"),
            )
            invalid_cursor = client.get(
                "/api/v1/journal-events?after=01",
                headers=_headers("player"),
            )
            invalid_query = client.get(
                "/api/v1/journal?query=bad%00query",
                headers=_headers("player"),
            )
        assert [item["document_id"] for item in player.json()["documents"]] == ["handout-a"]
        assert other.json()["documents"] == []
        assert other.json()["folders"] == []
        assert [item["document_id"] for item in gm.json()["documents"]] == ["handout-a"]
        assert rejected_pin.status_code == 409
        assert rejected_pin.json()["code"] == "journal_pin_out_of_bounds"
        assert rejected_pin.json()["details"] == {}
        assert invalid_cursor.status_code == 400
        assert invalid_cursor.json()["code"] == "invalid_journal_event_cursor"
        assert invalid_query.status_code == 400
        assert invalid_query.json()["code"] == "invalid_journal_query"
        assert store.revision("table-a") == 2
    finally:
        journal_connection.close()
        connection.close()


def test_player_projection_omits_folder_and_hidden_link_identities(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "session-links.sqlite3", check_same_thread=False)
    journal_connection = sqlite3.connect(
        tmp_path / "journal-links.sqlite3", check_same_thread=False
    )
    fixture = build_solo_table_fixture()
    service = VTTSessionService.open(
        session_id="session-a",
        initial_state=fixture.encounter_state,
        driver=DndCombatEncounterDriver(version_pins=fixture.version_pins),
        seed=fixture.seed,
        event_store=SQLiteSessionEventStore(connection),
    )
    store = SQLiteJournalStore(journal_connection)
    store.execute(
        JournalPutFolderCommand(
            table_id="table-a",
            command_id="folder",
            expected_revision=0,
            folder=JournalFolder(folder_id="gm-secrets", name="GM Secrets"),
        )
    )
    store.execute(
        JournalPutDocumentCommand(
            table_id="table-a",
            command_id="hidden",
            expected_revision=1,
            document=_document(
                "hidden-target",
                audience=("participant:other",),
                folder_id="gm-secrets",
            ),
        )
    )
    store.execute(
        JournalPutDocumentCommand(
            table_id="table-a",
            command_id="visible",
            expected_revision=2,
            document=_document(
                "visible-source",
                audience=("participant:other", "role:player"),
                folder_id="gm-secrets",
                link="hidden-target",
            ),
        )
    )
    app = create_vtt_app(
        service,
        scene=fixture.scene,
        access_policy=_policy(),
        journal_store=store,
        journal_table_id="table-a",
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/v1/journal", headers=_headers("player"))
        assert response.status_code == 200
        assert response.json()["folders"] == []
        assert response.json()["documents"] == [
            {
                **_document(
                    "visible-source",
                    audience=("role:player",),
                ).model_dump(mode="json"),
            }
        ]
        encoded = response.text
        assert "gm-secrets" not in encoded
        assert "hidden-target" not in encoded
        assert "Hidden target label" not in encoded
        assert "participant:other" not in encoded

        with TestClient(app, raise_server_exceptions=False) as client:
            folder_search = client.get(
                "/api/v1/journal?query=gm-secrets",
                headers=_headers("player"),
            )
            hidden_link_search = client.get(
                "/api/v1/journal?query=hidden-target",
                headers=_headers("player"),
            )
        assert folder_search.json()["documents"] == []
        assert hidden_link_search.json()["documents"] == []
    finally:
        journal_connection.close()
        connection.close()


def test_audience_narrowing_sse_emits_sanitized_prior_visible_tombstone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = sqlite3.connect(tmp_path / "session-sse.sqlite3", check_same_thread=False)
    journal_connection = sqlite3.connect(tmp_path / "journal-sse.sqlite3", check_same_thread=False)
    fixture = build_solo_table_fixture()
    service = VTTSessionService.open(
        session_id="session-a",
        initial_state=fixture.encounter_state,
        driver=DndCombatEncounterDriver(version_pins=fixture.version_pins),
        seed=fixture.seed,
        event_store=SQLiteSessionEventStore(connection),
    )
    store = SQLiteJournalStore(journal_connection)
    store.execute(
        JournalPutDocumentCommand(
            table_id="table-a",
            command_id="hidden",
            expected_revision=0,
            document=_document("hidden-target", audience=("participant:other",)),
        )
    )
    public = _document("shared", audience=("all",), link="hidden-target")
    store.execute(
        JournalPutDocumentCommand(
            table_id="table-a",
            command_id="public",
            expected_revision=1,
            document=public,
        )
    )
    store.execute(
        JournalPutDocumentCommand(
            table_id="table-a",
            command_id="narrow",
            expected_revision=2,
            document=public.model_copy(update={"audience": ("participant:other",)}),
        )
    )
    app = create_vtt_app(
        service,
        scene=fixture.scene,
        access_policy=_policy(),
        journal_store=store,
        journal_table_id="table-a",
    )
    try:
        monkeypatch.setattr(journal_api, "SSE_POLL_INTERVAL_SECONDS", 0.001)
        status, payload = asyncio.run(
            _capture_sse(
                app,
                "/api/v1/journal-events?after=2",
                headers=_headers("player"),
                data_event_count=1,
            )
        )
        assert status == 200
        assert "event: vtt.journal_event" in payload
        assert '"event_type":"document_deleted"' in payload
        assert '"document_id":"shared"' in payload
        assert "hidden-target" not in payload
        assert "Hidden target label" not in payload
    finally:
        journal_connection.close()
        connection.close()


def test_journal_sse_rejects_a_forged_delete_tombstone_before_emitting() -> None:
    connection = sqlite3.connect(":memory:")
    store = SQLiteJournalStore(connection)
    original = _document("shared", audience=("all",))
    store.execute(
        JournalPutDocumentCommand(
            table_id="table-a",
            command_id="put-shared",
            expected_revision=0,
            document=original,
        )
    )
    store.execute(
        JournalDeleteDocumentCommand(
            table_id="table-a",
            command_id="delete-shared",
            expected_revision=1,
            document_id="shared",
        )
    )
    row = connection.execute(
        "SELECT receipt_json FROM _vtt_journal_event_log WHERE table_id = ? AND revision = 2",
        ("table-a",),
    ).fetchone()
    assert row is not None
    receipt = json.loads(str(row[0]))
    receipt["event"]["document"]["title"] = "Forged"
    receipt["event"]["document"]["blocks"] = [
        {
            "schema_version": "vtt.journal_block.v1",
            "block_type": "paragraph",
            "text": "Forged body",
        }
    ]
    connection.execute(
        "UPDATE _vtt_journal_event_log SET receipt_json = ? WHERE table_id = ? AND revision = 2",
        (
            json.dumps(
                receipt,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            "table-a",
        ),
    )
    connection.commit()

    async def read_first_event() -> str:
        stream = journal_api._stream(
            _ConnectedRequest(),
            store=store,
            table_id="table-a",
            after=1,
            participant=None,
        )
        return await anext(stream)

    with pytest.raises(JournalStoreCorruptionError, match="tombstone"):
        asyncio.run(read_first_event())
    connection.close()


def test_journal_sse_rejects_a_forged_folder_tombstone_before_emitting() -> None:
    connection = sqlite3.connect(":memory:")
    store = SQLiteJournalStore(connection)
    store.execute(
        JournalPutFolderCommand(
            table_id="table-a",
            command_id="put-folder",
            expected_revision=0,
            folder=JournalFolder(
                folder_id="lore",
                parent_folder_id=None,
                name="Lore",
            ),
        )
    )
    store.execute(
        JournalDeleteFolderCommand(
            table_id="table-a",
            command_id="delete-folder",
            expected_revision=1,
            folder_id="lore",
        )
    )
    row = connection.execute(
        "SELECT receipt_json FROM _vtt_journal_event_log WHERE table_id = ? AND revision = 2",
        ("table-a",),
    ).fetchone()
    assert row is not None
    receipt = json.loads(str(row[0]))
    receipt["event"]["folder"]["name"] = "Forged"
    connection.execute(
        "UPDATE _vtt_journal_event_log SET receipt_json = ? WHERE table_id = ? AND revision = 2",
        (
            json.dumps(
                receipt,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            "table-a",
        ),
    )
    connection.commit()

    async def read_first_event() -> str:
        stream = journal_api._stream(
            _ConnectedRequest(),
            store=store,
            table_id="table-a",
            after=1,
            participant=None,
        )
        return await anext(stream)

    with pytest.raises(JournalStoreCorruptionError, match="tombstone"):
        asyncio.run(read_first_event())
    connection.close()


def test_exact_pinned_retry_survives_scene_archive_but_binding_and_collision_still_fail(
    tmp_path: Path,
) -> None:
    connection = sqlite3.connect(tmp_path / "session-replay.sqlite3", check_same_thread=False)
    journal_connection = sqlite3.connect(
        tmp_path / "journal-replay.sqlite3", check_same_thread=False
    )
    scene_connection = sqlite3.connect(tmp_path / "scenes-replay.sqlite3", check_same_thread=False)
    fixture = build_solo_table_fixture()
    service = VTTSessionService.open(
        session_id="session-a",
        initial_state=fixture.encounter_state,
        driver=DndCombatEncounterDriver(version_pins=fixture.version_pins),
        seed=fixture.seed,
        event_store=SQLiteSessionEventStore(connection),
    )
    store = SQLiteJournalStore(journal_connection)
    scenes = SQLiteSceneLibrary(scene_connection)

    def scene(scene_id: str) -> SceneRecord:
        return SceneRecord(
            scene_id=scene_id,
            map_metadata=SceneMapMetadata(
                name=scene_id,
                width_px=100,
                height_px=100,
                grid_size_px=10.0,
                gridless=False,
            ),
        )

    scenes.execute(
        SceneCreateCommand(
            table_id="table-a",
            command_id="create-target",
            expected_revision=0,
            scene=scene("pin-target"),
        )
    )
    scenes.execute(
        SceneCreateCommand(
            table_id="table-a",
            command_id="create-successor",
            expected_revision=1,
            scene=scene("successor"),
        )
    )
    request = _put("pinned", 0, ["all"])
    request["command"]["document"]["map_pin"] = {
        "schema_version": "vtt.journal_map_pin.v1",
        "scene_id": "pin-target",
        "position": {"x_ft": 5.0, "y_ft": 5.0, "z_ft": 0.0},
        "color": "#5eead4",
    }
    app = create_vtt_app(
        service,
        scene=fixture.scene,
        access_policy=_policy(),
        journal_store=store,
        journal_table_id="table-a",
        scene_library=scenes,
        scene_library_table_id="table-a",
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            created = client.post("/api/v1/journal-commands", json=request, headers=_headers("gm"))
            assert created.status_code == 200
            assert created.json()["replayed"] is False
            scenes.execute(
                SceneArchiveCommand(
                    table_id="table-a",
                    command_id="archive-target",
                    expected_revision=2,
                    scene_id="pin-target",
                    successor_scene_id="successor",
                )
            )
            replayed = client.post("/api/v1/journal-commands", json=request, headers=_headers("gm"))
            wrong_binding = {
                **request,
                "session_id": "other-session",
            }
            rejected_binding = client.post(
                "/api/v1/journal-commands",
                json=wrong_binding,
                headers=_headers("gm"),
            )
            collision = {
                **request,
                "command": {
                    **request["command"],
                    "document": {
                        **request["command"]["document"],
                        "title": "Different title",
                    },
                },
            }
            rejected_collision = client.post(
                "/api/v1/journal-commands",
                json=collision,
                headers=_headers("gm"),
            )
        assert replayed.status_code == 200
        assert replayed.json()["replayed"] is True
        assert replayed.json()["receipt"] == created.json()["receipt"]
        assert rejected_binding.status_code == 409
        assert rejected_binding.json()["code"] == "journal_binding_mismatch"
        assert rejected_collision.status_code == 409
        assert rejected_collision.json()["code"] == "journal_command_id_conflict"
        assert store.revision("table-a") == 1
    finally:
        scene_connection.close()
        journal_connection.close()
        connection.close()
