"""Protected HTTP and reconnectable SSE transport for the durable VTT journal."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import unicodedata
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, FastAPI, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import JsonValue

from .access import TableAccessPolicy
from .annotations import AnnotationPoint
from .journal_contracts import (
    JournalDeleteDocumentCommand,
    JournalDeleteFolderCommand,
    JournalDocument,
    JournalDocumentDeletedEvent,
    JournalDocumentLinkBlock,
    JournalDocumentPutEvent,
    JournalFolderDeletedEvent,
    JournalFolderPutEvent,
    JournalMutationCommand,
    JournalMutationEvent,
    JournalPutDocumentCommand,
    JournalRequest,
    JournalResponse,
    JournalView,
)
from .journal_store import (
    JournalCapacityError,
    JournalCommandConflictError,
    JournalDocumentLinkError,
    JournalFolderCycleError,
    JournalFolderNotEmptyError,
    JournalFolderReferenceError,
    JournalLinkedDocumentError,
    JournalRecordNotFoundError,
    JournalRevisionConflictError,
    JournalSnapshot,
    JournalStoreCorruptionError,
    JournalStoreError,
    JournalStoreSchemaError,
    SQLiteJournalStore,
)
from .participants import TableParticipant, audience_allows, validate_audience_selectors
from .scene import SquareGridScene
from .scene_library_store import SQLiteSceneLibrary
from .scene_library_store import (
    SceneLibraryStoreCorruptionError,
    SceneLibraryStoreError,
    SceneLibraryStoreSchemaError,
)

JOURNAL_PROTECTED_ROUTES = frozenset(
    {
        ("GET", "/api/v1/journal"),
        ("POST", "/api/v1/journal-commands"),
        ("GET", "/api/v1/journal-events"),
    }
)
SSE_POLL_INTERVAL_SECONDS = 0.25
SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0

logger = logging.getLogger(__name__)


class JournalAPIError(RuntimeError):
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
    access_policy: TableAccessPolicy | None,
) -> TableParticipant | None:
    if access_policy is None:
        return None
    participant = getattr(request.state, "vtt_participant", None)
    if not isinstance(participant, TableParticipant):
        raise RuntimeError("protected journal request is missing its principal")
    canonical = access_policy.roster.participant(participant.participant_id)
    if canonical != participant:
        raise RuntimeError("protected journal request has a noncanonical principal")
    return participant


def _read_snapshot(store: SQLiteJournalStore, table_id: str) -> JournalSnapshot:
    try:
        return store.snapshot(table_id)
    except (JournalStoreCorruptionError, JournalStoreSchemaError) as exc:
        raise JournalAPIError(
            status_code=500,
            code="journal_store_corrupt",
            message="The journal store contains invalid durable data.",
        ) from exc
    except (sqlite3.Error, JournalStoreError) as exc:
        raise JournalAPIError(
            status_code=503,
            code="journal_storage_unavailable",
            message="The journal could not be persisted or read.",
        ) from exc


def _visible(document: JournalDocument, participant: TableParticipant | None) -> bool:
    return participant is None or audience_allows(document.audience, participant)


def _project_document(
    document: JournalDocument,
    *,
    visible_ids: frozenset[str],
    participant: TableParticipant | None,
) -> JournalDocument:
    blocks = tuple(
        block
        for block in document.blocks
        if not isinstance(block, JournalDocumentLinkBlock) or block.document_id in visible_ids
    )
    reveal_private_metadata = participant is None or participant.role == "gm"
    if reveal_private_metadata:
        audience = document.audience
    elif document.audience == ("all",):
        audience = document.audience
    else:
        audience = tuple(
            selector
            for selector in document.audience
            if selector == f"role:{participant.role}"
            or selector == f"participant:{participant.participant_id}"
            or (
                participant.role == "player"
                and selector.startswith("actor:")
                and selector.removeprefix("actor:") in participant.owned_actor_ids
            )
        )
        if not audience:  # pragma: no cover - caller projects visible records only
            raise RuntimeError("visible journal document has no projected audience")
    return document.model_copy(
        update={
            "blocks": blocks,
            "folder_id": document.folder_id if reveal_private_metadata else None,
            "audience": audience,
        }
    )


def _search_text(document: JournalDocument) -> str:
    values = [document.title, *document.tags]
    for block in document.blocks:
        if hasattr(block, "text"):
            values.append(block.text)
        elif hasattr(block, "items"):
            values.extend(block.items)
        elif isinstance(block, JournalDocumentLinkBlock):
            values.append(block.label)
    return unicodedata.normalize("NFKC", " ".join(values)).casefold()


def _validate_query(query: str | None) -> None:
    if query is None:
        return
    if (
        not query
        or query != query.strip()
        or len(query) > 160
        or any(unicodedata.category(character) == "Cc" for character in query)
    ):
        raise JournalAPIError(
            status_code=400,
            code="invalid_journal_query",
            message="The journal query must be canonical text of 1-160 characters.",
        )


def _project_view(
    snapshot: JournalSnapshot,
    *,
    session_id: str,
    table_id: str,
    participant: TableParticipant | None,
    query: str | None,
) -> JournalView:
    visible = tuple(document for document in snapshot.documents if _visible(document, participant))
    visible_ids = frozenset(document.document_id for document in visible)
    reveal_folders = participant is None or participant.role == "gm"
    projected = tuple(
        _project_document(
            document,
            visible_ids=visible_ids,
            participant=participant,
        )
        for document in visible
    )
    if query is not None:
        _validate_query(query)
        tokens = unicodedata.normalize("NFKC", query).casefold().split()
        projected = tuple(
            document
            for document in projected
            if all(token in _search_text(document) for token in tokens)
        )[:200]
        result_ids = frozenset(document.document_id for document in projected)
        projected = tuple(
            _project_document(
                document,
                visible_ids=result_ids,
                participant=participant,
            )
            for document in projected
        )
    folders = snapshot.folders if reveal_folders else ()
    return JournalView(
        session_id=session_id,
        table_id=table_id,
        revision=snapshot.revision,
        folders=folders,
        documents=projected,
    )


def _validate_document_policy(
    document: JournalDocument,
    *,
    access_policy: TableAccessPolicy | None,
) -> None:
    selectors = validate_audience_selectors(document.audience)
    if access_policy is None:
        return
    participant_ids = {item.participant_id for item in access_policy.roster.participants}
    actor_ids = {
        actor_id for item in access_policy.roster.participants for actor_id in item.owned_actor_ids
    }
    for selector in selectors:
        if (
            selector.startswith("participant:")
            and selector.removeprefix("participant:") not in participant_ids
        ):
            break
        if selector.startswith("actor:") and selector.removeprefix("actor:") not in actor_ids:
            break
    else:
        return
    raise JournalAPIError(
        status_code=422,
        code="invalid_journal_audience",
        message="The journal audience is not supported by this table.",
    )


def _map_pin_bounds(
    pin: AnnotationPoint,
    *,
    scene: SquareGridScene,
    width_px: int | None,
    height_px: int | None,
    origin_x_px: float | None,
    origin_y_px: float | None,
    cell_extent_px: float | None,
    distance_ft: float | None,
) -> bool:
    if width_px is None:
        min_x = scene.origin_ft.x_ft
        max_x = min_x + scene.columns * scene.cell_size_ft
        min_y = scene.origin_ft.y_ft
        max_y = min_y + scene.rows * scene.cell_size_ft
    else:
        assert None not in (height_px, origin_x_px, origin_y_px, cell_extent_px, distance_ft)
        scale = float(distance_ft) / float(cell_extent_px)
        board_x = scene.origin_ft.x_ft + float(distance_ft) / 2
        board_y = scene.origin_ft.y_ft + float(distance_ft) / 2
        min_x = board_x - float(origin_x_px) * scale
        max_x = board_x + (width_px - float(origin_x_px)) * scale
        min_y = board_y - float(origin_y_px) * scale
        max_y = board_y + (int(height_px) - float(origin_y_px)) * scale
    tolerance = 1e-9
    return (
        min_x - tolerance <= pin.x_ft <= max_x + tolerance
        and min_y - tolerance <= pin.y_ft <= max_y + tolerance
        and abs(pin.z_ft - scene.origin_ft.z_ft) <= tolerance
    )


def _validate_pin(
    document: JournalDocument,
    *,
    configured_scene: SquareGridScene,
    scenes: SQLiteSceneLibrary | None,
    table_id: str,
) -> None:
    pin = document.map_pin
    if pin is None:
        return
    if scenes is None:
        if pin.scene_id != configured_scene.scene_id or not _map_pin_bounds(
            pin.position,
            scene=configured_scene,
            width_px=None,
            height_px=None,
            origin_x_px=None,
            origin_y_px=None,
            cell_extent_px=None,
            distance_ft=None,
        ):
            raise JournalAPIError(
                status_code=409,
                code="journal_pin_out_of_bounds",
                message="The journal pin must fit a known table scene.",
            )
        return
    try:
        entry = scenes.snapshot(table_id).scene(pin.scene_id)
    except (SceneLibraryStoreCorruptionError, SceneLibraryStoreSchemaError) as exc:
        raise JournalAPIError(
            status_code=500,
            code="journal_scene_store_corrupt",
            message="The journal scene catalog contains invalid durable data.",
        ) from exc
    except (sqlite3.Error, SceneLibraryStoreError) as exc:
        raise JournalAPIError(
            status_code=503,
            code="journal_scene_storage_unavailable",
            message="The journal scene catalog could not be read.",
        ) from exc
    if entry is None or entry.archived:
        raise JournalAPIError(
            status_code=409,
            code="journal_pin_scene_missing",
            message="The journal pin targets an unavailable scene.",
        )
    metadata = entry.scene.map_metadata
    calibration = metadata.calibration
    if not _map_pin_bounds(
        pin.position,
        scene=configured_scene,
        width_px=metadata.width_px,
        height_px=metadata.height_px,
        origin_x_px=calibration.origin_x_px,
        origin_y_px=calibration.origin_y_px,
        cell_extent_px=calibration.cell_extent_px,
        distance_ft=calibration.distance_ft,
    ):
        raise JournalAPIError(
            status_code=409,
            code="journal_pin_out_of_bounds",
            message="The journal pin must fit its target scene.",
        )


def _execute(store: SQLiteJournalStore, command: JournalMutationCommand):
    try:
        return store.execute(command)
    except JournalRevisionConflictError as exc:
        raise JournalAPIError(
            status_code=409,
            code="journal_stale_revision",
            message="The journal command targets a stale revision.",
        ) from exc
    except JournalCommandConflictError as exc:
        raise JournalAPIError(
            status_code=409,
            code="journal_command_id_conflict",
            message="The journal command ID already has different content.",
        ) from exc
    except JournalRecordNotFoundError as exc:
        raise JournalAPIError(
            status_code=404,
            code="journal_record_not_found",
            message="The requested journal record does not exist.",
        ) from exc
    except (JournalFolderReferenceError, JournalDocumentLinkError) as exc:
        raise JournalAPIError(
            status_code=409,
            code="journal_reference_invalid",
            message="The journal record references unavailable content.",
        ) from exc
    except JournalFolderCycleError as exc:
        raise JournalAPIError(
            status_code=409,
            code="journal_folder_cycle",
            message="The journal folder relationship is invalid.",
        ) from exc
    except (JournalFolderNotEmptyError, JournalLinkedDocumentError) as exc:
        raise JournalAPIError(
            status_code=409,
            code="journal_record_in_use",
            message="The journal record is still in use.",
        ) from exc
    except JournalCapacityError as exc:
        raise JournalAPIError(
            status_code=409,
            code="journal_capacity_exceeded",
            message="The journal has reached its active-record limit.",
        ) from exc
    except (JournalStoreCorruptionError, JournalStoreSchemaError) as exc:
        raise JournalAPIError(
            status_code=500,
            code="journal_store_corrupt",
            message="The journal store contains invalid durable data.",
        ) from exc
    except (sqlite3.Error, JournalStoreError) as exc:
        raise JournalAPIError(
            status_code=503,
            code="journal_storage_unavailable",
            message="The journal could not be persisted or read.",
        ) from exc


def _exact_replay(
    store: SQLiteJournalStore,
    command: JournalMutationCommand,
):
    try:
        return store.replay(command)
    except JournalCommandConflictError as exc:
        raise JournalAPIError(
            status_code=409,
            code="journal_command_id_conflict",
            message="The journal command ID already has different content.",
        ) from exc
    except (JournalStoreCorruptionError, JournalStoreSchemaError) as exc:
        raise JournalAPIError(
            status_code=500,
            code="journal_store_corrupt",
            message="The journal store contains invalid durable data.",
        ) from exc
    except (sqlite3.Error, JournalStoreError) as exc:
        raise JournalAPIError(
            status_code=503,
            code="journal_storage_unavailable",
            message="The journal could not be persisted or read.",
        ) from exc


def _cursor(value: str | None, field: str) -> int | None:
    if value is None:
        return None
    if not value.isdigit() or str(int(value)) != value:
        raise JournalAPIError(
            status_code=400,
            code="invalid_journal_event_cursor",
            message="The journal event cursor must be a canonical non-negative integer.",
            details={"field": field},
        )
    return int(value)


def _render_event(event: JournalMutationEvent) -> str:
    data = json.dumps(
        event.model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"id: {event.sequence}\nevent: vtt.journal_event\ndata: {data}\n\n"


def _fold_documents(events: tuple[JournalMutationEvent, ...]) -> dict[str, JournalDocument]:
    documents: dict[str, JournalDocument] = {}
    for event in events:
        if isinstance(event, JournalDocumentPutEvent):
            documents[event.document.document_id] = event.document
        elif isinstance(event, JournalDocumentDeletedEvent):
            documents.pop(event.document.document_id, None)
    return documents


def _project_event(
    event: JournalMutationEvent,
    *,
    previous: JournalDocument | None,
    participant: TableParticipant | None,
    visible_ids: frozenset[str],
    previous_visible_ids: frozenset[str],
) -> JournalMutationEvent | None:
    if isinstance(event, (JournalFolderPutEvent, JournalFolderDeletedEvent)):
        return event if participant is None or participant.role == "gm" else None
    if _visible(event.document, participant):
        if participant is None or participant.role == "gm":
            return event
        return event.model_copy(
            update={
                "document": _project_document(
                    event.document,
                    visible_ids=visible_ids,
                    participant=participant,
                )
            }
        )
    if (
        isinstance(event, JournalDocumentPutEvent)
        and previous is not None
        and _visible(previous, participant)
    ):
        return JournalDocumentDeletedEvent(
            table_id=event.table_id,
            event_id=event.event_id,
            sequence=event.sequence,
            revision=event.revision,
            command_id=event.command_id,
            document=_project_document(
                previous,
                visible_ids=previous_visible_ids,
                participant=participant,
            ),
        )
    return None


async def _stream(
    request: Request,
    *,
    store: SQLiteJournalStore,
    table_id: str,
    after: int,
    participant: TableParticipant | None,
) -> AsyncIterator[str]:
    cursor = after
    previous = _fold_documents(
        tuple(event for event in store.events_after(table_id, 0) if event.sequence <= after)
    )
    loop = asyncio.get_running_loop()
    heartbeat = loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
    while True:
        if await request.is_disconnected():
            return
        events = store.events_after(table_id, cursor)
        if events:
            yielded = False
            for event in events:
                previous_visible_ids = frozenset(
                    document_id
                    for document_id, document in previous.items()
                    if _visible(document, participant)
                )
                old = None
                if isinstance(event, (JournalDocumentPutEvent, JournalDocumentDeletedEvent)):
                    old = previous.get(event.document.document_id)
                if isinstance(event, JournalDocumentPutEvent):
                    previous[event.document.document_id] = event.document
                elif isinstance(event, JournalDocumentDeletedEvent):
                    previous.pop(event.document.document_id, None)
                visible_ids = frozenset(
                    document_id
                    for document_id, document in previous.items()
                    if _visible(document, participant)
                )
                projected = _project_event(
                    event,
                    previous=old,
                    participant=participant,
                    visible_ids=visible_ids,
                    previous_visible_ids=previous_visible_ids,
                )
                cursor = event.sequence
                if projected is not None:
                    yield _render_event(projected)
                    yielded = True
            if yielded:
                heartbeat = loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
        elif loop.time() >= heartbeat:
            yield ": heartbeat\n\n"
            heartbeat = loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
        await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)


def install_journal_routes(
    app: FastAPI,
    *,
    store: SQLiteJournalStore,
    session_id: str,
    table_id: str,
    configured_scene: SquareGridScene,
    scenes: SQLiteSceneLibrary | None,
    access_policy: TableAccessPolicy | None,
) -> None:
    router = APIRouter()

    @router.get("/api/v1/journal", response_model=JournalView)
    async def get_journal(
        request: Request,
        query: Annotated[str | None, Query()] = None,
    ) -> JournalView:
        participant = _request_participant(request, access_policy)
        _validate_query(query)
        snapshot = _read_snapshot(store, table_id)
        return _project_view(
            snapshot,
            session_id=session_id,
            table_id=table_id,
            participant=participant,
            query=query,
        )

    @router.post("/api/v1/journal-commands", response_model=JournalResponse)
    async def mutate_journal(payload: JournalRequest, request: Request) -> JournalResponse:
        participant = _request_participant(request, access_policy)
        if participant is not None and participant.role != "gm":
            raise JournalAPIError(
                status_code=403,
                code="journal_forbidden",
                message="Only a Game Master may change the journal.",
            )
        if payload.session_id != session_id or payload.command.table_id != table_id:
            raise JournalAPIError(
                status_code=409,
                code="journal_binding_mismatch",
                message="The journal request belongs to a different table or session.",
            )
        replay = _exact_replay(store, payload.command)
        if replay is not None:
            return JournalResponse(
                session_id=session_id,
                replayed=True,
                receipt=replay.receipt,
            )
        if isinstance(payload.command, JournalPutDocumentCommand):
            _validate_document_policy(payload.command.document, access_policy=access_policy)
            _validate_pin(
                payload.command.document,
                configured_scene=configured_scene,
                scenes=scenes,
                table_id=table_id,
            )
        result = _execute(store, payload.command)
        return JournalResponse(
            session_id=session_id,
            replayed=result.replayed,
            receipt=result.receipt,
        )

    @router.get("/api/v1/journal-events", response_class=StreamingResponse)
    async def journal_events(
        request: Request,
        after: Annotated[str | None, Query()] = None,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        participant = _request_participant(request, access_policy)
        values = [
            value
            for value in (_cursor(after, "after"), _cursor(last_event_id, "Last-Event-ID"))
            if value is not None
        ]
        cursor = max([0, *values])
        return StreamingResponse(
            _stream(
                request,
                store=store,
                table_id=table_id,
                after=cursor,
                participant=participant,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    app.include_router(router)


__all__ = ["JOURNAL_PROTECTED_ROUTES", "JournalAPIError", "install_journal_routes"]
