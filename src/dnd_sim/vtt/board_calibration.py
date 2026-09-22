"""Explicit, bounded square and hex map calibration in pixels and engine feet."""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .scene import FeetPosition

BOARD_CALIBRATION_SCHEMA_VERSION = "vtt.board_calibration.v1"
MAX_CALIBRATION_EXTENT_PX = 100_000.0
MAX_CALIBRATION_DISTANCE_FT = 100_000.0
MAX_CELL_COORDINATE = 1_000_000

FiniteFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]
PositiveExtent = Annotated[
    float,
    Field(
        strict=True,
        gt=0.0,
        le=MAX_CALIBRATION_EXTENT_PX,
        allow_inf_nan=False,
    ),
]
PositiveDistance = Annotated[
    float,
    Field(
        strict=True,
        gt=0.0,
        le=MAX_CALIBRATION_DISTANCE_FT,
        allow_inf_nan=False,
    ),
]
CellCoordinate = Annotated[
    int,
    Field(strict=True, ge=-MAX_CELL_COORDINATE, le=MAX_CELL_COORDINATE),
]


class _StrictCalibrationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ViewPoint(_StrictCalibrationModel):
    x_px: FiniteFloat
    y_px: FiniteFloat


class SquareBoardCell(_StrictCalibrationModel):
    column: CellCoordinate
    row: CellCoordinate


class AxialHexCell(_StrictCalibrationModel):
    q: CellCoordinate
    r: CellCoordinate


BoardCell: TypeAlias = SquareBoardCell | AxialHexCell

_HEX_NEIGHBOR_DELTAS = (
    (1, 0),
    (1, -1),
    (0, -1),
    (-1, 0),
    (-1, 1),
    (0, 1),
)


def _round_half_away_from_zero(value: float) -> int:
    return math.floor(value + 0.5) if value >= 0.0 else math.ceil(value - 0.5)


def _round_axial(q_fraction: float, r_fraction: float) -> AxialHexCell:
    s_fraction = -q_fraction - r_fraction
    q = _round_half_away_from_zero(q_fraction)
    r = _round_half_away_from_zero(r_fraction)
    s = _round_half_away_from_zero(s_fraction)
    q_error = abs(q - q_fraction)
    r_error = abs(r - r_fraction)
    s_error = abs(s - s_fraction)
    if q_error >= r_error and q_error >= s_error:
        q = -r - s
    elif r_error >= s_error:
        r = -q - s
    return AxialHexCell(q=q, r=r)


