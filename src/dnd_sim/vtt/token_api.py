"""Authenticated HTTP and sanitized reconnect signals for tabletop tokens."""

from __future__ import annotations

import asyncio
import json
import math
import sqlite3
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import Annotated, Any, Literal, Self

from fastapi import APIRouter, FastAPI, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    JsonValue,
    ValidationError,
    field_validator,
    model_validator,
)

from .access import TableAccessPolicy
from .participants import TableParticipant
from .scene import FeetPosition
from .scene_library_contracts import SceneMapMetadata
from .scene_library_store import (
    SQLiteSceneLibrary,
    SceneLibraryStoreCorruptionError,
    SceneLibraryStoreError,
    SceneLibraryStoreSchemaError,
)
from .session_service import VTTSessionService
from .token_contracts import (
    TokenCreateCommand,
    TokenDeleteCommand,
    TokenDuplicateCommand,
    TokenMutationCommand,
    TokenMutationEvent,
    TokenMutationReceipt,
    TokenRecord,
    TokenUpdateCommand,
    TokenView,
    project_token_view,
)
from .token_store import (
    SQLiteTokenStore,
    TokenCommandConflictError,
    TokenIdConflictError,
    TokenLockedError,
    TokenNotFoundError,
    TokenRevisionConflictError,
    TokenSceneMismatchError,
    TokenStoreCorruptionError,
    TokenStoreError,
    TokenStoreSchemaError,
)

VTT_TOKEN_REQUEST_SCHEMA_VERSION = "vtt.token_request.v1"
VTT_TOKEN_RESPONSE_SCHEMA_VERSION = "vtt.token_response.v1"
TOKEN_CHANGE_SIGNAL_SCHEMA_VERSION = "vtt.token_change_signal.v1"

TOKEN_PROTECTED_ROUTES = frozenset(
    {
        ("GET", "/api/v1/tokens"),
        ("POST", "/api/v1/token-commands"),
        ("GET", "/api/v1/token-events"),
    }
)

SSE_POLL_INTERVAL_SECONDS = 0.25
SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0


class _StrictTokenHTTPModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _canonical_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    return value


