"""Minimal FastAPI JSON gateway for one durable VTT session."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

from dnd_sim.interactive.session import EngineSessionError

from .access import TableAccessError, TableAccessPolicy
from .annotation_api import (
    ANNOTATION_PROTECTED_ROUTES,
    AnnotationAPIError,
    install_annotation_routes,
)
from .annotation_store import SQLiteAnnotationBoard
from .chat_api import CHAT_PROTECTED_ROUTES, ChatAPIError, install_chat_routes
from .chat_store import SQLiteChatLog
from .contracts import (
    VTTCommand,
    VTTCommitResponse,
    VTTEvent,
    VTTPreviewResponse,
    VTTResponse,
    VTTVersionInfo,
)
from .event_store import CommandConflictError, EventStoreError
from .participants import (
    PARTICIPANT_SCHEMA_VERSION,
    ROSTER_SCHEMA_VERSION,
    TableParticipant,
    TableRoster,
    audience_allows,
)
from .presence_api import (
    PRESENCE_PROTECTED_ROUTES,
    EpochMillisecondsClock,
    PresenceAPIError,
    install_presence_routes,
    system_epoch_ms,
)
from .presence_store import SQLitePresenceStore
from .scene import SquareGridScene
from .scene_library_api import (
    SCENE_LIBRARY_PROTECTED_ROUTES,
    SceneLibraryAPIError,
    install_scene_library_routes,
)
from .scene_library_store import SQLiteSceneLibrary
from .session_service import VTTSessionService, VTTSessionServiceError

VTT_SESSION_VIEW_SCHEMA_VERSION = "vtt.session_view.v1"
VTT_TABLE_VIEW_SCHEMA_VERSION = "vtt.table_view.v1"
VTT_ERROR_SCHEMA_VERSION = "vtt.error.v1"
OPEN_LOCAL_PARTICIPANT_ID = "local"
DEFAULT_VTT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:3000",
    "http://localhost:3000",
)
SSE_POLL_INTERVAL_SECONDS = 0.25
SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0
_PROTECTED_TABLE_ROUTES = frozenset(
    {
        ("GET", "/api/v1/session"),
        ("GET", "/api/v1/table"),
        ("GET", "/api/v1/events"),
        ("POST", "/api/v1/commands"),
    }
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


class VTTTableView(_StrictHTTPModel):
    """Credential-free identity and participant directory for one table."""

    schema_version: Literal[VTT_TABLE_VIEW_SCHEMA_VERSION] = VTT_TABLE_VIEW_SCHEMA_VERSION
    access_mode: Literal["open_local", "protected"]
    table_id: str
    current_participant: TableParticipant
    participants: tuple[TableParticipant, ...]

    @field_validator("participants", mode="before")
    @classmethod
    def normalize_participants(cls, value: Any) -> tuple[Any, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("participants must be an ordered list or tuple")
        return tuple(value)

    @model_validator(mode="after")
    def validate_directory(self) -> "VTTTableView":
        roster = TableRoster(
            schema_version=ROSTER_SCHEMA_VERSION,
            table_id=self.table_id,
            participants=self.participants,
        )
        canonical_current = roster.participant(self.current_participant.participant_id)
        if canonical_current != self.current_participant:
            raise ValueError("current_participant must match its participant-directory entry")

        if self.access_mode == "open_local":
            expected_local = _open_local_participant()
            if self.current_participant != expected_local or self.participants != (expected_local,):
                raise ValueError(
                    "an open_local table must expose only the synthetic local participant"
                )
        return self


def _open_local_participant() -> TableParticipant:
    """Return the synthetic authority matching existing open-local mutation ownership."""

    return TableParticipant(
        schema_version=PARTICIPANT_SCHEMA_VERSION,
        participant_id=OPEN_LOCAL_PARTICIPANT_ID,
        display_name="Local GM",
        role="gm",
        owned_actor_ids=(),
    )


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


class VTTEventCursorError(ValueError):
    """Raised when a reconnect cursor is not a canonical non-negative integer."""

    def __init__(self, field: str) -> None:
        super().__init__(f"{field} must be a canonical non-negative integer")
        self.field = field


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, JsonValue] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    error = VTTError(
        code=code,
        message=message,
        details={} if details is None else details,
    )
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(mode="json"),
        headers=headers,
    )


def _access_error_response(exc: TableAccessError) -> JSONResponse:
    if exc.code == "authentication_required":
        return _error_response(
            status_code=401,
            code=exc.code,
            message=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _error_response(
        status_code=403,
        code=exc.code,
        message=str(exc),
    )


class _TableAuthenticationMiddleware:
    """Authenticate protected routes before FastAPI reads a request body."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        access_policy: TableAccessPolicy,
        protected_routes: frozenset[tuple[str, str]] = _PROTECTED_TABLE_ROUTES,
    ) -> None:
        self._app = app
        self._access_policy = access_policy
        self._protected_routes = protected_routes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or (str(scope.get("method", "")), str(scope.get("path", "")))
            not in self._protected_routes
        ):
            await self._app(scope, receive, send)
            return

        authorization_values = Headers(scope=scope).getlist("authorization")
        authorization = authorization_values[0] if len(authorization_values) == 1 else None
        try:
            participant = self._access_policy.authenticate(authorization)
        except TableAccessError as exc:
            await _access_error_response(exc)(scope, receive, send)
            return

        scope.setdefault("state", {})["vtt_participant"] = participant
        await self._app(scope, receive, send)


