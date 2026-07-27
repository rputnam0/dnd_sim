"""Runnable, restartable composition root for the Echo Vault solo table."""

from __future__ import annotations

import argparse
import sqlite3
from collections.abc import Sequence
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from dnd_sim.interactive.dnd_encounter_driver import DndCombatEncounterDriver

from .annotation_store import SQLiteAnnotationBoard
from .event_store import SQLiteSessionEventStore
from .http_api import create_vtt_app
from .session_service import VTTSessionService
from .solo_table import build_solo_table_fixture

_SOLO_TABLE_SESSION_ID = "echo-vault-session"


def create_solo_table_app(database_path: str | Path) -> FastAPI:
    """Create one HTTP app owning a durable Echo Vault session and connection."""

    if not isinstance(database_path, (str, Path)):
        raise TypeError("database_path must be a string or pathlib.Path")
    normalized_path = str(database_path)
    if not normalized_path.strip():
        raise ValueError("database_path must not be empty")

    connection = sqlite3.connect(
        normalized_path,
        timeout=30.0,
        check_same_thread=False,
    )
    annotation_connection: sqlite3.Connection | None = None
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
        app = create_vtt_app(
            service,
            scene=fixture.scene,
            annotation_board=annotation_board,
        )
    except Exception:
        if annotation_connection is not None:
            annotation_connection.close()
        connection.close()
        raise

    if annotation_connection is None:  # pragma: no cover - guarded by composition above
        connection.close()
        raise RuntimeError("the solo annotation connection was not initialized")
    app.router.add_event_handler("shutdown", annotation_connection.close)
    app.router.add_event_handler("shutdown", connection.close)
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
