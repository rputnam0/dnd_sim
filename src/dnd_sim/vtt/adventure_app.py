"""Local single-player adventure gateway over the shared durable session service."""

from __future__ import annotations

import argparse
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
import logging
from pathlib import Path
import sqlite3

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
import uvicorn

from dnd_sim.adventure import AdventureDriver, create_initial_state
from dnd_sim.interactive.session import EngineSessionError

from .contracts import VTTCommand, VTTCommitResponse
from .event_store import CommandConflictError, EventStoreError, SQLiteSessionEventStore
from .session_service import VTTSessionService, VTTSessionServiceError

logger = logging.getLogger(__name__)
_SESSION_ID = "lantern-below"
_MAX_COMMAND_BYTES = 65_536
_DEFAULT_ORIGINS = ("http://127.0.0.1:3000", "http://localhost:3000")


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"schema_version": "vtt.error.v1", "code": code, "message": message, "details": {}},
        headers={"Cache-Control": "no-store"},
    )


def create_adventure_app(
    database_path: str | Path,
    *,
    seed: int = 20_261_002,
    allowed_origins: Sequence[str] = _DEFAULT_ORIGINS,
) -> FastAPI:
    """Open one durable adventure; close its database when the app shuts down.

    This composition is for a trusted local player and binds to loopback in the
    CLI. Browser origins are explicitly restricted, including actual requests,
    while CLI/test clients without an Origin header remain usable.
    """
    if not isinstance(database_path, (str, Path)) or not str(database_path).strip():
        raise ValueError("database_path must be a non-empty local path")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    origins = tuple(allowed_origins)
    if not origins or any(
        not isinstance(origin, str)
        or not origin.startswith(("http://127.0.0.1:", "http://localhost:"))
        or any(char in origin for char in "?#@")
        for origin in origins
    ):
        raise ValueError("allowed_origins must be explicit localhost browser origins")

    connection = sqlite3.connect(str(database_path), timeout=30, check_same_thread=False)
    try:
        connection.execute("PRAGMA busy_timeout = 30000")
        driver = AdventureDriver()
        service = VTTSessionService.open(
            session_id=_SESSION_ID,
            initial_state=create_initial_state(),
            driver=driver,
            seed=seed,
            event_store=SQLiteSessionEventStore(connection),
        )
    except BaseException:
        connection.close()
        raise

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            connection.close()

    app = FastAPI(title="The Lantern Below", lifespan=lifespan)
    # Available to integration tests/operators, never returned by a player route.
    app.state.adventure_service = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def local_browser_boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin is not None and origin not in origins:
            return _error(403, "origin_rejected", "This browser origin is not allowed.")
        if request.headers.get("sec-fetch-site") == "cross-site" and origin is None:
            return _error(403, "origin_rejected", "This browser origin is not allowed.")
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(EngineSessionError)
    async def engine_error(_request: Request, exc: EngineSessionError) -> JSONResponse:
        if exc.code in {"stale_revision", "command_id_conflict", "session_id_mismatch"}:
            return _error(409, exc.code, "The adventure changed. Reload before choosing again.")
        if exc.code == "driver_failure":
            logger.error("Adventure command failed: %s", exc.details)
            return _error(422, "invalid_action", "That action cannot be resolved here.")
        if exc.code == "invalid_turn_declaration":
            if exc.details.get("rule_error_code") == "no_legal_targets":
                return _error(
                    422,
                    exc.code,
                    "That target is out of range or blocked. Move into range or choose another target.",
                )
            return _error(
                422,
                exc.code,
                "Check the target, movement distance, and remaining resources for this turn.",
            )
        if exc.code == "invalid_movement":
            return _error(422, exc.code, "Choose a reachable destination inside this room.")
        return _error(422, exc.code, "That choice is unavailable in the current adventure.")

    @app.exception_handler(VTTSessionServiceError)
    @app.exception_handler(CommandConflictError)
    async def conflict(_request: Request, _exc: Exception) -> JSONResponse:
        return _error(409, "session_conflict", "Reload the adventure before choosing again.")

    @app.exception_handler(EventStoreError)
    @app.exception_handler(sqlite3.Error)
    async def storage_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.error("Adventure save failed: %s", type(exc).__name__)
        return _error(
            503, "save_unavailable", "The adventure could not be saved. Retry this action."
        )

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.error("Adventure request failed: %s", type(exc).__name__)
        return _error(500, "request_failed", "The adventure request failed. Reload to recover.")

    @app.get("/api/v1/adventure")
    def adventure_view() -> dict:
        view = service.read_view()
        return {
            **view.projection,
            "schema_version": "adventure.view.v1",
            "session_id": view.session_id,
            "revision": view.revision,
            "versions": view.versions.model_dump(mode="json"),
        }

    @app.post("/api/v1/adventure/commands")
    async def adventure_command(request: Request):
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
            return _error(415, "json_required", "Commands must use application/json.")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > _MAX_COMMAND_BYTES:
                return _error(413, "command_too_large", "This command is too large.")
            body.extend(chunk)
        try:
            command = VTTCommand.model_validate_json(bytes(body))
        except ValidationError:
            return _error(422, "invalid_command", "The command has an invalid format.")
        if command.mode != "commit" or command.kind not in {
            "adventure.choose.v1",
            "dnd.declare_turn.v1",
        }:
            return _error(422, "unsupported_command", "Choose an available adventure action.")
        result = await run_in_threadpool(service.execute, command)
        if not isinstance(result, VTTCommitResponse):
            raise RuntimeError("adventure commits must return a commit receipt")
        return result

    return app


def main(argv: Sequence[str] | None = None) -> None:
    """Launch a local adventure server backed by a player-owned SQLite save."""
    parser = argparse.ArgumentParser(description="Play The Lantern Below locally")
    parser.add_argument("--database", type=Path, default=Path(".local/lantern-adventure.sqlite"))
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--seed", type=int, default=20_261_002)
    parser.add_argument("--web-origin", action="append", help="Allowed local browser origin")
    args = parser.parse_args(argv)
    args.database.parent.mkdir(parents=True, exist_ok=True)
    app = create_adventure_app(
        args.database,
        seed=args.seed,
        allowed_origins=args.web_origin or _DEFAULT_ORIGINS,
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