def _request_participant(request: Request) -> TableParticipant | None:
    """Return the principal installed by the authentication middleware."""

    policy = getattr(request.app.state, "vtt_access_policy", None)
    if policy is None:
        return None
    if not isinstance(policy, TableAccessPolicy):
        raise RuntimeError("the configured VTT access policy is invalid")
    participant = getattr(request.state, "vtt_participant", None)
    if not isinstance(participant, TableParticipant):
        raise RuntimeError("a protected VTT request is missing its principal")
    return participant


def _audience_is_visible(
    audience: tuple[str, ...],
    participant: TableParticipant | None,
) -> bool:
    if participant is None:
        return True
    try:
        return audience_allows(audience, participant)
    except (TypeError, ValueError):
        # Unknown/legacy audience syntax is never safe to expose from a
        # protected table. Explicit selectors are the only supported policy.
        return False


def _filter_response_events(
    response: VTTResponse,
    participant: TableParticipant | None,
) -> VTTResponse:
    if participant is None:
        return response
    visible_events = tuple(
        event for event in response.events if _audience_is_visible(event.audience, participant)
    )
    if isinstance(response, VTTPreviewResponse):
        return VTTPreviewResponse.model_validate(
            {
                **response.model_dump(mode="json"),
                "events": [event.model_dump(mode="json") for event in visible_events],
            }
        )
    return VTTCommitResponse.model_validate(
        {
            **response.model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in visible_events],
            "first_sequence": (visible_events[0].sequence if visible_events else None),
            "last_sequence": (visible_events[-1].sequence if visible_events else None),
        }
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


def _event_cursor(value: str | None, *, field: str) -> int | None:
    if value is None:
        return None
    if not value or any(character not in "0123456789" for character in value):
        raise VTTEventCursorError(field)
    try:
        cursor = int(value)
    except (ValueError, OverflowError) as exc:
        raise VTTEventCursorError(field) from exc
    if str(cursor) != value:
        raise VTTEventCursorError(field)
    return cursor


def _resume_after(*, after: str | None, last_event_id: str | None) -> int:
    query_cursor = _event_cursor(after, field="after")
    header_cursor = _event_cursor(last_event_id, field="Last-Event-ID")
    return max(cursor for cursor in (0, query_cursor, header_cursor) if cursor is not None)


