"""Authenticated visibility authoring and audience-safe projection routes."""

from __future__ import annotations

import asyncio
import json
import math
import sqlite3
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Annotated, Any, Literal, Self

from fastapi import APIRouter, FastAPI, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, JsonValue, field_validator, model_validator

from .access import TableAccessPolicy
from .active_board import resolve_active_board
from .participants import TableParticipant, TableRoster
from .scene import FeetPosition, SquareGridScene
from .scene_library_store import (
    SQLiteSceneLibrary,
    SceneLibraryStoreCorruptionError,
    SceneLibraryStoreError,
    SceneLibraryStoreSchemaError,
)
from .session_service import VTTSessionService
from .token_contracts import TokenRecord, TokenView
from .token_store import (
    SQLiteTokenStore,
    TokenStoreCorruptionError,
    TokenStoreError,
    TokenStoreSchemaError,
)
from .visibility_contracts import (
    FogOperation,
    LightEmitter,
    SceneEnvironment,
    SightBarrier,
    TokenVision,
    VisibilityCatalogView,
    VisibilityChangedEvent,
    VisibilityCommand,
    VisibilityDeleteCommand,
    VisibilityDoorStateCommand,
    VisibilityFogUndoCommand,
    VisibilityMutationReceipt,
    VisibilityPutCommand,
    VisibilityRecord,
    VisibilityPoint,
    barrier_blocks_movement,
)
from .visibility_projection import (
    VisibilityProjection,
    VisibilityProjectionError,
    project_visibility,
)
from .visibility_store import (
    SQLiteVisibilityStore,
    VisibilityCommandConflictError,
    VisibilityExecutionResult,
    VisibilityLimitError,
    VisibilityRecordConflictError,
    VisibilityRecordNotFoundError,
    VisibilityRevisionConflictError,
    VisibilityStoreCorruptionError,
    VisibilityStoreError,
    VisibilityStoreSchemaError,
)

VTT_VISIBILITY_REQUEST_SCHEMA_VERSION = "vtt.visibility_request.v1"
VTT_VISIBILITY_RESPONSE_SCHEMA_VERSION = "vtt.visibility_response.v1"
VISIBILITY_CHANGE_SIGNAL_SCHEMA_VERSION = "vtt.visibility_change_signal.v1"

VISIBILITY_PROTECTED_ROUTES = frozenset(
    {
        ("GET", "/api/v1/visibility"),
        ("GET", "/api/v1/visibility-preview"),
        ("POST", "/api/v1/visibility-commands"),
        ("GET", "/api/v1/visibility-events"),
    }
)

SSE_POLL_INTERVAL_SECONDS = 0.25
SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0


class _StrictVisibilityHTTPModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


_BROWSER_FLOAT_FIELDS = frozenset(
    {
        "x_ft",
        "y_ft",
        "bright_radius_ft",
        "dim_radius_ft",
        "normal_range_ft",
        "darkvision_range_ft",
        "emitted_bright_radius_ft",
        "emitted_dim_radius_ft",
        "direction_degrees",
        "angle_degrees",
    }
)


def _canonicalize_browser_floats(value: Any, *, field_name: str | None = None) -> Any:
    if field_name in _BROWSER_FLOAT_FIELDS and type(value) is int:
        return float(value)
    if isinstance(value, Mapping):
        return {
            key: _canonicalize_browser_floats(item, field_name=str(key))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize_browser_floats(item, field_name=field_name) for item in value]
    return value


def _canonical_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    return value


class VisibilityRequest(_StrictVisibilityHTTPModel):
    schema_version: Literal[VTT_VISIBILITY_REQUEST_SCHEMA_VERSION] = (
        VTT_VISIBILITY_REQUEST_SCHEMA_VERSION
    )
    session_id: str
    command: VisibilityCommand

    @model_validator(mode="before")
    @classmethod
    def canonicalize_browser_numbers(cls, value: Any) -> Any:
        return _canonicalize_browser_floats(value)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="session_id")


