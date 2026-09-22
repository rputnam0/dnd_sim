"""Optional authenticated HTTP and SSE transport for a durable scene library."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator, Mapping
from typing import Annotated, Any, Literal, Self

from fastapi import APIRouter, FastAPI, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, JsonValue, field_validator, model_validator

from .access import TableAccessPolicy
from .map_asset_store import (
    SQLiteMapAssetStore,
    MapAssetNotFoundError,
    MapAssetStoreCorruptionError,
    MapAssetStoreError,
    MapAssetStoreSchemaError,
)
from .participants import TableParticipant
from .scene_library_contracts import (
    SceneActivatedEvent,
    SceneArchivedEvent,
    SceneCreateCommand,
    SceneCreatedEvent,
    SceneDuplicatedEvent,
    SceneImportedEvent,
    SceneImportCommand,
    SceneLibraryView,
    SceneMutationCommand,
    SceneMutationEvent,
    SceneUpdateCommand,
    SceneUpdatedEvent,
)
from .scene_library_store import (
    SQLiteSceneLibrary,
    SceneActiveArchiveError,
    SceneAlreadyActiveError,
    SceneArchivedError,
    SceneCommandConflictError,
    SceneIdConflictError,
    SceneImportConflictError,
    SceneLibraryStoreCorruptionError,
    SceneLibraryStoreError,
    SceneLibraryStoreSchemaError,
    SceneNotFoundError,
    SceneRevisionConflictError,
    SceneSuccessorError,
)

VTT_SCENE_LIBRARY_REQUEST_SCHEMA_VERSION = "vtt.scene_library_request.v1"
VTT_SCENE_LIBRARY_RESPONSE_SCHEMA_VERSION = "vtt.scene_library_response.v1"

SSE_POLL_INTERVAL_SECONDS = 0.25
SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0

SCENE_LIBRARY_PROTECTED_ROUTES = frozenset(
    {
        ("GET", "/api/v1/scenes"),
        ("POST", "/api/v1/scene-commands"),
        ("GET", "/api/v1/scene-events"),
    }
)


class _StrictSceneHTTPModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _canonical_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    return value


def _canonicalize_browser_calibration_numbers(
    value: Any,
    *,
    field_name: str | None = None,
) -> Any:
    """Restore float semantics lost when browsers stringify whole-valued numbers."""

    if (
        field_name
        in {
            "grid_size_px",
            "origin_x_px",
            "origin_y_px",
            "cell_extent_px",
            "distance_ft",
        }
        and type(value) is int
    ):
        return float(value)
    if isinstance(value, Mapping):
        return {
            key: _canonicalize_browser_calibration_numbers(item, field_name=str(key))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _canonicalize_browser_calibration_numbers(item, field_name=field_name) for item in value
        ]
    return value


class SceneLibraryRequest(_StrictSceneHTTPModel):
    schema_version: Literal[VTT_SCENE_LIBRARY_REQUEST_SCHEMA_VERSION] = (
        VTT_SCENE_LIBRARY_REQUEST_SCHEMA_VERSION
    )
    session_id: str
    command: SceneMutationCommand

    @model_validator(mode="before")
    @classmethod
    def canonicalize_browser_numbers(cls, value: Any) -> Any:
        return _canonicalize_browser_calibration_numbers(value)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="session_id")


class SceneLibraryResponse(_StrictSceneHTTPModel):
    schema_version: Literal[VTT_SCENE_LIBRARY_RESPONSE_SCHEMA_VERSION] = (
        VTT_SCENE_LIBRARY_RESPONSE_SCHEMA_VERSION
    )
    session_id: str
    table_id: str
    command_id: str
    revision: int
    replayed: bool
    event: SceneMutationEvent

    @field_validator("session_id", "table_id", "command_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @field_validator("revision")
    @classmethod
    def validate_revision(cls, value: int) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError("revision must be a positive integer")
        return value

    @field_validator("replayed", mode="before")
    @classmethod
    def validate_replayed(cls, value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError("replayed must be a boolean")
        return value

    @model_validator(mode="after")
    def validate_event_identity(self) -> Self:
        if (
            self.event.table_id != self.table_id
            or self.event.command_id != self.command_id
            or self.event.revision != self.revision
        ):
            raise ValueError("event identity must match the scene response")
        return self


class SceneLibraryAPIError(RuntimeError):
    """Stable scene transport failure rendered by the parent VTT app."""

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


def _corrupt_store_error() -> SceneLibraryAPIError:
    return SceneLibraryAPIError(
        status_code=500,
        code="scene_store_corrupt",
        message="The scene library contains invalid durable data.",
    )


def _unavailable_store_error() -> SceneLibraryAPIError:
    return SceneLibraryAPIError(
        status_code=503,
        code="scene_storage_unavailable",
        message="The scene library could not be persisted or read.",
    )


def _read_view(library: SQLiteSceneLibrary, *, table_id: str) -> SceneLibraryView:
    try:
        return library.snapshot(table_id)
    except (SceneLibraryStoreCorruptionError, SceneLibraryStoreSchemaError) as exc:
        raise _corrupt_store_error() from exc
    except (sqlite3.Error, SceneLibraryStoreError) as exc:
        raise _unavailable_store_error() from exc


def _events_after(
    library: SQLiteSceneLibrary,
    *,
    table_id: str,
    sequence: int,
) -> tuple[SceneMutationEvent, ...]:
    try:
        return library.events_after(table_id, sequence)
    except (SceneLibraryStoreCorruptionError, SceneLibraryStoreSchemaError) as exc:
        raise _corrupt_store_error() from exc
    except (sqlite3.Error, SceneLibraryStoreError) as exc:
        raise _unavailable_store_error() from exc


def _request_participant(
    request: Request,
    *,
    access_policy: TableAccessPolicy | None,
) -> TableParticipant | None:
    if access_policy is None:
        return None
    participant = getattr(request.state, "vtt_participant", None)
    if not isinstance(participant, TableParticipant):
        raise RuntimeError("a protected scene request is missing its principal")
    canonical = access_policy.roster.participant(participant.participant_id)
    if canonical is None or canonical != participant:
        raise RuntimeError("a protected scene request has a noncanonical principal")
    return participant


def _scene_forbidden() -> SceneLibraryAPIError:
    return SceneLibraryAPIError(
        status_code=403,
        code="scene_forbidden",
        message="This participant is not permitted to mutate the scene library.",
    )


def _visible_view(
    view: SceneLibraryView,
    participant: TableParticipant | None,
) -> SceneLibraryView:
    if participant is None or participant.role == "gm":
        return view
    active_entry = None if view.active_scene_id is None else view.scene(view.active_scene_id)
    return SceneLibraryView(
        table_id=view.table_id,
        revision=view.revision,
        active_scene_id=view.active_scene_id,
        scenes=() if active_entry is None else (active_entry,),
    )


def _event_visible_to(
    event: SceneMutationEvent,
    participant: TableParticipant | None,
) -> bool:
    if participant is None or participant.role == "gm":
        return True
    if isinstance(event, (SceneCreatedEvent, SceneImportedEvent)):
        return event.became_active
    if isinstance(event, SceneDuplicatedEvent):
        return False
    if isinstance(event, SceneUpdatedEvent):
        return event.active
    if isinstance(event, SceneActivatedEvent):
        return True
    return isinstance(event, SceneArchivedEvent) and event.successor_scene_id is not None


def _binding_error(*, session_id: str, table_id: str) -> SceneLibraryAPIError:
    return SceneLibraryAPIError(
        status_code=409,
        code="scene_binding_mismatch",
        message="The scene request belongs to a different table or session.",
        details={
            "expected_session_id": session_id,
            "expected_table_id": table_id,
        },
    )


def _execute_library(
    library: SQLiteSceneLibrary,
    command: SceneMutationCommand,
):
    try:
        return library.execute(command)
    except SceneRevisionConflictError as exc:
        raise SceneLibraryAPIError(
            status_code=409,
            code="scene_stale_revision",
            message="The scene command targets a stale library revision.",
            details={"current_revision": exc.current_revision},
        ) from exc
    except SceneCommandConflictError as exc:
        raise SceneLibraryAPIError(
            status_code=409,
            code="scene_command_id_conflict",
            message="The scene command ID is already committed with different content.",
        ) from exc
    except SceneImportConflictError as exc:
        raise SceneLibraryAPIError(
            status_code=409,
            code="scene_import_conflict",
            message="The imported scene ID was already used.",
        ) from exc
    except SceneIdConflictError as exc:
        raise SceneLibraryAPIError(
            status_code=409,
            code="scene_id_conflict",
            message="The scene ID was already used.",
        ) from exc
    except SceneNotFoundError as exc:
        raise SceneLibraryAPIError(
            status_code=404,
            code="scene_not_found",
            message="The requested scene does not exist.",
        ) from exc
    except SceneArchivedError as exc:
        raise SceneLibraryAPIError(
            status_code=409,
            code="scene_archived",
            message="The requested scene is archived.",
        ) from exc
    except SceneAlreadyActiveError as exc:
        raise SceneLibraryAPIError(
            status_code=409,
            code="scene_already_active",
            message="The requested scene is already active.",
        ) from exc
    except SceneActiveArchiveError as exc:
        raise SceneLibraryAPIError(
            status_code=409,
            code="scene_active_archive_requires_successor",
            message="The active scene requires an available successor before archival.",
        ) from exc
    except SceneSuccessorError as exc:
        raise SceneLibraryAPIError(
            status_code=409,
            code="scene_invalid_successor",
            message="The scene archive successor is not available.",
        ) from exc
    except (SceneLibraryStoreCorruptionError, SceneLibraryStoreSchemaError) as exc:
        raise _corrupt_store_error() from exc
    except (sqlite3.Error, SceneLibraryStoreError) as exc:
        raise _unavailable_store_error() from exc


def _command_map_metadata(command: SceneMutationCommand):
    if isinstance(command, SceneCreateCommand):
        return command.scene.map_metadata
    if isinstance(command, SceneUpdateCommand):
        return command.map_metadata
    if isinstance(command, SceneImportCommand):
        return command.bundle.scene.map_metadata
    return None


def _validate_managed_asset_reference(
    library: SQLiteSceneLibrary,
    asset_store: SQLiteMapAssetStore,
    *,
    table_id: str,
    command: SceneMutationCommand,
) -> None:
    metadata = _command_map_metadata(command)
    if metadata is None or metadata.asset is None:
        return
    reference = metadata.asset
    if reference.content_path.startswith("/api/v1/map-assets/"):
        try:
            stored, _content = asset_store.content(table_id, reference.asset_id)
        except MapAssetNotFoundError as exc:
            raise SceneLibraryAPIError(
                status_code=404,
                code="scene_asset_not_found",
                message="The referenced map asset is unavailable.",
            ) from exc
        except (MapAssetStoreCorruptionError, MapAssetStoreSchemaError) as exc:
            raise SceneLibraryAPIError(
                status_code=500,
                code="scene_asset_store_corrupt",
                message="The map asset catalog contains invalid durable data.",
            ) from exc
        except (sqlite3.Error, MapAssetStoreError) as exc:
            raise SceneLibraryAPIError(
                status_code=503,
                code="scene_asset_storage_unavailable",
                message="The referenced map asset could not be read.",
            ) from exc
        if stored.reference != reference:
            raise SceneLibraryAPIError(
                status_code=409,
                code="scene_asset_mismatch",
                message="The map reference does not match the durable asset record.",
            )
        if metadata.width_px != stored.width_px or metadata.height_px != stored.height_px:
            raise SceneLibraryAPIError(
                status_code=409,
                code="scene_asset_dimensions_mismatch",
                message="The scene dimensions do not match the durable map asset.",
            )
        return

    view = _read_view(library, table_id=table_id)
    trusted_static_references = {
        entry.scene.map_metadata.asset
        for entry in view.scenes
        if entry.scene.map_metadata.asset is not None
        and entry.scene.map_metadata.asset.content_path.startswith("/assets/maps/")
    }
    if reference not in trusted_static_references:
        raise SceneLibraryAPIError(
            status_code=409,
            code="scene_asset_unmanaged",
            message="Static map references must already be trusted by this table.",
        )


def _event_cursor(value: str | None, *, field: str) -> int | None:
    if value is None:
        return None
    if not value or any(character not in "0123456789" for character in value):
        raise SceneLibraryAPIError(
            status_code=400,
            code="invalid_scene_event_cursor",
            message="The scene event cursor must be a canonical non-negative integer.",
            details={"field": field},
        )
    try:
        cursor = int(value)
    except (ValueError, OverflowError) as exc:
        raise SceneLibraryAPIError(
            status_code=400,
            code="invalid_scene_event_cursor",
            message="The scene event cursor must be a canonical non-negative integer.",
            details={"field": field},
        ) from exc
    if str(cursor) != value:
        raise SceneLibraryAPIError(
            status_code=400,
            code="invalid_scene_event_cursor",
            message="The scene event cursor must be a canonical non-negative integer.",
            details={"field": field},
        )
    return cursor


def _resume_after(*, after: str | None, last_event_id: str | None) -> int:
    query_cursor = _event_cursor(after, field="after")
    header_cursor = _event_cursor(last_event_id, field="Last-Event-ID")
    return max(cursor for cursor in (0, query_cursor, header_cursor) if cursor is not None)


def _render_sse_event(event: SceneMutationEvent) -> str:
    payload = json.dumps(
        event.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"id: {event.sequence}\nevent: vtt.scene_event\ndata: {payload}\n\n"


async def _stream_scene_events(
    *,
    request: Request,
    library: SQLiteSceneLibrary,
    table_id: str,
    after: int,
    initial_events: tuple[SceneMutationEvent, ...],
    participant: TableParticipant | None,
) -> AsyncIterator[str]:
    cursor = after
    pending_events = initial_events
    event_loop = asyncio.get_running_loop()
    next_heartbeat = event_loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
    while True:
        if await request.is_disconnected():
            return
        events = pending_events
        pending_events = ()
        if not events:
            events = _events_after(library, table_id=table_id, sequence=cursor)
        if events:
            yielded_visible_event = False
            for event in events:
                if await request.is_disconnected():
                    return
                cursor = event.sequence
                if not _event_visible_to(event, participant):
                    continue
                yield _render_sse_event(event)
                yielded_visible_event = True
            if yielded_visible_event:
                next_heartbeat = event_loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
        elif event_loop.time() >= next_heartbeat:
            yield ": heartbeat\n\n"
            next_heartbeat = event_loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
        await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)


def install_scene_library_routes(
    app: FastAPI,
    *,
    library: SQLiteSceneLibrary,
    session_id: str,
    table_id: str,
    access_policy: TableAccessPolicy | None,
    map_asset_store: SQLiteMapAssetStore | None = None,
) -> None:
    """Install optional scene routes without changing encounter HTTP schemas."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")
    if not isinstance(library, SQLiteSceneLibrary):
        raise TypeError("library must be a SQLiteSceneLibrary")
    configured_session_id = _canonical_text(session_id, field_name="session_id")
    configured_table_id = _canonical_text(table_id, field_name="table_id")
    router = APIRouter()

    @router.get("/api/v1/scenes", response_model=SceneLibraryView)
    async def get_scenes(request: Request) -> SceneLibraryView:
        participant = _request_participant(request, access_policy=access_policy)
        view = _read_view(library, table_id=configured_table_id)
        return _visible_view(view, participant)

    @router.post("/api/v1/scene-commands", response_model=SceneLibraryResponse)
    async def execute_scene_command(
        payload: SceneLibraryRequest,
        request: Request,
    ) -> SceneLibraryResponse:
        participant = _request_participant(request, access_policy=access_policy)
        if participant is not None and participant.role != "gm":
            raise _scene_forbidden()
        if (
            payload.session_id != configured_session_id
            or payload.command.table_id != configured_table_id
        ):
            raise _binding_error(
                session_id=configured_session_id,
                table_id=configured_table_id,
            )
        if map_asset_store is not None:
            _validate_managed_asset_reference(
                library,
                map_asset_store,
                table_id=configured_table_id,
                command=payload.command,
            )
        result = _execute_library(library, payload.command)
        return SceneLibraryResponse(
            session_id=configured_session_id,
            table_id=configured_table_id,
            command_id=result.receipt.command_id,
            revision=result.receipt.revision,
            replayed=result.replayed,
            event=result.receipt.event,
        )

    @router.get("/api/v1/scene-events", response_class=StreamingResponse)
    async def get_scene_events(
        request: Request,
        after: Annotated[str | None, Query()] = None,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        participant = _request_participant(request, access_policy=access_policy)
        cursor = _resume_after(after=after, last_event_id=last_event_id)
        initial_events = _events_after(
            library,
            table_id=configured_table_id,
            sequence=cursor,
        )
        return StreamingResponse(
            _stream_scene_events(
                request=request,
                library=library,
                table_id=configured_table_id,
                after=cursor,
                initial_events=initial_events,
                participant=participant,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    app.include_router(router)


__all__ = [
    "SCENE_LIBRARY_PROTECTED_ROUTES",
    "VTT_SCENE_LIBRARY_REQUEST_SCHEMA_VERSION",
    "VTT_SCENE_LIBRARY_RESPONSE_SCHEMA_VERSION",
    "SceneLibraryAPIError",
    "SceneLibraryRequest",
    "SceneLibraryResponse",
    "install_scene_library_routes",
]
