"""Optional HTTP and SSE transport for one durable plain-text VTT chat log."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, FastAPI, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import JsonValue

from .access import TableAccessPolicy
from .chat_contracts import (
    ChatDeleteCommand,
    ChatDeletedEvent,
    ChatMessage,
    ChatMutationCommand,
    ChatMutationEvent,
    ChatPostCommand,
    ChatPostedEvent,
    ChatRequest,
    ChatResponse,
    ChatView,
)
from .chat_store import (
    ChatCommandConflictError,
    ChatExecutionResult,
    ChatMessageConflictError,
    ChatMessageNotFoundError,
    ChatRevisionConflictError,
    ChatStoreCorruptionError,
    ChatStoreError,
    ChatStoreSchemaError,
    SQLiteChatLog,
)
from .participants import (
    TableParticipant,
    TableRoster,
    audience_allows,
    validate_audience_selectors,
)

OPEN_LOCAL_CHAT_AUTHOR_ID = "local"
SSE_POLL_INTERVAL_SECONDS = 0.25
SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0

CHAT_PROTECTED_ROUTES = frozenset(
    {
        ("GET", "/api/v1/chat"),
        ("POST", "/api/v1/chat-commands"),
        ("GET", "/api/v1/chat-events"),
    }
)


class ChatAPIError(RuntimeError):
    """Stable chat transport failure rendered by the parent VTT app."""

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
class _ChatState:
    revision: int
    messages: tuple[ChatMessage, ...]
    messages_by_id: dict[str, ChatMessage]
    commands: dict[str, ChatMutationEvent]


def _canonical_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    return value


def _corrupt_store_error() -> ChatAPIError:
    return ChatAPIError(
        status_code=500,
        code="chat_store_corrupt",
        message="The chat store contains invalid durable data.",
    )


def _unavailable_store_error() -> ChatAPIError:
    return ChatAPIError(
        status_code=503,
        code="chat_storage_unavailable",
        message="The chat log could not be persisted or read.",
    )


def _validate_audience_policy(audience: tuple[str, ...], roster: TableRoster | None) -> None:
    try:
        selectors = validate_audience_selectors(audience)
    except (TypeError, ValueError) as exc:
        raise ChatAPIError(
            status_code=422,
            code="invalid_chat_audience",
            message="The chat audience is not supported by this table.",
        ) from exc
    if roster is None:
        return
    participant_ids = {item.participant_id for item in roster.participants}
    actor_ids = {actor_id for item in roster.participants for actor_id in item.owned_actor_ids}
    for selector in selectors:
        if selector.startswith("participant:"):
            if selector.removeprefix("participant:") not in participant_ids:
                break
        elif selector.startswith("actor:"):
            if selector.removeprefix("actor:") not in actor_ids:
                break
    else:
        return
    raise ChatAPIError(
        status_code=422,
        code="invalid_chat_audience",
        message="The chat audience is not supported by this table.",
    )


def _event_author_and_audience(event: ChatMutationEvent) -> tuple[str, tuple[str, ...]]:
    if isinstance(event, ChatPostedEvent):
        return event.message.author_id, event.message.audience
    return event.author_id, event.audience


def _validate_stored_event(event: ChatMutationEvent, *, roster: TableRoster | None) -> None:
    author_id, audience = _event_author_and_audience(event)
    try:
        _validate_audience_policy(audience, roster)
    except ChatAPIError as exc:
        raise _corrupt_store_error() from exc
    if roster is not None and roster.participant(author_id) is None:
        raise _corrupt_store_error()


def _read_state(log: SQLiteChatLog, *, table_id: str, roster: TableRoster | None) -> _ChatState:
    try:
        snapshot = log.snapshot(table_id)
    except (ChatStoreCorruptionError, ChatStoreSchemaError) as exc:
        raise _corrupt_store_error() from exc
    except (sqlite3.Error, ChatStoreError) as exc:
        raise _unavailable_store_error() from exc
    commands: dict[str, ChatMutationEvent] = {}
    for event in snapshot.events:
        _validate_stored_event(event, roster=roster)
        if event.command_id in commands:
            raise _corrupt_store_error()
        commands[event.command_id] = event
    return _ChatState(
        revision=snapshot.revision,
        messages=snapshot.messages,
        messages_by_id={message.message_id: message for message in snapshot.messages},
        commands=commands,
    )


def _events_after(
    log: SQLiteChatLog,
    *,
    table_id: str,
    sequence: int,
) -> tuple[ChatMutationEvent, ...]:
    try:
        return log.events_after(table_id, sequence)
    except (ChatStoreCorruptionError, ChatStoreSchemaError) as exc:
        raise _corrupt_store_error() from exc
    except (sqlite3.Error, ChatStoreError) as exc:
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
        raise RuntimeError("a protected chat request is missing its principal")
    canonical = access_policy.roster.participant(participant.participant_id)
    if canonical is None or canonical != participant:
        raise RuntimeError("a protected chat request has a noncanonical principal")
    return participant


def _chat_forbidden() -> ChatAPIError:
    return ChatAPIError(
        status_code=403,
        code="chat_forbidden",
        message="This participant is not permitted to mutate the chat message.",
    )


def _authorize_mutation(
    participant: TableParticipant | None,
    command: ChatMutationCommand,
    *,
    historical: ChatMutationEvent | None,
    current: ChatMessage | None,
) -> None:
    if participant is None or participant.role == "gm":
        return
    if participant.role != "player":
        raise _chat_forbidden()
    if historical is not None:
        author_id, _audience = _event_author_and_audience(historical)
        if author_id != participant.participant_id:
            raise _chat_forbidden()
        return
    if isinstance(command, ChatPostCommand):
        return
    if current is None:
        raise ChatAPIError(
            status_code=404,
            code="chat_message_not_found",
            message="The requested chat message does not exist.",
        )
    if current.author_id != participant.participant_id:
        raise _chat_forbidden()


def _normalize_post_command(
    command: ChatPostCommand,
    *,
    participant: TableParticipant | None,
) -> ChatPostCommand:
    author_id = OPEN_LOCAL_CHAT_AUTHOR_ID if participant is None else participant.participant_id
    message = ChatMessage.model_validate(
        {
            **command.message.model_dump(mode="json"),
            "author_id": author_id,
        }
    )
    return ChatPostCommand(
        table_id=command.table_id,
        command_id=command.command_id,
        expected_revision=command.expected_revision,
        message=message,
    )


def _execute_log(
    log: SQLiteChatLog,
    command: ChatMutationCommand,
    *,
    current_revision: int,
) -> ChatExecutionResult:
    try:
        return log.execute(command)
    except ChatRevisionConflictError as exc:
        raise ChatAPIError(
            status_code=409,
            code="chat_stale_revision",
            message="The chat command targets a stale log revision.",
            details={"current_revision": current_revision},
        ) from exc
    except ChatCommandConflictError as exc:
        raise ChatAPIError(
            status_code=409,
            code="chat_command_id_conflict",
            message="The chat command ID is already committed with different content.",
        ) from exc
    except ChatMessageConflictError as exc:
        raise ChatAPIError(
            status_code=409,
            code="chat_message_id_conflict",
            message="The chat message ID was already used.",
        ) from exc
    except ChatMessageNotFoundError as exc:
        raise ChatAPIError(
            status_code=404,
            code="chat_message_not_found",
            message="The requested chat message does not exist.",
        ) from exc
    except (ChatStoreCorruptionError, ChatStoreSchemaError) as exc:
        raise _corrupt_store_error() from exc
    except (sqlite3.Error, ChatStoreError) as exc:
        raise _unavailable_store_error() from exc


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


def _event_visible_to(
    event: ChatMutationEvent,
    participant: TableParticipant | None,
) -> bool:
    """Keep authors subscribed to their own durable outbound chat records."""

    author_id, audience = _event_author_and_audience(event)
    if participant is not None and participant.participant_id == author_id:
        return True
    return _visible_to(audience, participant)


def _message_visible_to(
    message: ChatMessage,
    participant: TableParticipant | None,
) -> bool:
    """Treat authorship as an implicit audience for refresh-safe private chat."""

    if participant is not None and participant.participant_id == message.author_id:
        return True
    return _visible_to(message.audience, participant)


def _direct_response_event(
    event: ChatMutationEvent,
    participant: TableParticipant | None,
) -> ChatMutationEvent | None:
    if _event_visible_to(event, participant):
        return event
    return None


def _binding_error(*, session_id: str, table_id: str) -> ChatAPIError:
    return ChatAPIError(
        status_code=409,
        code="chat_binding_mismatch",
        message="The chat request belongs to a different table or session.",
        details={
            "expected_session_id": session_id,
            "expected_table_id": table_id,
        },
    )


def _event_cursor(value: str | None, *, field: str) -> int | None:
    if value is None:
        return None
    if not value or any(character not in "0123456789" for character in value):
        raise ChatAPIError(
            status_code=400,
            code="invalid_chat_event_cursor",
            message="The chat event cursor must be a canonical non-negative integer.",
            details={"field": field},
        )
    try:
        cursor = int(value)
    except (ValueError, OverflowError) as exc:
        raise ChatAPIError(
            status_code=400,
            code="invalid_chat_event_cursor",
            message="The chat event cursor must be a canonical non-negative integer.",
            details={"field": field},
        ) from exc
    if str(cursor) != value:
        raise ChatAPIError(
            status_code=400,
            code="invalid_chat_event_cursor",
            message="The chat event cursor must be a canonical non-negative integer.",
            details={"field": field},
        )
    return cursor


def _resume_after(*, after: str | None, last_event_id: str | None) -> int:
    query_cursor = _event_cursor(after, field="after")
    header_cursor = _event_cursor(last_event_id, field="Last-Event-ID")
    return max(cursor for cursor in (0, query_cursor, header_cursor) if cursor is not None)


def _render_sse_event(event: ChatMutationEvent) -> str:
    payload = json.dumps(
        event.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"id: {event.sequence}\nevent: vtt.chat_event\ndata: {payload}\n\n"


async def _stream_chat_events(
    *,
    request: Request,
    log: SQLiteChatLog,
    table_id: str,
    after: int,
    initial_events: tuple[ChatMutationEvent, ...],
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
            events = _events_after(log, table_id=table_id, sequence=cursor)
        if events:
            yielded_visible_event = False
            for event in events:
                if await request.is_disconnected():
                    return
                cursor = event.sequence
                _validate_stored_event(event, roster=roster)
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


def install_chat_routes(
    app: FastAPI,
    *,
    log: SQLiteChatLog,
    session_id: str,
    table_id: str,
    access_policy: TableAccessPolicy | None,
) -> None:
    """Install optional chat routes without changing engine HTTP schemas."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")
    if not isinstance(log, SQLiteChatLog):
        raise TypeError("log must be a SQLiteChatLog")
    configured_session_id = _canonical_text(session_id, field_name="session_id")
    configured_table_id = _canonical_text(table_id, field_name="table_id")
    roster = None if access_policy is None else access_policy.roster
    router = APIRouter()

    @router.get("/api/v1/chat", response_model=ChatView)
    async def get_chat(request: Request) -> ChatView:
        participant = _request_participant(request, access_policy=access_policy)
        state = _read_state(log, table_id=configured_table_id, roster=roster)
        visible = tuple(
            message for message in state.messages if _message_visible_to(message, participant)
        )
        return ChatView(
            session_id=configured_session_id,
            table_id=configured_table_id,
            revision=state.revision,
            messages=visible,
        )

    @router.post("/api/v1/chat-commands", response_model=ChatResponse)
    async def execute_chat_command(payload: ChatRequest, request: Request) -> ChatResponse:
        participant = _request_participant(request, access_policy=access_policy)
        if participant is not None and participant.role == "spectator":
            raise _chat_forbidden()
        if (
            payload.session_id != configured_session_id
            or payload.command.table_id != configured_table_id
        ):
            raise _binding_error(
                session_id=configured_session_id,
                table_id=configured_table_id,
            )
        state = _read_state(log, table_id=configured_table_id, roster=roster)
        historical = state.commands.get(payload.command.command_id)
        current = None
        if isinstance(payload.command, ChatDeleteCommand):
            current = state.messages_by_id.get(payload.command.message_id)
        _authorize_mutation(
            participant,
            payload.command,
            historical=historical,
            current=current,
        )

        command: ChatMutationCommand
        if isinstance(payload.command, ChatPostCommand):
            _validate_audience_policy(payload.command.message.audience, roster)
            command = _normalize_post_command(payload.command, participant=participant)
        else:
            if historical is None and current is None:
                raise ChatAPIError(
                    status_code=404,
                    code="chat_message_not_found",
                    message="The requested chat message does not exist.",
                )
            command = payload.command
        result = _execute_log(log, command, current_revision=state.revision)
        event = result.receipt.event
        _validate_stored_event(event, roster=roster)
        return ChatResponse(
            session_id=configured_session_id,
            table_id=configured_table_id,
            command_id=result.receipt.command_id,
            revision=result.receipt.revision,
            replayed=result.replayed,
            event=_direct_response_event(event, participant),
        )

    @router.get("/api/v1/chat-events", response_class=StreamingResponse)
    async def get_chat_events(
        request: Request,
        after: Annotated[str | None, Query()] = None,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        participant = _request_participant(request, access_policy=access_policy)
        cursor = _resume_after(after=after, last_event_id=last_event_id)
        initial_events = _events_after(
            log,
            table_id=configured_table_id,
            sequence=cursor,
        )
        for event in initial_events:
            _validate_stored_event(event, roster=roster)
        return StreamingResponse(
            _stream_chat_events(
                request=request,
                log=log,
                table_id=configured_table_id,
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
    "CHAT_PROTECTED_ROUTES",
    "OPEN_LOCAL_CHAT_AUTHOR_ID",
    "ChatAPIError",
    "install_chat_routes",
]
