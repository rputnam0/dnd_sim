"""Deterministic audience-safe raster projection for VTT visibility state."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .active_board import ActiveBoardProjection
from .participants import TableParticipant, TableRoster, audience_allows
from .token_contracts import TokenRecord, TokenView, project_token_view
from .visibility_contracts import (
    FogOperation,
    LightEmitter,
    SceneEnvironment,
    SightBarrier,
    TokenVision,
    VisibilityCatalogView,
    VisibilityPoint,
    barrier_blocks_sight,
    fog_reveals_point,
)

VISIBILITY_PROJECTION_SCHEMA_VERSION = "vtt.visibility_projection.v1"
VISIBILITY_MASK_RUN_SCHEMA_VERSION = "vtt.visibility_mask_run.v1"
MAX_VISIBILITY_MASK_SAMPLES = 65_536
# One unit is one sample/record-or-polygon-vertex relationship. This cap is
# checked before raster sampling so authored maxima cannot multiply into
# unbounded request work.
MAX_VISIBILITY_PROJECTION_WORK = 8_000_000

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]


class VisibilityProjectionError(RuntimeError):
    """Raised when authoritative source state cannot safely produce a projection."""


class _StrictProjectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class VisibilityMaskRun(_StrictProjectionModel):
    schema_version: Literal[VISIBILITY_MASK_RUN_SCHEMA_VERSION] = VISIBILITY_MASK_RUN_SCHEMA_VERSION
    start: NonNegativeInt
    length: PositiveInt


class VisibilityProjection(_StrictProjectionModel):
    """Player-safe result containing no authored visibility records."""

    schema_version: Literal[VISIBILITY_PROJECTION_SCHEMA_VERSION] = (
        VISIBILITY_PROJECTION_SCHEMA_VERSION
    )
    table_id: str
    scene_id: str
    scene_revision: NonNegativeInt
    token_revision: NonNegativeInt
    visibility_revision: NonNegativeInt
    encounter_revision: NonNegativeInt
    mask_width: PositiveInt
    mask_height: PositiveInt
    visible_runs: tuple[VisibilityMaskRun, ...]
    tokens: tuple[TokenRecord, ...]

    @model_validator(mode="after")
    def validate_mask_and_token_order(self) -> "VisibilityProjection":
        sample_count = self.mask_width * self.mask_height
        if sample_count > MAX_VISIBILITY_MASK_SAMPLES:
            raise ValueError("visibility mask exceeds the supported sample count")
        previous_end = 0
        for index, run in enumerate(self.visible_runs):
            if run.start + run.length > sample_count:
                raise ValueError("visibility mask run leaves the mask bounds")
            if index > 0 and run.start <= previous_end:
                raise ValueError("visibility mask runs must be sorted and separated")
            previous_end = run.start + run.length
        token_ids = tuple(token.token_id for token in self.tokens)
        if token_ids != tuple(sorted(set(token_ids))):
            raise ValueError("visible tokens must have unique sorted identities")
        if any(token.scene_id != self.scene_id for token in self.tokens):
            raise ValueError("visible tokens must belong to the projected scene")
        return self


@dataclass(frozen=True, slots=True)
class _Observer:
    origin: VisibilityPoint
    normal_range_ft: float
    darkvision_range_ft: float


@dataclass(frozen=True, slots=True)
class _TokenLight:
    origin: VisibilityPoint
    bright_radius_ft: float
    dim_radius_ft: float


@dataclass(frozen=True, slots=True)
class _BarrierEntry:
    barrier: SightBarrier
    minimum_x: float
    minimum_y: float
    maximum_x: float
    maximum_y: float


@dataclass(frozen=True, slots=True)
class _BarrierNode:
    minimum_x: float
    minimum_y: float
    maximum_x: float
    maximum_y: float
    left: _BarrierNode | None
    right: _BarrierNode | None
    entries: tuple[_BarrierEntry, ...]


class _BarrierIndex:
    """Immutable BVH that prunes barriers outside each sight segment."""

    _LEAF_SIZE = 8

    def __init__(self, barriers: tuple[SightBarrier, ...]) -> None:
        entries = tuple(
            _BarrierEntry(
                barrier=barrier,
                minimum_x=min(barrier.start.x_ft, barrier.end.x_ft),
                minimum_y=min(barrier.start.y_ft, barrier.end.y_ft),
                maximum_x=max(barrier.start.x_ft, barrier.end.x_ft),
                maximum_y=max(barrier.start.y_ft, barrier.end.y_ft),
            )
            for barrier in barriers
            if barrier.blocks_sight
            and not (barrier.behavior == "door" and barrier.portal_state == "open")
        )
        self._root = self._build(entries)

    @classmethod
    def _build(cls, entries: tuple[_BarrierEntry, ...]) -> _BarrierNode | None:
        if not entries:
            return None
        minimum_x = min(entry.minimum_x for entry in entries)
        minimum_y = min(entry.minimum_y for entry in entries)
        maximum_x = max(entry.maximum_x for entry in entries)
        maximum_y = max(entry.maximum_y for entry in entries)
        if len(entries) <= cls._LEAF_SIZE:
            return _BarrierNode(
                minimum_x=minimum_x,
                minimum_y=minimum_y,
                maximum_x=maximum_x,
                maximum_y=maximum_y,
                left=None,
                right=None,
                entries=entries,
            )
        split_on_x = maximum_x - minimum_x >= maximum_y - minimum_y
        ordered = tuple(
            sorted(
                entries,
                key=lambda entry: (
                    (
                        (entry.minimum_x + entry.maximum_x)
                        if split_on_x
                        else (entry.minimum_y + entry.maximum_y)
                    ),
                    entry.barrier.record_id,
                ),
            )
        )
        middle = len(ordered) // 2
        return _BarrierNode(
            minimum_x=minimum_x,
            minimum_y=minimum_y,
            maximum_x=maximum_x,
            maximum_y=maximum_y,
            left=cls._build(ordered[:middle]),
            right=cls._build(ordered[middle:]),
            entries=(),
        )

    @staticmethod
    def _segment_intersects_bounds(
        start: VisibilityPoint,
        end: VisibilityPoint,
        node: _BarrierNode,
    ) -> bool:
        """Use Liang-Barsky clipping to reject whole BVH branches exactly."""

        delta_x = end.x_ft - start.x_ft
        delta_y = end.y_ft - start.y_ft
        minimum_t = 0.0
        maximum_t = 1.0
        for direction, distance in (
            (-delta_x, start.x_ft - node.minimum_x),
            (delta_x, node.maximum_x - start.x_ft),
            (-delta_y, start.y_ft - node.minimum_y),
            (delta_y, node.maximum_y - start.y_ft),
        ):
            if math.isclose(direction, 0.0, rel_tol=0.0, abs_tol=1e-12):
                if distance < -1e-9:
                    return False
                continue
            ratio = distance / direction
            if direction < 0.0:
                minimum_t = max(minimum_t, ratio)
            else:
                maximum_t = min(maximum_t, ratio)
            if minimum_t - maximum_t > 1e-9:
                return False
        return True

    def blocks(self, observer: VisibilityPoint, target: VisibilityPoint) -> bool:
        root = self._root
        if root is None:
            return False
        pending = [root]
        while pending:
            node = pending.pop()
            if not self._segment_intersects_bounds(observer, target, node):
                continue
            if node.entries:
                if any(
                    barrier_blocks_sight(entry.barrier, observer, target) for entry in node.entries
                ):
                    return True
                continue
            if node.right is not None:
                pending.append(node.right)
            if node.left is not None:
                pending.append(node.left)
        return False


def _estimated_projection_work(
    *,
    sample_count: int,
    fog: tuple[FogOperation, ...],
    lights: tuple[LightEmitter, ...],
    token_lights: tuple[_TokenLight, ...],
    observers: tuple[_Observer, ...],
) -> int:
    per_sample_work = (
        sum(len(operation.polygon) for operation in fog)
        + len(lights)
        + len(token_lights)
        + len(observers)
    )
    return sample_count * per_sample_work


def _mask_dimensions(width_px: int, height_px: int, max_samples: int) -> tuple[int, int]:
    if type(max_samples) is not int or not 1 <= max_samples <= MAX_VISIBILITY_MASK_SAMPLES:
        raise ValueError("max_samples must be a positive bounded integer")
    if width_px * height_px <= max_samples:
        return width_px, height_px
    scale = math.sqrt(max_samples / float(width_px * height_px))
    width = max(1, math.floor(width_px * scale))
    height = max(1, math.floor(height_px * scale))
    while width * height > max_samples:
        if width / width_px >= height / height_px and width > 1:
            width -= 1
        elif height > 1:
            height -= 1
        else:  # pragma: no cover - max_samples >= 1 makes this unreachable
            break
    return width, height


def _pixel_to_feet(
    active_board: ActiveBoardProjection,
    *,
    x_px: float,
    y_px: float,
) -> VisibilityPoint:
    calibration = active_board.map_metadata.calibration
    half_step = calibration.distance_ft / 2.0
    origin_x_ft = active_board.scene.origin_ft.x_ft + half_step
    origin_y_ft = active_board.scene.origin_ft.y_ft + half_step
    return VisibilityPoint(
        x_ft=origin_x_ft
        + (x_px - calibration.origin_x_px) / calibration.cell_extent_px * calibration.distance_ft,
        y_ft=origin_y_ft
        + (y_px - calibration.origin_y_px) / calibration.cell_extent_px * calibration.distance_ft,
    )


def _distance(start: VisibilityPoint, end: VisibilityPoint) -> float:
    return math.hypot(end.x_ft - start.x_ft, end.y_ft - start.y_ft)


def _inside_light(light: LightEmitter, point: VisibilityPoint) -> int:
    distance = _distance(light.origin, point)
    if distance > light.dim_radius_ft:
        return 0
    if light.shape == "cone" and distance > 1e-9:
        direction = (
            math.degrees(math.atan2(point.y_ft - light.origin.y_ft, point.x_ft - light.origin.x_ft))
            % 360.0
        )
        delta = abs((direction - light.direction_degrees + 180.0) % 360.0 - 180.0)
        if delta > light.angle_degrees / 2.0 + 1e-9:
            return 0
    return 2 if distance <= light.bright_radius_ft else 1


def _illumination(
    point: VisibilityPoint,
    *,
    environment: SceneEnvironment,
    lights: tuple[LightEmitter, ...],
    token_lights: tuple[_TokenLight, ...],
) -> int:
    level = {"darkness": 0, "dim": 1, "bright": 2}[environment.darkness]
    for light in lights:
        level = max(level, _inside_light(light, point))
        if level == 2:
            return level
    for light in token_lights:
        distance = _distance(light.origin, point)
        if distance <= light.bright_radius_ft:
            return 2
        if distance <= light.dim_radius_ft:
            level = max(level, 1)
    return level


def _has_line_of_sight(
    observer: VisibilityPoint,
    point: VisibilityPoint,
    barriers: _BarrierIndex,
) -> bool:
    return not barriers.blocks(observer, point)


def _point_is_visible(
    point: VisibilityPoint,
    *,
    observers: tuple[_Observer, ...],
    barriers: _BarrierIndex,
    fog: tuple[FogOperation, ...],
    environment: SceneEnvironment,
    lights: tuple[LightEmitter, ...],
    token_lights: tuple[_TokenLight, ...],
) -> bool:
    if not fog_reveals_point(fog, point):
        return False
    illumination = _illumination(
        point,
        environment=environment,
        lights=lights,
        token_lights=token_lights,
    )
    for observer in observers:
        distance = _distance(observer.origin, point)
        has_range = (
            illumination > 0
            and observer.normal_range_ft > 0.0
            and distance <= observer.normal_range_ft + 1e-9
        ) or (
            observer.darkvision_range_ft > 0.0 and distance <= observer.darkvision_range_ft + 1e-9
        )
        if has_range and _has_line_of_sight(observer.origin, point, barriers):
            return True
    return False


def _permitted_observer_actor_ids(
    participant: TableParticipant,
    roster: TableRoster,
    environment: SceneEnvironment,
) -> frozenset[str]:
    if participant.role != "player":
        return frozenset()
    if environment.shared_vision == "owned_only":
        return frozenset(participant.owned_actor_ids)
    return frozenset(
        actor_id
        for member in roster.participants
        if member.role == "player"
        for actor_id in member.owned_actor_ids
    )


def _build_observers(
    *,
    participant: TableParticipant,
    roster: TableRoster,
    environment: SceneEnvironment,
    tokens: TokenView,
    visions: tuple[TokenVision, ...],
) -> tuple[_Observer, ...]:
    permitted_actor_ids = _permitted_observer_actor_ids(participant, roster, environment)
    token_by_id = {token.token_id: token for token in tokens.tokens}
    observers = []
    for vision in sorted(visions, key=lambda item: item.token_id):
        token = token_by_id.get(vision.token_id)
        if (
            not vision.enabled
            or token is None
            or token.actor_id not in permitted_actor_ids
            or token.visibility == "gm_only"
        ):
            continue
        observers.append(
            _Observer(
                origin=VisibilityPoint(
                    x_ft=token.pose.position_ft.x_ft,
                    y_ft=token.pose.position_ft.y_ft,
                ),
                normal_range_ft=vision.normal_range_ft,
                darkvision_range_ft=vision.darkvision_range_ft,
            )
        )
    return tuple(observers)


def _build_token_lights(
    tokens: TokenView,
    visions: tuple[TokenVision, ...],
) -> tuple[_TokenLight, ...]:
    token_by_id = {token.token_id: token for token in tokens.tokens}
    emitted = []
    for vision in visions:
        token = token_by_id.get(vision.token_id)
        if not vision.enabled or token is None or vision.emitted_dim_radius_ft <= 0.0:
            continue
        emitted.append(
            _TokenLight(
                origin=VisibilityPoint(
                    x_ft=token.pose.position_ft.x_ft,
                    y_ft=token.pose.position_ft.y_ft,
                ),
                bright_radius_ft=vision.emitted_bright_radius_ft,
                dim_radius_ft=vision.emitted_dim_radius_ft,
            )
        )
    return tuple(emitted)


def _runs(visible: list[bool]) -> tuple[VisibilityMaskRun, ...]:
    runs = []
    start: int | None = None
    for index, is_visible in enumerate((*visible, False)):
        if is_visible and start is None:
            start = index
        elif not is_visible and start is not None:
            runs.append(VisibilityMaskRun(start=start, length=index - start))
            start = None
    return tuple(runs)


def project_visibility(
    *,
    active_board: ActiveBoardProjection,
    catalog: VisibilityCatalogView,
    tokens: TokenView,
    participant: TableParticipant,
    roster: TableRoster,
    encounter_revision: int,
    max_samples: int = MAX_VISIBILITY_MASK_SAMPLES,
) -> VisibilityProjection:
    """Project one authenticated audience without serializing authored secrets."""

    if not isinstance(active_board, ActiveBoardProjection):
        raise TypeError("active_board must be an ActiveBoardProjection")
    if not isinstance(catalog, VisibilityCatalogView):
        raise TypeError("catalog must be a VisibilityCatalogView")
    if not isinstance(tokens, TokenView):
        raise TypeError("tokens must be a TokenView")
    if not isinstance(participant, TableParticipant):
        raise TypeError("participant must be a TableParticipant")
    if not isinstance(roster, TableRoster):
        raise TypeError("roster must be a TableRoster")
    if type(encounter_revision) is not int or encounter_revision < 0:
        raise ValueError("encounter_revision must be a non-negative integer")
    if (
        catalog.table_id != roster.table_id
        or tokens.table_id != roster.table_id
        or catalog.scene_id != active_board.scene.scene_id
        or tokens.scene_id != active_board.scene.scene_id
        or roster.participant(participant.participant_id) != participant
    ):
        raise VisibilityProjectionError("visibility projection sources are inconsistent")

    environments = tuple(
        record for record in catalog.records if isinstance(record, SceneEnvironment)
    )
    if len(environments) != 1:
        raise VisibilityProjectionError("visibility projection requires one scene environment")
    environment = environments[0]
    barriers = _BarrierIndex(
        tuple(record for record in catalog.records if isinstance(record, SightBarrier))
    )
    fog = tuple(
        sorted(
            (record for record in catalog.records if isinstance(record, FogOperation)),
            key=lambda record: record.operation_index,
        )
    )
    visions = tuple(record for record in catalog.records if isinstance(record, TokenVision))
    applicable_lights = tuple(
        record
        for record in catalog.records
        if isinstance(record, LightEmitter) and audience_allows(record.audience, participant)
    )
    observers = _build_observers(
        participant=participant,
        roster=roster,
        environment=environment,
        tokens=tokens,
        visions=visions,
    )
    token_lights = _build_token_lights(tokens, visions)

    width, height = _mask_dimensions(
        active_board.map_metadata.width_px,
        active_board.map_metadata.height_px,
        max_samples,
    )
    if (
        _estimated_projection_work(
            sample_count=width * height,
            fog=fog,
            lights=applicable_lights,
            token_lights=token_lights,
            observers=observers,
        )
        > MAX_VISIBILITY_PROJECTION_WORK
    ):
        raise VisibilityProjectionError(
            "visibility projection exceeds the deterministic combined work budget"
        )
    visible_samples = []
    for row in range(height):
        for column in range(width):
            point = _pixel_to_feet(
                active_board,
                x_px=(column + 0.5) * active_board.map_metadata.width_px / width,
                y_px=(row + 0.5) * active_board.map_metadata.height_px / height,
            )
            visible_samples.append(
                _point_is_visible(
                    point,
                    observers=observers,
                    barriers=barriers,
                    fog=fog,
                    environment=environment,
                    lights=applicable_lights,
                    token_lights=token_lights,
                )
            )

    audience_tokens = project_token_view(tokens, participant)
    visible_tokens = tuple(
        token
        for token in audience_tokens.tokens
        if _point_is_visible(
            VisibilityPoint(
                x_ft=token.pose.position_ft.x_ft,
                y_ft=token.pose.position_ft.y_ft,
            ),
            observers=observers,
            barriers=barriers,
            fog=fog,
            environment=environment,
            lights=applicable_lights,
            token_lights=token_lights,
        )
    )
    return VisibilityProjection(
        table_id=roster.table_id,
        scene_id=active_board.scene.scene_id,
        scene_revision=active_board.scene_revision,
        token_revision=tokens.revision,
        visibility_revision=catalog.revision,
        encounter_revision=encounter_revision,
        mask_width=width,
        mask_height=height,
        visible_runs=_runs(visible_samples),
        tokens=visible_tokens,
    )


__all__ = [
    "MAX_VISIBILITY_MASK_SAMPLES",
    "MAX_VISIBILITY_PROJECTION_WORK",
    "VISIBILITY_MASK_RUN_SCHEMA_VERSION",
    "VISIBILITY_PROJECTION_SCHEMA_VERSION",
    "VisibilityMaskRun",
    "VisibilityProjection",
    "VisibilityProjectionError",
    "project_visibility",
]
