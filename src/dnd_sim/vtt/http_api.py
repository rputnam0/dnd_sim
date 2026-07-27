"""Minimal FastAPI JSON gateway for one durable VTT session."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from dnd_sim.interactive.session import EngineSessionError

from .contracts import (
    VTTCommand,
    VTTCommitResponse,
    VTTPreviewResponse,
    VTTResponse,
    VTTVersionInfo,
)
from .event_store import CommandConflictError, EventStoreError
from .scene import SquareGridScene
from .session_service import VTTSessionService, VTTSessionServiceError

VTT_SESSION_VIEW_SCHEMA_VERSION = "vtt.session_view.v1"
VTT_ERROR_SCHEMA_VERSION = "vtt.error.v1"
DEFAULT_VTT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:3000",
    "http://localhost:3000",
)

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]

_ENGINE_CONFLICT_CODES = frozenset(
    {
        "command_id_conflict",
        "encounter_already_started",
        "encounter_complete",
        "pending_reaction",
        "actor_mismatch",
        "session_id_mismatch",
        "stale_revision",
        "turn_not_prepared",
        "turn_already_prepared",
        "turn_complete",
        "version_mismatch",
    }
)
_ENGINE_INTERNAL_CODES = frozenset(
    {
        "driver_failure",
        "invalid_driver_versions",
        "invalid_projection",
        "invalid_state",
        "projection_unsupported",
    }
)


class _StrictHTTPModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class VTTSessionView(_StrictHTTPModel):
    """The client-safe read model for the currently open VTT session."""

    schema_version: Literal[VTT_SESSION_VIEW_SCHEMA_VERSION] = VTT_SESSION_VIEW_SCHEMA_VERSION
    session_id: str
    revision: NonNegativeInt
    versions: VTTVersionInfo
    scene: SquareGridScene | None
    projection: dict[str, JsonValue]

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("session_id must not be empty")
        return normalized


class VTTError(_StrictHTTPModel):
    """Stable error envelope returned by every HTTP failure path."""

    schema_version: Literal[VTT_ERROR_SCHEMA_VERSION] = VTT_ERROR_SCHEMA_VERSION
    code: str
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("code", "message")
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{info.field_name} must not be empty")
        return normalized


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, JsonValue] | None = None,
) -> JSONResponse:
    error = VTTError(
        code=code,
        message=message,
        details={} if details is None else details,
    )
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(mode="json"),
    )


def _validation_issues(exc: RequestValidationError) -> list[JsonValue]:
    issues: list[JsonValue] = []
    for error in exc.errors():
        location = [
            part if isinstance(part, (str, int)) else str(part) for part in error.get("loc", ())
        ]
        issues.append(
            {
                "location": location,
                "code": str(error.get("type", "invalid")),
                "message": str(error.get("msg", "Invalid request value")),
            }
        )
    return issues


def _validate_allowed_origins(origins: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(origins, tuple):
        raise TypeError("allowed_origins must be a tuple")
    validated: list[str] = []
    for origin in origins:
        if not isinstance(origin, str) or not origin:
            raise ValueError("allowed origins must be non-empty strings")
        if origin == "*":
            raise ValueError("wildcard CORS origins are not allowed")
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(f"allowed origin '{origin}' must be an exact HTTP origin")
        if origin in validated:
            raise ValueError(f"allowed origin '{origin}' is duplicated")
        validated.append(origin)
    return tuple(validated)


def create_vtt_app(
    service: VTTSessionService,
    *,
    scene: SquareGridScene | None = None,
    allowed_origins: tuple[str, ...] = DEFAULT_VTT_ALLOWED_ORIGINS,
) -> FastAPI:
    """Create a JSON-only VTT app around one already-owned session service."""

    if not isinstance(service, VTTSessionService):
        raise TypeError("service must be a VTTSessionService")
    if scene is not None and not isinstance(scene, SquareGridScene):
        raise TypeError("scene must be a SquareGridScene or None")
    configured_scene = None if scene is None else scene.model_copy(deep=True)
    configured_origins = _validate_allowed_origins(allowed_origins)

    app = FastAPI(title="dnd-sim VTT API", version="1")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configured_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
    )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            status_code=422,
            code="invalid_request",
            message="The request does not match the VTT command contract.",
            details={"issues": _validation_issues(exc)},
        )

    @app.exception_handler(VTTSessionServiceError)
    async def session_service_error(
        _request: Request,
        _exc: VTTSessionServiceError,
    ) -> JSONResponse:
        return _error_response(
            status_code=409,
            code="session_mismatch",
            message="The command belongs to a different VTT session.",
            details={"expected_session_id": service.session_id},
        )

    @app.exception_handler(CommandConflictError)
    async def command_conflict_error(
        _request: Request,
        _exc: CommandConflictError,
    ) -> JSONResponse:
        return _error_response(
            status_code=409,
            code="command_id_conflict",
            message="The command ID is already committed with different content.",
        )

    @app.exception_handler(EngineSessionError)
    async def engine_session_error(
        _request: Request,
        exc: EngineSessionError,
    ) -> JSONResponse:
        if exc.code in _ENGINE_CONFLICT_CODES:
            status_code = 409
        elif exc.code in _ENGINE_INTERNAL_CODES:
            status_code = 500
        else:
            status_code = 400
        return _error_response(
            status_code=status_code,
            code=exc.code,
            message=str(exc),
            details=exc.details,
        )

    @app.exception_handler(EventStoreError)
    async def event_store_error(
        _request: Request,
        _exc: EventStoreError,
    ) -> JSONResponse:
        return _error_response(
            status_code=503,
            code="storage_unavailable",
            message="The VTT session could not be persisted.",
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(
        _request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        code = {
            404: "not_found",
            405: "method_not_allowed",
        }.get(exc.status_code, "http_error")
        return _error_response(
            status_code=exc.status_code,
            code=code,
            message=str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def unexpected_error(
        _request: Request,
        _exc: Exception,
    ) -> JSONResponse:
        return _error_response(
            status_code=500,
            code="internal_error",
            message="The VTT request could not be completed.",
        )

    @app.get("/healthz", response_model=dict[str, str])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/session", response_model=VTTSessionView)
    async def get_session() -> VTTSessionView:
        session = service.read_view()
        return VTTSessionView(
            session_id=session.session_id,
            revision=session.revision,
            versions=session.versions,
            scene=configured_scene,
            projection=session.projection,
        )

    @app.post(
        "/api/v1/commands",
        response_model=VTTPreviewResponse | VTTCommitResponse,
    )
    async def execute_command(command: VTTCommand) -> VTTResponse:
        return service.execute(command)

    return app


__all__ = [
    "DEFAULT_VTT_ALLOWED_ORIGINS",
    "VTT_ERROR_SCHEMA_VERSION",
    "VTT_SESSION_VIEW_SCHEMA_VERSION",
    "VTTError",
    "VTTSessionView",
    "create_vtt_app",
]
