"""Renderer-neutral tabletop annotation contracts expressed only in feet."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

ANNOTATION_SCHEMA_VERSION = "vtt.annotation.v1"

MAX_ABSOLUTE_COORDINATE_FT = 1_000_000.0
MAX_TEMPLATE_SIZE_FT = 100_000.0
MAX_RULER_WAYPOINTS = 128
MAX_PING_DURATION_MS = 60_000


def _require_float(value: Any) -> float:
    if type(value) is not float:
        raise ValueError("value must be a floating-point number")
    return value


CoordinateFeet = Annotated[
    float,
    BeforeValidator(_require_float),
    Field(
        strict=True,
        ge=-MAX_ABSOLUTE_COORDINATE_FT,
        le=MAX_ABSOLUTE_COORDINATE_FT,
        allow_inf_nan=False,
    ),
]
TemplateDistanceFeet = Annotated[
    float,
    BeforeValidator(_require_float),
    Field(strict=True, gt=0.0, le=MAX_TEMPLATE_SIZE_FT, allow_inf_nan=False),
]
SegmentDistanceFeet = Annotated[
    float,
    BeforeValidator(_require_float),
    Field(
        strict=True,
        ge=0.0,
        le=MAX_ABSOLUTE_COORDINATE_FT * 2.0,
        allow_inf_nan=False,
    ),
]
TotalDistanceFeet = Annotated[
    float,
    BeforeValidator(_require_float),
    Field(
        strict=True,
        ge=0.0,
        le=MAX_ABSOLUTE_COORDINATE_FT * 2.0 * (MAX_RULER_WAYPOINTS - 1),
        allow_inf_nan=False,
    ),
]
DirectionDegrees = Annotated[
    float,
    BeforeValidator(_require_float),
    Field(strict=True, ge=0.0, lt=360.0, allow_inf_nan=False),
]
ConeAngleDegrees = Annotated[
    float,
    BeforeValidator(_require_float),
    Field(strict=True, gt=0.0, le=180.0, allow_inf_nan=False),
]
PingDurationMilliseconds = Annotated[
    int,
    Field(strict=True, ge=250, le=MAX_PING_DURATION_MS),
]


class _StrictAnnotationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _canonical_text(value: str, *, field_name: str, maximum_length: int = 128) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if normalized != value:
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    if len(normalized) > maximum_length:
        raise ValueError(f"{field_name} must be at most {maximum_length} characters")
    return normalized


def _ordered_audience(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("audience must be an ordered list or tuple")
    recipients: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError("audience entries must be strings")
        recipient_id = _canonical_text(item, field_name="audience recipient ID")
        if recipient_id not in seen:
            recipients.append(recipient_id)
            seen.add(recipient_id)
    if not recipients:
        raise ValueError("audience must contain at least one recipient")
    if "all" in seen and recipients != ["all"]:
        raise ValueError("audience 'all' cannot be combined with explicit recipient IDs")
    return tuple(recipients)


class AnnotationPoint(_StrictAnnotationModel):
    """A world-space point whose units are explicitly feet."""

    x_ft: CoordinateFeet
    y_ft: CoordinateFeet
    z_ft: CoordinateFeet = 0.0


class _AnnotationBase(_StrictAnnotationModel):
    schema_version: Literal[ANNOTATION_SCHEMA_VERSION] = ANNOTATION_SCHEMA_VERSION
    annotation_id: str
    scene_id: str
    author_id: str
    audience: tuple[str, ...] = ("all",)

    @field_validator("annotation_id", "scene_id", "author_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @field_validator("audience", mode="before")
    @classmethod
    def validate_audience(cls, value: Any) -> tuple[str, ...]:
        return _ordered_audience(value)


def chebyshev_distance_ft(start: AnnotationPoint, end: AnnotationPoint) -> float:
    """Return 5e-style diagonal distance for one arbitrary feet-space segment."""

    if not isinstance(start, AnnotationPoint) or not isinstance(end, AnnotationPoint):
        raise TypeError("start and end must be AnnotationPoint instances")
    distance = max(
        abs(end.x_ft - start.x_ft),
        abs(end.y_ft - start.y_ft),
        abs(end.z_ft - start.z_ft),
    )
    return 0.0 if distance == 0.0 else distance


class RulerAnnotation(_AnnotationBase):
    """A polyline ruler using summed 5e Chebyshev distance per segment."""

    annotation_type: Literal["ruler"] = "ruler"
    waypoints: tuple[AnnotationPoint, ...]
    segment_distances_ft: tuple[SegmentDistanceFeet, ...] = ()
    total_distance_ft: TotalDistanceFeet = 0.0

    @field_validator("waypoints", "segment_distances_ft", mode="before")
    @classmethod
    def validate_ordered_tuple(cls, value: Any, info: Any) -> tuple[Any, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{info.field_name} must be an ordered list or tuple")
        return tuple(value)

    @model_validator(mode="after")
    def derive_distances(self) -> "RulerAnnotation":
        if len(self.waypoints) < 2:
            raise ValueError("a ruler requires at least two waypoints")
        if len(self.waypoints) > MAX_RULER_WAYPOINTS:
            raise ValueError(f"a ruler supports at most {MAX_RULER_WAYPOINTS} waypoints")
        if any(start == end for start, end in zip(self.waypoints, self.waypoints[1:])):
            raise ValueError("ruler consecutive waypoints must be distinct")

        expected_segments = tuple(
            chebyshev_distance_ft(start, end)
            for start, end in zip(self.waypoints, self.waypoints[1:])
        )
        expected_total = sum(expected_segments, start=0.0)
        supplied_fields = self.model_fields_set
        if (
            "segment_distances_ft" in supplied_fields
            and self.segment_distances_ft != expected_segments
        ):
            raise ValueError("segment_distances_ft must match the ruler waypoints")
        if "total_distance_ft" in supplied_fields and self.total_distance_ft != expected_total:
            raise ValueError("total_distance_ft must match the ruler segment distances")

        object.__setattr__(self, "segment_distances_ft", expected_segments)
        object.__setattr__(self, "total_distance_ft", expected_total)
        return self


class PingAnnotation(_AnnotationBase):
    """A transient location ping; lifecycle duration is expressed in milliseconds."""

    annotation_type: Literal["ping"] = "ping"
    position: AnnotationPoint
    duration_ms: PingDurationMilliseconds = 1_500


class CircleTemplateAnnotation(_AnnotationBase):
    """A circular area template on the center point's horizontal plane."""

    annotation_type: Literal["circle_template"] = "circle_template"
    center: AnnotationPoint
    radius_ft: TemplateDistanceFeet