class BoardCalibration(_StrictCalibrationModel):
    """One invertible map-to-engine calibration independent of renderer styling."""

    schema_version: Literal[BOARD_CALIBRATION_SCHEMA_VERSION] = BOARD_CALIBRATION_SCHEMA_VERSION
    topology: Literal["gridless", "square", "hex_flat", "hex_pointy"]
    origin_x_px: FiniteFloat
    origin_y_px: FiniteFloat
    cell_extent_px: PositiveExtent
    distance_ft: PositiveDistance

    @field_validator("topology")
    @classmethod
    def validate_topology(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("topology must be a string")
        return value

    def _require_cell(self, cell: BoardCell) -> None:
        if self.topology == "gridless":
            raise ValueError("gridless calibration does not expose cells")
        if self.topology == "square" and not isinstance(cell, SquareBoardCell):
            raise TypeError("square calibration requires a SquareBoardCell")
        if self.topology.startswith("hex_") and not isinstance(cell, AxialHexCell):
            raise TypeError("hex calibration requires an AxialHexCell")

    def cell_to_pixel(self, cell: BoardCell) -> ViewPoint:
        self._require_cell(cell)
        if isinstance(cell, SquareBoardCell):
            return ViewPoint(
                x_px=self.origin_x_px + cell.column * self.cell_extent_px,
                y_px=self.origin_y_px + cell.row * self.cell_extent_px,
            )
        if self.topology == "hex_pointy":
            return ViewPoint(
                x_px=self.origin_x_px + self.cell_extent_px * (cell.q + cell.r / 2.0),
                y_px=self.origin_y_px + self.cell_extent_px * math.sqrt(3.0) / 2.0 * cell.r,
            )
        return ViewPoint(
            x_px=self.origin_x_px + self.cell_extent_px * math.sqrt(3.0) / 2.0 * cell.q,
            y_px=self.origin_y_px + self.cell_extent_px * (cell.r + cell.q / 2.0),
        )

    def pixel_to_cell(self, point: ViewPoint) -> BoardCell:
        if not isinstance(point, ViewPoint):
            raise TypeError("point must be a ViewPoint")
        if self.topology == "gridless":
            raise ValueError("gridless calibration does not expose cells")
        x = (point.x_px - self.origin_x_px) / self.cell_extent_px
        y = (point.y_px - self.origin_y_px) / self.cell_extent_px
        if self.topology == "square":
            return SquareBoardCell(
                column=math.floor(x + 0.5),
                row=math.floor(y + 0.5),
            )
        if self.topology == "hex_pointy":
            r_fraction = 2.0 / math.sqrt(3.0) * y
            q_fraction = x - r_fraction / 2.0
        else:
            q_fraction = 2.0 / math.sqrt(3.0) * x
            r_fraction = y - q_fraction / 2.0
        return _round_axial(q_fraction, r_fraction)

    def cell_to_feet(
        self,
        cell: BoardCell,
        *,
        origin_ft: FeetPosition,
    ) -> FeetPosition:
        if not isinstance(origin_ft, FeetPosition):
            raise TypeError("origin_ft must be a FeetPosition")
        pixel = self.cell_to_pixel(cell)
        return FeetPosition(
            x_ft=origin_ft.x_ft
            + (pixel.x_px - self.origin_x_px) / self.cell_extent_px * self.distance_ft,
            y_ft=origin_ft.y_ft
            + (pixel.y_px - self.origin_y_px) / self.cell_extent_px * self.distance_ft,
            z_ft=origin_ft.z_ft,
        )

    def feet_to_cell(
        self,
        position: FeetPosition,
        *,
        origin_ft: FeetPosition,
    ) -> BoardCell:
        if not isinstance(position, FeetPosition) or not isinstance(origin_ft, FeetPosition):
            raise TypeError("position and origin_ft must be FeetPosition values")
        point = ViewPoint(
            x_px=self.origin_x_px
            + (position.x_ft - origin_ft.x_ft) / self.distance_ft * self.cell_extent_px,
            y_px=self.origin_y_px
            + (position.y_ft - origin_ft.y_ft) / self.distance_ft * self.cell_extent_px,
        )
        return self.pixel_to_cell(point)

    def neighbors(self, cell: AxialHexCell) -> tuple[AxialHexCell, ...]:
        if self.topology not in {"hex_flat", "hex_pointy"}:
            raise ValueError("neighbors require a hex calibration")
        if not isinstance(cell, AxialHexCell):
            raise TypeError("cell must be an AxialHexCell")
        return tuple(
            AxialHexCell(q=cell.q + delta_q, r=cell.r + delta_r)
            for delta_q, delta_r in _HEX_NEIGHBOR_DELTAS
        )

    def cell_distance_ft(self, start: BoardCell, end: BoardCell) -> float:
        self._require_cell(start)
        self._require_cell(end)
        if isinstance(start, SquareBoardCell) and isinstance(end, SquareBoardCell):
            steps = max(abs(end.column - start.column), abs(end.row - start.row))
        elif isinstance(start, AxialHexCell) and isinstance(end, AxialHexCell):
            delta_q = end.q - start.q
            delta_r = end.r - start.r
            steps = max(abs(delta_q), abs(delta_r), abs(delta_q + delta_r))
        else:  # pragma: no cover - topology checks above reject mixed cell types
            raise TypeError("cell types must match the calibration topology")
        return float(steps) * self.distance_ft

    def pixel_distance_ft(self, start: ViewPoint, end: ViewPoint) -> float:
        if not isinstance(start, ViewPoint) or not isinstance(end, ViewPoint):
            raise TypeError("start and end must be ViewPoint values")
        return (
            math.hypot(end.x_px - start.x_px, end.y_px - start.y_px)
            / self.cell_extent_px
            * self.distance_ft
        )

    def cell_is_complete(self, cell: BoardCell, *, width_px: int, height_px: int) -> bool:
        """Return whether the cell's full rendered footprint lies inside the map."""

        self._require_cell(cell)
        center = self.cell_to_pixel(cell)
        if self.topology == "square":
            half_width = half_height = self.cell_extent_px / 2.0
        elif self.topology == "hex_pointy":
            half_width = self.cell_extent_px / 2.0
            half_height = self.cell_extent_px / math.sqrt(3.0)
        else:
            half_width = self.cell_extent_px / math.sqrt(3.0)
            half_height = self.cell_extent_px / 2.0
        return (
            center.x_px - half_width >= 0.0
            and center.y_px - half_height >= 0.0
            and center.x_px + half_width <= float(width_px)
            and center.y_px + half_height <= float(height_px)
        )

    def require_usable_map(self, *, width_px: int, height_px: int) -> Self:
        if type(width_px) is not int or type(height_px) is not int:
            raise TypeError("map dimensions must be integers")
        if width_px < 1 or height_px < 1:
            raise ValueError("map dimensions must be positive")
        if (
            not all(
                math.isfinite(value)
                for value in (
                    self.origin_x_px,
                    self.origin_y_px,
                    self.cell_extent_px,
                    self.distance_ft,
                )
            )
            or self.cell_extent_px <= 0.0
        ):
            raise ValueError("calibration must contain finite positive extents")
        if self.topology == "gridless":
            if not (0.0 <= self.origin_x_px < width_px and 0.0 <= self.origin_y_px < height_px):
                raise ValueError("gridless calibration origin must lie inside the map")
            return self

        candidate = self.pixel_to_cell(ViewPoint(x_px=width_px / 2.0, y_px=height_px / 2.0))
        candidates: list[BoardCell] = [candidate]
        if isinstance(candidate, SquareBoardCell):
            candidates.extend(
                SquareBoardCell(column=candidate.column + column, row=candidate.row + row)
                for column in range(-2, 3)
                for row in range(-2, 3)
            )
        else:
            candidates.extend(self.neighbors(candidate))
            candidates.extend(
                neighbor
                for adjacent in self.neighbors(candidate)
                for neighbor in self.neighbors(adjacent)
            )
        if not any(
            self.cell_is_complete(cell, width_px=width_px, height_px=height_px)
            for cell in candidates
        ):
            raise ValueError("calibration does not provide a complete usable cell")
        return self


__all__ = [
    "BOARD_CALIBRATION_SCHEMA_VERSION",
    "MAX_CALIBRATION_DISTANCE_FT",
    "MAX_CALIBRATION_EXTENT_PX",
    "AxialHexCell",
    "BoardCalibration",
    "BoardCell",
    "SquareBoardCell",
    "ViewPoint",
]