class VisibilityResponse(_StrictVisibilityHTTPModel):
    schema_version: Literal[VTT_VISIBILITY_RESPONSE_SCHEMA_VERSION] = (
        VTT_VISIBILITY_RESPONSE_SCHEMA_VERSION
    )
    session_id: str
    table_id: str
    command_id: str
    revision: int
    replayed: bool
    event: VisibilityChangedEvent

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if (
            type(self.revision) is not int
            or self.revision < 1
            or self.event.table_id != self.table_id
            or self.event.command_id != self.command_id
            or self.event.revision != self.revision
        ):
            raise ValueError("visibility response does not match its event")
        return self


class VisibilityChangeSignal(_StrictVisibilityHTTPModel):
    schema_version: Literal[VISIBILITY_CHANGE_SIGNAL_SCHEMA_VERSION] = (
        VISIBILITY_CHANGE_SIGNAL_SCHEMA_VERSION
    )
    sequence: int
    revision: int
    scene_id: str

    @model_validator(mode="after")
    def validate_signal(self) -> Self:
        if type(self.sequence) is not int or self.sequence < 1 or self.sequence != self.revision:
            raise ValueError("visibility signal sequence and revision must match")
        _canonical_text(self.scene_id, field_name="scene_id")
        return self


class VisibilityAPIError(RuntimeError):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, JsonValue] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = {} if details is None else dict(details)


def _request_participant(
    request: Request,
    *,
    access_policy: TableAccessPolicy | None,
) -> TableParticipant | None:
    if access_policy is None:
        return None
    participant = getattr(request.state, "vtt_participant", None)
    if not isinstance(participant, TableParticipant):
        raise RuntimeError("a protected visibility request is missing its principal")
    canonical = access_policy.roster.participant(participant.participant_id)
    if canonical is None or canonical != participant:
        raise RuntimeError("a protected visibility request has a noncanonical principal")
    return participant


def _storage_error(exc: Exception) -> VisibilityAPIError:
    if isinstance(
        exc,
        (
            VisibilityStoreCorruptionError,
            VisibilityStoreSchemaError,
            SceneLibraryStoreCorruptionError,
            SceneLibraryStoreSchemaError,
            TokenStoreCorruptionError,
            TokenStoreSchemaError,
        ),
    ):
        return VisibilityAPIError(
            status_code=500,
            code="visibility_store_corrupt",
            message="The visibility catalog contains invalid durable data.",
        )
    return VisibilityAPIError(
        status_code=503,
        code="visibility_storage_unavailable",
        message="The visibility catalog could not be persisted or read.",
    )


def _scene_entry(
    scenes: SQLiteSceneLibrary,
    *,
    table_id: str,
    scene_id: str,
    require_active: bool,
):
    try:
        snapshot = scenes.snapshot(table_id)
    except (sqlite3.Error, SceneLibraryStoreError) as exc:
        raise _storage_error(exc) from exc
    entry = snapshot.scene(scene_id)
    if entry is None or entry.archived or (require_active and snapshot.active_scene_id != scene_id):
        raise VisibilityAPIError(
            status_code=404,
            code="visibility_scene_unavailable",
            message="The requested visibility scene is unavailable.",
        )
    return entry


def _active_scene_id(scenes: SQLiteSceneLibrary, table_id: str) -> str:
    try:
        scene_id = scenes.snapshot(table_id).active_scene_id
    except (sqlite3.Error, SceneLibraryStoreError) as exc:
        raise _storage_error(exc) from exc
    if scene_id is None:
        raise VisibilityAPIError(
            status_code=409,
            code="visibility_scene_unavailable",
            message="The active visibility scene is unavailable.",
        )
    return scene_id


