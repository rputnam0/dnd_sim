"""Optional authenticated HTTP and sanitized SSE transport for VTT presence."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Any, Literal, Self

from fastapi import APIRouter, FastAPI, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from .access import TableAccessPolicy
from .participants import TableParticipant
from .presence_contracts import PresenceHeartbeatCommand, PresenceHeartbeatEvent, PresenceView
from .presence_store import (
    PresenceCommandConflictError,
    PresenceParticipantNotFoundError,
    PresenceRevisionConflictError,
    PresenceStoreCorruptionError,
    PresenceStoreError,
    PresenceStoreSchemaError,
    PresenceTableMismatchError,
    PresenceTimeRegressionError,
    SQLitePresenceStore,
)

VTT_PRESENCE_HEARTBEAT_REQUEST_SCHEMA_VERSION = "vtt.presence_heartbeat_request.v1"
VTT_PRESENCE_HEARTBEAT_RESPONSE_SCHEMA_VERSION = "vtt.presence_heartbeat_response.v1"
PRESENCE_CHANGE_SIGNAL_SCHEMA_VERSION = "vtt.presence_change_signal.v1"

SSE_POLL_INTERVAL_SECONDS = 0.25
SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0

PRESENCE_PROTECTED_ROUTES = frozenset(
    {
        ("GET", "/api/v1/presence"),
        ("POST", "/api/v1/presence-heartbeats"),
        ("GET", "/api/v1/presence-events"),
    }
)

PositiveInt = Annotated[int, Field(strict=True, ge=1)]
EpochMillisecondsClock = Callable[[], int]


class _StrictPresenceHTTPModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _canonical_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    return value


class PresenceHeartbeatRequest(_StrictPresenceHTTPModel):
    schema_version: Literal[VTT_PRESENCE_HEARTBEAT_REQUEST_SCHEMA_VERSION] = (
        VTT_PRESENCE_HEARTBEAT_REQUEST_SCHEMA_VERSION
    )
    session_id: str
    command: PresenceHeartbeatCommand

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="session_id")


class PresenceChangeSignal(_StrictPresenceHTTPModel):
    """Minimal public notification instructing clients to refetch presence."""

    schema_version: Literal[PRESENCE_CHANGE_SIGNAL_SCHEMA_VERSION] = (
        PRESENCE_CHANGE_SIGNAL_SCHEMA_VERSION
    )
    sequence: PositiveInt
    revision: PositiveInt
    participant_id: str

    @field_validator("participant_id")
    @classmethod
    def validate_participant_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="participant_id")

    @model_validator(mode="after")
    def validate_sequence_revision(self) -> Self:
        if self.sequence != self.revision:
            raise ValueError("sequence must match revision")
        return self


class PresenceHeartbeatResponse(_StrictPresenceHTTPModel):
    schema_version: Literal[VTT_PRESENCE_HEARTBEAT_RESPONSE_SCHEMA_VERSION] = (
        VTT_PRESENCE_HEARTBEAT_RESPONSE_SCHEMA_VERSION
    )
    session_id: str
    table_id: str
    command_id: str
    revision: PositiveInt
    replayed: bool
    signal: PresenceChangeSignal

    @field_validator("session_id", "table_id", "command_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @field_validator("replayed", mode="before")
    @classmethod
    def validate_replayed(cls, value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError("replayed must be a boolean")
        return value

    @model_validator(mode="after")
    def validate_signal_identity(self) -> Self:
        if self.signal.revision != self.revision:
            raise ValueError("signal.revision must match revision")
        return self


class PresenceAPIError(RuntimeError):
    """Stable presence transport failure rendered by the parent VTT app."""

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


def system_epoch_ms() -> int:
    """Return server-controlled Unix epoch milliseconds for durable comparisons."""

    return time.time_ns() // 1_000_000


def _read_epoch_ms(clock: EpochMillisecondsClock) -> int:
    try:
        value = clock()
    except Exception as exc:
        raise PresenceAPIError(
            status_code=500,
            code="presence_clock_failure",
            message="The presence clock could not be read.",
        ) from exc
    if type(value) is not int or value < 0:
        raise PresenceAPIError(
            status_code=500,
            code="presence_clock_failure",
            message="The presence clock returned an invalid epoch-millisecond value.",
        )
    return value


def _corrupt_store_error() -> PresenceAPIError:
    return PresenceAPIError(
        status_code=500,
        code="presence_store_corrupt",
        message="The presence log contains invalid durable data.",
    )


def _unavailable_store_error() -> PresenceAPIError:
    return PresenceAPIError(
        status_code=503,
        code="presence_storage_unavailable",
        message="Presence could not be persisted or read.",
    )


def _clock_regression_error() -> PresenceAPIError:
    return PresenceAPIError(
        status_code=500,
        code="presence_clock_regressed",
        message="The presence clock precedes the latest durable observation.",
    )


def _request_participant(
    request: Request,
    *,
    store: SQLitePresenceStore,
    access_policy: TableAccessPolicy | None,
) -> TableParticipant:
    if access_policy is None:
        participants = store.roster.participants
        if len(participants) != 1:
            raise RuntimeError("open-local presence requires exactly one participant")
        return participants[0]

    participant = getattr(request.state, "vtt_participant", None)
    if not isinstance(participant, TableParticipant):
        raise RuntimeError("a protected presence request is missing its principal")
    canonical = access_policy.roster.participant(participant.participant_id)
    if canonical is None or canonical != participant:
        raise RuntimeError("a protected presence request has a noncanonical principal")
    return participant


def _read_view(
    store: SQLitePresenceStore,
    *,
    participant_id: str,
    evaluated_at_ms: int,
) -> PresenceView:
    try:
        return store.view(viewer_id=participant_id, evaluated_at_ms=evaluated_at_ms)
    except PresenceTimeRegressionError as exc:
        raise _clock_regression_error() from exc
    except (PresenceStoreCorruptionError, PresenceStoreSchemaError) as exc:
        raise _corrupt_store_error() from exc
    except PresenceParticipantNotFoundError as exc:
        raise PresenceAPIError(
            status_code=500,
            code="presence_roster_mismatch",
            message="The authenticated participant is not in the presence roster.",
        ) from exc
    except (sqlite3.Error, PresenceStoreError) as exc:
        raise _unavailable_store_error() from exc


def _execute_heartbeat(
    store: SQLitePresenceStore,
    command: PresenceHeartbeatCommand,
    *,
    observed_at_ms: int,
):
    try:
        return store.heartbeat(command, observed_at_ms=observed_at_ms)
    except PresenceRevisionConflictError as exc:
        raise PresenceAPIError(
            status_code=409,
            code="presence_stale_revision",
            message="The presence heartbeat targets a stale revision.",
            details={"current_revision": exc.current_revision},
        ) from exc
    except PresenceCommandConflictError as exc:
        raise PresenceAPIError(
            status_code=409,
            code="presence_command_id_conflict",
            message="The presence command ID is already committed with different content.",
        ) from exc
    except PresenceTimeRegressionError as exc:
        raise _clock_regression_error() from exc
    except PresenceTableMismatchError as exc:
        raise PresenceAPIError(
            status_code=409,
            code="presence_binding_mismatch",
            message="The presence command belongs to a different table.",
        ) from exc
    except (PresenceStoreCorruptionError, PresenceStoreSchemaError) as exc:
        raise _corrupt_store_error() from exc
    except PresenceParticipantNotFoundError as exc:
        raise PresenceAPIError(
            status_code=500,
            code="presence_roster_mismatch",
            message="The heartbeat participant is not in the presence roster.",
        ) from exc
    except (sqlite3.Error, PresenceStoreError) as exc:
        raise _unavailable_store_error() from exc


def _events_after(
    store: SQLitePresenceStore,
    *,
    participant_id: str,
    sequence: int,
) -> tuple[PresenceHeartbeatEvent, ...]:
    try:
        return store.events_after(viewer_id=participant_id, sequence=sequence)
    except (PresenceStoreCorruptionError, PresenceStoreSchemaError) as exc:
        raise _corrupt_store_error() from exc
    except PresenceParticipantNotFoundError as exc:
        raise PresenceAPIError(
            status_code=500,
            code="presence_roster_mismatch",
            message="The authenticated participant is not in the presence roster.",
        ) from exc
    except (sqlite3.Error, PresenceStoreError) as exc:
        raise _unavailable_store_error() from exc


def _binding_error(*, session_id: str, table_id: str) -> PresenceAPIError:
    return PresenceAPIError(
        status_code=409,
        code="presence_binding_mismatch",
        message="The presence heartbeat belongs to a different table or session.",
        details={
            "expected_session_id": session_id,
            "expected_table_id": table_id,
        },
    )


def _impersonation_error() -> PresenceAPIError:
    return PresenceAPIError(
        status_code=403,
        code="presence_impersonation_forbidden",
        message="A participant may heartbeat only their authenticated presence identity.",
    )


def _event_cursor(value: str | None, *, field: str) -> int | None:
    if value is None:
        return None
    if not value or any(character not in "0123456789" for character in value):
        raise PresenceAPIError(
            status_code=400,
            code="invalid_presence_event_cursor",
            message="The presence event cursor must be a canonical non-negative integer.",
            details={"field": field},
        )
    cursor = int(value)
    if str(cursor) != value:
        raise PresenceAPIError(
            status_code=400,
            code="invalid_presence_event_cursor",
            message="The presence event cursor must be a canonical non-negative integer.",
            details={"field": field},
        )
    return cursor


def _resume_after(*, after: str | None, last_event_id: str | None) -> int:
    query_cursor = _event_cursor(after, field="after")
    header_cursor = _event_cursor(last_event_id, field="Last-Event-ID")
    return max(cursor for cursor in (0, query_cursor, header_cursor) if cursor is not None)


def _signal(event: PresenceHeartbeatEvent) -> PresenceChangeSignal:
    return PresenceChangeSignal(
        sequence=event.sequence,
        revision=event.revision,
        participant_id=event.participant_id,
    )


def _render_sse_signal(event: PresenceHeartbeatEvent) -> str:
    signal = _signal(event)
    payload = json.dumps(
        signal.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"id: {signal.sequence}\nevent: vtt.presence_changed\ndata: {payload}\n\n"


async def _stream_presence_events(
    *,
    request: Request,
    store: SQLitePresenceStore,
    participant_id: str,
    after: int,
    initial_events: tuple[PresenceHeartbeatEvent, ...],
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
            events = _events_after(
                store,
                participant_id=participant_id,
                sequence=cursor,
            )
        if events:
            for event in events:
                if await request.is_disconnected():
                    return
                cursor = event.sequence
                yield _render_sse_signal(event)
            next_heartbeat = event_loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
        elif event_loop.time() >= next_heartbeat:
            yield ": heartbeat\n\n"
            next_heartbeat = event_loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
        await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)


def install_presence_routes(
    app: FastAPI,
    *,
    store: SQLitePresenceStore,
    session_id: str,
    table_id: str,
    access_policy: TableAccessPolicy | None,
    epoch_ms_clock: EpochMillisecondsClock,
) -> None:
    """Install optional presence routes without exposing durable heartbeat internals."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")
    if not isinstance(store, SQLitePresenceStore):
        raise TypeError("store must be a SQLitePresenceStore")
    if not callable(epoch_ms_clock):
        raise TypeError("epoch_ms_clock must be callable")
    configured_session_id = _canonical_text(session_id, field_name="session_id")
    configured_table_id = _canonical_text(table_id, field_name="table_id")
    router = APIRouter()

    @router.get("/api/v1/presence", response_model=PresenceView)
    async def get_presence(request: Request) -> PresenceView:
        participant = _request_participant(
            request,
            store=store,
            access_policy=access_policy,
        )
        return _read_view(
            store,
            participant_id=participant.participant_id,
            evaluated_at_ms=_read_epoch_ms(epoch_ms_clock),
        )

    @router.post(
        "/api/v1/presence-heartbeats",
        response_model=PresenceHeartbeatResponse,
    )
    async def execute_presence_heartbeat(
        payload: PresenceHeartbeatRequest,
        request: Request,
    ) -> PresenceHeartbeatResponse:
        participant = _request_participant(
            request,
            store=store,
            access_policy=access_policy,
        )
        if payload.command.participant_id != participant.participant_id:
            raise _impersonation_error()
        if (
            payload.session_id != configured_session_id
            or payload.command.table_id != configured_table_id
        ):
            raise _binding_error(
                session_id=configured_session_id,
                table_id=configured_table_id,
            )
        result = _execute_heartbeat(
            store,
            payload.command,
            observed_at_ms=_read_epoch_ms(epoch_ms_clock),
        )
        signal = _signal(result.receipt.event)
        return PresenceHeartbeatResponse(
            session_id=configured_session_id,
            table_id=configured_table_id,
            command_id=result.receipt.command_id,
            revision=result.receipt.revision,
            replayed=result.replayed,
            signal=signal,
        )

    @router.get("/api/v1/presence-events", response_class=StreamingResponse)
    async def get_presence_events(
        request: Request,
        after: Annotated[str | None, Query()] = None,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        participant = _request_participant(
            request,
            store=store,
            access_policy=access_policy,
        )
        cursor = _resume_after(after=after, last_event_id=last_event_id)
        initial_events = _events_after(
            store,
            participant_id=participant.participant_id,
            sequence=cursor,
        )
        return StreamingResponse(
            _stream_presence_events(
                request=request,
                store=store,
                participant_id=participant.participant_id,
                after=cursor,
                initial_events=initial_events,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    app.include_router(router)


__all__ = [
    "PRESENCE_CHANGE_SIGNAL_SCHEMA_VERSION",
    "PRESENCE_PROTECTED_ROUTES",
    "VTT_PRESENCE_HEARTBEAT_REQUEST_SCHEMA_VERSION",
    "VTT_PRESENCE_HEARTBEAT_RESPONSE_SCHEMA_VERSION",
    "EpochMillisecondsClock",
    "PresenceAPIError",
    "PresenceChangeSignal",
    "PresenceHeartbeatRequest",
    "PresenceHeartbeatResponse",
    "install_presence_routes",
    "system_epoch_ms",
]
