"""Runnable, restartable composition root for the Echo Vault solo table."""

from __future__ import annotations

import argparse
import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from dnd_sim.interactive.dnd_encounter_driver import DndCombatEncounterDriver

from .annotation_store import SQLiteAnnotationBoard
from .chat_store import SQLiteChatLog
from .event_store import SQLiteSessionEventStore
from .http_api import OPEN_LOCAL_PARTICIPANT_ID, create_vtt_app
from .map_asset_store import SQLiteMapAssetStore
from .journal_store import SQLiteJournalStore
from .participants import (
    PARTICIPANT_SCHEMA_VERSION,
    ROSTER_SCHEMA_VERSION,
    TableParticipant,
    TableRoster,
)
from .presence_store import (
    DEFAULT_PRESENCE_AWAY_AFTER_MS,
    DEFAULT_PRESENCE_OFFLINE_AFTER_MS,
    SQLitePresenceStore,
)
from .presentation_store import SQLitePresentationStore
from .scene import FeetPosition
from .scene_library_contracts import (
    SceneCreateCommand,
    SceneMapAssetReference,
    SceneMapMetadata,
    SceneRecord,
)
from .scene_library_store import SQLiteSceneLibrary
from .session_service import VTTSessionService
from .solo_table import build_solo_table_fixture
from .token_contracts import TokenCreateCommand, TokenPose, TokenRecord
from .token_store import SQLiteTokenStore
from .visibility_store import SQLiteVisibilityStore

_SOLO_TABLE_SESSION_ID = "echo-vault-session"
_SOLO_SCENE_GRID_SIZE_PX = 181.0
_SOLO_SCENE_BOOTSTRAP_COMMAND_ID = "bootstrap-echo-vault-scene-v1"
_SOLO_SCENE_MAP_ASSET_SHA256 = "90ece48257967087c27ac6ae2da497434526f88811242b9ae7a267cbee0d6b89"


def _close_connections(*connections: sqlite3.Connection | None) -> None:
    """Attempt every close and report the first cleanup failure afterward."""

    first_error: Exception | None = None
    for connection in connections:
        if connection is None:
            continue
        try:
            connection.close()
        except Exception as exc:  # pragma: no cover - sqlite close is normally infallible
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error


