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
from .scene_library_contracts import SceneCreateCommand, SceneMapMetadata, SceneRecord
from .scene_library_store import SQLiteSceneLibrary
from .session_service import VTTSessionService
from .solo_table import build_solo_table_fixture

_SOLO_TABLE_SESSION_ID = "echo-vault-session"
_SOLO_SCENE_GRID_SIZE_PX = 64.0
_SOLO_SCENE_BOOTSTRAP_COMMAND_ID = "bootstrap-echo-vault-scene-v1"


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
    presence_connection: sqlite3.Connection | None = None
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
                        ),
                    ),
                )
            )

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
        app = create_vtt_app(
            service,
            scene=fixture.scene,
            annotation_board=annotation_board,
            chat_log=chat_log,
            scene_library=scene_library,
            presence_store=presence_store,
            presence_epoch_ms_clock=epoch_ms_clock,
        )
    except Exception:
        try:
            _close_connections(
                presence_connection,
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
        or presence_connection is None
    ):  # pragma: no cover
        _close_connections(
            presence_connection,
            scene_library_connection,
            chat_connection,
            annotation_connection,
            connection,
        )
        raise RuntimeError("the solo durable connections were not initialized")

    def close_owned_connections() -> None:
        _close_connections(
            presence_connection,
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