class ConeTemplateAnnotation(_AnnotationBase):
    """A horizontal cone sector; zero degrees points along positive world X."""

    annotation_type: Literal["cone_template"] = "cone_template"
    origin: AnnotationPoint
    direction_degrees: DirectionDegrees
    length_ft: TemplateDistanceFeet
    angle_degrees: ConeAngleDegrees = 90.0


class LineTemplateAnnotation(_AnnotationBase):
    """A horizontal rectangular line template centered on start-to-end."""

    annotation_type: Literal["line_template"] = "line_template"
    start: AnnotationPoint
    end: AnnotationPoint
    width_ft: TemplateDistanceFeet

    @model_validator(mode="after")
    def validate_horizontal_segment(self) -> "LineTemplateAnnotation":
        if self.start.z_ft != self.end.z_ft:
            raise ValueError("line template start and end must share the same z_ft")
        if self.start.x_ft == self.end.x_ft and self.start.y_ft == self.end.y_ft:
            raise ValueError("line template requires distinct horizontal start and end points")
        return self


class CubeTemplateAnnotation(_AnnotationBase):
    """An axis-aligned cube centered on a world-space point."""

    annotation_type: Literal["cube_template"] = "cube_template"
    center: AnnotationPoint
    size_ft: TemplateDistanceFeet


