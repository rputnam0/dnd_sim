"""Strict renderer-neutral barriers, light, senses, and manual-fog records."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .participants import validate_audience_selectors

SIGHT_BARRIER_SCHEMA_VERSION = "vtt.sight_barrier.v1"
LIGHT_EMITTER_SCHEMA_VERSION = "vtt.light_emitter.v1"
SCENE_ENVIRONMENT_SCHEMA_VERSION = "vtt.scene_environment.v1"
TOKEN_VISION_SCHEMA_VERSION = "vtt.token_vision.v1"
FOG_OPERATION_SCHEMA_VERSION = "vtt.fog_operation.v1"
VISIBILITY_COMMAND_SCHEMA_VERSION = "vtt.visibility_command.v1"
VISIBILITY_EVENT_SCHEMA_VERSION = "vtt.visibility_event.v1"
VISIBILITY_RECEIPT_SCHEMA_VERSION = "vtt.visibility_receipt.v1"
VISIBILITY_CATALOG_VIEW_SCHEMA_VERSION = "vtt.visibility_catalog_view.v1"

MAX_VISIBILITY_COORDINATE_FT = 1_000_000.0
MAX_VISION_RANGE_FT = 100_000.0
MAX_FOG_POLYGON_VERTICES = 128
MIN_SEGMENT_LENGTH_FT = 0.01
MIN_POLYGON_AREA_SQ_FT = 0.01


def _require_float(value: Any) -> float:
    if type(value) is not float:
        raise ValueError("value must be a floating-point number")
    return value


FiniteCoordinate = Annotated[
    float,
    Field(
        strict=True,
        ge=-MAX_VISIBILITY_COORDINATE_FT,
        le=MAX_VISIBILITY_COORDINATE_FT,
        allow_inf_nan=False,
    ),
]
NonNegativeRange = Annotated[
    float,
    Field(strict=True, ge=0.0, le=MAX_VISION_RANGE_FT, allow_inf_nan=False),
]
DirectionDegrees = Annotated[
    float,
    Field(strict=True, ge=0.0, lt=360.0, allow_inf_nan=False),
]
AngleDegrees = Annotated[
    float,
    Field(strict=True, gt=0.0, le=360.0, allow_inf_nan=False),
]


class _StrictVisibilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _canonical_id(value: str, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value) is None
    ):
        raise ValueError(f"{field_name} must be a canonical URL-safe identifier")
    return value


class VisibilityPoint(_StrictVisibilityModel):
    x_ft: FiniteCoordinate
    y_ft: FiniteCoordinate


class _VisibilityRecordBase(_StrictVisibilityModel):
    record_id: str
    scene_id: str

    @field_validator("record_id", "scene_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _canonical_id(value, field_name=info.field_name)


class SightBarrier(_VisibilityRecordBase):
    schema_version: Literal[SIGHT_BARRIER_SCHEMA_VERSION] = SIGHT_BARRIER_SCHEMA_VERSION
    record_type: Literal["barrier"] = "barrier"
    start: VisibilityPoint
    end: VisibilityPoint
    behavior: Literal["wall", "window", "door"]
    blocks_sight: bool
    blocks_movement: bool
    portal_state: Literal["open", "closed"] | None = None

    @model_validator(mode="after")
    def validate_barrier(self) -> "SightBarrier":
        if (
            math.hypot(
                self.end.x_ft - self.start.x_ft,
                self.end.y_ft - self.start.y_ft,
            )
            < MIN_SEGMENT_LENGTH_FT
        ):
            raise ValueError("barrier endpoints must define a nondegenerate segment")
        if self.behavior == "door":
            if self.portal_state is None:
                raise ValueError("a door barrier requires portal_state")
        elif self.portal_state is not None:
            raise ValueError("only a door barrier may define portal_state")
        if self.behavior == "window" and self.blocks_sight:
            raise ValueError("a window barrier must pass sight")
        return self


class LightEmitter(_VisibilityRecordBase):
    schema_version: Literal[LIGHT_EMITTER_SCHEMA_VERSION] = LIGHT_EMITTER_SCHEMA_VERSION
    record_type: Literal["light"] = "light"
    origin: VisibilityPoint
    bright_radius_ft: NonNegativeRange
    dim_radius_ft: NonNegativeRange
    shape: Literal["circle", "cone"]
    direction_degrees: DirectionDegrees
    angle_degrees: AngleDegrees
    audience: tuple[str, ...] = ("all",)

    @field_validator("audience", mode="before")
    @classmethod
    def validate_audience(cls, value: Any) -> tuple[str, ...]:
        return validate_audience_selectors(value)

    @model_validator(mode="after")
    def validate_light(self) -> "LightEmitter":
        if self.dim_radius_ft < self.bright_radius_ft:
            raise ValueError("dim radius must be at least the bright radius")
        if self.dim_radius_ft <= 0.0:
            raise ValueError("a light emitter requires a positive dim radius")
        if self.shape == "circle" and (
            self.direction_degrees != 0.0 or self.angle_degrees != 360.0
        ):
            raise ValueError("circle light direction and angle must be canonical")
        if self.shape == "cone" and self.angle_degrees > 180.0:
            raise ValueError("cone light angle must not exceed 180 degrees")
        return self


class SceneEnvironment(_VisibilityRecordBase):
    schema_version: Literal[SCENE_ENVIRONMENT_SCHEMA_VERSION] = SCENE_ENVIRONMENT_SCHEMA_VERSION
    record_type: Literal["environment"] = "environment"
    darkness: Literal["bright", "dim", "darkness"]
    shared_vision: Literal["owned_only", "party"]

    @model_validator(mode="after")
    def validate_environment_identity(self) -> "SceneEnvironment":
        if self.record_id != "scene-environment":
            raise ValueError("scene environment uses one canonical record_id")
        return self


class TokenVision(_VisibilityRecordBase):
    schema_version: Literal[TOKEN_VISION_SCHEMA_VERSION] = TOKEN_VISION_SCHEMA_VERSION
    record_type: Literal["token_vision"] = "token_vision"
    token_id: str
    enabled: bool
    normal_range_ft: NonNegativeRange
    darkvision_range_ft: NonNegativeRange
    emitted_bright_radius_ft: NonNegativeRange
    emitted_dim_radius_ft: NonNegativeRange

    @field_validator("token_id")
    @classmethod
    def validate_token_id(cls, value: str) -> str:
        return _canonical_id(value, field_name="token_id")

    @model_validator(mode="after")
    def validate_emitted_light(self) -> "TokenVision":
        if self.emitted_dim_radius_ft < self.emitted_bright_radius_ft:
            raise ValueError("emitted dim radius must be at least the bright radius")
        return self


def _cross(start: VisibilityPoint, middle: VisibilityPoint, end: VisibilityPoint) -> float:
    return (middle.x_ft - start.x_ft) * (end.y_ft - start.y_ft) - (middle.y_ft - start.y_ft) * (
        end.x_ft - start.x_ft
    )


def _point_on_segment(
    point: VisibilityPoint,
    start: VisibilityPoint,
    end: VisibilityPoint,
) -> bool:
    epsilon = 1e-9
    return abs(_cross(start, end, point)) <= epsilon and (
        min(start.x_ft, end.x_ft) - epsilon <= point.x_ft <= max(start.x_ft, end.x_ft) + epsilon
        and min(start.y_ft, end.y_ft) - epsilon <= point.y_ft <= max(start.y_ft, end.y_ft) + epsilon
    )


def _segments_intersect(
    first_start: VisibilityPoint,
    first_end: VisibilityPoint,
    second_start: VisibilityPoint,
    second_end: VisibilityPoint,
) -> bool:
    first_side_start = _cross(first_start, first_end, second_start)
    first_side_end = _cross(first_start, first_end, second_end)
    second_side_start = _cross(second_start, second_end, first_start)
    second_side_end = _cross(second_start, second_end, first_end)
    epsilon = 1e-9
    if (
        (first_side_start > epsilon and first_side_end < -epsilon)
        or (first_side_start < -epsilon and first_side_end > epsilon)
    ) and (
        (second_side_start > epsilon and second_side_end < -epsilon)
        or (second_side_start < -epsilon and second_side_end > epsilon)
    ):
        return True
    return any(
        (abs(cross) <= epsilon and _point_on_segment(point, segment_start, segment_end))
        for cross, point, segment_start, segment_end in (
            (first_side_start, second_start, first_start, first_end),
            (first_side_end, second_end, first_start, first_end),
            (second_side_start, first_start, second_start, second_end),
            (second_side_end, first_end, second_start, second_end),
        )
    )


def _polygon_area(polygon: Sequence[VisibilityPoint]) -> float:
    return (
        abs(
            sum(
                point.x_ft * polygon[(index + 1) % len(polygon)].y_ft
                - polygon[(index + 1) % len(polygon)].x_ft * point.y_ft
                for index, point in enumerate(polygon)
            )
        )
        / 2.0
    )


def _polygon_is_simple(polygon: Sequence[VisibilityPoint]) -> bool:
    count = len(polygon)
    for first in range(count):
        first_next = (first + 1) % count
        for second in range(first + 1, count):
            second_next = (second + 1) % count
            if first == second or first_next == second or second_next == first:
                continue
            if _segments_intersect(
                polygon[first],
                polygon[first_next],
                polygon[second],
                polygon[second_next],
            ):
                return False
    return True


class FogOperation(_VisibilityRecordBase):
    schema_version: Literal[FOG_OPERATION_SCHEMA_VERSION] = FOG_OPERATION_SCHEMA_VERSION
    record_type: Literal["fog_operation"] = "fog_operation"
    operation_index: Annotated[int, Field(strict=True, ge=1, le=2_000)]
    operation: Literal["reveal", "hide"]
    polygon: tuple[VisibilityPoint, ...]
    inverse_of: str | None = None

    @field_validator("polygon", mode="before")
    @classmethod
    def normalize_polygon(cls, value: Any) -> tuple[Any, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("polygon must be an ordered list or tuple")
        return tuple(value)

    @field_validator("inverse_of")
    @classmethod
    def validate_inverse_of(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _canonical_id(value, field_name="inverse_of")

    @model_validator(mode="after")
    def validate_polygon(self) -> "FogOperation":
        if not 3 <= len(self.polygon) <= MAX_FOG_POLYGON_VERTICES:
            raise ValueError("fog polygon vertex count is out of bounds")
        if any(
            self.polygon[index] == self.polygon[(index + 1) % len(self.polygon)]
            for index in range(len(self.polygon))
        ):
            raise ValueError("fog polygon has duplicate adjacent vertices")
        if _polygon_area(self.polygon) < MIN_POLYGON_AREA_SQ_FT:
            raise ValueError("fog polygon area is degenerate")
        if not _polygon_is_simple(self.polygon):
            raise ValueError("fog polygon must not self-intersect")
        return self


VisibilityRecord: TypeAlias = Annotated[
    SightBarrier | LightEmitter | SceneEnvironment | TokenVision | FogOperation,
    Field(discriminator="record_type"),
]


class VisibilityCatalogView(_StrictVisibilityModel):
    schema_version: Literal[VISIBILITY_CATALOG_VIEW_SCHEMA_VERSION] = (
        VISIBILITY_CATALOG_VIEW_SCHEMA_VERSION
    )
    table_id: str
    scene_id: str
    revision: Annotated[int, Field(strict=True, ge=0)]
    records: tuple[VisibilityRecord, ...] = ()

    @field_validator("table_id", "scene_id")
    @classmethod
    def validate_catalog_identity(cls, value: str, info: Any) -> str:
        return _canonical_id(value, field_name=info.field_name)

    @field_validator("records", mode="before")
    @classmethod
    def normalize_records(cls, value: Any) -> tuple[Any, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("records must be an ordered list or tuple")
        return tuple(value)

    @model_validator(mode="after")
    def validate_scope_and_order(self) -> "VisibilityCatalogView":
        if any(record.scene_id != self.scene_id for record in self.records):
            raise ValueError("all visibility records must belong to scene_id")
        identities = tuple(record.record_id for record in self.records)
        if identities != tuple(sorted(set(identities))):
            raise ValueError("visibility records must have unique sorted identities")
        environments = sum(isinstance(record, SceneEnvironment) for record in self.records)
        if environments > 1:
            raise ValueError("a scene may contain at most one environment record")
        vision_token_ids = tuple(
            record.token_id for record in self.records if isinstance(record, TokenVision)
        )
        if len(vision_token_ids) != len(set(vision_token_ids)):
            raise ValueError("a token may contain at most one vision record")
        fog_indexes = tuple(
            sorted(
                record.operation_index
                for record in self.records
                if isinstance(record, FogOperation)
            )
        )
        if fog_indexes and fog_indexes != tuple(range(1, len(fog_indexes) + 1)):
            raise ValueError("fog operation indexes must be contiguous")
        return self


class _VisibilityCommandBase(_StrictVisibilityModel):
    schema_version: Literal[VISIBILITY_COMMAND_SCHEMA_VERSION] = VISIBILITY_COMMAND_SCHEMA_VERSION
    table_id: str
    command_id: str
    expected_revision: Annotated[int, Field(strict=True, ge=0)]

    @field_validator("table_id", "command_id")
    @classmethod
    def validate_command_identity(cls, value: str, info: Any) -> str:
        return _canonical_id(value, field_name=info.field_name)


class VisibilityPutCommand(_VisibilityCommandBase):
    command_type: Literal["put"] = "put"
    record: VisibilityRecord


class VisibilityDeleteCommand(_VisibilityCommandBase):
    command_type: Literal["delete"] = "delete"
    scene_id: str
    record_id: str

    @field_validator("scene_id", "record_id")
    @classmethod
    def validate_target_identity(cls, value: str, info: Any) -> str:
        return _canonical_id(value, field_name=info.field_name)


class VisibilityDoorStateCommand(_VisibilityCommandBase):
    command_type: Literal["set_door_state"] = "set_door_state"
    scene_id: str
    barrier_id: str
    portal_state: Literal["open", "closed"]

    @field_validator("scene_id", "barrier_id")
    @classmethod
    def validate_door_identity(cls, value: str, info: Any) -> str:
        return _canonical_id(value, field_name=info.field_name)


class VisibilityFogUndoCommand(_VisibilityCommandBase):
    command_type: Literal["undo_fog"] = "undo_fog"
    scene_id: str
    target_record_id: str
    inverse_record_id: str

    @field_validator("scene_id", "target_record_id", "inverse_record_id")
    @classmethod
    def validate_fog_identity(cls, value: str, info: Any) -> str:
        return _canonical_id(value, field_name=info.field_name)


VisibilityCommand: TypeAlias = Annotated[
    VisibilityPutCommand
    | VisibilityDeleteCommand
    | VisibilityDoorStateCommand
    | VisibilityFogUndoCommand,
    Field(discriminator="command_type"),
]


class VisibilityChangedEvent(_StrictVisibilityModel):
    schema_version: Literal[VISIBILITY_EVENT_SCHEMA_VERSION] = VISIBILITY_EVENT_SCHEMA_VERSION
    event_type: Literal["visibility_changed"] = "visibility_changed"
    sequence: Annotated[int, Field(strict=True, ge=1)]
    revision: Annotated[int, Field(strict=True, ge=1)]
    table_id: str
    command_id: str
    scene_id: str
    operation: Literal["put", "delete", "set_door_state", "undo_fog"]
    record: VisibilityRecord | None
    deleted_record_id: str | None

    @field_validator("table_id", "command_id", "scene_id")
    @classmethod
    def validate_event_identity(cls, value: str, info: Any) -> str:
        return _canonical_id(value, field_name=info.field_name)

    @field_validator("deleted_record_id")
    @classmethod
    def validate_deleted_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _canonical_id(value, field_name="deleted_record_id")

    @model_validator(mode="after")
    def validate_payload(self) -> "VisibilityChangedEvent":
        if self.sequence != self.revision:
            raise ValueError("visibility event sequence and revision must match")
        if self.operation == "delete":
            if self.record is not None or self.deleted_record_id is None:
                raise ValueError("delete visibility events require only deleted_record_id")
        elif (
            self.record is None
            or self.deleted_record_id is not None
            or self.record.scene_id != self.scene_id
        ):
            raise ValueError("visibility change event record does not match its scene")
        return self


class VisibilityMutationReceipt(_StrictVisibilityModel):
    schema_version: Literal[VISIBILITY_RECEIPT_SCHEMA_VERSION] = VISIBILITY_RECEIPT_SCHEMA_VERSION
    table_id: str
    command_id: str
    revision: Annotated[int, Field(strict=True, ge=1)]
    event: VisibilityChangedEvent

    @model_validator(mode="after")
    def validate_receipt_binding(self) -> "VisibilityMutationReceipt":
        if (
            self.table_id != self.event.table_id
            or self.command_id != self.event.command_id
            or self.revision != self.event.revision
        ):
            raise ValueError("visibility receipt does not match its event")
        return self


def barrier_blocks_sight(
    barrier: SightBarrier,
    observer: VisibilityPoint,
    target: VisibilityPoint,
) -> bool:
    """Return conservative deterministic sight blocking for one barrier segment."""

    if not isinstance(barrier, SightBarrier):
        raise TypeError("barrier must be a SightBarrier")
    if not isinstance(observer, VisibilityPoint) or not isinstance(target, VisibilityPoint):
        raise TypeError("observer and target must be VisibilityPoint values")
    if not barrier.blocks_sight or (barrier.behavior == "door" and barrier.portal_state == "open"):
        return False
    # Observer/target endpoints do not block their own ray. Every other touch is
    # conservatively opaque, preventing precision cracks at joined barriers.
    if barrier.start in {observer, target} or barrier.end in {observer, target}:
        return False
    return _segments_intersect(observer, target, barrier.start, barrier.end)


def barrier_blocks_movement(
    barrier: SightBarrier,
    start: VisibilityPoint,
    end: VisibilityPoint,
) -> bool:
    """Return whether one authored barrier blocks a planar movement segment."""

    if not isinstance(barrier, SightBarrier):
        raise TypeError("barrier must be a SightBarrier")
    if not isinstance(start, VisibilityPoint) or not isinstance(end, VisibilityPoint):
        raise TypeError("start and end must be VisibilityPoint values")
    if not barrier.blocks_movement or (
        barrier.behavior == "door" and barrier.portal_state == "open"
    ):
        return False
    return _segments_intersect(start, end, barrier.start, barrier.end)


def _polygon_contains_point(
    polygon: Sequence[VisibilityPoint],
    point: VisibilityPoint,
) -> bool:
    for index, start in enumerate(polygon):
        if _point_on_segment(point, start, polygon[(index + 1) % len(polygon)]):
            return True
    inside = False
    previous = polygon[-1]
    for current in polygon:
        crosses = (current.y_ft > point.y_ft) != (previous.y_ft > point.y_ft)
        if crosses:
            x_intersection = (previous.x_ft - current.x_ft) * (point.y_ft - current.y_ft) / (
                previous.y_ft - current.y_ft
            ) + current.x_ft
            if point.x_ft < x_intersection:
                inside = not inside
        previous = current
    return inside


def fog_reveals_point(
    operations: Sequence[FogOperation],
    point: VisibilityPoint,
) -> bool:
    """Fold ordered immutable fog operations; fog is hidden before the first reveal."""

    if not isinstance(operations, (list, tuple)):
        raise TypeError("operations must be an ordered sequence")
    if not isinstance(point, VisibilityPoint):
        raise TypeError("point must be a VisibilityPoint")
    expected_index = 1
    revealed = False
    scene_id: str | None = None
    for operation in operations:
        if not isinstance(operation, FogOperation):
            raise TypeError("operations must contain FogOperation values")
        if operation.operation_index != expected_index:
            raise ValueError("fog operation indexes must be contiguous from one")
        expected_index += 1
        if scene_id is None:
            scene_id = operation.scene_id
        elif operation.scene_id != scene_id:
            raise ValueError("fog operations must belong to one scene")
        if _polygon_contains_point(operation.polygon, point):
            revealed = operation.operation == "reveal"
    return revealed


__all__ = [
    "FOG_OPERATION_SCHEMA_VERSION",
    "LIGHT_EMITTER_SCHEMA_VERSION",
    "MAX_FOG_POLYGON_VERTICES",
    "MAX_VISIBILITY_COORDINATE_FT",
    "MAX_VISION_RANGE_FT",
    "SCENE_ENVIRONMENT_SCHEMA_VERSION",
    "SIGHT_BARRIER_SCHEMA_VERSION",
    "TOKEN_VISION_SCHEMA_VERSION",
    "VISIBILITY_CATALOG_VIEW_SCHEMA_VERSION",
    "VISIBILITY_COMMAND_SCHEMA_VERSION",
    "VISIBILITY_EVENT_SCHEMA_VERSION",
    "VISIBILITY_RECEIPT_SCHEMA_VERSION",
    "FogOperation",
    "LightEmitter",
    "SceneEnvironment",
    "SightBarrier",
    "TokenVision",
    "VisibilityPoint",
    "VisibilityRecord",
    "VisibilityCatalogView",
    "VisibilityChangedEvent",
    "VisibilityCommand",
    "VisibilityDeleteCommand",
    "VisibilityDoorStateCommand",
    "VisibilityFogUndoCommand",
    "VisibilityMutationReceipt",
    "VisibilityPutCommand",
    "barrier_blocks_sight",
    "barrier_blocks_movement",
    "fog_reveals_point",
]
