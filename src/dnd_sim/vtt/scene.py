"""Renderer-neutral square-grid scene and token projection contracts.

Engine positions in this module are always expressed in feet. Pixel coordinates
exist only in :class:`GridPixelTransform`, keeping presentation scale and origin
out of authoritative scene and actor state.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dnd_sim.models import ActorRuntimeState

SCENE_SCHEMA_VERSION = "vtt.scene.v1"
SCENE_PROJECTION_SCHEMA_VERSION = "vtt.scene_projection.v1"

FiniteCoordinate = Annotated[float, Field(allow_inf_nan=False)]
PositiveFiniteFloat = Annotated[float, Field(gt=0.0, allow_inf_nan=False)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]


class _StrictSceneModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _canonical_text(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if normalized != value:
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    return value


class FeetPosition(_StrictSceneModel):
    """An authoritative engine-space position, explicitly measured in feet."""

    x_ft: FiniteCoordinate
    y_ft: FiniteCoordinate
    z_ft: FiniteCoordinate = 0.0


class GridCell(_StrictSceneModel):
    """A zero-based square-grid cell address."""

    column: NonNegativeInt
    row: NonNegativeInt


class PixelPoint(_StrictSceneModel):
    """A presentation-space point, explicitly measured in pixels."""

    x_px: FiniteCoordinate
    y_px: FiniteCoordinate


class SquareGridScene(_StrictSceneModel):
    """A bounded, versioned square-grid scene in canonical engine units."""

    schema_version: Literal["vtt.scene.v1"]
    scene_id: str
    name: str
    grid_type: Literal["square"] = "square"
    cell_size_ft: PositiveFiniteFloat
    columns: PositiveInt
    rows: PositiveInt
    origin_ft: FeetPosition = Field(
        default_factory=lambda: FeetPosition(x_ft=0.0, y_ft=0.0, z_ft=0.0)
    )

    @field_validator("scene_id", "name")
    @classmethod
    def validate_text(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    def _require_cell_in_bounds(self, cell: GridCell) -> None:
        if not isinstance(cell, GridCell):
            raise TypeError("cell must be a GridCell")
        if cell.column >= self.columns or cell.row >= self.rows:
            raise ValueError(
                f"grid cell ({cell.column}, {cell.row}) is outside scene bounds "
                f"({self.columns} columns, {self.rows} rows)"
            )

    def feet_to_grid_cell(self, position: FeetPosition) -> GridCell:
        """Map a feet position to its containing cell using half-open bounds."""

        if not isinstance(position, FeetPosition):
            raise TypeError("position must be a FeetPosition")
        column = math.floor((position.x_ft - self.origin_ft.x_ft) / self.cell_size_ft)
        row = math.floor((position.y_ft - self.origin_ft.y_ft) / self.cell_size_ft)
        if column < 0 or row < 0 or column >= self.columns or row >= self.rows:
            raise ValueError(
                f"feet position ({position.x_ft}, {position.y_ft}, {position.z_ft}) "
                "is outside scene bounds"
            )
        return GridCell(column=column, row=row)

    def grid_cell_to_feet(self, cell: GridCell, *, z_ft: float | None = None) -> FeetPosition:
        """Map a cell to its deterministic center point in engine feet."""

        self._require_cell_in_bounds(cell)
        resolved_z_ft = self.origin_ft.z_ft if z_ft is None else z_ft
        return FeetPosition(
            x_ft=self.origin_ft.x_ft + (cell.column + 0.5) * self.cell_size_ft,
            y_ft=self.origin_ft.y_ft + (cell.row + 0.5) * self.cell_size_ft,
            z_ft=resolved_z_ft,
        )


class GridPixelTransform(_StrictSceneModel):
    """Presentation-only transform between grid cells and pixel coordinates."""

    origin_x_px: FiniteCoordinate
    origin_y_px: FiniteCoordinate
    pixels_per_cell: PositiveFiniteFloat

    def grid_cell_to_pixel(self, cell: GridCell, *, scene: SquareGridScene) -> PixelPoint:
        """Return the pixel-space center of a bounded scene cell."""

        if not isinstance(scene, SquareGridScene):
            raise TypeError("scene must be a SquareGridScene")
        scene._require_cell_in_bounds(cell)
        return PixelPoint(
            x_px=self.origin_x_px + (cell.column + 0.5) * self.pixels_per_cell,
            y_px=self.origin_y_px + (cell.row + 0.5) * self.pixels_per_cell,
        )

    def pixel_to_grid_cell(self, point: PixelPoint, *, scene: SquareGridScene) -> GridCell:
        """Map a pixel point to its containing cell using half-open bounds."""

        if not isinstance(point, PixelPoint):
            raise TypeError("point must be a PixelPoint")
        if not isinstance(scene, SquareGridScene):
            raise TypeError("scene must be a SquareGridScene")
        column = math.floor((point.x_px - self.origin_x_px) / self.pixels_per_cell)
        row = math.floor((point.y_px - self.origin_y_px) / self.pixels_per_cell)
        if column < 0 or row < 0 or column >= scene.columns or row >= scene.rows:
            raise ValueError(f"pixel point ({point.x_px}, {point.y_px}) is outside scene bounds")
        return GridCell(column=column, row=row)


class SceneToken(_StrictSceneModel):
    """The deliberately small public token view for one engine actor."""

    actor_id: str
    team: str
    name: str
    position_ft: FeetPosition
    hp: NonNegativeInt
    max_hp: PositiveInt
    conditions: tuple[str, ...] = ()

    @field_validator("actor_id", "team", "name")
    @classmethod
    def validate_text(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @field_validator("conditions")
    @classmethod
    def validate_conditions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for condition in values:
            _canonical_text(condition, field_name="condition")
        if values != tuple(sorted(set(values))):
            raise ValueError("conditions must be unique and sorted")
        return values

    @model_validator(mode="after")
    def validate_hp(self) -> SceneToken:
        if self.hp > self.max_hp:
            raise ValueError("hp must not exceed max_hp")
        return self


class SceneProjection(_StrictSceneModel):
    """A deterministic, JSON-safe allowlisted projection of a scene."""

    schema_version: Literal["vtt.scene_projection.v1"]
    scene_id: str
    tokens: tuple[SceneToken, ...]

    @field_validator("scene_id")
    @classmethod
    def validate_scene_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="scene_id")

    @model_validator(mode="after")
    def validate_token_order_and_identity(self) -> SceneProjection:
        actor_ids = tuple(token.actor_id for token in self.tokens)
        if actor_ids != tuple(sorted(set(actor_ids))):
            raise ValueError("tokens must have unique actor identities in sorted order")
        return self


def _project_conditions(actor: ActorRuntimeState) -> tuple[str, ...]:
    conditions: list[str] = []
    for condition in actor.conditions:
        if not isinstance(condition, str):
            raise ValueError("actor conditions must be strings")
        conditions.append(_canonical_text(condition, field_name="condition"))
    return tuple(sorted(set(conditions)))


def project_scene(
    scene: SquareGridScene,
    actors: Mapping[str, ActorRuntimeState],
) -> SceneProjection:
    """Project only public token fields from a mapping of runtime actors.

    Runtime resources, traits, actions, visibility internals, and all other actor
    implementation state are intentionally not traversed into the result.
    """

    if not isinstance(scene, SquareGridScene):
        raise TypeError("scene must be a SquareGridScene")
    if not isinstance(actors, Mapping):
        raise TypeError("actors must be a mapping")

    actor_items = list(actors.items())
    for actor_id, actor in actor_items:
        if not isinstance(actor_id, str):
            raise ValueError("actor mapping keys must be strings")
        _canonical_text(actor_id, field_name="actor mapping key")
        if not isinstance(actor, ActorRuntimeState):
            raise TypeError(f"actor '{actor_id}' must be an ActorRuntimeState")
        if actor.actor_id != actor_id:
            raise ValueError(
                f"actor identity mismatch: mapping key '{actor_id}' does not match "
                f"ActorRuntimeState.actor_id '{actor.actor_id}'"
            )

    tokens: list[SceneToken] = []
    for actor_id, actor in sorted(actor_items, key=lambda item: item[0]):
        position = FeetPosition(
            x_ft=actor.position[0],
            y_ft=actor.position[1],
            z_ft=actor.position[2],
        )
        scene.feet_to_grid_cell(position)
        tokens.append(
            SceneToken(
                actor_id=actor_id,
                team=actor.team,
                name=actor.name,
                position_ft=position,
                hp=actor.hp,
                max_hp=actor.max_hp,
                conditions=_project_conditions(actor),
            )
        )

    return SceneProjection(
        schema_version=SCENE_PROJECTION_SCHEMA_VERSION,
        scene_id=scene.scene_id,
        tokens=tuple(tokens),
    )