VTTAnnotation: TypeAlias = Annotated[
    RulerAnnotation
    | PingAnnotation
    | CircleTemplateAnnotation
    | ConeTemplateAnnotation
    | LineTemplateAnnotation
    | CubeTemplateAnnotation,
    Field(discriminator="annotation_type"),
]

_ANNOTATION_ADAPTER = TypeAdapter(VTTAnnotation)
_ANNOTATION_TYPES = (
    RulerAnnotation,
    PingAnnotation,
    CircleTemplateAnnotation,
    ConeTemplateAnnotation,
    LineTemplateAnnotation,
    CubeTemplateAnnotation,
)


def parse_annotation(value: Any) -> VTTAnnotation:
    """Validate one Python/decoded-JSON value through the discriminated union."""

    return _ANNOTATION_ADAPTER.validate_python(value)


def parse_annotation_json(value: str | bytes | bytearray) -> VTTAnnotation:
    """Validate one encoded JSON annotation through the discriminated union."""

    return _ANNOTATION_ADAPTER.validate_json(value)


@dataclass(frozen=True, slots=True)
class AnnotationBounds:
    """Axis-aligned world-space annotation bounds, expressed only in feet."""

    min_x_ft: float
    max_x_ft: float
    min_y_ft: float
    max_y_ft: float
    min_z_ft: float
    max_z_ft: float


@dataclass(frozen=True, slots=True)
class _DerivedPoint:
    """Internal unbounded geometry produced from already validated control points."""

    x_ft: float
    y_ft: float
    z_ft: float


def _point_bounds(points: Sequence[AnnotationPoint | _DerivedPoint]) -> AnnotationBounds:
    if not points:
        raise ValueError("at least one point is required to compute annotation bounds")
    return AnnotationBounds(
        min_x_ft=min(point.x_ft for point in points),
        max_x_ft=max(point.x_ft for point in points),
        min_y_ft=min(point.y_ft for point in points),
        max_y_ft=max(point.y_ft for point in points),
        min_z_ft=min(point.z_ft for point in points),
        max_z_ft=max(point.z_ft for point in points),
    )


def _cone_boundary_points(annotation: ConeTemplateAnnotation) -> tuple[_DerivedPoint, ...]:
    half_angle = annotation.angle_degrees / 2.0
    candidate_angles = [
        annotation.direction_degrees - half_angle,
        annotation.direction_degrees + half_angle,
    ]
    for cardinal_angle in (0.0, 90.0, 180.0, 270.0):
        angular_difference = abs(
            (cardinal_angle - annotation.direction_degrees + 180.0) % 360.0 - 180.0
        )
        if angular_difference <= half_angle:
            candidate_angles.append(cardinal_angle)

    points = [
        _DerivedPoint(
            x_ft=annotation.origin.x_ft,
            y_ft=annotation.origin.y_ft,
            z_ft=annotation.origin.z_ft,
        )
    ]
    for angle in candidate_angles:
        radians = math.radians(angle)
        points.append(
            _DerivedPoint(
                x_ft=annotation.origin.x_ft + annotation.length_ft * math.cos(radians),
                y_ft=annotation.origin.y_ft + annotation.length_ft * math.sin(radians),
                z_ft=annotation.origin.z_ft,
            )
        )
    return tuple(points)


def _line_boundary_points(annotation: LineTemplateAnnotation) -> tuple[_DerivedPoint, ...]:
    delta_x = annotation.end.x_ft - annotation.start.x_ft
    delta_y = annotation.end.y_ft - annotation.start.y_ft
    planar_length = math.hypot(delta_x, delta_y)
    half_width = annotation.width_ft / 2.0
    offset_x = -delta_y / planar_length * half_width
    offset_y = delta_x / planar_length * half_width
    return tuple(
        _DerivedPoint(
            x_ft=point.x_ft + direction * offset_x,
            y_ft=point.y_ft + direction * offset_y,
            z_ft=point.z_ft,
        )
        for point in (annotation.start, annotation.end)
        for direction in (-1.0, 1.0)
    )