def _render_sse_event(event: VTTEvent) -> str:
    payload = json.dumps(
        event.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"id: {event.sequence}\nevent: vtt.event\ndata: {payload}\n\n"


async def _stream_events(
    *,
    request: Request,
    service: VTTSessionService,
    after: int,
    participant: TableParticipant | None,
) -> AsyncIterator[str]:
    cursor = after
    event_loop = asyncio.get_running_loop()
    next_heartbeat = event_loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS

    while True:
        if await request.is_disconnected():
            return

        events = service.events_after(cursor)
        if events:
            yielded_visible_event = False
            for event in events:
                if await request.is_disconnected():
                    return
                cursor = event.sequence
                if not _audience_is_visible(event.audience, participant):
                    continue
                yield _render_sse_event(event)
                yielded_visible_event = True
            if yielded_visible_event:
                next_heartbeat = event_loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
        elif event_loop.time() >= next_heartbeat:
            yield ": heartbeat\n\n"
            next_heartbeat = event_loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS

        await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)


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
    access_policy: TableAccessPolicy | None = None,
    annotation_board: SQLiteAnnotationBoard | None = None,
    annotation_table_id: str | None = None,
    chat_log: SQLiteChatLog | None = None,
    chat_table_id: str | None = None,
    scene_library: SQLiteSceneLibrary | None = None,
    scene_library_table_id: str | None = None,
    presence_store: SQLitePresenceStore | None = None,
    presence_epoch_ms_clock: EpochMillisecondsClock | None = None,
) -> FastAPI:
    """Create a JSON-only VTT app around one already-owned session service."""

    if not isinstance(service, VTTSessionService):
        raise TypeError("service must be a VTTSessionService")
    if scene is not None and not isinstance(scene, SquareGridScene):
        raise TypeError("scene must be a SquareGridScene or None")
    if access_policy is not None and not isinstance(access_policy, TableAccessPolicy):
        raise TypeError("access_policy must be a TableAccessPolicy or None")
    if annotation_board is not None and not isinstance(annotation_board, SQLiteAnnotationBoard):
        raise TypeError("annotation_board must be a SQLiteAnnotationBoard or None")
    if annotation_board is None and annotation_table_id is not None:
        raise ValueError("annotation_table_id requires an annotation_board")
    if annotation_board is not None and scene is None:
        raise ValueError("annotation_board requires a configured scene")
    if chat_log is not None and not isinstance(chat_log, SQLiteChatLog):
        raise TypeError("chat_log must be a SQLiteChatLog or None")
    if chat_log is None and chat_table_id is not None:
        raise ValueError("chat_table_id requires a chat_log")
    if scene_library is not None and not isinstance(scene_library, SQLiteSceneLibrary):
        raise TypeError("scene_library must be a SQLiteSceneLibrary or None")
    if scene_library is None and scene_library_table_id is not None:
        raise ValueError("scene_library_table_id requires a scene_library")
    if presence_store is not None and not isinstance(presence_store, SQLitePresenceStore):
        raise TypeError("presence_store must be a SQLitePresenceStore or None")
    if presence_store is None and presence_epoch_ms_clock is not None:
        raise ValueError("presence_epoch_ms_clock requires a presence_store")
    configured_scene = None if scene is None else scene.model_copy(deep=True)
    configured_origins = _validate_allowed_origins(allowed_origins)
    configured_annotation_table_id: str | None = None
    if annotation_board is not None:
        configured_annotation_table_id = annotation_table_id
        if configured_annotation_table_id is None:
            configured_annotation_table_id = (
                access_policy.roster.table_id if access_policy is not None else service.session_id
            )
        if (
            access_policy is not None
            and configured_annotation_table_id != access_policy.roster.table_id
        ):
            raise ValueError("annotation_table_id must match the access-policy table")
    configured_chat_table_id: str | None = None
    if chat_log is not None:
        configured_chat_table_id = chat_table_id
        if configured_chat_table_id is None:
            configured_chat_table_id = (
                access_policy.roster.table_id if access_policy is not None else service.session_id
            )
        if access_policy is not None and configured_chat_table_id != access_policy.roster.table_id:
            raise ValueError("chat_table_id must match the access-policy table")
    configured_scene_library_table_id: str | None = None
    if scene_library is not None:
        configured_scene_library_table_id = scene_library_table_id
        if configured_scene_library_table_id is None:
            configured_scene_library_table_id = (
                access_policy.roster.table_id if access_policy is not None else service.session_id
            )
        if (
            access_policy is not None
            and configured_scene_library_table_id != access_policy.roster.table_id
        ):
            raise ValueError("scene_library_table_id must match the access-policy table")
    configured_presence_clock: EpochMillisecondsClock | None = None
    if presence_store is not None:
        if access_policy is not None:
            if presence_store.roster != access_policy.roster:
                raise ValueError("presence_store must match the access-policy roster")
        else:
            local_participant = _open_local_participant()
            local_roster = TableRoster(
                schema_version=ROSTER_SCHEMA_VERSION,
                table_id=service.session_id,
                participants=(local_participant,),
            )
            if presence_store.roster != local_roster:
                raise ValueError("presence_store must match the open-local roster")
        configured_presence_clock = (
            system_epoch_ms if presence_epoch_ms_clock is None else presence_epoch_ms_clock
        )
        if not callable(configured_presence_clock):
            raise TypeError("presence_epoch_ms_clock must be callable")

    app = FastAPI(title="dnd-sim VTT API", version="1")
    app.state.vtt_access_policy = access_policy
    app.state.vtt_annotation_board = annotation_board
    app.state.vtt_chat_log = chat_log
    app.state.vtt_scene_library = scene_library
    app.state.vtt_presence_store = presence_store
    if access_policy is not None:
        protected_routes = set(_PROTECTED_TABLE_ROUTES)
        if annotation_board is not None:
            protected_routes.update(ANNOTATION_PROTECTED_ROUTES)
        if chat_log is not None:
            protected_routes.update(CHAT_PROTECTED_ROUTES)
        if scene_library is not None:
            protected_routes.update(SCENE_LIBRARY_PROTECTED_ROUTES)
        if presence_store is not None:
            protected_routes.update(PRESENCE_PROTECTED_ROUTES)
        app.add_middleware(
            _TableAuthenticationMiddleware,
            access_policy=access_policy,
            protected_routes=frozenset(protected_routes),
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configured_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["authorization", "content-type"],
    )

    @app.exception_handler(TableAccessError)
    async def table_access_error(
        _request: Request,
        exc: TableAccessError,
    ) -> JSONResponse:
        return _access_error_response(exc)

    @app.exception_handler(AnnotationAPIError)
    async def annotation_api_error(
        _request: Request,
        exc: AnnotationAPIError,
    ) -> JSONResponse:
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(ChatAPIError)
    async def chat_api_error(
        _request: Request,
        exc: ChatAPIError,
    ) -> JSONResponse:
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(SceneLibraryAPIError)
    async def scene_library_api_error(
        _request: Request,
        exc: SceneLibraryAPIError,
    ) -> JSONResponse:
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(PresenceAPIError)
    async def presence_api_error(
        _request: Request,
        exc: PresenceAPIError,
    ) -> JSONResponse:
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
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

    @app.exception_handler(VTTEventCursorError)
    async def event_cursor_error(
        _request: Request,
        exc: VTTEventCursorError,
    ) -> JSONResponse:
        return _error_response(
            status_code=400,
            code="invalid_event_cursor",
            message="The event cursor must be a canonical non-negative integer.",
            details={"field": exc.field},
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

    @app.get("/api/v1/table", response_model=VTTTableView)
    async def get_table(request: Request) -> VTTTableView:
        participant = _request_participant(request)
        if participant is None:
            local_participant = _open_local_participant()
            return VTTTableView(
                access_mode="open_local",
                table_id=service.session_id,
                current_participant=local_participant,
                participants=(local_participant,),
            )

        if access_policy is None:  # pragma: no cover - guarded by _request_participant
            raise RuntimeError("a protected table view is missing its access policy")
        roster = access_policy.roster
        return VTTTableView(
            access_mode="protected",
            table_id=roster.table_id,
            current_participant=participant,
            participants=roster.participants,
        )

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

    @app.get("/api/v1/events", response_class=StreamingResponse)
    async def get_events(
        request: Request,
        after: Annotated[str | None, Query()] = None,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        participant = _request_participant(request)
        cursor = _resume_after(
            after=after,
            last_event_id=last_event_id,
        )
        return StreamingResponse(
            _stream_events(
                request=request,
                service=service,
                after=cursor,
                participant=participant,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post(
        "/api/v1/commands",
        response_model=VTTPreviewResponse | VTTCommitResponse,
    )
    async def execute_command(
        command: VTTCommand,
        request: Request,
    ) -> VTTResponse:
        participant = _request_participant(request)
        if access_policy is not None:
            if participant is None:
                raise RuntimeError("a protected command is missing its principal")
            access_policy.authorize_command(participant, command)
        return _filter_response_events(service.execute(command), participant)

    if annotation_board is not None:
        if configured_scene is None or configured_annotation_table_id is None:
            raise RuntimeError("annotation route configuration was not normalized")
        install_annotation_routes(
            app,
            board=annotation_board,
            session_id=service.session_id,
            table_id=configured_annotation_table_id,
            scene=configured_scene,
            access_policy=access_policy,
        )

    if chat_log is not None:
        if configured_chat_table_id is None:
            raise RuntimeError("chat route configuration was not normalized")
        install_chat_routes(
            app,
            log=chat_log,
            session_id=service.session_id,
            table_id=configured_chat_table_id,
            access_policy=access_policy,
        )

    if scene_library is not None:
        if configured_scene_library_table_id is None:
            raise RuntimeError("scene-library route configuration was not normalized")
        install_scene_library_routes(
            app,
            library=scene_library,
            session_id=service.session_id,
            table_id=configured_scene_library_table_id,
            access_policy=access_policy,
        )

    if presence_store is not None:
        if configured_presence_clock is None:
            raise RuntimeError("presence route configuration was not normalized")
        install_presence_routes(
            app,
            store=presence_store,
            session_id=service.session_id,
            table_id=presence_store.table_id,
            access_policy=access_policy,
            epoch_ms_clock=configured_presence_clock,
        )

    return app


__all__ = [
    "DEFAULT_VTT_ALLOWED_ORIGINS",
    "OPEN_LOCAL_PARTICIPANT_ID",
    "VTT_ERROR_SCHEMA_VERSION",
    "VTT_SESSION_VIEW_SCHEMA_VERSION",
    "VTT_TABLE_VIEW_SCHEMA_VERSION",
    "VTTError",
    "VTTSessionView",
    "VTTTableView",
    "create_vtt_app",
]
