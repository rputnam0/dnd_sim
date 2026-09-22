"""Authenticated, bounded HTTP boundary for standalone installation metadata."""

from __future__ import annotations

import logging
import secrets
import sqlite3
from threading import RLock
from typing import TYPE_CHECKING, Any, TypeVar

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from .http_api import VTTError
from .installation_api_contracts import (
    InstallationLoginRequest,
    InstallationLoginResponse,
    InstallationSessionView,
    WorldArchiveRequest,
    WorldCreateRequest,
    WorldDashboardMutationResponse,
    WorldDashboardView,
    WorldRenameRequest,
)
from .installation_contracts import AdminPublic, SessionPublic
from .installation_store import (
    AuthenticationError,
    BootstrapClaimError,
    InstallationAlreadyInitializedError,
    InstallationSafeModeError,
    InstallationStoreError,
    SQLiteInstallationStore,
)
from .world_catalog_contracts import (
    WorldArchiveCommand,
    WorldCreateCommand,
    WorldCreatedEvent,
    WorldRecord,
    WorldRenameCommand,
)
from .world_catalog_store import (
    SQLiteWorldCatalog,
    WorldArchivedError,
    WorldCatalogStoreError,
    WorldCommandConflictError,
    WorldIdConflictError,
    WorldLimitError,
    WorldNameConflictError,
    WorldNameUnchangedError,
    WorldNotFoundError,
    WorldRevisionConflictError,
    WorldTableConflictError,
)

MAX_ADMIN_BODY_BYTES = 16_384
logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from .world_preparation import WorldPreparationManager
DEFAULT_ADMIN_ALLOWED_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")
_ROOT = "/api/v1/installation"
_Model = TypeVar("_Model", bound=BaseModel)
_WORLD_CONFLICT_CODES = {
    WorldCommandConflictError: "world_command_conflict",
    WorldRevisionConflictError: "world_revision_conflict",
    WorldIdConflictError: "world_identity_conflict",
    WorldTableConflictError: "world_identity_conflict",
    WorldNameConflictError: "world_name_conflict",
    WorldNotFoundError: "world_not_found",
    WorldArchivedError: "world_archived",
    WorldNameUnchangedError: "world_name_unchanged",
    WorldLimitError: "world_limit_reached",
}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=VTTError(code=code, message=message).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


class _AdministrationCORSMiddleware(CORSMiddleware):
    """Keep rejected preflights inside the same input-free error contract."""

    def preflight_response(self, request_headers: Headers) -> Response:
        response = super().preflight_response(request_headers)
        if response.status_code < 400:
            return response
        error = _error(400, "origin_not_allowed", "Cross-origin request is not allowed.")
        for name, value in response.headers.items():
            if name not in {"content-length", "content-type"}:
                error.headers[name] = value
        return error


async def _bounded_body(request: Request) -> bytes | None:
    """Return no payload for oversized input; never retain an unbounded body."""

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_ADMIN_BODY_BYTES:
            return None
        body.extend(chunk)
    return bytes(body)


def _decode(model: type[_Model], body: bytes | None) -> _Model:
    if body is None:
        raise ValueError("invalid request")
    return model.model_validate_json(body)


def _bearer(request: Request) -> str:
    if len(request.headers.getlist("authorization")) != 1:
        raise AuthenticationError("authentication required")
    scheme, separator, token = request.headers["authorization"].partition(" ")
    if scheme.lower() != "bearer" or not separator or not token or " " in token:
        raise AuthenticationError("authentication required")
    return token


