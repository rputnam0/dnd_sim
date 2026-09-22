"""Authenticated HTTP transport for shared sound and synchronized player view."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Any

from fastapi import APIRouter, FastAPI, Header, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import JsonValue

from .access import TableAccessPolicy
from .active_board import ActiveBoardProjection, resolve_active_board
from .participants import TableParticipant, audience_allows, validate_audience_selectors
from .presentation_contracts import (
    CameraShareCommand,
    CameraState,
    PlaybackPlayCommand,
    PlaybackState,
    PresentationCommand,
    PresentationRequest,
    PresentationResponse,
    PresentationSignal,
    PresentationView,
)
from .presentation_store import (
    SQLitePresentationStore,
    PresentationCapacityError,
    PresentationCommandConflictError,
    PresentationInvalidAudioError,
    PresentationRecordConflictError,
    PresentationRecordNotFoundError,
    PresentationReferenceError,
    PresentationRevisionConflictError,
    PresentationStateError,
    PresentationStoreCorruptionError,
    PresentationStoreError,
    PresentationStoreSchemaError,
)
from .scene import SquareGridScene
from .scene_library_store import SQLiteSceneLibrary, SceneLibraryStoreError

PRESENTATION_PROTECTED_ROUTES = frozenset(
    {
        ("GET", "/api/v1/presentation"),
        ("POST", "/api/v1/presentation-commands"),
        ("GET", "/api/v1/presentation-events"),
    }
)
PRESENTATION_PROTECTED_ROUTE_PREFIXES = frozenset({("GET", "/api/v1/sound-assets/")})
SSE_POLL_INTERVAL_SECONDS = 0.25
SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0

EpochClock = Callable[[], int]


class PresentationAPIError(RuntimeError):
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


def _participant(
    request: Request, access_policy: TableAccessPolicy | None
) -> TableParticipant | None:
    if access_policy is None:
        return None
    participant = getattr(request.state, "vtt_participant", None)
    if not isinstance(participant, TableParticipant):
        raise RuntimeError("a protected presentation request is missing its principal")
    canonical = access_policy.roster.participant(participant.participant_id)
    if canonical is None or canonical != participant:
        raise RuntimeError("a protected presentation request has a noncanonical principal")
    return participant


def _clock_value(clock: EpochClock) -> int:
    value = clock()
    if type(value) is not int or value < 0:
        raise RuntimeError("the presentation clock returned an invalid epoch")
    return value


def _active_board(
    *,
    configured_scene: SquareGridScene,
    scenes: SQLiteSceneLibrary,
    table_id: str,
) -> ActiveBoardProjection | None:
    try:
        return resolve_active_board(
            configured_scene=configured_scene,
            scene_library=scenes,
            table_id=table_id,
        )
    except (sqlite3.Error, SceneLibraryStoreError) as exc:
        raise PresentationAPIError(
            status_code=503,
            code="presentation_storage_unavailable",
            message="Presentation state could not be read.",
        ) from exc


def _visible_view(
    *,
    store: SQLitePresentationStore,
    session_id: str,
    table_id: str,
    epoch_ms: int,
    participant: TableParticipant | None,
    active_board: ActiveBoardProjection | None,
) -> PresentationView:
    try:
        snapshot = store.snapshot(table_id)
    except (PresentationStoreCorruptionError, PresentationStoreSchemaError) as exc:
        raise PresentationAPIError(
            status_code=500,
            code="presentation_store_corrupt",
            message="Presentation state contains invalid durable data.",
        ) from exc
    except (sqlite3.Error, PresentationStoreError) as exc:
        raise PresentationAPIError(
            status_code=503,
            code="presentation_storage_unavailable",
            message="Presentation state could not be read.",
        ) from exc

    camera = snapshot.camera
    if active_board is None or camera.scene_id != active_board.scene.scene_id:
        camera = CameraState(epoch=camera.epoch)
    if participant is None or participant.role == "gm":
        return PresentationView(
            session_id=session_id,
            table_id=table_id,
            revision=snapshot.revision,
            server_epoch_ms=epoch_ms,
            tracks=snapshot.tracks,
            playlists=snapshot.playlists,
            playback=snapshot.playback,
            camera=camera,
        )
    if snapshot.playback.status == "stopped" or not audience_allows(
        snapshot.playback.audience, participant
    ):
        return PresentationView(
            session_id=session_id,
            table_id=table_id,
            revision=snapshot.revision,
            server_epoch_ms=epoch_ms,
            camera=camera,
        )
    track = next(item for item in snapshot.tracks if item.track_id == snapshot.playback.track_id)
    playback = snapshot.playback.model_copy(update={"playlist_id": None, "audience": ("all",)})
    return PresentationView(
        session_id=session_id,
        table_id=table_id,
        revision=snapshot.revision,
        server_epoch_ms=epoch_ms,
        tracks=(track,),
        playback=playback,
        camera=camera,
    )


def _validate_audience(
    command: PlaybackPlayCommand, access_policy: TableAccessPolicy | None
) -> None:
    selectors = validate_audience_selectors(command.audience)
    if access_policy is None:
        return
    participant_ids = {item.participant_id for item in access_policy.roster.participants}
    actor_ids = {
        actor_id for item in access_policy.roster.participants for actor_id in item.owned_actor_ids
    }
    if any(
        selector.startswith("participant:")
        and selector.removeprefix("participant:") not in participant_ids
        or selector.startswith("actor:")
        and selector.removeprefix("actor:") not in actor_ids
        for selector in selectors
    ):
        raise PresentationAPIError(
            status_code=422,
            code="presentation_invalid_audience",
            message="The playback audience is not supported by this table.",
        )


def _validate_camera(command: CameraShareCommand, board: ActiveBoardProjection | None) -> None:
    if board is None or command.scene_id != board.scene.scene_id:
        raise PresentationAPIError(
            status_code=409,
            code="presentation_scene_mismatch",
            message="The shared camera must target the active scene.",
        )
    calibration = board.map_metadata.calibration
    origin = board.scene.origin_ft
    x_px = (
        calibration.origin_x_px
        + ((command.center_x_ft - origin.x_ft) / calibration.distance_ft)
        * calibration.cell_extent_px
    )
    y_px = (
        calibration.origin_y_px
        + ((command.center_y_ft - origin.y_ft) / calibration.distance_ft)
        * calibration.cell_extent_px
    )
    if not (
        0.0 <= x_px <= board.map_metadata.width_px and 0.0 <= y_px <= board.map_metadata.height_px
    ):
        raise PresentationAPIError(
            status_code=422,
            code="presentation_camera_out_of_bounds",
            message="The shared camera center must lie inside the active map.",
        )


def _execute(
    store: SQLitePresentationStore,
    command: PresentationCommand,
    *,
    epoch_ms: int,
):
    try:
        return store.execute(command, epoch_ms=epoch_ms)
    except PresentationRevisionConflictError as exc:
        raise PresentationAPIError(
            status_code=409,
            code="presentation_stale_revision",
            message="The presentation command targets a stale revision.",
            details={"current_revision": exc.current_revision},
        ) from exc
    except PresentationCommandConflictError as exc:
        raise PresentationAPIError(
            status_code=409,
            code="presentation_command_conflict",
            message="The presentation command ID was already used with different content.",
        ) from exc
    except PresentationRecordConflictError as exc:
        raise PresentationAPIError(
            status_code=409,
            code="presentation_record_conflict",
            message="The presentation record ID was already used.",
        ) from exc
    except (PresentationRecordNotFoundError, PresentationReferenceError) as exc:
        raise PresentationAPIError(
            status_code=409,
            code="presentation_reference_invalid",
            message="The presentation command references unavailable state.",
        ) from exc
    except PresentationStateError as exc:
        raise PresentationAPIError(
            status_code=409,
            code="presentation_state_conflict",
            message=str(exc),
        ) from exc
    except PresentationCapacityError as exc:
        raise PresentationAPIError(
            status_code=409,
            code="presentation_capacity_exhausted",
            message=str(exc),
        ) from exc
    except PresentationInvalidAudioError as exc:
        raise PresentationAPIError(
            status_code=422,
            code="presentation_invalid_audio",
            message=str(exc),
        ) from exc
    except (PresentationStoreCorruptionError, PresentationStoreSchemaError) as exc:
        raise PresentationAPIError(
            status_code=500,
            code="presentation_store_corrupt",
            message="Presentation state contains invalid durable data.",
        ) from exc
    except (sqlite3.Error, PresentationStoreError) as exc:
        raise PresentationAPIError(
            status_code=503,
            code="presentation_storage_unavailable",
            message="Presentation state could not be persisted.",
        ) from exc


def _cursor(value: str | None, field: str) -> int | None:
    if value is None:
        return None
    if (
        not value
        or not value.isascii()
        or not value.isdigit()
        or (len(value) > 1 and value[0] == "0")
    ):
        raise PresentationAPIError(
            status_code=400,
            code="presentation_invalid_cursor",
            message=f"{field} must be a canonical non-negative integer.",
        )
    return int(value)


def _render_signal(signal: PresentationSignal) -> str:
    payload = json.dumps(
        signal.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"id: {signal.sequence}\nevent: vtt.presentation_changed\ndata: {payload}\n\n"


async def _stream(
    request: Request,
    *,
    store: SQLitePresentationStore,
    table_id: str,
    after: int,
) -> AsyncIterator[str]:
    cursor = after
    loop = asyncio.get_running_loop()
    heartbeat = loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
    while True:
        if await request.is_disconnected():
            return
        try:
            events = store.events_after(table_id, cursor)
        except (PresentationStoreCorruptionError, PresentationStoreSchemaError) as exc:
            raise PresentationAPIError(
                status_code=500,
                code="presentation_store_corrupt",
                message="Presentation state contains invalid durable data.",
            ) from exc
        if events:
            for event in events:
                cursor = event.sequence
                yield _render_signal(event)
            heartbeat = loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
        elif loop.time() >= heartbeat:
            yield ": heartbeat\n\n"
            heartbeat = loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
        await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)


def install_presentation_routes(
    app: FastAPI,
    *,
    store: SQLitePresentationStore,
    scenes: SQLiteSceneLibrary,
    configured_scene: SquareGridScene,
    session_id: str,
    table_id: str,
    access_policy: TableAccessPolicy | None,
    epoch_ms_clock: EpochClock,
) -> None:
    router = APIRouter()

    def board() -> ActiveBoardProjection | None:
        return _active_board(
            configured_scene=configured_scene,
            scenes=scenes,
            table_id=table_id,
        )

    @router.get("/api/v1/presentation", response_model=PresentationView)
    async def get_presentation(request: Request) -> PresentationView:
        return _visible_view(
            store=store,
            session_id=session_id,
            table_id=table_id,
            epoch_ms=_clock_value(epoch_ms_clock),
            participant=_participant(request, access_policy),
            active_board=board(),
        )

    @router.post("/api/v1/presentation-commands", response_model=PresentationResponse)
    async def mutate_presentation(
        payload: PresentationRequest, request: Request
    ) -> PresentationResponse:
        participant = _participant(request, access_policy)
        if participant is not None and participant.role != "gm":
            raise PresentationAPIError(
                status_code=403,
                code="presentation_forbidden",
                message="Only a Game Master may change shared presentation state.",
            )
        if payload.session_id != session_id or payload.command.table_id != table_id:
            raise PresentationAPIError(
                status_code=409,
                code="presentation_binding_mismatch",
                message="The presentation request belongs to a different table or session.",
            )
        try:
            replay = store.replay(payload.command)
        except PresentationCommandConflictError as exc:
            raise PresentationAPIError(
                status_code=409,
                code="presentation_command_conflict",
                message="The presentation command ID was already used with different content.",
            ) from exc
        except (PresentationStoreCorruptionError, PresentationStoreSchemaError) as exc:
            raise PresentationAPIError(
                status_code=500,
                code="presentation_store_corrupt",
                message="Presentation state contains invalid durable data.",
            ) from exc
        except (sqlite3.Error, PresentationStoreError) as exc:
            raise PresentationAPIError(
                status_code=503,
                code="presentation_storage_unavailable",
                message="Presentation state could not be read.",
            ) from exc
        if replay is not None:
            return PresentationResponse(
                session_id=session_id,
                replayed=True,
                receipt=replay.receipt,
            )
        if isinstance(payload.command, PlaybackPlayCommand):
            _validate_audience(payload.command, access_policy)
        if isinstance(payload.command, CameraShareCommand):
            _validate_camera(payload.command, board())
        result = _execute(
            store,
            payload.command,
            epoch_ms=_clock_value(epoch_ms_clock),
        )
        return PresentationResponse(
            session_id=session_id,
            replayed=result.replayed,
            receipt=result.receipt,
        )

    @router.get("/api/v1/sound-assets/{track_id}/content.{extension}")
    async def get_sound_content(track_id: str, extension: str, request: Request) -> Response:
        participant = _participant(request, access_policy)
        try:
            snapshot = store.snapshot(table_id)
            if participant is not None and participant.role != "gm":
                if (
                    snapshot.playback.track_id != track_id
                    or snapshot.playback.status == "stopped"
                    or not audience_allows(snapshot.playback.audience, participant)
                ):
                    raise PresentationRecordNotFoundError("sound track does not exist")
            record, content = store.content(table_id, track_id)
            if record.content_path.rsplit(".", 1)[-1] != extension:
                raise PresentationRecordNotFoundError("sound track does not exist")
        except PresentationRecordNotFoundError as exc:
            raise PresentationAPIError(
                status_code=404,
                code="sound_asset_not_found",
                message="The requested sound asset is unavailable.",
            ) from exc
        except (PresentationStoreCorruptionError, PresentationStoreSchemaError) as exc:
            raise PresentationAPIError(
                status_code=500,
                code="presentation_store_corrupt",
                message="Presentation state contains invalid durable data.",
            ) from exc
        return Response(
            content=content,
            media_type=record.media_type,
            headers={
                "Cache-Control": "private, max-age=3600, immutable",
                "ETag": f'"{record.sha256}"',
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": "inline",
            },
        )

    @router.get("/api/v1/presentation-events", response_class=StreamingResponse)
    async def presentation_events(
        request: Request,
        after: Annotated[str | None, Query()] = None,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        _participant(request, access_policy)
        values = [
            value
            for value in (
                _cursor(after, "after"),
                _cursor(last_event_id, "Last-Event-ID"),
            )
            if value is not None
        ]
        cursor = max([0, *values])
        return StreamingResponse(
            _stream(request, store=store, table_id=table_id, after=cursor),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    app.include_router(router)


__all__ = [
    "PRESENTATION_PROTECTED_ROUTES",
    "PRESENTATION_PROTECTED_ROUTE_PREFIXES",
    "PresentationAPIError",
    "install_presentation_routes",
]