def _bound_tokens(
    *,
    store: SQLiteTokenStore,
    service: VTTSessionService,
    table_id: str,
    scene_id: str,
) -> TokenView:
    try:
        truth = store.snapshot(table_id, scene_id)
    except (sqlite3.Error, TokenStoreError) as exc:
        raise _storage_error(exc) from exc
    projection = service.read_view().projection
    actors = projection.get("actors")
    bound = []
    for token in truth.tokens:
        if token.actor_id is None:
            bound.append(token)
            continue
        actor = actors.get(token.actor_id) if isinstance(actors, Mapping) else None
        position = actor.get("position") if isinstance(actor, Mapping) else None
        if (
            not isinstance(position, Sequence)
            or isinstance(position, (str, bytes, bytearray))
            or len(position) != 3
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in position
            )
        ):
            raise VisibilityAPIError(
                status_code=409,
                code="visibility_projection_unavailable",
                message="The authoritative visibility projection is unavailable.",
            )
        bound.append(
            token.model_copy(
                update={
                    "pose": token.pose.model_copy(
                        update={
                            "position_ft": FeetPosition(
                                x_ft=float(position[0]),
                                y_ft=float(position[1]),
                                z_ft=float(position[2]),
                            )
                        }
                    )
                }
            )
        )
    return TokenView(
        table_id=truth.table_id,
        scene_id=truth.scene_id,
        revision=truth.revision,
        tokens=tuple(bound),
    )


def project_current_visibility(
    *,
    store: SQLiteVisibilityStore,
    scenes: SQLiteSceneLibrary,
    token_store: SQLiteTokenStore,
    service: VTTSessionService,
    configured_scene: SquareGridScene,
    table_id: str,
    roster: TableRoster,
    participant: TableParticipant,
) -> VisibilityProjection:
    """Resolve all authoritative revisions and project the current active scene."""

    active_board = resolve_active_board(
        configured_scene=configured_scene,
        scene_library=scenes,
        table_id=table_id,
    )
    if active_board is None:
        raise VisibilityAPIError(
            status_code=409,
            code="visibility_scene_unavailable",
            message="The active visibility scene is unavailable.",
        )
    try:
        catalog = store.snapshot(table_id, active_board.scene.scene_id)
    except (sqlite3.Error, VisibilityStoreError) as exc:
        raise _storage_error(exc) from exc
    tokens = _bound_tokens(
        store=token_store,
        service=service,
        table_id=table_id,
        scene_id=active_board.scene.scene_id,
    )
    try:
        return project_visibility(
            active_board=active_board,
            catalog=catalog,
            tokens=tokens,
            participant=participant,
            roster=roster,
            encounter_revision=service.revision,
        )
    except VisibilityProjectionError as exc:
        raise VisibilityAPIError(
            status_code=409,
            code="visibility_projection_unavailable",
            message="The authoritative visibility projection is unavailable.",
        ) from exc


def current_movement_path_is_blocked(
    *,
    store: SQLiteVisibilityStore,
    table_id: str,
    scene_id: str,
    movement_path: Any,
) -> bool:
    """Check a canonical engine-feet path without exposing barrier identity."""

    if not isinstance(movement_path, list) or len(movement_path) < 2:
        return False
    points = []
    for waypoint in movement_path:
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
            return False
        points.append(VisibilityPoint(x_ft=float(waypoint[0]), y_ft=float(waypoint[1])))
    try:
        catalog = store.snapshot(table_id, scene_id)
    except (sqlite3.Error, VisibilityStoreError) as exc:
        raise _storage_error(exc) from exc
    barriers = tuple(record for record in catalog.records if isinstance(record, SightBarrier))
    return any(
        barrier_blocks_movement(barrier, points[index - 1], points[index])
        for index in range(1, len(points))
        for barrier in barriers
    )


def _scene_bounds(
    configured_scene: SquareGridScene,
    metadata,
) -> tuple[float, float, float, float]:
    calibration = metadata.calibration
    center_x = configured_scene.origin_ft.x_ft + calibration.distance_ft / 2.0
    center_y = configured_scene.origin_ft.y_ft + calibration.distance_ft / 2.0
    minimum_x = (
        center_x - calibration.origin_x_px / calibration.cell_extent_px * calibration.distance_ft
    )
    minimum_y = (
        center_y - calibration.origin_y_px / calibration.cell_extent_px * calibration.distance_ft
    )
    maximum_x = (
        center_x
        + (metadata.width_px - calibration.origin_x_px)
        / calibration.cell_extent_px
        * calibration.distance_ft
    )
    maximum_y = (
        center_y
        + (metadata.height_px - calibration.origin_y_px)
        / calibration.cell_extent_px
        * calibration.distance_ft
    )
    return minimum_x, minimum_y, maximum_x, maximum_y