def annotation_bounds_ft(annotation: VTTAnnotation) -> AnnotationBounds:
    """Project deterministic feet-space bounds without introducing pixel authority."""

    if not isinstance(annotation, _ANNOTATION_TYPES):
        raise TypeError("annotation must be a supported VTT annotation model")
    if isinstance(annotation, RulerAnnotation):
        return _point_bounds(annotation.waypoints)
    if isinstance(annotation, PingAnnotation):
        return _point_bounds((annotation.position,))
    if isinstance(annotation, CircleTemplateAnnotation):
        return AnnotationBounds(
            min_x_ft=annotation.center.x_ft - annotation.radius_ft,
            max_x_ft=annotation.center.x_ft + annotation.radius_ft,
            min_y_ft=annotation.center.y_ft - annotation.radius_ft,
            max_y_ft=annotation.center.y_ft + annotation.radius_ft,
            min_z_ft=annotation.center.z_ft,
            max_z_ft=annotation.center.z_ft,
        )
    if isinstance(annotation, ConeTemplateAnnotation):
        return _point_bounds(_cone_boundary_points(annotation))
    if isinstance(annotation, LineTemplateAnnotation):
        return _point_bounds(_line_boundary_points(annotation))

    half_size = annotation.size_ft / 2.0
    return AnnotationBounds(
        min_x_ft=annotation.center.x_ft - half_size,
        max_x_ft=annotation.center.x_ft + half_size,
        min_y_ft=annotation.center.y_ft - half_size,
        max_y_ft=annotation.center.y_ft + half_size,
        min_z_ft=annotation.center.z_ft - half_size,
        max_z_ft=annotation.center.z_ft + half_size,
    )


def project_annotations(
    annotations: Sequence[VTTAnnotation],
    *,
    scene_id: str,
    recipient_id: str | None,
) -> tuple[VTTAnnotation, ...]:
    """Filter by scene/audience and sort by ID for a deterministic public projection."""

    if not isinstance(annotations, Sequence) or isinstance(annotations, (str, bytes, bytearray)):
        raise TypeError("annotations must be a sequence")
    selected_scene_id = _canonical_text(scene_id, field_name="scene_id")
    selected_recipient_id = (
        None if recipient_id is None else _canonical_text(recipient_id, field_name="recipient_id")
    )

    seen_ids: set[str] = set()
    projected: list[VTTAnnotation] = []
    for annotation in annotations:
        if not isinstance(annotation, _ANNOTATION_TYPES):
            raise TypeError("annotations must contain only supported VTT annotation models")
        if annotation.annotation_id in seen_ids:
            raise ValueError(f"duplicate annotation_id '{annotation.annotation_id}'")
        seen_ids.add(annotation.annotation_id)
        if annotation.scene_id != selected_scene_id:
            continue
        if annotation.audience != ("all",) and (
            selected_recipient_id is None or selected_recipient_id not in annotation.audience
        ):
            continue
        projected.append(annotation)

    return tuple(sorted(projected, key=lambda annotation: annotation.annotation_id))


__all__ = [
    "ANNOTATION_SCHEMA_VERSION",
    "MAX_ABSOLUTE_COORDINATE_FT",
    "MAX_PING_DURATION_MS",
    "MAX_RULER_WAYPOINTS",
    "MAX_TEMPLATE_SIZE_FT",
    "AnnotationBounds",
    "AnnotationPoint",
    "CircleTemplateAnnotation",
    "ConeTemplateAnnotation",
    "CubeTemplateAnnotation",
    "LineTemplateAnnotation",
    "PingAnnotation",
    "RulerAnnotation",
    "VTTAnnotation",
    "annotation_bounds_ft",
    "chebyshev_distance_ft",
    "parse_annotation",
    "parse_annotation_json",
    "project_annotations",
]