_BROWSER_FLOAT_FIELDS = frozenset(
    {
        "x_ft",
        "y_ft",
        "z_ft",
        "width_ft",
        "height_ft",
        "rotation_degrees",
        "aura_radius_ft",
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


class TokenRequest(_StrictTokenHTTPModel):
    schema_version: Literal[VTT_TOKEN_REQUEST_SCHEMA_VERSION] = VTT_TOKEN_REQUEST_SCHEMA_VERSION
    session_id: str
    command: TokenMutationCommand

    @model_validator(mode="before")
    @classmethod
    def canonicalize_browser_numbers(cls, value: Any) -> Any:
        return _canonicalize_browser_floats(value)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="session_id")


class TokenResponse(_StrictTokenHTTPModel):
    schema_version: Literal[VTT_TOKEN_RESPONSE_SCHEMA_VERSION] = VTT_TOKEN_RESPONSE_SCHEMA_VERSION
    session_id: str
    table_id: str
    command_id: str
    revision: int
    replayed: bool
    event: TokenMutationEvent

    @field_validator("session_id", "table_id", "command_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @field_validator("revision")
    @classmethod
    def validate_revision(cls, value: int) -> int:
        if type(value) is not int or value < 1:
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
            raise ValueError("event identity must match the token response")
        return self


class TokenChangeSignal(_StrictTokenHTTPModel):
    """Identity-free notification that one scene token projection changed."""

    schema_version: Literal[TOKEN_CHANGE_SIGNAL_SCHEMA_VERSION] = TOKEN_CHANGE_SIGNAL_SCHEMA_VERSION
    sequence: int
    revision: int
    scene_id: str

    @field_validator("sequence", "revision")
    @classmethod
    def validate_positive_int(cls, value: int, info: Any) -> int:
        if type(value) is not int or value < 1:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    @field_validator("scene_id")
    @classmethod
    def validate_scene_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="scene_id")

    @model_validator(mode="after")
    def validate_sequence_revision(self) -> Self:
        if self.sequence != self.revision:
            raise ValueError("sequence must match revision")
        return self


class TokenAPIError(RuntimeError):
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
        raise RuntimeError("a protected token request is missing its principal")
    canonical = access_policy.roster.participant(participant.participant_id)
    if canonical is None or canonical != participant:
        raise RuntimeError("a protected token request has a noncanonical principal")
    return participant


def _storage_error(exc: Exception) -> TokenAPIError:
    if isinstance(
        exc,
        (
            TokenStoreCorruptionError,
            TokenStoreSchemaError,
            SceneLibraryStoreCorruptionError,
            SceneLibraryStoreSchemaError,
        ),
    ):
        return TokenAPIError(
            status_code=500,
            code="token_store_corrupt",
            message="The token catalog contains invalid durable data.",
        )
    return TokenAPIError(
        status_code=503,
        code="token_storage_unavailable",
        message="The token catalog could not be persisted or read.",
    )


def _scene_entry(
    scenes: SQLiteSceneLibrary,
    *,
    table_id: str,
    scene_id: str,
    participant: TableParticipant | None,
):
    try:
        view = scenes.snapshot(table_id)
    except (sqlite3.Error, SceneLibraryStoreError) as exc:
        raise _storage_error(exc) from exc
    entry = view.scene(scene_id)
    if entry is None or (
        participant is not None and participant.role != "gm" and view.active_scene_id != scene_id
    ):
        raise TokenAPIError(
            status_code=404,
            code="token_scene_not_found",
            message="The requested token scene is unavailable.",
        )
    return entry


def _read_truth(store: SQLiteTokenStore, *, table_id: str, scene_id: str) -> TokenView:
    try:
        return store.snapshot(table_id, scene_id)
    except (sqlite3.Error, TokenStoreError) as exc:
        raise _storage_error(exc) from exc


def _actor_position(service: VTTSessionService, actor_id: str) -> FeetPosition:
    projection = service.read_view().projection
    actors = projection.get("actors")
    actor = actors.get(actor_id) if isinstance(actors, Mapping) else None
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
        raise TokenAPIError(
            status_code=409,
            code="token_actor_not_found",
            message="The linked engine actor is unavailable.",
        )
    try:
        return FeetPosition(
            x_ft=float(position[0]),
            y_ft=float(position[1]),
            z_ft=float(position[2]),
        )
    except ValidationError as exc:  # pragma: no cover - finite shape checked above
        raise TokenAPIError(
            status_code=500,
            code="token_engine_projection_invalid",
            message="The engine actor projection is invalid.",
        ) from exc


def _bind_actor_positions(view: TokenView, service: VTTSessionService) -> TokenView:
    tokens: list[TokenRecord] = []
    for token in view.tokens:
        if token.actor_id is None:
            tokens.append(token)
            continue
        position = _actor_position(service, token.actor_id)
        tokens.append(
            token.model_copy(
                update={"pose": token.pose.model_copy(update={"position_ft": position})}
            )
        )
    return TokenView(
        table_id=view.table_id,
        scene_id=view.scene_id,
        revision=view.revision,
        tokens=tuple(tokens),
    )


def project_engine_projection_for_tokens(
    projection: Mapping[str, Any],
    *,
    store: SQLiteTokenStore,
    table_id: str,
    scene_id: str,
    participant: TableParticipant | None,
    visibility_actor_ids: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Remove engine actors and target choices absent from the token audience view."""

    if not isinstance(projection, Mapping):
        raise TypeError("projection must be a mapping")
    if participant is None or participant.role == "gm":
        return dict(projection)
    truth = _read_truth(store, table_id=table_id, scene_id=scene_id)
    visible = project_token_view(truth, participant)
    visible_actor_ids = {token.actor_id for token in visible.tokens if token.actor_id is not None}
    if visibility_actor_ids is not None:
        if not isinstance(visibility_actor_ids, frozenset) or any(
            not isinstance(actor_id, str) for actor_id in visibility_actor_ids
        ):
            raise TypeError("visibility_actor_ids must be a frozenset of strings or None")
        visible_actor_ids.intersection_update(visibility_actor_ids)
    raw_actors = projection.get("actors")
    if not isinstance(raw_actors, Mapping):
        return dict(projection)
    filtered: dict[str, Any] = dict(projection)
    filtered["actors"] = {
        actor_id: actor
        for actor_id, actor in raw_actors.items()
        if isinstance(actor_id, str) and actor_id in visible_actor_ids
    }
    initiative = projection.get("initiative_order")
    if isinstance(initiative, (list, tuple)):
        filtered["initiative_order"] = [
            actor_id for actor_id in initiative if actor_id in visible_actor_ids
        ]
    active_actor_id = projection.get("active_actor_id")
    active_visible = active_actor_id in visible_actor_ids
    if "active_actor_id" in projection and not active_visible:
        filtered["active_actor_id"] = None
    for field in ("prompt", "result"):
        value = projection.get(field)
        if isinstance(value, Mapping) and value.get("actor_id") not in visible_actor_ids:
            filtered[field] = None
    choices = projection.get("choices")
    if isinstance(choices, Mapping):
        if choices.get("actor_id") not in visible_actor_ids:
            filtered["choices"] = None
        else:
            filtered_choices = dict(choices)
            raw_actions = choices.get("actions")
            if isinstance(raw_actions, (list, tuple)):
                actions: list[Any] = []
                for raw_action in raw_actions:
                    if not isinstance(raw_action, Mapping):
                        actions.append(raw_action)
                        continue
                    action = dict(raw_action)
                    for field in ("selectable_target_ids", "legal_target_ids"):
                        values = raw_action.get(field)
                        if isinstance(values, (list, tuple)):
                            action[field] = [
                                actor_id for actor_id in values if actor_id in visible_actor_ids
                            ]
                    actions.append(action)
                filtered_choices["actions"] = actions
            filtered["choices"] = filtered_choices
    return filtered


def hidden_engine_actor_values_for_tokens(
    projection: Mapping[str, Any],
    *,
    store: SQLiteTokenStore,
    table_id: str,
    scene_id: str,
    participant: TableParticipant | None,
    visibility_actor_ids: frozenset[str] | None = None,
) -> frozenset[str]:
    """Return exact identity strings that must not cross this token audience."""

    if participant is None or participant.role == "gm":
        return frozenset()
    raw_actors = projection.get("actors")
    if not isinstance(raw_actors, Mapping):
        return frozenset()
    visible_projection = project_engine_projection_for_tokens(
        projection,
        store=store,
        table_id=table_id,
        scene_id=scene_id,
        participant=participant,
        visibility_actor_ids=visibility_actor_ids,
    )
    visible_actors = visible_projection.get("actors")
    visible_ids = set(visible_actors) if isinstance(visible_actors, Mapping) else set()
    protected_values: set[str] = set()
    for actor_id, actor in raw_actors.items():
        if not isinstance(actor_id, str) or actor_id in visible_ids:
            continue
        protected_values.add(actor_id)
        if isinstance(actor, Mapping):
            for field in ("actor_id", "name"):
                value = actor.get(field)
                if isinstance(value, str) and value:
                    protected_values.add(value)
    return frozenset(protected_values)


def _validate_actor_authority(token: TokenRecord | None, service: VTTSessionService) -> None:
    if token is None or token.actor_id is None:
        return
    if token.pose.position_ft != _actor_position(service, token.actor_id):
        raise TokenAPIError(
            status_code=409,
            code="token_actor_position_authoritative",
            message="Move linked actors through an authoritative engine command.",
        )


def _validate_pose_bounds(
    token: TokenRecord | None,
    scene_origin: FeetPosition,
    map_metadata: SceneMapMetadata,
) -> None:
    if token is None:
        return
    calibration = map_metadata.calibration
    if calibration.topology in {"hex_flat", "hex_pointy"}:
        footprint = token.pose.occupied_hex_cells
        if not footprint:
            raise TokenAPIError(
                status_code=409,
                code="token_hex_footprint_invalid",
                message="Hex-board tokens require an explicit axial footprint.",
            )
        origin_center = FeetPosition(
            x_ft=scene_origin.x_ft + calibration.distance_ft / 2.0,
            y_ft=scene_origin.y_ft + calibration.distance_ft / 2.0,
            z_ft=scene_origin.z_ft,
        )
        anchor = calibration.feet_to_cell(
            token.pose.position_ft,
            origin_ft=origin_center,
        )
        coordinates = {(cell.q, cell.r) for cell in footprint}
        if (anchor.q, anchor.r) not in coordinates:
            raise TokenAPIError(
                status_code=409,
                code="token_hex_footprint_invalid",
                message="The token anchor must occupy one of its axial cells.",
            )
        connected = {(footprint[0].q, footprint[0].r)}
        frontier = list(connected)
        neighbor_deltas = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))
        while frontier:
            q, r = frontier.pop()
            for delta_q, delta_r in neighbor_deltas:
                adjacent = (q + delta_q, r + delta_r)
                if adjacent in coordinates and adjacent not in connected:
                    connected.add(adjacent)
                    frontier.append(adjacent)
        if connected != coordinates:
            raise TokenAPIError(
                status_code=409,
                code="token_hex_footprint_invalid",
                message="A hex token footprint must be a connected axial cell set.",
            )
        if not all(
            calibration.cell_is_complete(
                cell,
                width_px=map_metadata.width_px,
                height_px=map_metadata.height_px,
            )
            for cell in footprint
        ):
            raise TokenAPIError(
                status_code=409,
                code="token_pose_out_of_bounds",
                message="The entire token must remain inside the authoritative board.",
            )
        return
    if token.pose.occupied_hex_cells:
        raise TokenAPIError(
            status_code=409,
            code="token_hex_footprint_invalid",
            message="Axial token footprints are valid only on hex boards.",
        )
    radians = math.radians(token.pose.rotation_degrees)
    cosine = abs(math.cos(radians))
    sine = abs(math.sin(radians))
    half_width = (cosine * token.pose.width_ft + sine * token.pose.height_ft) / 2.0
    half_height = (sine * token.pose.width_ft + cosine * token.pose.height_ft) / 2.0
    position = token.pose.position_ft
    origin_center_x_ft = scene_origin.x_ft + calibration.distance_ft / 2.0
    origin_center_y_ft = scene_origin.y_ft + calibration.distance_ft / 2.0
    minimum_x = origin_center_x_ft + (
        -calibration.origin_x_px / calibration.cell_extent_px * calibration.distance_ft
    )
    minimum_y = origin_center_y_ft + (
        -calibration.origin_y_px / calibration.cell_extent_px * calibration.distance_ft
    )
    maximum_x = origin_center_x_ft + (
        (map_metadata.width_px - calibration.origin_x_px)
        / calibration.cell_extent_px
        * calibration.distance_ft
    )
    maximum_y = origin_center_y_ft + (
        (map_metadata.height_px - calibration.origin_y_px)
        / calibration.cell_extent_px
        * calibration.distance_ft
    )
    if (
        position.x_ft - half_width < minimum_x
        or position.x_ft + half_width > maximum_x
        or position.y_ft - half_height < minimum_y
        or position.y_ft + half_height > maximum_y
    ):
        raise TokenAPIError(
            status_code=409,
            code="token_pose_out_of_bounds",
            message="The entire token must remain inside the authoritative board.",
        )


def _execute(store: SQLiteTokenStore, command: TokenMutationCommand):
    try:
        return store.execute(command)
    except TokenRevisionConflictError as exc:
        raise TokenAPIError(
            status_code=409,
            code="token_stale_revision",
            message="The token command targets a stale catalog revision.",
            details={"current_revision": exc.current_revision},
        ) from exc
    except TokenCommandConflictError as exc:
        raise TokenAPIError(
            status_code=409,
            code="token_command_id_conflict",
            message="The token command ID was already used with different content.",
        ) from exc
    except TokenIdConflictError as exc:
        raise TokenAPIError(
            status_code=409,
            code="token_id_conflict",
            message="The token ID was already used.",
        ) from exc
    except TokenNotFoundError as exc:
        raise TokenAPIError(
            status_code=404,
            code="token_not_found",
            message="The requested token is unavailable.",
        ) from exc
    except TokenSceneMismatchError as exc:
        raise TokenAPIError(
            status_code=409,
            code="token_scene_mismatch",
            message="The token belongs to a different scene.",
        ) from exc
    except TokenLockedError as exc:
        raise TokenAPIError(
            status_code=409,
            code="token_locked",
            message="Unlock the token before changing its pose.",
        ) from exc
    except (sqlite3.Error, TokenStoreError) as exc:
        raise _storage_error(exc) from exc


def _event_scene_id(event: TokenMutationEvent) -> str:
    if hasattr(event, "token"):
        return event.token.scene_id  # type: ignore[union-attr]
    return event.scene_id  # type: ignore[union-attr]


def _event_cursor(value: str | None, *, field: str) -> int | None:
    if value is None:
        return None
    if not value or any(character not in "0123456789" for character in value):
        raise TokenAPIError(
            status_code=400,
            code="invalid_token_event_cursor",
            message="The token event cursor must be a canonical non-negative integer.",
            details={"field": field},
        )
    cursor = int(value)
    if str(cursor) != value:
        raise TokenAPIError(
            status_code=400,
            code="invalid_token_event_cursor",
            message="The token event cursor must be a canonical non-negative integer.",
            details={"field": field},
        )
    return cursor


def _resume_after(*, after: str | None, last_event_id: str | None) -> int:
    query = _event_cursor(after, field="after")
    header = _event_cursor(last_event_id, field="Last-Event-ID")
    return max(value for value in (0, query, header) if value is not None)


def _events_after(store: SQLiteTokenStore, table_id: str, sequence: int):
    try:
        return store.events_after(table_id, sequence)
    except (sqlite3.Error, TokenStoreError) as exc:
        raise _storage_error(exc) from exc


def _render_signal(event: TokenMutationEvent, scene_id: str) -> str:
    signal = TokenChangeSignal(
        sequence=event.sequence,
        revision=event.revision,
        scene_id=scene_id,
    )
    payload = json.dumps(
        signal.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"id: {signal.sequence}\nevent: vtt.tokens_changed\ndata: {payload}\n\n"


async def _stream_token_events(
    *,
    request: Request,
    store: SQLiteTokenStore,
    table_id: str,
    scene_id: str,
    scenes: SQLiteSceneLibrary,
    participant: TableParticipant | None,
    after: int,
    initial_events: tuple[TokenMutationEvent, ...],
) -> AsyncIterator[str]:
    cursor = after
    pending = initial_events
    loop = asyncio.get_running_loop()
    next_heartbeat = loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
    while True:
        if await request.is_disconnected():
            return
        if participant is not None and participant.role != "gm":
            active_scene_id = scenes.snapshot(table_id).active_scene_id
            if active_scene_id != scene_id:
                return
        events = pending
        pending = ()
        if not events:
            events = _events_after(store, table_id, cursor)
        if events:
            yielded = False
            for event in events:
                cursor = event.sequence
                if _event_scene_id(event) != scene_id:
                    continue
                yield _render_signal(event, scene_id)
                yielded = True
            if yielded:
                next_heartbeat = loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
        elif loop.time() >= next_heartbeat:
            yield ": heartbeat\n\n"
            next_heartbeat = loop.time() + SSE_HEARTBEAT_INTERVAL_SECONDS
        await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)


def _response(session_id: str, result) -> TokenResponse:
    receipt: TokenMutationReceipt = result.receipt
    return TokenResponse(
        session_id=session_id,
        table_id=receipt.table_id,
        command_id=receipt.command_id,
        revision=receipt.revision,
        replayed=result.replayed,
        event=receipt.event,
    )


def install_token_routes(
    app: FastAPI,
    *,
    store: SQLiteTokenStore,
    scenes: SQLiteSceneLibrary,
    service: VTTSessionService,
    scene_origin: FeetPosition,
    session_id: str,
    table_id: str,
    access_policy: TableAccessPolicy | None,
    visibility_tokens: Callable[[TableParticipant], tuple[TokenRecord, ...]] | None = None,
) -> None:
    """Install token lifecycle routes without changing encounter command schemas."""

    configured_session_id = _canonical_text(session_id, field_name="session_id")
    configured_table_id = _canonical_text(table_id, field_name="table_id")
    if not isinstance(scene_origin, FeetPosition):
        raise TypeError("scene_origin must be a FeetPosition")
    if visibility_tokens is not None and not callable(visibility_tokens):
        raise TypeError("visibility_tokens must be callable or None")
    scene_origin = scene_origin.model_copy(deep=True)
    router = APIRouter()

    @router.get("/api/v1/tokens", response_model=TokenView)
    async def get_tokens(
        request: Request,
        scene_id: Annotated[str, Query(min_length=1, max_length=128)],
    ) -> TokenView:
        participant = _request_participant(request, access_policy=access_policy)
        entry = _scene_entry(
            scenes,
            table_id=configured_table_id,
            scene_id=scene_id,
            participant=participant,
        )
        truth = _read_truth(store, table_id=configured_table_id, scene_id=scene_id)
        if visibility_tokens is not None and participant is not None and participant.role != "gm":
            projected_tokens = visibility_tokens(participant)
            if any(token.scene_id != scene_id for token in projected_tokens):
                raise RuntimeError("visibility tokens do not match the requested scene")
            visible = TokenView(
                table_id=truth.table_id,
                scene_id=truth.scene_id,
                revision=truth.revision,
                tokens=projected_tokens,
            )
        else:
            visible = project_token_view(truth, participant)
        bound = _bind_actor_positions(visible, service)
        for token in bound.tokens:
            _validate_pose_bounds(token, scene_origin, entry.scene.map_metadata)
        return bound

    @router.post("/api/v1/token-commands", response_model=TokenResponse)
    async def execute_token_command(
        payload: TokenRequest,
        request: Request,
    ) -> TokenResponse:
        participant = _request_participant(request, access_policy=access_policy)
        if participant is not None and participant.role != "gm":
            raise TokenAPIError(
                status_code=403,
                code="token_forbidden",
                message="This participant is not permitted to mutate tokens.",
            )
        if (
            payload.session_id != configured_session_id
            or payload.command.table_id != configured_table_id
        ):
            raise TokenAPIError(
                status_code=409,
                code="token_binding_mismatch",
                message="The token request belongs to a different table or session.",
                details={
                    "expected_session_id": configured_session_id,
                    "expected_table_id": configured_table_id,
                },
            )
        try:
            replayed = store.replay(payload.command)
        except (sqlite3.Error, TokenStoreError) as exc:
            if isinstance(exc, TokenCommandConflictError):
                raise TokenAPIError(
                    status_code=409,
                    code="token_command_id_conflict",
                    message="The token command ID was already used with different content.",
                ) from exc
            raise _storage_error(exc) from exc
        if replayed is not None:
            return _response(configured_session_id, replayed)

        command = payload.command
        authority_metadata: SceneMapMetadata | None = None
        if isinstance(command, (TokenCreateCommand, TokenUpdateCommand)):
            entry = _scene_entry(
                scenes,
                table_id=configured_table_id,
                scene_id=command.token.scene_id,
                participant=participant,
            )
            if entry.archived:
                raise TokenAPIError(
                    status_code=409,
                    code="token_scene_archived",
                    message="Tokens cannot be changed on an archived scene.",
                )
            authority_metadata = entry.scene.map_metadata
        elif isinstance(command, TokenDeleteCommand):
            _scene_entry(
                scenes,
                table_id=configured_table_id,
                scene_id=command.scene_id,
                participant=participant,
            )
        elif not isinstance(command, TokenDuplicateCommand):  # pragma: no cover
            raise RuntimeError("unsupported token command")
        authority_token: TokenRecord | None = None
        if isinstance(command, (TokenCreateCommand, TokenUpdateCommand)):
            authority_token = command.token
        elif isinstance(command, TokenDuplicateCommand):
            try:
                source = store.token(configured_table_id, command.source_token_id)
            except (sqlite3.Error, TokenStoreError) as exc:
                raise _storage_error(exc) from exc
            if source is not None:
                entry = _scene_entry(
                    scenes,
                    table_id=configured_table_id,
                    scene_id=source.scene_id,
                    participant=participant,
                )
                if entry.archived:
                    raise TokenAPIError(
                        status_code=409,
                        code="token_scene_archived",
                        message="Tokens cannot be changed on an archived scene.",
                    )
                authority_token = source.model_copy(update={"pose": command.pose})
                authority_metadata = entry.scene.map_metadata
        _validate_actor_authority(authority_token, service)
        if authority_token is not None:
            if authority_metadata is None:  # pragma: no cover - resolved above
                raise RuntimeError("token authority metadata was not resolved")
            _validate_pose_bounds(authority_token, scene_origin, authority_metadata)
        return _response(configured_session_id, _execute(store, command))

    @router.get("/api/v1/token-events", response_class=StreamingResponse)
    async def get_token_events(
        request: Request,
        scene_id: Annotated[str, Query(min_length=1, max_length=128)],
        after: Annotated[str | None, Query()] = None,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        participant = _request_participant(request, access_policy=access_policy)
        _scene_entry(
            scenes,
            table_id=configured_table_id,
            scene_id=scene_id,
            participant=participant,
        )
        cursor = _resume_after(after=after, last_event_id=last_event_id)
        initial = _events_after(store, configured_table_id, cursor)
        return StreamingResponse(
            _stream_token_events(
                request=request,
                store=store,
                table_id=configured_table_id,
                scene_id=scene_id,
                scenes=scenes,
                participant=participant,
                after=cursor,
                initial_events=initial,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    app.include_router(router)


__all__ = [
    "TOKEN_CHANGE_SIGNAL_SCHEMA_VERSION",
    "TOKEN_PROTECTED_ROUTES",
    "VTT_TOKEN_REQUEST_SCHEMA_VERSION",
    "VTT_TOKEN_RESPONSE_SCHEMA_VERSION",
    "TokenAPIError",
    "TokenChangeSignal",
    "TokenRequest",
    "TokenResponse",
    "install_token_routes",
    "hidden_engine_actor_values_for_tokens",
    "project_engine_projection_for_tokens",
]