def _record_points(record: VisibilityRecord) -> tuple[Any, ...]:
    if isinstance(record, SightBarrier):
        return (record.start, record.end)
    if isinstance(record, LightEmitter):
        return (record.origin,)
    if isinstance(record, FogOperation):
        return record.polygon
    return ()


def _validate_record_authority(
    record: VisibilityRecord,
    *,
    configured_scene: SquareGridScene,
    scenes: SQLiteSceneLibrary,
    token_store: SQLiteTokenStore,
    table_id: str,
) -> None:
    entry = _scene_entry(
        scenes,
        table_id=table_id,
        scene_id=record.scene_id,
        require_active=False,
    )
    minimum_x, minimum_y, maximum_x, maximum_y = _scene_bounds(
        configured_scene,
        entry.scene.map_metadata,
    )
    if any(
        point.x_ft < minimum_x
        or point.x_ft > maximum_x
        or point.y_ft < minimum_y
        or point.y_ft > maximum_y
        for point in _record_points(record)
    ):
        raise VisibilityAPIError(
            status_code=409,
            code="visibility_geometry_out_of_bounds",
            message="Visibility geometry must remain inside its scene.",
        )
    if isinstance(record, TokenVision):
        try:
            token = token_store.token(table_id, record.token_id)
        except (sqlite3.Error, TokenStoreError) as exc:
            raise _storage_error(exc) from exc
        if token is None or token.scene_id != record.scene_id:
            raise VisibilityAPIError(
                status_code=404,
                code="visibility_token_unavailable",
                message="The requested visibility token is unavailable.",
            )


def _execute(store: SQLiteVisibilityStore, command: VisibilityCommand):
    try:
        return store.execute(command)
    except VisibilityRevisionConflictError as exc:
        raise VisibilityAPIError(
            status_code=409,
            code="visibility_stale_revision",
            message="The visibility command targets a stale catalog revision.",
            details={"current_revision": exc.current_revision},
        ) from exc
    except VisibilityCommandConflictError as exc:
        raise VisibilityAPIError(
            status_code=409,
            code="visibility_command_id_conflict",
            message="The visibility command ID was already used with different content.",
        ) from exc
    except VisibilityRecordNotFoundError as exc:
        raise VisibilityAPIError(
            status_code=404,
            code="visibility_record_unavailable",
            message="The requested visibility record is unavailable.",
        ) from exc
    except VisibilityRecordConflictError as exc:
        raise VisibilityAPIError(
            status_code=409,
            code="visibility_record_conflict",
            message="The visibility record conflicts with current scene state.",
        ) from exc
    except VisibilityLimitError as exc:
        raise VisibilityAPIError(
            status_code=409,
            code="visibility_limit_exceeded",
            message="The visibility command exceeds a supported scene limit.",
        ) from exc
    except (sqlite3.Error, VisibilityStoreError) as exc:
        raise _storage_error(exc) from exc


def _response(session_id: str, result: VisibilityExecutionResult) -> VisibilityResponse:
    receipt: VisibilityMutationReceipt = result.receipt
    return VisibilityResponse(
        session_id=session_id,
        table_id=receipt.table_id,
        command_id=receipt.command_id,
        revision=receipt.revision,
        replayed=result.replayed,
        event=receipt.event,
    )


def _event_cursor(value: str | None, *, field: str) -> int | None:
    if value is None:
        return None
    if not value or any(character not in "0123456789" for character in value):
        raise VisibilityAPIError(
            status_code=400,
            code="invalid_visibility_event_cursor",
            message="The visibility event cursor must be a canonical non-negative integer.",
            details={"field": field},
        )
    cursor = int(value)
    if str(cursor) != value:
        raise VisibilityAPIError(
            status_code=400,
            code="invalid_visibility_event_cursor",
            message="The visibility event cursor must be a canonical non-negative integer.",
            details={"field": field},
        )
    return cursor


