"""Optional HTTP and SSE transport for one durable VTT annotation board."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Self

from fastapi import APIRouter, FastAPI, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from .access import TableAccessPolicy
from .annotation_store import (
    AnnotationCommandConflictError,
    AnnotationDeleteCommand,
    AnnotationDeleteEvent,
    AnnotationExecutionResult,
    AnnotationMutationCommand,
    AnnotationMutationEvent,
    AnnotationMutationReceipt,
    AnnotationNotFoundError,
    AnnotationPutCommand,
    AnnotationPutEvent,
    AnnotationRevisionConflictError,
    AnnotationStoreCorruptionError,
    AnnotationStoreError,
    AnnotationStoreSchemaError,
    SQLiteAnnotationBoard,
)
from .annotations import VTTAnnotation, parse_annotation
from .participants import (
    TableParticipant,
    TableRoster,
    audience_allows,
    validate_audience_selectors,
)
from .scene import SquareGridScene

VTT_ANNOTATIONS_VIEW_SCHEMA_VERSION = "vtt.annotations_view.v1"
VTT_ANNOTATION_REQUEST_SCHEMA_VERSION = "vtt.annotation_request.v1"
VTT_ANNOTATION_RESPONSE_SCHEMA_VERSION = "vtt.annotation_response.v1"
OPEN_LOCAL_ANNOTATION_AUTHOR_ID = "local"

SSE_POLL_INTERVAL_SECONDS = 0.25
SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0

ANNOTATION_PROTECTED_ROUTES = frozenset(
    {
        ("GET", "/api/v1/annotations"),
        ("POST", "/api/v1/annotation-commands"),
        ("GET", "/api/v1/annotation-events"),
    }
)

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]


class _StrictAnnotationHTTPModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _canonical_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    return value


def _canonicalize_float_semantics(value: Any, *, field_name: str | None = None) -> Any:
    """Convert browser-shaped integral JSON numbers only for annotation float fields."""

    is_float_field = bool(
        field_name is not None and (field_name.endswith("_ft") or field_name.endswith("_degrees"))
    )
    if is_float_field and type(value) is int:
        return float(value)
    if isinstance(value, Mapping):
        return {
            key: _canonicalize_float_semantics(item, field_name=str(key))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize_float_semantics(item, field_name=field_name) for item in value]
    return value


class VTTAnnotationRequest(_StrictAnnotationHTTPModel):
    """One session-bound request wrapping the durable board command contract."""

    schema_version: Literal[VTT_ANNOTATION_REQUEST_SCHEMA_VERSION] = (
        VTT_ANNOTATION_REQUEST_SCHEMA_VERSION
    )
    session_id: str
    command: AnnotationMutationCommand

    @model_validator(mode="before")
    @classmethod
    def canonicalize_browser_annotation_numbers(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        command = value.get("command")
        if not isinstance(command, Mapping) or command.get("command_type") != "put":
            return value
        annotation = command.get("annotation")
        if not isinstance(annotation, Mapping):
            return value
        raw_audience = annotation.get("audience", ("all",))
        try:
            validate_audience_selectors(raw_audience)
        except (TypeError, ValueError) as exc:
            raise ValueError("annotation audience must use canonical selectors") from exc
        normalized_command = dict(command)
        normalized_command["annotation"] = _canonicalize_float_semantics(annotation)
        return {**value, "command": normalized_command}

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="session_id")


class VTTAnnotationsView(_StrictAnnotationHTTPModel):
    """Exact current annotation projection for one configured table scene."""

    schema_version: Literal[VTT_ANNOTATIONS_VIEW_SCHEMA_VERSION] = (
        VTT_ANNOTATIONS_VIEW_SCHEMA_VERSION
    )
    session_id: str
    table_id: str
    scene_id: str
    revision: NonNegativeInt
    annotations: tuple[VTTAnnotation, ...] = ()

    @field_validator("session_id", "table_id", "scene_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        annotation_ids = tuple(item.annotation_id for item in self.annotations)
        if annotation_ids != tuple(sorted(annotation_ids)):
            raise ValueError("annotations must use canonical annotation-id order")
        if len(set(annotation_ids)) != len(annotation_ids):
            raise ValueError("annotations must not contain duplicate IDs")
        if any(item.scene_id != self.scene_id for item in self.annotations):
            raise ValueError("annotations must belong to scene_id")
        return self


class VTTAnnotationResponse(_StrictAnnotationHTTPModel):
    """Session-bound result of one durable annotation mutation."""

    schema_version: Literal[VTT_ANNOTATION_RESPONSE_SCHEMA_VERSION] = (
        VTT_ANNOTATION_RESPONSE_SCHEMA_VERSION
    )
    session_id: str
    replayed: bool
    receipt: AnnotationMutationReceipt

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="session_id")

    @field_validator("replayed", mode="before")
    @classmethod
    def validate_replayed(cls, value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError("replayed must be a boolean")
        return value


class AnnotationAPIError(RuntimeError):
    """Stable annotation transport failure rendered by the parent VTT app."""

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


@dataclass(frozen=True, slots=True)
class _HistoricalMutation:
    event: AnnotationMutationEvent
    annotation: VTTAnnotation


@dataclass(frozen=True, slots=True)
class _BoardState:
    revision: int
    annotations: dict[str, VTTAnnotation]
    commands: dict[str, _HistoricalMutation]


def _corrupt_store_error() -> AnnotationAPIError:
    return AnnotationAPIError(
        status_code=500,
        code="annotation_store_corrupt",
        message="The annotation store contains invalid durable data.",
    )


def _unavailable_store_error() -> AnnotationAPIError:
    return AnnotationAPIError(
        status_code=503,
        code="annotation_storage_unavailable",
        message="The annotation board could not be persisted or read.",
    )


def _events_after(
    board: SQLiteAnnotationBoard,
    *,
    table_id: str,
    sequence: int,
) -> tuple[AnnotationMutationEvent, ...]:
    try:
        return board.events_after(table_id, sequence)
    except (AnnotationStoreCorruptionError, AnnotationStoreSchemaError) as exc:
        raise _corrupt_store_error() from exc
    except (sqlite3.Error, AnnotationStoreError) as exc:
        raise _unavailable_store_error() from exc


def _fold_board(events: tuple[AnnotationMutationEvent, ...]) -> _BoardState:
    annotations: dict[str, VTTAnnotation] = {}
    commands: dict[str, _HistoricalMutation] = {}
    expected_sequence = 1
    expected_revision = 1
    try:
        for event in events:
            if event.sequence != expected_sequence or event.revision != expected_revision:
                raise AnnotationStoreCorruptionError(
                    "stored annotation history has a sequence or revision gap"
                )
            if event.command_id in commands:
                raise AnnotationStoreCorruptionError(
                    "stored annotation history has a duplicate command ID"
                )
            if isinstance(event, AnnotationPutEvent):
                annotation = event.annotation
                annotations[event.annotation_id] = annotation
            else:
                annotation = annotations.get(event.annotation_id)
                if annotation is None:
                    raise AnnotationStoreCorruptionError(
                        "stored delete event targets a missing annotation"
                    )
                if annotation.scene_id != event.scene_id or annotation.audience != event.audience:
                    raise AnnotationStoreCorruptionError(
                        "stored delete tombstone does not match its annotation"
                    )
                del annotations[event.annotation_id]
            commands[event.command_id] = _HistoricalMutation(
                event=event,
                annotation=annotation,
            )
            expected_sequence += 1
            expected_revision += 1
    except AnnotationStoreCorruptionError as exc:
        raise _corrupt_store_error() from exc
    return _BoardState(
        revision=expected_revision - 1,
        annotations=annotations,
        commands=commands,
    )


def _read_board_state(board: SQLiteAnnotationBoard, *, table_id: str) -> _BoardState:
    return _fold_board(_events_after(board, table_id=table_id, sequence=0))


def _validate_audience_policy(audience: tuple[str, ...], roster: TableRoster | None) -> None:
    try:
        selectors = validate_audience_selectors(audience)
    except (TypeError, ValueError) as exc:
        raise AnnotationAPIError(
            status_code=422,
            code="invalid_annotation_audience",
            message="The annotation audience is not supported by this table.",
        ) from exc
    if roster is None:
        return
    participant_ids = {item.participant_id for item in roster.participants}
    actor_ids = {actor_id for item in roster.participants for actor_id in item.owned_actor_ids}
    for selector in selectors:
        if selector.startswith("participant:"):
            participant_id = selector.removeprefix("participant:")
            if participant_id not in participant_ids:
                break
        elif selector.startswith("actor:"):
            actor_id = selector.removeprefix("actor:")
            if actor_id not in actor_ids:
                break
    else:
        return
    raise AnnotationAPIError(
        status_code=422,
        code="invalid_annotation_audience",
        message="The annotation audience is not supported by this table.",
    )


def _validate_stored_annotation(
    annotation: VTTAnnotation,
    *,
    roster: TableRoster | None,
) -> None:
    try:
        _validate_audience_policy(annotation.audience, roster)
    except AnnotationAPIError as exc:
        raise _corrupt_store_error() from exc
    if roster is not None and roster.participant(annotation.author_id) is None:
        raise _corrupt_store_error()


def _visible_to(
    audience: tuple[str, ...],
    participant: TableParticipant | None,
) -> bool:
    if participant is None:
        return True
    try:
        return audience_allows(audience, participant)
    except (TypeError, ValueError) as exc:
        raise _corrupt_store_error() from exc


def _request_participant(
    request: Request,
    *,
    access_policy: TableAccessPolicy | None,
) -> TableParticipant | None:
    if access_policy is None:
        return None
    participant = getattr(request.state, "vtt_participant", None)
    if not isinstance(participant, TableParticipant):
        raise RuntimeError("a protected annotation request is missing its principal")
    canonical = access_policy.roster.participant(participant.participant_id)
    if canonical is None or canonical != participant:
        raise RuntimeError("a protected annotation request has a noncanonical principal")
    return participant


def _annotation_forbidden() -> AnnotationAPIError:
    return AnnotationAPIError(
        status_code=403,
        code="annotation_forbidden",
        message="This participant is not permitted to mutate the annotation.",
    )


def _authorize_owner(
    participant: TableParticipant | None,
    annotation: VTTAnnotation | None,
) -> None:
    if participant is None or participant.role == "gm":
        return
    if participant.role != "player":
        raise _annotation_forbidden()
    if annotation is not None and annotation.author_id != participant.participant_id:
        raise _annotation_forbidden()


def _binding_error(*, session_id: str, table_id: str) -> AnnotationAPIError:
    return AnnotationAPIError(
        status_code=409,
        code="annotation_binding_mismatch",
        message="The annotation request belongs to a different table or session.",
        details={
            "expected_session_id": session_id,
            "expected_table_id": table_id,
        },
    )


def _scene_error(*, scene_id: str) -> AnnotationAPIError:
    return AnnotationAPIError(
        status_code=409,
        code="annotation_scene_mismatch",
        message="The annotation request belongs to a different scene.",
        details={"expected_scene_id": scene_id},
    )


def _execute_board(
    board: SQLiteAnnotationBoard,
    command: AnnotationMutationCommand,
    *,
    current_revision: int,
) -> AnnotationExecutionResult:
    try:
        return board.execute(command)
    except AnnotationRevisionConflictError as exc:
        raise AnnotationAPIError(
            status_code=409,
            code="annotation_stale_revision",
            message="The annotation command targets a stale board revision.",
            details={"current_revision": current_revision},
        ) from exc
    except AnnotationCommandConflictError as exc:
        raise AnnotationAPIError(
            status_code=409,
            code="annotation_command_id_conflict",
            message="The annotation command ID is already committed with different content.",
        ) from exc
    except AnnotationNotFoundError as exc:
        raise AnnotationAPIError(
            status_code=404,
            code="annotation_not_found",
            message="The requested annotation does not exist.",
        ) from exc
    except (AnnotationStoreCorruptionError, AnnotationStoreSchemaError) as exc:
        raise _corrupt_store_error() from exc
    except (sqlite3.Error, AnnotationStoreError) as exc:
        raise _unavailable_store_error() from exc


def _normalize_put_command(
    command: AnnotationPutCommand,
    *,
    participant: TableParticipant | None,
    existing: VTTAnnotation | None,
) -> AnnotationPutCommand:
    if existing is not None:
        author_id = existing.author_id
    elif participant is None:
        author_id = OPEN_LOCAL_ANNOTATION_AUTHOR_ID
    else:
        author_id = participant.participant_id
    annotation = parse_annotation(
        {
            **command.annotation.model_dump(mode="json"),
            "author_id": author_id,
        }
    )
    return AnnotationPutCommand(
        table_id=command.table_id,
        command_id=command.command_id,
        expected_revision=command.expected_revision,
        annotation=annotation,
    )


def _event_scene_and_audience(
    event: AnnotationMutationEvent,
) -> tuple[str, tuple[str, ...]]:
    if isinstance(event, AnnotationPutEvent):
        return event.annotation.scene_id, event.annotation.audience
    return event.scene_id, event.audience


def _validate_stream_event(
    event: AnnotationMutationEvent,
    *,
    roster: TableRoster | None,
) -> None:
    if isinstance(event, AnnotationPutEvent):
        _validate_stored_annotation(event.annotation, roster=roster)
        return
    try:
        _validate_audience_policy(event.audience, roster)
    except AnnotationAPIError as exc:
        raise _corrupt_store_error() from exc


def _event_is_visible(
    event: AnnotationMutationEvent,
    *,
    scene_id: str,
    participant: TableParticipant | None,
) -> bool:
    event_scene_id, audience = _event_scene_and_audience(event)
    return event_scene_id == scene_id and _visible_to(audience, participant)


def _event_cursor(value: str | None, *, field: str) -> int | None:
    if value is None:
        return None
    if not value or any(character not in "0123456789" for character in value):
        raise AnnotationAPIError(
            status_code=400,
            code="invalid_annotation_event_cursor",
            message="The annotation event cursor must be a canonical non-negative integer.",
            details={"field": field},
        )
    try:
        cursor = int(value)
    except (ValueError, OverflowError) as exc:
        raise AnnotationAPIError(
            status_code=400,
            code="invalid_annotation_event_cursor",
            message="The annotation event cursor must be a canonical non-negative integer.",
            details={"field": field},
        ) from exc
    if str(cursor) != value:
        raise AnnotationAPIError(
            status_code=400,
            code="invalid_annotation_event_cursor",
            message="The annotation event cursor must be a canonical non-negative integer.",
            details={"field": field},
        )
    return cursor


def _resume_after(*, after: str | None, last_event_id: str | None) -> int:
    query_cursor = _event_cursor(after, field="after")
    header_cursor = _event_cursor(last_event_id, field="Last-Event-ID")
    return max(cursor for cursor in (0, query_cursor, header_cursor) if cursor is not None)


def _render_sse_event(event: AnnotationMutationEvent) -> str:
    payload = json.dumps(
        event.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"id: {event.sequence}\nevent: vtt.annotation_event\ndata: {payload}\n\n"


async def _stream_annotation_events(
    *,
    request: Request,
    board: SQLiteAnnotationBoard,
    table_id: str,
    scene_id: str,
    after: int,
    initial_events: tuple[AnnotationMutationEvent, ...],
    participant: TableParticipant | None,
    roster: TableRoster | None,
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
            events = _events_after(board, table_id=table_id, sequence=cursor)
        if events:
            yielded_visible_event = False
            for event in events:
                if await request.is_disconnected():
                    return
                cursor = event.sequence
                _validate_stream_event(event, roster=roster)
                if not _event_is_visible(
                    event,
                    scene_id=scene_id,
                    participant=participant,
                ):
                    continue
                yield _render_sse_event(event)
                yielded_visible_event = True
            if yielded_visible_event:
                next_heartbeat = event_loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
        elif event_loop.time() >= next_heartbeat:
            yield ": heartbeat\n\n"
            next_heartbeat = event_loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
        await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)


def install_annotation_routes(
    app: FastAPI,
    *,
    board: SQLiteAnnotationBoard,
    session_id: str,
    table_id: str,
    scene: SquareGridScene,
    access_policy: TableAccessPolicy | None,
) -> None:
    """Install optional board routes without changing the engine HTTP schemas."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")
    if not isinstance(board, SQLiteAnnotationBoard):
        raise TypeError("board must be a SQLiteAnnotationBoard")
    configured_session_id = _canonical_text(session_id, field_name="session_id")
    configured_table_id = _canonical_text(table_id, field_name="table_id")
    if not isinstance(scene, SquareGridScene):
        raise TypeError("scene must be a SquareGridScene")
    configured_scene = scene.model_copy(deep=True)
    roster = None if access_policy is None else access_policy.roster
    router = APIRouter()

    @router.get("/api/v1/annotations", response_model=VTTAnnotationsView)
    async def get_annotations(request: Request) -> VTTAnnotationsView:
        participant = _request_participant(request, access_policy=access_policy)
        state = _read_board_state(board, table_id=configured_table_id)
        visible: list[VTTAnnotation] = []
        for annotation_id in sorted(state.annotations):
            annotation = state.annotations[annotation_id]
            if annotation.scene_id != configured_scene.scene_id:
                continue
            _validate_stored_annotation(annotation, roster=roster)
            if _visible_to(annotation.audience, participant):
                visible.append(annotation)
        return VTTAnnotationsView(
            session_id=configured_session_id,
            table_id=configured_table_id,
            scene_id=configured_scene.scene_id,
            revision=state.revision,
            annotations=tuple(visible),
        )

    @router.post(
        "/api/v1/annotation-commands",
        response_model=VTTAnnotationResponse,
    )
    async def execute_annotation_command(
        payload: VTTAnnotationRequest,
        request: Request,
    ) -> VTTAnnotationResponse:
        participant = _request_participant(request, access_policy=access_policy)
        if participant is not None and participant.role == "spectator":
            raise _annotation_forbidden()
        if (
            payload.session_id != configured_session_id
            or payload.command.table_id != configured_table_id
        ):
            raise _binding_error(
                session_id=configured_session_id,
                table_id=configured_table_id,
            )

        state = _read_board_state(board, table_id=configured_table_id)
        historical = state.commands.get(payload.command.command_id)
        if historical is not None:
            target = historical.annotation
        else:
            target_id = (
                payload.command.annotation.annotation_id
                if isinstance(payload.command, AnnotationPutCommand)
                else payload.command.annotation_id
            )
            target = state.annotations.get(target_id)
        if target is not None:
            _validate_stored_annotation(target, roster=roster)
        _authorize_owner(participant, target)

        command: AnnotationMutationCommand
        if isinstance(payload.command, AnnotationPutCommand):
            if payload.command.annotation.scene_id != configured_scene.scene_id:
                raise _scene_error(scene_id=configured_scene.scene_id)
            if target is not None and target.scene_id != configured_scene.scene_id:
                raise _scene_error(scene_id=configured_scene.scene_id)
            _validate_audience_policy(payload.command.annotation.audience, roster)
            command = _normalize_put_command(
                payload.command,
                participant=participant,
                existing=target,
            )
        else:
            if target is None:
                raise AnnotationAPIError(
                    status_code=404,
                    code="annotation_not_found",
                    message="The requested annotation does not exist.",
                )
            if target.scene_id != configured_scene.scene_id:
                raise _scene_error(scene_id=configured_scene.scene_id)
            command = payload.command

        result = _execute_board(
            board,
            command,
            current_revision=state.revision,
        )
        return VTTAnnotationResponse(
            session_id=configured_session_id,
            replayed=result.replayed,
            receipt=result.receipt,
        )

    @router.get("/api/v1/annotation-events", response_class=StreamingResponse)
    async def get_annotation_events(
        request: Request,
        after: Annotated[str | None, Query()] = None,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        participant = _request_participant(request, access_policy=access_policy)
        cursor = _resume_after(after=after, last_event_id=last_event_id)
        initial_events = _events_after(
            board,
            table_id=configured_table_id,
            sequence=cursor,
        )
        for event in initial_events:
            _validate_stream_event(event, roster=roster)
        return StreamingResponse(
            _stream_annotation_events(
                request=request,
                board=board,
                table_id=configured_table_id,
                scene_id=configured_scene.scene_id,
                after=cursor,
                initial_events=initial_events,
                participant=participant,
                roster=roster,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    app.include_router(router)


__all__ = [
    "ANNOTATION_PROTECTED_ROUTES",
    "OPEN_LOCAL_ANNOTATION_AUTHOR_ID",
    "VTT_ANNOTATIONS_VIEW_SCHEMA_VERSION",
    "VTT_ANNOTATION_REQUEST_SCHEMA_VERSION",
    "VTT_ANNOTATION_RESPONSE_SCHEMA_VERSION",
    "AnnotationAPIError",
    "VTTAnnotationRequest",
    "VTTAnnotationResponse",
    "VTTAnnotationsView",
    "install_annotation_routes",
]