def install_administration_routes(
    app: FastAPI,
    *,
    installation: SQLiteInstallationStore,
    catalog: SQLiteWorldCatalog | None,
    lock: RLock,
    world_manager: WorldPreparationManager | None = None,
) -> None:
    """Compose routes around stores whose connections are owned by the app.

    Every store access is serialized with the same application lock. Protected
    bodies are not parsed until authentication succeeds, and credentials are
    checked again after reading a body, before entering a mutation transaction.
    """

    app.add_middleware(
        _AdministrationCORSMiddleware,
        allow_origins=list(DEFAULT_ADMIN_ALLOWED_ORIGINS),
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-VTT-Setup-Claim"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def no_store(request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    async def boundary_error(request: Request, exc: Exception) -> JSONResponse:
        del request
        if isinstance(exc, AuthenticationError):
            return _error(401, "authentication_required", "Administrator authentication required.")
        if isinstance(exc, BootstrapClaimError):
            return _error(401, "setup_claim_rejected", "Setup claim rejected.")
        if isinstance(exc, InstallationAlreadyInitializedError):
            return _error(
                409, "installation_already_initialized", "Installation is already initialized."
            )
        if isinstance(exc, InstallationSafeModeError):
            return _error(503, "installation_safe_mode", "Installation is in read-only safe mode.")
        if type(exc) in _WORLD_CONFLICT_CODES:
            return _error(
                409,
                _WORLD_CONFLICT_CODES[type(exc)],
                "World catalog command conflicts with current state.",
            )
        if isinstance(exc, (sqlite3.DatabaseError, InstallationStoreError, WorldCatalogStoreError)):
            return _error(503, "storage_unavailable", "Administration storage is unavailable.")
        if isinstance(exc, (ValidationError, RequestValidationError, ValueError)):
            return _error(422, "invalid_request", "Request payload is invalid.")
        if isinstance(exc, HTTPException):
            code = "not_found" if exc.status_code == 404 else "request_not_allowed"
            return _error(exc.status_code, code, "Requested operation is unavailable.")
        return _error(500, "internal_error", "Administration request could not be completed.")

    for exception_type in (
        InstallationStoreError,
        WorldCatalogStoreError,
        sqlite3.DatabaseError,
        ValidationError,
        RequestValidationError,
        ValueError,
        HTTPException,
        Exception,
    ):
        app.add_exception_handler(exception_type, boundary_error)

    def require_available() -> None:
        if installation.view().state == "safe_mode":
            raise InstallationSafeModeError("installation safe mode")

    def authenticate(request: Request) -> tuple[str, SessionPublic, AdminPublic]:
        require_available()
        token = _bearer(request)
        session = installation.authenticate_session(token)
        admin = next(
            (admin for admin in installation.admins() if admin.admin_id == session.admin_id), None
        )
        if admin is None:
            raise AuthenticationError("authentication required")
        return token, session, admin

    def require_catalog() -> SQLiteWorldCatalog:
        if catalog is None:
            raise WorldCatalogStoreError("world catalog unavailable")
        return catalog

    def dashboard(catalog_view: Any) -> WorldDashboardView:
        return WorldDashboardView(
            catalog=catalog_view,
            launch_supported=world_manager is not None,
            launch_unavailable_reason=(
                None if world_manager is not None else "world_provisioning_not_implemented"
            ),
        )

    @app.get(_ROOT)
    async def installation_view() -> dict[str, Any]:
        with lock:
            return installation.view().model_dump(mode="json")

    @app.post(_ROOT + "/setup", status_code=201)
    async def setup(request: Request) -> dict[str, Any]:
        # Bytes and the oversized sentinel are validated inside initialize(),
        # after the claim, so malformed input is not an authentication oracle.
        body = await _bounded_body(request)
        claims = request.headers.getlist("x-vtt-setup-claim")
        claim = claims[0] if len(claims) == 1 else ""
        with lock:
            return installation.initialize(bootstrap_claim=claim, admin_payload=body).model_dump(
                mode="json"
            )

    @app.post(_ROOT + "/login")
    async def login(request: Request) -> InstallationLoginResponse:
        with lock:
            require_available()
        body = await _bounded_body(request)
        with lock:
            require_available()
            payload = _decode(InstallationLoginRequest, body)
            issuance = installation.login(
                username=payload.username, password=payload.password.get_secret_value()
            )
            admin = next(
                admin
                for admin in installation.admins()
                if admin.admin_id == issuance.session.admin_id
            )
            return InstallationLoginResponse(
                admin=admin, session=issuance.session, bearer_token=issuance.consume_bearer()
            )

    @app.get(_ROOT + "/session")
    async def session(request: Request) -> InstallationSessionView:
        with lock:
            _, session, admin = authenticate(request)
            return InstallationSessionView(admin=admin, session=session)

    @app.post(_ROOT + "/logout", status_code=204)
    async def logout(request: Request) -> Response:
        with lock:
            token, _, _ = authenticate(request)
            installation.revoke_session(token)
            if world_manager is not None:
                world_manager.prune()
        return Response(status_code=204)

    @app.get(_ROOT + "/worlds")
    async def worlds(request: Request) -> WorldDashboardView:
        with lock:
            authenticate(request)
            return dashboard(require_catalog().snapshot())

    if world_manager is not None:

        @app.post(_ROOT + "/worlds/{world_id}/launch")
        async def launch_world(world_id: str, request: Request) -> Any:
            # Preparing is an explicit transition with no caller-supplied state.
            with lock:
                token, _, admin = authenticate(request)
                return world_manager.launch(world_id, admin_bearer=token, admin=admin)

        @app.post(_ROOT + "/worlds/{world_id}/return", status_code=204)
        async def return_world(world_id: str, request: Request) -> Response:
            with lock:
                world_manager.return_world(world_id, _bearer(request))
            return Response(status_code=204)

    async def mutate(request: Request, model: type[_Model]) -> WorldDashboardMutationResponse:
        with lock:
            authenticate(request)
        body = await _bounded_body(request)
        with lock:
            authenticate(request)
            payload = _decode(model, body)
            with require_catalog().transaction() as transaction:
                if isinstance(payload, WorldCreateRequest):
                    # Reconstruct IDs from the original durable receipt while
                    # holding the write transaction. execute() then checks the
                    # complete original command, including name and revision.
                    previous = next(
                        (
                            receipt
                            for receipt in transaction.receipts_after(0)
                            if receipt.command_id == payload.command_id
                        ),
                        None,
                    )
                    if previous is not None:
                        if not isinstance(previous.event, WorldCreatedEvent):
                            raise WorldCommandConflictError("command content changed")
                        world = previous.event.world.model_copy(update={"name": payload.name})
                    else:
                        world = WorldRecord(
                            world_id="world_" + secrets.token_urlsafe(24),
                            table_id="table_" + secrets.token_urlsafe(24),
                            name=payload.name,
                        )
                    command = WorldCreateCommand(
                        command_id=payload.command_id,
                        expected_revision=payload.expected_revision,
                        world=world,
                    )
                elif isinstance(payload, WorldRenameRequest):
                    command = WorldRenameCommand(**payload.model_dump())
                else:
                    command = WorldArchiveCommand(**payload.model_dump())
                result = transaction.execute(command)
                updated_dashboard = dashboard(transaction.snapshot())
            if world_manager is not None:
                world_manager.prune()
            return WorldDashboardMutationResponse(
                receipt=result.receipt, replayed=result.replayed, dashboard=updated_dashboard
            )

    @app.post(_ROOT + "/worlds/create")
    async def create_world(request: Request) -> WorldDashboardMutationResponse:
        return await mutate(request, WorldCreateRequest)

    @app.post(_ROOT + "/worlds/rename")
    async def rename_world(request: Request) -> WorldDashboardMutationResponse:
        return await mutate(request, WorldRenameRequest)

    @app.post(_ROOT + "/worlds/archive")
    async def archive_world(request: Request) -> WorldDashboardMutationResponse:
        return await mutate(request, WorldArchiveRequest)