def _resume_after(*, after: str | None, last_event_id: str | None) -> int:
    query = _event_cursor(after, field="after")
    header = _event_cursor(last_event_id, field="Last-Event-ID")
    return max(value for value in (0, query, header) if value is not None)


def _events_after(store: SQLiteVisibilityStore, table_id: str, sequence: int):
    try:
        return store.events_after(table_id, sequence)
    except (sqlite3.Error, VisibilityStoreError) as exc:
        raise _storage_error(exc) from exc


def _render_signal(event: VisibilityChangedEvent) -> str:
    signal = VisibilityChangeSignal(
        sequence=event.sequence,
        revision=event.revision,
        scene_id=event.scene_id,
    )
    payload = json.dumps(
        signal.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"id: {signal.sequence}\nevent: vtt.visibility_changed\ndata: {payload}\n\n"


async def _stream_events(
    *,
    request: Request,
    store: SQLiteVisibilityStore,
    scenes: SQLiteSceneLibrary,
    table_id: str,
    scene_id: str,
    participant: TableParticipant | None,
    after: int,
    initial_events: tuple[VisibilityChangedEvent, ...],
) -> AsyncIterator[str]:
    cursor = after
    pending = initial_events
    loop = asyncio.get_running_loop()
    next_heartbeat = loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
    while True:
        if await request.is_disconnected():
            return
        if participant is not None and participant.role != "gm":
            if _active_scene_id(scenes, table_id) != scene_id:
                return
        events = pending
        pending = ()
        if not events:
            events = _events_after(store, table_id, cursor)
        if events:
            yielded = False
            for event in events:
                cursor = event.sequence
                if event.scene_id != scene_id:
                    continue
                yield _render_signal(event)
                yielded = True
            if yielded:
                next_heartbeat = loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
        elif loop.time() >= next_heartbeat:
            yield ": heartbeat\n\n"
            next_heartbeat = loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
        await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)


