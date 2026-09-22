"""Local-operator composition root for standalone VTT administration.

This app provisions installation identity and a metadata-only world catalog. It
does not compose a table, encounter, fixture, content pack, or gameplay service.
"""

from __future__ import annotations

import argparse
import logging
import secrets
import sqlite3
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from threading import RLock

import uvicorn
from fastapi import FastAPI

from .installation_api import install_administration_routes
from .installation_store import SQLiteInstallationStore
from .world_catalog_store import SQLiteWorldCatalog, WorldCatalogStoreError

logger = logging.getLogger(__name__)
_CATALOG_TABLES = {
    "_vtt_world_catalog_metadata",
    "_vtt_world_catalog_head",
    "_vtt_world_catalog_events",
}


def create_standalone_app(
    database_path: str | Path,
    *,
    bootstrap_claim_delivery: Callable[[str], None] | None = None,
) -> FastAPI:
    """Open durable metadata stores, delivering a claim only on a fresh database.

    A fresh database requires an explicitly injected, local operator channel.
    Delivery happens before provisioning, so a failed callback cannot leave a
    durable claim whose plaintext was never delivered. Existing installations
    preserve the original verifier and never generate or redeliver a claim.
    An interrupted first composition or subsequently missing catalog requires
    operator recovery: reopening never recreates an existing catalog's schema.
    """

    if not isinstance(database_path, (str, Path)):
        raise TypeError("database_path must be a string or pathlib.Path")
    normalized_path = str(database_path)
    if not normalized_path.strip() or normalized_path == ":memory:":
        raise ValueError("database_path must be a durable SQLite file path")
    if bootstrap_claim_delivery is not None and not callable(bootstrap_claim_delivery):
        raise TypeError("bootstrap_claim_delivery must be callable or None")

    lock = RLock()
    connections: list[sqlite3.Connection] = []
    closed = False

    def close_owned_connections() -> None:
        nonlocal closed
        with lock:
            if closed:
                return
            closed = True
            first_error: Exception | None = None
            for connection in reversed(connections):
                try:
                    connection.close()
                except Exception as exc:  # pragma: no cover - defensive cleanup
                    if first_error is None:
                        first_error = exc
            if first_error is not None:
                raise first_error

    try:
        installation_connection = sqlite3.connect(
            normalized_path, timeout=30.0, check_same_thread=False
        )
        connections.append(installation_connection)
        tables = {
            str(row[0])
            for row in installation_connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        fresh = not tables
        if tables and not any(name.startswith("_vtt_installation_") for name in tables):
            raise RuntimeError(
                "Existing database has no installation identity; refusing to provision it."
            )
        claim: str | None = None
        if fresh:
            if bootstrap_claim_delivery is None:
                raise RuntimeError(
                    "Fresh installation requires a local operator bootstrap claim delivery callback."
                )
            claim = secrets.token_urlsafe(32)
            bootstrap_claim_delivery(claim)
        installation = SQLiteInstallationStore(installation_connection, bootstrap_claim=claim)
        claim = None

        catalog_connection = sqlite3.connect(normalized_path, timeout=30.0, check_same_thread=False)
        connections.append(catalog_connection)
        catalog: SQLiteWorldCatalog | None = None
        if installation.view().state != "safe_mode" and (fresh or _CATALOG_TABLES.issubset(tables)):
            try:
                catalog = SQLiteWorldCatalog(catalog_connection)
                catalog.snapshot()
            except (WorldCatalogStoreError, sqlite3.DatabaseError):
                # Installation status/session management remain available, but
                # an unreadable catalog is never silently replaced or repaired.
                catalog = None

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            del app
            try:
                yield
            finally:
                close_owned_connections()

        app = FastAPI(
            title="Standalone VTT Administration",
            docs_url=None,
            redoc_url=None,
            openapi_url=None,
            lifespan=lifespan,
        )
        app.state.close_owned_connections = close_owned_connections
        install_administration_routes(app, installation=installation, catalog=catalog, lock=lock)
        return app
    except BaseException:
        close_owned_connections()
        raise


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65_535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _deliver_bootstrap_claim(claim: str) -> None:
    """Deliver once through the controlling terminal, never logs or web output."""

    try:
        with open("/dev/tty", "w", encoding="utf-8") as terminal:
            terminal.write(
                "Standalone VTT first-run setup claim (keep private):\n"
                + claim
                + "\nSave this claim until setup succeeds; it is not reissued on restart.\n"
            )
            terminal.flush()
    except OSError:
        raise RuntimeError(
            "First-run setup requires an available local controlling terminal."
        ) from None


def main(argv: Sequence[str] | None = None) -> None:
    """Run installation administration on loopback port 8001 by default."""

    parser = argparse.ArgumentParser(description="Run standalone VTT installation administration.")
    parser.add_argument(
        "--database", required=True, type=Path, help="Durable installation SQLite file."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1).")
    parser.add_argument("--port", default=8001, type=_port, help="TCP port (default: 8001).")
    arguments = parser.parse_args(argv)
    app = create_standalone_app(
        arguments.database, bootstrap_claim_delivery=_deliver_bootstrap_claim
    )
    try:
        uvicorn.run(app, host=arguments.host, port=arguments.port)
    finally:
        # Uvicorn startup/bind failures may happen before ASGI lifespan starts.
        app.state.close_owned_connections()


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    main()


__all__ = ["create_standalone_app", "main"]
