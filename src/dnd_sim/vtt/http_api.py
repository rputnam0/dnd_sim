"""Minimal FastAPI JSON gateway for one durable VTT session."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import AsyncIterator, Callable
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
from dnd_sim.interactive.dnd_turn_driver import TRUSTED_BOARD_MOVEMENT_DISTANCE_KEY
from dnd_sim.roll_journal import AuthoritativeRollRecord

from .access import TableAccessError, TableAccessPolicy
from .active_board import ActiveBoardProjection, resolve_active_board
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
from .map_asset_api import (
    MAP_ASSET_PROTECTED_ROUTES,
    MAP_ASSET_PROTECTED_ROUTE_PREFIXES,
    MapAssetAPIError,
    install_map_asset_routes,
)
from .map_asset_store import SQLiteMapAssetStore
from .journal_api import JOURNAL_PROTECTED_ROUTES, JournalAPIError, install_journal_routes
from .journal_store import SQLiteJournalStore
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
from .presentation_api import (
    PRESENTATION_PROTECTED_ROUTE_PREFIXES,
    PRESENTATION_PROTECTED_ROUTES,
    PresentationAPIError,
    install_presentation_routes,
)
from .presentation_store import SQLitePresentationStore
from .roll_cards import project_roll_card
from .scene import FeetPosition, SquareGridScene
from .scene_library_api import (
    SCENE_LIBRARY_PROTECTED_ROUTES,
    SceneLibraryAPIError,
    install_scene_library_routes,
)
from .scene_library_store import SQLiteSceneLibrary
from .session_service import VTTSessionService, VTTSessionServiceError
from .token_api import (
    TOKEN_PROTECTED_ROUTES,
    TokenAPIError,
    hidden_engine_actor_values_for_tokens,
    install_token_routes,
    project_engine_projection_for_tokens,
)
from .token_store import SQLiteTokenStore
from .visibility_api import (
    VISIBILITY_PROTECTED_ROUTES,
    VisibilityAPIError,
    current_movement_path_is_blocked,
    install_visibility_routes,
    project_current_visibility,
)
from .visibility_store import SQLiteVisibilityStore

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
    active_board: ActiveBoardProjection | None
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


class VTTBoardMovementError(ValueError):
    """A stable rejection raised before a board-invalid engine command executes."""

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _trusted_board_movement_metadata(
    command: VTTCommand,
    *,
    active_board: ActiveBoardProjection | None,
    projection: dict[str, JsonValue],
) -> dict[str, JsonValue] | None:
    if (
        active_board is None
        or active_board.map_metadata.calibration.topology not in {"hex_flat", "hex_pointy"}
        or command.kind != "dnd.declare_turn.v1"
        or command.mode not in {"preview", "commit"}
    ):
        return None
    path = command.payload.get("movement_path")
    if not isinstance(path, list):
        return None
    calibration = active_board.map_metadata.calibration
    origin = FeetPosition(
        x_ft=active_board.scene.origin_ft.x_ft + calibration.distance_ft / 2.0,
        y_ft=active_board.scene.origin_ft.y_ft + calibration.distance_ft / 2.0,
        z_ft=active_board.scene.origin_ft.z_ft,
    )
    cells = []
    path_elevation_ft: float | None = None
    for waypoint in path:
        if (
            not isinstance(waypoint, list)
            or len(waypoint) != 3
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in waypoint
            )
        ):
            return None
        position = FeetPosition(
            x_ft=float(waypoint[0]),
            y_ft=float(waypoint[1]),
            z_ft=float(waypoint[2]),
        )
        if path_elevation_ft is None:
            path_elevation_ft = position.z_ft
        elif not math.isclose(
            position.z_ft,
            path_elevation_ft,
            rel_tol=0.0,
            abs_tol=1e-6,
        ):
            raise VTTBoardMovementError(
                code="board_movement_elevation_changed",
                message="Calibrated hex movement must stay on one elevation.",
            )
        cell = calibration.feet_to_cell(position, origin_ft=origin)
        center = calibration.cell_to_feet(cell, origin_ft=origin)
        if not math.isclose(center.x_ft, position.x_ft, abs_tol=1e-6) or not math.isclose(
            center.y_ft, position.y_ft, abs_tol=1e-6
        ):
            raise VTTBoardMovementError(
                code="board_movement_not_cell_centered",
                message="Hex movement waypoints must use calibrated cell centers.",
            )
        if not calibration.cell_is_complete(
            cell,
            width_px=active_board.map_metadata.width_px,
            height_px=active_board.map_metadata.height_px,
        ):
            raise VTTBoardMovementError(
                code="board_movement_out_of_bounds",
                message="The movement path leaves the authoritative board.",
            )
        cells.append(cell)
    distance_ft = sum(
        calibration.cell_distance_ft(cells[index - 1], cells[index])
        for index in range(1, len(cells))
    )
    actors = projection.get("actors")
    actor = actors.get(command.actor_id) if isinstance(actors, dict) else None
    remaining = actor.get("movement_remaining") if isinstance(actor, dict) else None
    if (
        isinstance(remaining, (int, float))
        and not isinstance(remaining, bool)
        and math.isfinite(float(remaining))
        and distance_ft > float(remaining) + 1e-6
    ):
        raise VTTBoardMovementError(
            code="board_movement_exceeds_budget",
            message="The calibrated board path exceeds the actor's remaining movement.",
        )
    return {TRUSTED_BOARD_MOVEMENT_DISTANCE_KEY: float(distance_ft)}


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
        protected_route_prefixes: frozenset[tuple[str, str]] = frozenset(),
    ) -> None:
        self._app = app
        self._access_policy = access_policy
        self._protected_routes = protected_routes
        self._protected_route_prefixes = protected_route_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        method = str(scope.get("method", ""))
        path = str(scope.get("path", ""))
        protected = (method, path) in self._protected_routes or any(
            method == prefix_method and path.startswith(prefix)
            for prefix_method, prefix in self._protected_route_prefixes
        )
        if scope["type"] != "http" or not protected:
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
    *,
    hidden_actor_values: frozenset[str] = frozenset(),
) -> VTTResponse:
    visible_events = []
    for event in response.events:
        projected = _project_event_for_participant(
            event,
            participant=participant,
            hidden_actor_values=hidden_actor_values,
        )
        if projected is None:
            continue
        visible_events.append(projected)
    visible_events_tuple = tuple(visible_events)
    if isinstance(response, VTTPreviewResponse):
        return VTTPreviewResponse.model_validate(
            {
                **response.model_dump(mode="json"),
                "events": [event.model_dump(mode="json") for event in visible_events_tuple],
            }
        )
    return VTTCommitResponse.model_validate(
        {
            **response.model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in visible_events_tuple],
            "first_sequence": (visible_events_tuple[0].sequence if visible_events_tuple else None),
            "last_sequence": (visible_events_tuple[-1].sequence if visible_events_tuple else None),
        }
    )


_COMBAT_TRACKER_AUDIT_EVENT_KINDS = frozenset(
    {
        "dnd.encounter.cursor_overridden",
        "dnd.encounter.initiative_overridden",
        "dnd.encounter.actor_delayed",
    }
)


def _project_event_for_participant(
    event: Any,
    *,
    participant: TableParticipant | None,
    hidden_actor_values: frozenset[str],
):
    projected = _project_roll_event(
        event,
        participant=participant,
        hidden_actor_values=hidden_actor_values,
    )
    if projected is None or not _audience_is_visible(projected.audience, participant):
        return None
    if not _json_contains_any(projected.payload, hidden_actor_values):
        return projected
    if projected.kind not in _COMBAT_TRACKER_AUDIT_EVENT_KINDS:
        return None
    return type(projected).model_validate(
        {
            **projected.model_dump(mode="json"),
            "kind": "vtt.encounter.changed.v1",
            "audience": ["all"],
            "payload": {},
        }
    )


def _project_roll_event(
    event: Any,
    *,
    participant: TableParticipant | None,
    hidden_actor_values: frozenset[str],
):
    if event.kind != "dnd.roll.recorded.v1":
        return event
    if set(event.payload) != {"record"}:
        return None
    try:
        record = AuthoritativeRollRecord.model_validate(event.payload["record"])
        card = project_roll_card(
            record,
            participant=participant,
            hidden_actor_values=hidden_actor_values,
        )
    except (TypeError, ValueError):
        return None
    if card is None:
        return None
    return type(event).model_validate(
        {
            **event.model_dump(mode="json"),
            "kind": "vtt.roll.card.v1",
            "audience": ["all"],
            "payload": {"card": card.model_dump(mode="json")},
        }
    )


def _json_contains_any(value: JsonValue, protected_values: frozenset[str]) -> bool:
    if not protected_values:
        return False
    if isinstance(value, str):
        return value in protected_values
    if isinstance(value, list):
        return any(_json_contains_any(item, protected_values) for item in value)
    if isinstance(value, dict):
        return any(
            key in protected_values or _json_contains_any(item, protected_values)
            for key, item in value.items()
        )
    return False


def _reject_unprojected_token_command(
    command: VTTCommand,
    *,
    projection: dict[str, JsonValue],
    hidden_actor_values: frozenset[str],
) -> None:
    """Prevent a protected client from hand-addressing actors absent from its view."""

    actors = projection.get("actors")
    visible_actor_ids = set(actors) if isinstance(actors, dict) else set()
    if command.actor_id is not None and command.actor_id not in visible_actor_ids:
        raise TableAccessError(
            "command_target_not_visible",
            "This participant is not permitted to issue the command.",
        )
    if _json_contains_any(command.payload, hidden_actor_values) or _json_contains_any(
        command.intent_metadata,
        hidden_actor_values,
    ):
        raise TableAccessError(
            "command_target_not_visible",
            "This participant is not permitted to issue the command.",
        )
    if command.kind != "dnd.declare_turn.v1":
        return
    choices = projection.get("choices")
    if not isinstance(choices, dict):
        return
    raw_choices = choices.get("actions")
    if not isinstance(raw_choices, list):
        return
    selectable_by_action = {
        choice.get("action_name"): set(choice.get("selectable_target_ids", []))
        for choice in raw_choices
        if isinstance(choice, dict)
        and isinstance(choice.get("action_name"), str)
        and isinstance(choice.get("selectable_target_ids"), list)
    }
    for field in ("action", "bonus_action"):
        declaration = command.payload.get(field)
        if not isinstance(declaration, dict):
            continue
        action_name = declaration.get("action_name")
        targets = declaration.get("targets")
        if not isinstance(action_name, str) or not isinstance(targets, list):
            continue
        selectable = selectable_by_action.get(action_name)
        if selectable is None:
            continue
        for target in targets:
            if isinstance(target, dict) and target.get("actor_id") not in selectable:
                raise TableAccessError(
                    "command_target_not_visible",
                    "This participant is not permitted to issue the command.",
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
    token_store: SQLiteTokenStore | None,
    token_table_id: str | None,
    active_scene_id: Callable[[], str | None],
    visibility_actor_ids: Callable[[TableParticipant | None], frozenset[str] | None],
) -> AsyncIterator[str]:
    cursor = after
    event_loop = asyncio.get_running_loop()
    next_heartbeat = event_loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS

    while True:
        if await request.is_disconnected():
            return

        events = service.events_after(cursor)
        if events:
            hidden_actor_values = frozenset()
            if token_store is not None:
                resolved_scene_id = active_scene_id()
                if token_table_id is None or resolved_scene_id is None:
                    raise RuntimeError("token event projection configuration was not normalized")
                hidden_actor_values = hidden_engine_actor_values_for_tokens(
                    service.read_view().projection,
                    store=token_store,
                    table_id=token_table_id,
                    scene_id=resolved_scene_id,
                    participant=participant,
                    visibility_actor_ids=visibility_actor_ids(participant),
                )
            yielded_visible_event = False
            for event in events:
                if await request.is_disconnected():
                    return
                cursor = event.sequence
                projected = _project_event_for_participant(
                    event,
                    participant=participant,
                    hidden_actor_values=hidden_actor_values,
                )
                if projected is None:
                    continue
                yield _render_sse_event(projected)
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
    journal_store: SQLiteJournalStore | None = None,
    journal_table_id: str | None = None,
    scene_library: SQLiteSceneLibrary | None = None,
    scene_library_table_id: str | None = None,
    map_asset_store: SQLiteMapAssetStore | None = None,
    map_asset_table_id: str | None = None,
    token_store: SQLiteTokenStore | None = None,
    token_table_id: str | None = None,
    visibility_store: SQLiteVisibilityStore | None = None,
    visibility_table_id: str | None = None,
    presence_store: SQLitePresenceStore | None = None,
    presence_epoch_ms_clock: EpochMillisecondsClock | None = None,
    presentation_store: SQLitePresentationStore | None = None,
    presentation_table_id: str | None = None,
    presentation_epoch_ms_clock: EpochMillisecondsClock | None = None,
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
    if journal_store is not None and not isinstance(journal_store, SQLiteJournalStore):
        raise TypeError("journal_store must be a SQLiteJournalStore or None")
    if journal_store is None and journal_table_id is not None:
        raise ValueError("journal_table_id requires a journal_store")
    if journal_store is not None and scene is None:
        raise ValueError("journal_store requires a configured scene")
    if scene_library is not None and not isinstance(scene_library, SQLiteSceneLibrary):
        raise TypeError("scene_library must be a SQLiteSceneLibrary or None")
    if scene_library is None and scene_library_table_id is not None:
        raise ValueError("scene_library_table_id requires a scene_library")
    if map_asset_store is not None and not isinstance(map_asset_store, SQLiteMapAssetStore):
        raise TypeError("map_asset_store must be a SQLiteMapAssetStore or None")
    if map_asset_store is None and map_asset_table_id is not None:
        raise ValueError("map_asset_table_id requires a map_asset_store")
    if map_asset_store is not None and scene_library is None:
        raise ValueError("map_asset_store requires a scene_library")
    if token_store is not None and not isinstance(token_store, SQLiteTokenStore):
        raise TypeError("token_store must be a SQLiteTokenStore or None")
    if token_store is None and token_table_id is not None:
        raise ValueError("token_table_id requires a token_store")
    if token_store is not None and scene_library is None:
        raise ValueError("token_store requires a scene_library")
    if token_store is not None and scene is None:
        raise ValueError("token_store requires a configured scene")
    if visibility_store is not None and not isinstance(visibility_store, SQLiteVisibilityStore):
        raise TypeError("visibility_store must be a SQLiteVisibilityStore or None")
    if visibility_store is None and visibility_table_id is not None:
        raise ValueError("visibility_table_id requires a visibility_store")
    if visibility_store is not None and (
        scene_library is None or token_store is None or scene is None
    ):
        raise ValueError("visibility_store requires a scene, scene_library, and token_store")
    if presence_store is not None and not isinstance(presence_store, SQLitePresenceStore):
        raise TypeError("presence_store must be a SQLitePresenceStore or None")
    if presence_store is None and presence_epoch_ms_clock is not None:
        raise ValueError("presence_epoch_ms_clock requires a presence_store")
    if presentation_store is not None and not isinstance(
        presentation_store, SQLitePresentationStore
    ):
        raise TypeError("presentation_store must be a SQLitePresentationStore or None")
    if presentation_store is None and presentation_table_id is not None:
        raise ValueError("presentation_table_id requires a presentation_store")
    if presentation_store is None and presentation_epoch_ms_clock is not None:
        raise ValueError("presentation_epoch_ms_clock requires a presentation_store")
    if presentation_store is not None and (scene is None or scene_library is None):
        raise ValueError("presentation_store requires a scene and scene_library")
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
    configured_journal_table_id: str | None = None
    if journal_store is not None:
        configured_journal_table_id = journal_table_id
        if configured_journal_table_id is None:
            configured_journal_table_id = (
                access_policy.roster.table_id if access_policy is not None else service.session_id
            )
        if (
            access_policy is not None
            and configured_journal_table_id != access_policy.roster.table_id
        ):
            raise ValueError("journal_table_id must match the access-policy table")
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
        if (
            configured_journal_table_id is not None
            and configured_journal_table_id != configured_scene_library_table_id
        ):
            raise ValueError("journal and scene-library table IDs must match")
    configured_map_asset_table_id: str | None = None
    if map_asset_store is not None:
        configured_map_asset_table_id = map_asset_table_id
        if configured_map_asset_table_id is None:
            configured_map_asset_table_id = (
                access_policy.roster.table_id if access_policy is not None else service.session_id
            )
        if (
            access_policy is not None
            and configured_map_asset_table_id != access_policy.roster.table_id
        ):
            raise ValueError("map_asset_table_id must match the access-policy table")
        if configured_map_asset_table_id != configured_scene_library_table_id:
            raise ValueError("map_asset_table_id must match the scene-library table")
    configured_presence_clock: EpochMillisecondsClock | None = None
    configured_presentation_table_id: str | None = None
    configured_presentation_clock: EpochMillisecondsClock | None = None
    configured_token_table_id: str | None = None
    if token_store is not None:
        configured_token_table_id = token_table_id
        if configured_token_table_id is None:
            configured_token_table_id = (
                access_policy.roster.table_id if access_policy is not None else service.session_id
            )
        if access_policy is not None and configured_token_table_id != access_policy.roster.table_id:
            raise ValueError("token_table_id must match the access-policy table")
        if configured_token_table_id != configured_scene_library_table_id:
            raise ValueError("token_table_id must match the scene-library table")
    configured_visibility_table_id: str | None = None
    configured_visibility_roster: TableRoster | None = None
    if visibility_store is not None:
        configured_visibility_table_id = visibility_table_id
        if configured_visibility_table_id is None:
            configured_visibility_table_id = (
                access_policy.roster.table_id if access_policy is not None else service.session_id
            )
        if (
            access_policy is not None
            and configured_visibility_table_id != access_policy.roster.table_id
        ):
            raise ValueError("visibility_table_id must match the access-policy table")
        if configured_visibility_table_id != configured_scene_library_table_id:
            raise ValueError("visibility_table_id must match the scene-library table")
        if configured_visibility_table_id != configured_token_table_id:
            raise ValueError("visibility_table_id must match the token table")
        configured_visibility_roster = (
            access_policy.roster
            if access_policy is not None
            else TableRoster(
                schema_version=ROSTER_SCHEMA_VERSION,
                table_id=configured_visibility_table_id,
                participants=(_open_local_participant(),),
            )
        )
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
    if presentation_store is not None:
        configured_presentation_table_id = presentation_table_id
        if configured_presentation_table_id is None:
            configured_presentation_table_id = (
                access_policy.roster.table_id if access_policy is not None else service.session_id
            )
        if (
            access_policy is not None
            and configured_presentation_table_id != access_policy.roster.table_id
        ):
            raise ValueError("presentation_table_id must match the access-policy table")
        if configured_presentation_table_id != configured_scene_library_table_id:
            raise ValueError("presentation_table_id must match the scene-library table")
        configured_presentation_clock = (
            system_epoch_ms if presentation_epoch_ms_clock is None else presentation_epoch_ms_clock
        )
        if not callable(configured_presentation_clock):
            raise TypeError("presentation_epoch_ms_clock must be callable")

    app = FastAPI(title="dnd-sim VTT API", version="1")
    app.state.vtt_access_policy = access_policy
    app.state.vtt_annotation_board = annotation_board
    app.state.vtt_chat_log = chat_log
    app.state.vtt_journal_store = journal_store
    app.state.vtt_scene_library = scene_library
    app.state.vtt_map_asset_store = map_asset_store
    app.state.vtt_token_store = token_store
    app.state.vtt_visibility_store = visibility_store
    app.state.vtt_presence_store = presence_store
    app.state.vtt_presentation_store = presentation_store

    def current_active_board() -> ActiveBoardProjection | None:
        return resolve_active_board(
            configured_scene=configured_scene,
            scene_library=scene_library,
            table_id=configured_scene_library_table_id,
        )

    def current_scene() -> SquareGridScene | None:
        active_board = current_active_board()
        if active_board is not None:
            return active_board.scene
        return configured_scene if scene_library is None else None

    def current_active_scene_id() -> str | None:
        resolved = current_scene()
        return None if resolved is None else resolved.scene_id

    def current_visibility_projection(
        participant: TableParticipant | None,
    ):
        if visibility_store is None or participant is None or participant.role == "gm":
            return None
        if (
            scene_library is None
            or token_store is None
            or configured_scene is None
            or configured_visibility_table_id is None
            or configured_visibility_roster is None
        ):
            raise RuntimeError("visibility projection configuration was not normalized")
        return project_current_visibility(
            store=visibility_store,
            scenes=scene_library,
            token_store=token_store,
            service=service,
            configured_scene=configured_scene,
            table_id=configured_visibility_table_id,
            roster=configured_visibility_roster,
            participant=participant,
        )

    def current_visibility_actor_ids(
        participant: TableParticipant | None,
    ) -> frozenset[str] | None:
        projection = current_visibility_projection(participant)
        if projection is None:
            return None
        return frozenset(
            token.actor_id for token in projection.tokens if token.actor_id is not None
        )

    def current_visibility_tokens(
        participant: TableParticipant,
    ):
        projection = current_visibility_projection(participant)
        if projection is None:  # pragma: no cover - callback is player-only
            raise RuntimeError("visibility token projection requires a player")
        return projection.tokens

    if access_policy is not None:
        protected_routes = set(_PROTECTED_TABLE_ROUTES)
        if annotation_board is not None:
            protected_routes.update(ANNOTATION_PROTECTED_ROUTES)
        if chat_log is not None:
            protected_routes.update(CHAT_PROTECTED_ROUTES)
        if journal_store is not None:
            protected_routes.update(JOURNAL_PROTECTED_ROUTES)
        if scene_library is not None:
            protected_routes.update(SCENE_LIBRARY_PROTECTED_ROUTES)
        protected_route_prefixes: set[tuple[str, str]] = set()
        if map_asset_store is not None:
            protected_routes.update(MAP_ASSET_PROTECTED_ROUTES)
            protected_route_prefixes.update(MAP_ASSET_PROTECTED_ROUTE_PREFIXES)
        if token_store is not None:
            protected_routes.update(TOKEN_PROTECTED_ROUTES)
        if visibility_store is not None:
            protected_routes.update(VISIBILITY_PROTECTED_ROUTES)
        if presence_store is not None:
            protected_routes.update(PRESENCE_PROTECTED_ROUTES)
        if presentation_store is not None:
            protected_routes.update(PRESENTATION_PROTECTED_ROUTES)
            protected_route_prefixes.update(PRESENTATION_PROTECTED_ROUTE_PREFIXES)
        app.add_middleware(
            _TableAuthenticationMiddleware,
            access_policy=access_policy,
            protected_routes=frozenset(protected_routes),
            protected_route_prefixes=frozenset(protected_route_prefixes),
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

    @app.exception_handler(JournalAPIError)
    async def journal_api_error(
        _request: Request,
        exc: JournalAPIError,
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

    @app.exception_handler(MapAssetAPIError)
    async def map_asset_api_error(
        _request: Request,
        exc: MapAssetAPIError,
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

    @app.exception_handler(PresentationAPIError)
    async def presentation_api_error(
        _request: Request,
        exc: PresentationAPIError,
    ) -> JSONResponse:
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(TokenAPIError)
    async def token_api_error(
        _request: Request,
        exc: TokenAPIError,
    ) -> JSONResponse:
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(VisibilityAPIError)
    async def visibility_api_error(
        _request: Request,
        exc: VisibilityAPIError,
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

    @app.exception_handler(VTTBoardMovementError)
    async def board_movement_error(
        _request: Request,
        exc: VTTBoardMovementError,
    ) -> JSONResponse:
        return _error_response(
            status_code=409,
            code=exc.code,
            message=exc.message,
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
    async def get_session(request: Request) -> VTTSessionView:
        session = service.read_view()
        participant = _request_participant(request)
        projection = session.projection
        active_board = current_active_board()
        active_scene = active_board.scene if active_board is not None else current_scene()
        if token_store is not None:
            if configured_token_table_id is None or active_scene is None:
                raise RuntimeError("token projection configuration was not normalized")
            projection = project_engine_projection_for_tokens(
                projection,
                store=token_store,
                table_id=configured_token_table_id,
                scene_id=active_scene.scene_id,
                participant=participant,
                visibility_actor_ids=current_visibility_actor_ids(participant),
            )
        return VTTSessionView(
            session_id=session.session_id,
            revision=session.revision,
            versions=session.versions,
            scene=active_scene,
            active_board=active_board,
            projection=projection,
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
                token_store=token_store,
                token_table_id=configured_token_table_id,
                active_scene_id=current_active_scene_id,
                visibility_actor_ids=current_visibility_actor_ids,
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
        active_board = current_active_board()
        active_scene = active_board.scene if active_board is not None else current_scene()
        source_projection = service.read_view().projection
        if access_policy is not None:
            if participant is None:
                raise RuntimeError("a protected command is missing its principal")
            access_policy.authorize_command(participant, command)
        if token_store is not None and participant is not None and participant.role != "gm":
            if configured_token_table_id is None or active_scene is None:
                raise RuntimeError("token projection configuration was not normalized")
            projected_command_view = project_engine_projection_for_tokens(
                source_projection,
                store=token_store,
                table_id=configured_token_table_id,
                scene_id=active_scene.scene_id,
                participant=participant,
                visibility_actor_ids=current_visibility_actor_ids(participant),
            )
            current_hidden_values = hidden_engine_actor_values_for_tokens(
                source_projection,
                store=token_store,
                table_id=configured_token_table_id,
                scene_id=active_scene.scene_id,
                participant=participant,
                visibility_actor_ids=current_visibility_actor_ids(participant),
            )
            _reject_unprojected_token_command(
                command,
                projection=projected_command_view,
                hidden_actor_values=current_hidden_values,
            )
        if (
            visibility_store is not None
            and configured_visibility_table_id is not None
            and active_scene is not None
            and command.kind == "dnd.declare_turn.v1"
            and command.mode in {"preview", "commit"}
            and current_movement_path_is_blocked(
                store=visibility_store,
                table_id=configured_visibility_table_id,
                scene_id=active_scene.scene_id,
                movement_path=command.payload.get("movement_path"),
            )
        ):
            raise VTTBoardMovementError(
                code="board_movement_blocked",
                message="The movement path crosses an authoritative barrier.",
            )
        trusted_movement = _trusted_board_movement_metadata(
            command,
            active_board=active_board,
            projection=source_projection,
        )
        unfiltered_response = (
            service.execute(command)
            if trusted_movement is None
            else service.execute(
                command,
                trusted_intent_metadata=trusted_movement,
            )
        )
        hidden_actor_values = frozenset()
        if token_store is not None:
            if configured_token_table_id is None or active_scene is None:
                raise RuntimeError("token projection configuration was not normalized")
            source_projection = (
                unfiltered_response.projection
                if isinstance(unfiltered_response, VTTPreviewResponse)
                else service.read_view().projection
            )
            hidden_actor_values = hidden_engine_actor_values_for_tokens(
                source_projection,
                store=token_store,
                table_id=configured_token_table_id,
                scene_id=active_scene.scene_id,
                participant=participant,
                visibility_actor_ids=current_visibility_actor_ids(participant),
            )
        response = _filter_response_events(
            unfiltered_response,
            participant,
            hidden_actor_values=hidden_actor_values,
        )
        if isinstance(response, VTTPreviewResponse) and token_store is not None:
            if configured_token_table_id is None or active_scene is None:
                raise RuntimeError("token projection configuration was not normalized")
            projection = project_engine_projection_for_tokens(
                response.projection,
                store=token_store,
                table_id=configured_token_table_id,
                scene_id=active_scene.scene_id,
                participant=participant,
                visibility_actor_ids=current_visibility_actor_ids(participant),
            )
            return VTTPreviewResponse.model_validate(
                {**response.model_dump(mode="json"), "projection": projection}
            )
        return response

    if annotation_board is not None:
        if configured_scene is None or configured_annotation_table_id is None:
            raise RuntimeError("annotation route configuration was not normalized")
        install_annotation_routes(
            app,
            board=annotation_board,
            session_id=service.session_id,
            table_id=configured_annotation_table_id,
            scenes=scene_library,
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

    if journal_store is not None:
        if configured_journal_table_id is None or configured_scene is None:
            raise RuntimeError("journal route configuration was not normalized")
        install_journal_routes(
            app,
            store=journal_store,
            session_id=service.session_id,
            table_id=configured_journal_table_id,
            configured_scene=configured_scene,
            scenes=scene_library,
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
            map_asset_store=map_asset_store,
        )

    if map_asset_store is not None:
        if configured_map_asset_table_id is None or scene_library is None:
            raise RuntimeError("map asset route configuration was not normalized")
        install_map_asset_routes(
            app,
            store=map_asset_store,
            scenes=scene_library,
            session_id=service.session_id,
            table_id=configured_map_asset_table_id,
            access_policy=access_policy,
        )

    if token_store is not None:
        if configured_token_table_id is None or scene_library is None or configured_scene is None:
            raise RuntimeError("token route configuration was not normalized")
        install_token_routes(
            app,
            store=token_store,
            scenes=scene_library,
            service=service,
            scene_origin=configured_scene.origin_ft,
            session_id=service.session_id,
            table_id=configured_token_table_id,
            access_policy=access_policy,
            visibility_tokens=(None if visibility_store is None else current_visibility_tokens),
        )

    if visibility_store is not None:
        if (
            scene_library is None
            or token_store is None
            or configured_scene is None
            or configured_visibility_table_id is None
            or configured_visibility_roster is None
        ):
            raise RuntimeError("visibility route configuration was not normalized")
        install_visibility_routes(
            app,
            store=visibility_store,
            scenes=scene_library,
            token_store=token_store,
            service=service,
            configured_scene=configured_scene,
            session_id=service.session_id,
            table_id=configured_visibility_table_id,
            roster=configured_visibility_roster,
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

    if presentation_store is not None:
        if (
            configured_presentation_table_id is None
            or configured_presentation_clock is None
            or scene_library is None
            or configured_scene is None
        ):
            raise RuntimeError("presentation route configuration was not normalized")
        install_presentation_routes(
            app,
            store=presentation_store,
            scenes=scene_library,
            configured_scene=configured_scene,
            session_id=service.session_id,
            table_id=configured_presentation_table_id,
            access_policy=access_policy,
            epoch_ms_clock=configured_presentation_clock,
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