def install_visibility_routes(
    app: FastAPI,
    *,
    store: SQLiteVisibilityStore,
    scenes: SQLiteSceneLibrary,
    token_store: SQLiteTokenStore,
    service: VTTSessionService,
    configured_scene: SquareGridScene,
    session_id: str,
    table_id: str,
    roster: TableRoster,
    access_policy: TableAccessPolicy | None,
) -> None:
    configured_session_id = _canonical_text(session_id, field_name="session_id")
    configured_table_id = _canonical_text(table_id, field_name="table_id")
    router = APIRouter()

    @router.get(
        "/api/v1/visibility",
        response_model=VisibilityCatalogView | VisibilityProjection,
    )
    async def get_visibility(
        request: Request,
        scene_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    ) -> VisibilityCatalogView | VisibilityProjection:
        participant = _request_participant(request, access_policy=access_policy)
        active_scene_id = _active_scene_id(scenes, configured_table_id)
        requested_scene_id = active_scene_id if scene_id is None else scene_id
        if participant is None or participant.role == "gm":
            _scene_entry(
                scenes,
                table_id=configured_table_id,
                scene_id=requested_scene_id,
                require_active=False,
            )
            try:
                return store.snapshot(configured_table_id, requested_scene_id)
            except (sqlite3.Error, VisibilityStoreError) as exc:
                raise _storage_error(exc) from exc
        if requested_scene_id != active_scene_id:
            raise VisibilityAPIError(
                status_code=404,
                code="visibility_scene_unavailable",
                message="The requested visibility scene is unavailable.",
            )
        return project_current_visibility(
            store=store,
            scenes=scenes,
            token_store=token_store,
            service=service,
            configured_scene=configured_scene,
            table_id=configured_table_id,
            roster=roster,
            participant=participant,
        )

    @router.get(
        "/api/v1/visibility-preview",
        response_model=VisibilityProjection,
    )
    async def get_visibility_preview(
        request: Request,
        participant_id: Annotated[str, Query(min_length=1, max_length=128)],
    ) -> VisibilityProjection:
        participant = _request_participant(request, access_policy=access_policy)
        if participant is not None and participant.role != "gm":
            raise VisibilityAPIError(
                status_code=403,
                code="visibility_forbidden",
                message="This participant is not permitted to preview visibility.",
            )
        preview = roster.participant(participant_id)
        if preview is None or preview.role == "gm":
            raise VisibilityAPIError(
                status_code=404,
                code="visibility_participant_unavailable",
                message="The requested visibility participant is unavailable.",
            )
        return project_current_visibility(
            store=store,
            scenes=scenes,
            token_store=token_store,
            service=service,
            configured_scene=configured_scene,
            table_id=configured_table_id,
            roster=roster,
            participant=preview,
        )

    @router.post("/api/v1/visibility-commands", response_model=VisibilityResponse)
    async def execute_visibility_command(
        payload: VisibilityRequest,
        request: Request,
    ) -> VisibilityResponse:
        participant = _request_participant(request, access_policy=access_policy)
        if participant is not None and participant.role != "gm":
            raise VisibilityAPIError(
                status_code=403,
                code="visibility_forbidden",
                message="This participant is not permitted to author visibility.",
            )
        if (
            payload.session_id != configured_session_id
            or payload.command.table_id != configured_table_id
        ):
            raise VisibilityAPIError(
                status_code=409,
                code="visibility_binding_mismatch",
                message="The visibility request belongs to a different table or session.",
                details={
                    "expected_session_id": configured_session_id,
                    "expected_table_id": configured_table_id,
                },
            )
        try:
            replay = store.replay(payload.command)
        except VisibilityCommandConflictError as exc:
            raise VisibilityAPIError(
                status_code=409,
                code="visibility_command_id_conflict",
                message="The visibility command ID was already used with different content.",
            ) from exc
        except (sqlite3.Error, VisibilityStoreError) as exc:
            raise _storage_error(exc) from exc
        if replay is not None:
            return _response(configured_session_id, replay)

        command = payload.command
        if isinstance(command, VisibilityPutCommand):
            _validate_record_authority(
                command.record,
                configured_scene=configured_scene,
                scenes=scenes,
                token_store=token_store,
                table_id=configured_table_id,
            )
        elif isinstance(
            command,
            (VisibilityDeleteCommand, VisibilityDoorStateCommand, VisibilityFogUndoCommand),
        ):
            _scene_entry(
                scenes,
                table_id=configured_table_id,
                scene_id=command.scene_id,
                require_active=False,
            )
        return _response(configured_session_id, _execute(store, command))

    @router.get("/api/v1/visibility-events", response_class=StreamingResponse)
    async def get_visibility_events(
        request: Request,
        scene_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
        after: Annotated[str | None, Query()] = None,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        participant = _request_participant(request, access_policy=access_policy)
        active_scene_id = _active_scene_id(scenes, configured_table_id)
        requested_scene_id = active_scene_id if scene_id is None else scene_id
        _scene_entry(
            scenes,
            table_id=configured_table_id,
            scene_id=requested_scene_id,
            require_active=participant is not None and participant.role != "gm",
        )
        cursor = _resume_after(after=after, last_event_id=last_event_id)
        initial = _events_after(store, configured_table_id, cursor)
        return StreamingResponse(
            _stream_events(
                request=request,
                store=store,
                scenes=scenes,
                table_id=configured_table_id,
                scene_id=requested_scene_id,
                participant=participant,
                after=cursor,
                initial_events=initial,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    app.include_router(router)


__all__ = [
    "VISIBILITY_CHANGE_SIGNAL_SCHEMA_VERSION",
    "VISIBILITY_PROTECTED_ROUTES",
    "VTT_VISIBILITY_REQUEST_SCHEMA_VERSION",
    "VTT_VISIBILITY_RESPONSE_SCHEMA_VERSION",
    "VisibilityAPIError",
    "VisibilityChangeSignal",
    "VisibilityRequest",
    "VisibilityResponse",
    "install_visibility_routes",
    "current_movement_path_is_blocked",
    "project_current_visibility",
]