def create_solo_table_app(
    database_path: str | Path,
    *,
    epoch_ms_clock: Callable[[], int] | None = None,
) -> FastAPI:
    """Create one HTTP app owning a durable Echo Vault session and connection."""

    if not isinstance(database_path, (str, Path)):
        raise TypeError("database_path must be a string or pathlib.Path")
    normalized_path = str(database_path)
    if not normalized_path.strip():
        raise ValueError("database_path must not be empty")
    if epoch_ms_clock is not None and not callable(epoch_ms_clock):
        raise TypeError("epoch_ms_clock must be callable or None")

    connection = sqlite3.connect(
        normalized_path,
        timeout=30.0,
        check_same_thread=False,
    )
    annotation_connection: sqlite3.Connection | None = None
    chat_connection: sqlite3.Connection | None = None
    scene_library_connection: sqlite3.Connection | None = None
    map_asset_connection: sqlite3.Connection | None = None
    token_connection: sqlite3.Connection | None = None
    presence_connection: sqlite3.Connection | None = None
    visibility_connection: sqlite3.Connection | None = None
    journal_connection: sqlite3.Connection | None = None
    presentation_connection: sqlite3.Connection | None = None
    try:
        connection.execute("PRAGMA busy_timeout = 30000")
        fixture = build_solo_table_fixture()
        driver = DndCombatEncounterDriver(version_pins=fixture.version_pins)
        event_store = SQLiteSessionEventStore(connection)
        service = VTTSessionService.open(
            session_id=_SOLO_TABLE_SESSION_ID,
            initial_state=fixture.encounter_state,
            driver=driver,
            seed=fixture.seed,
            event_store=event_store,
        )
        # The session store and annotation board use independent connections to
        # the same durable database. This keeps their transaction ownership
        # isolated while preserving one portable solo-table file.
        annotation_connection = sqlite3.connect(
            normalized_path,
            timeout=30.0,
            check_same_thread=False,
        )
        annotation_connection.execute("PRAGMA busy_timeout = 30000")
        annotation_board = SQLiteAnnotationBoard(annotation_connection)

        # Chat owns a third transaction boundary so a long-lived chat read or
        # write cannot accidentally share session or annotation transactions.
        chat_connection = sqlite3.connect(
            normalized_path,
            timeout=30.0,
            check_same_thread=False,
        )
        chat_connection.execute("PRAGMA busy_timeout = 30000")
        chat_log = SQLiteChatLog(chat_connection)

        # Scene lifecycle owns a fourth transaction boundary. A deterministic
        # metadata-only bootstrap record makes existing solo databases
        # immediately scene-manageable without duplicating it on restart.
        scene_library_connection = sqlite3.connect(
            normalized_path,
            timeout=30.0,
            check_same_thread=False,
        )
        scene_library_connection.execute("PRAGMA busy_timeout = 30000")
        scene_library = SQLiteSceneLibrary(scene_library_connection)
        if scene_library.revision(_SOLO_TABLE_SESSION_ID) == 0:
            scene_library.execute(
                SceneCreateCommand(
                    table_id=_SOLO_TABLE_SESSION_ID,
                    command_id=_SOLO_SCENE_BOOTSTRAP_COMMAND_ID,
                    expected_revision=0,
                    scene=SceneRecord(
                        scene_id=fixture.scene.scene_id,
                        map_metadata=SceneMapMetadata(
                            name=fixture.scene.name,
                            width_px=int(fixture.scene.columns * _SOLO_SCENE_GRID_SIZE_PX),
                            height_px=int(fixture.scene.rows * _SOLO_SCENE_GRID_SIZE_PX),
                            grid_size_px=_SOLO_SCENE_GRID_SIZE_PX,
                            gridless=False,
                            asset=SceneMapAssetReference(
                                asset_id="echo-vault-original",
                                media_type="image/png",
                                content_path="/assets/maps/echo-vault-original.png",
                                sha256=_SOLO_SCENE_MAP_ASSET_SHA256,
                                alt_text=(
                                    "A top-down arcane vault chamber with a fractured "
                                    "central resonator and broken stone colonnades."
                                ),
                            ),
                        ),
                    ),
                )
            )

        # Uploaded map bytes own a fifth transaction boundary. The built-in
        # Echo Vault map remains a static bundled asset; only GM uploads enter
        # this private catalog.
        map_asset_connection = sqlite3.connect(
            normalized_path,
            timeout=30.0,
            check_same_thread=False,
        )
        map_asset_connection.execute("PRAGMA busy_timeout = 30000")
        map_asset_store = SQLiteMapAssetStore(map_asset_connection)

        # Token presentation owns a sixth boundary. Actor-linked bootstrap
        # tokens retain pose controls here while engine positions remain the
        # authoritative position returned by the HTTP projection.
        token_connection = sqlite3.connect(
            normalized_path,
            timeout=30.0,
            check_same_thread=False,
        )
        token_connection.execute("PRAGMA busy_timeout = 30000")
        token_store = SQLiteTokenStore(token_connection)
        if token_store.revision(_SOLO_TABLE_SESSION_ID) == 0:
            for revision, actor_id in enumerate(
                sorted(fixture.encounter_state.turn.context.actors),
            ):
                actor = fixture.encounter_state.turn.context.actors[actor_id]
                token_store.execute(
                    TokenCreateCommand(
                        table_id=_SOLO_TABLE_SESSION_ID,
                        command_id=f"bootstrap-token-{actor_id}-v1",
                        expected_revision=revision,
                        token=TokenRecord(
                            token_id=f"{actor_id}-token",
                            scene_id=fixture.scene.scene_id,
                            actor_id=actor_id,
                            name=actor.name,
                            pose=TokenPose(
                                position_ft=FeetPosition(
                                    x_ft=actor.position[0],
                                    y_ft=actor.position[1],
                                    z_ft=actor.position[2],
                                ),
                                width_ft=fixture.scene.cell_size_ft,
                                height_ft=fixture.scene.cell_size_ft,
                                rotation_degrees=0.0,
                                layer=0,
                            ),
                            visibility="public",
                            locked=False,
                            nameplate="always",
                            show_hp_bar=True,
                            aura_radius_ft=0.0,
                            aura_color="#4DD7B3",
                            condition_labels=tuple(sorted(actor.conditions)),
                        ),
                    )
                )

        # Presence owns a seventh transaction boundary so heartbeats cannot
        # hold locks across scene, media, or token operations.
        presence_connection = sqlite3.connect(
            normalized_path,
            timeout=30.0,
            check_same_thread=False,
        )
        presence_connection.execute("PRAGMA busy_timeout = 30000")
        local_participant = TableParticipant(
            schema_version=PARTICIPANT_SCHEMA_VERSION,
            participant_id=OPEN_LOCAL_PARTICIPANT_ID,
            display_name="Local GM",
            role="gm",
            owned_actor_ids=(),
        )
        presence_store = SQLitePresenceStore(
            presence_connection,
            roster=TableRoster(
                schema_version=ROSTER_SCHEMA_VERSION,
                table_id=_SOLO_TABLE_SESSION_ID,
                participants=(local_participant,),
            ),
            away_after_ms=DEFAULT_PRESENCE_AWAY_AFTER_MS,
            offline_after_ms=DEFAULT_PRESENCE_OFFLINE_AFTER_MS,
        )

        # Visibility authoring owns an eighth transaction boundary. Fog,
        # barriers, lights, and senses may then evolve independently from
        # encounter, token, presence, and media commits.
        visibility_connection = sqlite3.connect(
            normalized_path,
            timeout=30.0,
            check_same_thread=False,
        )
        visibility_connection.execute("PRAGMA busy_timeout = 30000")
        visibility_store = SQLiteVisibilityStore(visibility_connection)

        # Journal preparation owns a ninth transaction boundary so handouts,
        # folders, links, and pins persist independently from live encounter IO.
        journal_connection = sqlite3.connect(
            normalized_path,
            timeout=30.0,
            check_same_thread=False,
        )
        journal_connection.execute("PRAGMA busy_timeout = 30000")
        journal_store = SQLiteJournalStore(journal_connection)

        # Sound and shared camera state own a tenth transaction boundary.
        presentation_connection = sqlite3.connect(
            normalized_path,
            timeout=30.0,
            check_same_thread=False,
        )
        presentation_connection.execute("PRAGMA busy_timeout = 30000")
        presentation_store = SQLitePresentationStore(presentation_connection)
        app = create_vtt_app(
            service,
            scene=fixture.scene,
            annotation_board=annotation_board,
            chat_log=chat_log,
            scene_library=scene_library,
            map_asset_store=map_asset_store,
            token_store=token_store,
            visibility_store=visibility_store,
            journal_store=journal_store,
            presence_store=presence_store,
            presence_epoch_ms_clock=epoch_ms_clock,
            presentation_store=presentation_store,
            presentation_epoch_ms_clock=epoch_ms_clock,
        )
    except Exception:
        try:
            _close_connections(
                presentation_connection,
                journal_connection,
                visibility_connection,
                presence_connection,
                token_connection,
                map_asset_connection,
                scene_library_connection,
                chat_connection,
                annotation_connection,
                connection,
            )
        except Exception:
            pass
        raise

    if (
        annotation_connection is None
        or chat_connection is None
        or scene_library_connection is None
        or map_asset_connection is None
        or token_connection is None
        or presence_connection is None
        or visibility_connection is None
        or journal_connection is None
        or presentation_connection is None
    ):  # pragma: no cover
        _close_connections(
            presentation_connection,
            journal_connection,
            visibility_connection,
            presence_connection,
            token_connection,
            map_asset_connection,
            scene_library_connection,
            chat_connection,
            annotation_connection,
            connection,
        )
        raise RuntimeError("the solo durable connections were not initialized")

    def close_owned_connections() -> None:
        _close_connections(
            presentation_connection,
            journal_connection,
            visibility_connection,
            presence_connection,
            token_connection,
            map_asset_connection,
            scene_library_connection,
            chat_connection,
            annotation_connection,
            connection,
        )

    app.router.add_event_handler("shutdown", close_owned_connections)
    return app


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65_535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def main(argv: Sequence[str] | None = None) -> None:
    """Run a solo table using only explicitly composed process resources."""

    parser = argparse.ArgumentParser(description="Run the Echo Vault solo VTT table.")
    parser.add_argument(
        "--database",
        required=True,
        type=Path,
        help="SQLite database path used to persist the solo table.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface passed to Uvicorn (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        default=8000,
        type=_port,
        help="TCP port passed to Uvicorn (default: 8000).",
    )
    arguments = parser.parse_args(argv)

    app = create_solo_table_app(arguments.database)
    uvicorn.run(app, host=arguments.host, port=arguments.port)


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    main()


__all__ = ["create_solo_table_app", "main"]
