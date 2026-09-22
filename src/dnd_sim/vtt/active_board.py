"""One authoritative projection binding engine feet to the active scene library entry."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .scene import FeetPosition, SquareGridScene
from .scene_library_contracts import SceneMapMetadata
from .scene_library_store import SQLiteSceneLibrary

ACTIVE_BOARD_PROJECTION_SCHEMA_VERSION = "vtt.active_board_projection.v1"

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]


class ActiveBoardProjection(BaseModel):
    """Atomic active-scene identity, revision, coordinate frame, and calibration."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[ACTIVE_BOARD_PROJECTION_SCHEMA_VERSION] = (
        ACTIVE_BOARD_PROJECTION_SCHEMA_VERSION
    )
    scene_revision: NonNegativeInt
    scene: SquareGridScene
    map_metadata: SceneMapMetadata

    @model_validator(mode="after")
    def validate_scene_identity(self) -> "ActiveBoardProjection":
        if self.scene.scene_id == "":  # pragma: no cover - scene validates text first
            raise ValueError("active board scene_id must not be empty")
        if self.scene.name != self.map_metadata.name:
            raise ValueError("active board scene name must match its map metadata")
        return self


def resolve_active_board(
    *,
    configured_scene: SquareGridScene | None,
    scene_library: SQLiteSceneLibrary | None,
    table_id: str | None,
) -> ActiveBoardProjection | None:
    """Resolve the durable active entry once, without inventing a grid topology."""

    if scene_library is None:
        return None
    if table_id is None:
        raise RuntimeError("active board resolution requires a scene-library table")
    snapshot = scene_library.snapshot(table_id)
    if snapshot.active_scene_id is None:
        return None
    entry = snapshot.scene(snapshot.active_scene_id)
    if entry is None or entry.archived:  # pragma: no cover - snapshot invariant
        raise RuntimeError("the scene library has an invalid active scene")
    metadata = entry.scene.map_metadata
    calibration = metadata.calibration
    origin = (
        configured_scene.origin_ft
        if configured_scene is not None
        else FeetPosition(x_ft=0.0, y_ft=0.0, z_ft=0.0)
    )
    # Columns and rows remain a legacy feet-frame envelope only. Topology and
    # complete-cell membership come exclusively from map_metadata.calibration.
    columns = max(1, math.ceil(metadata.width_px / calibration.cell_extent_px))
    rows = max(1, math.ceil(metadata.height_px / calibration.cell_extent_px))
    scene = SquareGridScene(
        schema_version="vtt.scene.v1",
        scene_id=entry.scene.scene_id,
        name=metadata.name,
        cell_size_ft=calibration.distance_ft,
        columns=columns,
        rows=rows,
        origin_ft=origin,
    )
    return ActiveBoardProjection(
        scene_revision=snapshot.revision,
        scene=scene,
        map_metadata=metadata,
    )


__all__ = [
    "ACTIVE_BOARD_PROJECTION_SCHEMA_VERSION",
    "ActiveBoardProjection",
    "resolve_active_board",
]
