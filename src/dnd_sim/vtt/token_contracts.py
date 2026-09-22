"""Strict, renderer-neutral contracts for durable tabletop tokens."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Self, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    TypeAdapter,
    field_validator,
    model_serializer,
    model_validator,
)

from .board_calibration import AxialHexCell
from .participants import TableParticipant
from .scene import FeetPosition

TOKEN_POSE_SCHEMA_VERSION = "vtt.token_pose.v1"
TOKEN_RECORD_SCHEMA_VERSION = "vtt.token_record.v1"
TOKEN_VIEW_SCHEMA_VERSION = "vtt.token_view.v1"
TOKEN_COMMAND_SCHEMA_VERSION = "vtt.token_command.v1"
TOKEN_EVENT_SCHEMA_VERSION = "vtt.token_event.v1"
TOKEN_RECEIPT_SCHEMA_VERSION = "vtt.token_receipt.v1"

MAX_TOKEN_EXTENT_FT = 500.0
MAX_TOKEN_AURA_FT = 1_000.0
MAX_TOKEN_CONDITIONS = 32
MAX_TOKEN_HEX_CELLS = 64

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
PositiveExtent = Annotated[
    float,
    Field(strict=True, gt=0.0, le=MAX_TOKEN_EXTENT_FT, allow_inf_nan=False),
]
AuraRadius = Annotated[
    float,
    Field(strict=True, ge=0.0, le=MAX_TOKEN_AURA_FT, allow_inf_nan=False),
]
RotationDegrees = Annotated[
    float,
    Field(strict=True, ge=0.0, lt=360.0, allow_inf_nan=False),
]
LayerIndex = Annotated[int, Field(strict=True, ge=-100, le=100)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]


class _StrictTokenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _canonical_text(value: str, *, field_name: str, maximum_length: int = 160) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    if len(value) > maximum_length:
        raise ValueError(f"{field_name} must be at most {maximum_length} characters")
    return value


def _opaque_id(value: str, *, field_name: str) -> str:
    value = _canonical_text(value, field_name=field_name, maximum_length=128)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value) is None:
        raise ValueError(f"{field_name} must be a URL-safe identifier")
    return value


class TokenPose(_StrictTokenModel):
    """Scene-space presentation pose; positions remain canonical feet."""

    schema_version: Literal[TOKEN_POSE_SCHEMA_VERSION] = TOKEN_POSE_SCHEMA_VERSION
    position_ft: FeetPosition
    width_ft: PositiveExtent = 5.0
    height_ft: PositiveExtent = 5.0
    rotation_degrees: RotationDegrees = 0.0
    layer: LayerIndex = 0
    occupied_hex_cells: tuple[AxialHexCell, ...] = ()

    @field_validator("occupied_hex_cells", mode="before")
    @classmethod
    def validate_hex_footprint(cls, value: Any) -> tuple[Any, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("occupied_hex_cells must be an ordered list or tuple")
        cells = tuple(value)
        if len(cells) > MAX_TOKEN_HEX_CELLS:
            raise ValueError("occupied_hex_cells exceeds the supported count")
        coordinates: list[tuple[int, int]] = []
        for cell in cells:
            if isinstance(cell, AxialHexCell):
                coordinates.append((cell.q, cell.r))
            elif isinstance(cell, dict):
                q = cell.get("q")
                r = cell.get("r")
                if type(q) is not int or type(r) is not int:
                    return cells
                coordinates.append((q, r))
            else:
                return cells
        if coordinates != sorted(set(coordinates)):
            raise ValueError("occupied_hex_cells must be unique and sorted by q then r")
        return cells

    @model_serializer(mode="wrap")
    def serialize_without_empty_hex_footprint(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> dict[str, Any]:
        serialized = dict(handler(self))
        if not self.occupied_hex_cells:
            serialized.pop("occupied_hex_cells", None)
        return serialized


class TokenRecord(_StrictTokenModel):
    """One scene-local tabletop object optionally linked to an engine actor."""

    schema_version: Literal[TOKEN_RECORD_SCHEMA_VERSION] = TOKEN_RECORD_SCHEMA_VERSION
    token_id: str
    scene_id: str
    actor_id: str | None = None
    name: str
    pose: TokenPose
    visibility: Literal["public", "owners", "gm_only"] = "public"
    locked: bool = False
    nameplate: Literal["hidden", "hover", "always"] = "hover"
    show_hp_bar: bool = False
    aura_radius_ft: AuraRadius = 0.0
    aura_color: str = "#4DD7B3"
    condition_labels: tuple[str, ...] = ()

    @field_validator("token_id")
    @classmethod
    def validate_token_id(cls, value: str) -> str:
        return _opaque_id(value, field_name="token_id")

    @field_validator("scene_id", "actor_id")
    @classmethod
    def validate_linked_id(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _canonical_text(value, field_name=info.field_name, maximum_length=128)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _canonical_text(value, field_name="name")

    @field_validator("locked", "show_hp_bar", mode="before")
    @classmethod
    def validate_boolean(cls, value: Any, info: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a boolean")
        return value

    @field_validator("aura_color")
    @classmethod
    def validate_aura_color(cls, value: str) -> str:
        if not isinstance(value, str) or re.fullmatch(r"#[0-9A-F]{6}", value) is None:
            raise ValueError("aura_color must be an uppercase six-digit hex color")
        return value

    @field_validator("condition_labels", mode="before")
    @classmethod
    def validate_condition_labels(cls, values: Any) -> tuple[str, ...]:
        if not isinstance(values, (list, tuple)):
            raise ValueError("condition_labels must be an ordered list or tuple")
        values = tuple(values)
        if len(values) > MAX_TOKEN_CONDITIONS:
            raise ValueError("condition_labels exceeds the supported count")
        for value in values:
            _canonical_text(value, field_name="condition label", maximum_length=80)
        if values != tuple(sorted(set(values))):
            raise ValueError("condition_labels must be unique and sorted")
        return values

    @model_validator(mode="after")
    def validate_owner_visibility(self) -> Self:
        if self.visibility == "owners" and self.actor_id is None:
            raise ValueError("owners visibility requires an actor link")
        return self


class TokenView(_StrictTokenModel):
    """Audience-safe token projection for one scene at a table revision."""

    schema_version: Literal[TOKEN_VIEW_SCHEMA_VERSION] = TOKEN_VIEW_SCHEMA_VERSION
    table_id: str
    scene_id: str
    revision: NonNegativeInt
    tokens: tuple[TokenRecord, ...] = ()

    @field_validator("table_id")
    @classmethod
    def validate_table_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="table_id", maximum_length=128)

    @field_validator("scene_id")
    @classmethod
    def validate_scene_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="scene_id", maximum_length=128)

    @field_validator("tokens", mode="before")
    @classmethod
    def normalize_tokens(cls, value: Any) -> tuple[Any, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("tokens must be an ordered list or tuple")
        return tuple(value)

    @model_validator(mode="after")
    def validate_token_scope_and_order(self) -> Self:
        ids = tuple(token.token_id for token in self.tokens)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("tokens must have unique token IDs in sorted order")
        if any(token.scene_id != self.scene_id for token in self.tokens):
            raise ValueError("all tokens must belong to the projected scene")
        return self

    def token(self, token_id: str) -> TokenRecord | None:
        normalized = _opaque_id(token_id, field_name="token_id")
        return next((token for token in self.tokens if token.token_id == normalized), None)


def project_token_view(
    view: TokenView,
    participant: TableParticipant | None,
) -> TokenView:
    """Omit token identity entirely when the participant may not perceive it."""

    if not isinstance(view, TokenView):
        raise TypeError("view must be a TokenView")
    if participant is not None and not isinstance(participant, TableParticipant):
        raise TypeError("participant must be a TableParticipant or None")
    if participant is None or participant.role == "gm":
        return view.model_copy(deep=True)
    owned_actor_ids = set(participant.owned_actor_ids)
    visible = tuple(
        token
        for token in view.tokens
        if token.visibility == "public"
        or (token.visibility == "owners" and token.actor_id in owned_actor_ids)
    )
    return TokenView(
        table_id=view.table_id,
        scene_id=view.scene_id,
        revision=view.revision,
        tokens=visible,
    )


class _TokenCommandBase(_StrictTokenModel):
    schema_version: Literal[TOKEN_COMMAND_SCHEMA_VERSION] = TOKEN_COMMAND_SCHEMA_VERSION
    table_id: str
    command_id: str
    expected_revision: NonNegativeInt

    @field_validator("table_id", "command_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name, maximum_length=128)


class TokenCreateCommand(_TokenCommandBase):
    command_type: Literal["create"] = "create"
    token: TokenRecord


class TokenUpdateCommand(_TokenCommandBase):
    command_type: Literal["update"] = "update"
    token: TokenRecord


class TokenDuplicateCommand(_TokenCommandBase):
    command_type: Literal["duplicate"] = "duplicate"
    source_token_id: str
    new_token_id: str
    pose: TokenPose

    @field_validator("source_token_id", "new_token_id")
    @classmethod
    def validate_token_id(cls, value: str, info: Any) -> str:
        return _opaque_id(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_distinct_token_ids(self) -> Self:
        if self.source_token_id == self.new_token_id:
            raise ValueError("new_token_id must differ from source_token_id")
        return self


class TokenDeleteCommand(_TokenCommandBase):
    command_type: Literal["delete"] = "delete"
    scene_id: str
    token_id: str

    @field_validator("scene_id")
    @classmethod
    def validate_scene_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="scene_id", maximum_length=128)

    @field_validator("token_id")
    @classmethod
    def validate_target_id(cls, value: str, info: Any) -> str:
        return _opaque_id(value, field_name=info.field_name)


TokenMutationCommand: TypeAlias = Annotated[
    TokenCreateCommand | TokenUpdateCommand | TokenDuplicateCommand | TokenDeleteCommand,
    Field(discriminator="command_type"),
]


class _TokenEventBase(_StrictTokenModel):
    schema_version: Literal[TOKEN_EVENT_SCHEMA_VERSION] = TOKEN_EVENT_SCHEMA_VERSION
    table_id: str
    event_id: str
    sequence: PositiveInt
    revision: PositiveInt
    command_id: str

    @field_validator("table_id", "command_id", "event_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name, maximum_length=512)

    @model_validator(mode="after")
    def validate_sequence_revision(self) -> Self:
        if self.sequence != self.revision:
            raise ValueError("sequence must match revision")
        return self


class TokenCreatedEvent(_TokenEventBase):
    event_type: Literal["created"] = "created"
    token: TokenRecord


class TokenUpdatedEvent(_TokenEventBase):
    event_type: Literal["updated"] = "updated"
    token: TokenRecord


class TokenDuplicatedEvent(_TokenEventBase):
    event_type: Literal["duplicated"] = "duplicated"
    source_token_id: str
    token: TokenRecord

    @field_validator("source_token_id")
    @classmethod
    def validate_source_token_id(cls, value: str) -> str:
        return _opaque_id(value, field_name="source_token_id")


class TokenDeletedEvent(_TokenEventBase):
    event_type: Literal["deleted"] = "deleted"
    scene_id: str
    token_id: str

    @field_validator("scene_id")
    @classmethod
    def validate_scene_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="scene_id", maximum_length=128)

    @field_validator("token_id")
    @classmethod
    def validate_target_id(cls, value: str, info: Any) -> str:
        return _opaque_id(value, field_name=info.field_name)


TokenMutationEvent: TypeAlias = Annotated[
    TokenCreatedEvent | TokenUpdatedEvent | TokenDuplicatedEvent | TokenDeletedEvent,
    Field(discriminator="event_type"),
]


class TokenMutationReceipt(_StrictTokenModel):
    schema_version: Literal[TOKEN_RECEIPT_SCHEMA_VERSION] = TOKEN_RECEIPT_SCHEMA_VERSION
    table_id: str
    command_id: str
    revision: PositiveInt
    event: TokenMutationEvent

    @field_validator("table_id", "command_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name, maximum_length=128)

    @model_validator(mode="after")
    def validate_event_identity(self) -> Self:
        if (
            self.event.table_id != self.table_id
            or self.event.command_id != self.command_id
            or self.event.revision != self.revision
        ):
            raise ValueError("event identity must match its receipt")
        return self


_COMMAND_ADAPTER = TypeAdapter(TokenMutationCommand)
_EVENT_ADAPTER = TypeAdapter(TokenMutationEvent)


def parse_token_command(value: Any) -> TokenMutationCommand:
    return _COMMAND_ADAPTER.validate_python(value, strict=True)


def parse_token_event(value: Any) -> TokenMutationEvent:
    return _EVENT_ADAPTER.validate_python(value, strict=True)
