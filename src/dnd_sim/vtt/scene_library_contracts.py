"""Strict portable contracts for durable VTT scene-library lifecycle state."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Annotated, Any, Literal, Self, TypeAlias

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    TypeAdapter,
    field_validator,
    model_serializer,
    model_validator,
)

from .board_calibration import BoardCalibration

SCENE_MAP_ASSET_SCHEMA_VERSION = "vtt.scene_map_asset.v1"
SCENE_MAP_METADATA_SCHEMA_VERSION = "vtt.scene_map_metadata.v1"
SCENE_RECORD_SCHEMA_VERSION = "vtt.scene_record.v1"
SCENE_LIBRARY_VIEW_SCHEMA_VERSION = "vtt.scene_library_view.v1"
SCENE_EXPORT_SCHEMA_VERSION = "vtt.scene_export.v1"
SCENE_COMMAND_SCHEMA_VERSION = "vtt.scene_command.v1"
SCENE_EVENT_SCHEMA_VERSION = "vtt.scene_event.v1"
SCENE_RECEIPT_SCHEMA_VERSION = "vtt.scene_receipt.v1"

MAX_MAP_DIMENSION_PX = 1_000_000
MAX_GRID_SIZE_PX = 100_000.0


def _require_float(value: Any) -> float:
    if type(value) is not float:
        raise ValueError("value must be a floating-point number")
    return value


PositivePixelDimension = Annotated[
    int,
    Field(strict=True, ge=1, le=MAX_MAP_DIMENSION_PX),
]
GridPixelSize = Annotated[
    float,
    BeforeValidator(_require_float),
    Field(strict=True, gt=0.0, le=MAX_GRID_SIZE_PX, allow_inf_nan=False),
]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]


class _StrictSceneLibraryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _canonical_text(value: str, *, field_name: str, maximum_length: int = 128) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    if len(value) > maximum_length:
        raise ValueError(f"{field_name} must be at most {maximum_length} characters")
    return value


class SceneMapAssetReference(_StrictSceneLibraryModel):
    """A portable reference to a validated same-origin map image."""

    schema_version: Literal[SCENE_MAP_ASSET_SCHEMA_VERSION] = SCENE_MAP_ASSET_SCHEMA_VERSION
    asset_id: str
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    content_path: str
    sha256: str
    alt_text: str

    @field_validator("asset_id")
    @classmethod
    def validate_asset_id(cls, value: str) -> str:
        value = _canonical_text(value, field_name="asset_id")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value) is None:
            raise ValueError("asset_id must be a URL-safe identifier")
        return value

    @field_validator("content_path")
    @classmethod
    def validate_content_path(cls, value: str) -> str:
        value = _canonical_text(value, field_name="content_path", maximum_length=256)
        static_path = re.fullmatch(
            r"/assets/maps/[A-Za-z0-9][A-Za-z0-9._/-]*",
            value,
        )
        api_path = re.fullmatch(
            r"/api/v1/map-assets/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/content\.(?:png|jpg|webp)",
            value,
        )
        if static_path is None and api_path is None:
            raise ValueError("content_path must identify a same-origin map asset")
        path_segments = value.split("/")
        if any(segment in {"", ".", ".."} for segment in path_segments[3:]):
            raise ValueError("content_path must not contain empty or relative segments")
        return value

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("sha256 must be a lowercase hexadecimal SHA-256 digest")
        return value

    @field_validator("alt_text")
    @classmethod
    def validate_alt_text(cls, value: str) -> str:
        return _canonical_text(value, field_name="alt_text", maximum_length=240)

    @model_validator(mode="after")
    def validate_media_extension(self) -> Self:
        expected_extensions = {
            "image/png": (".png",),
            "image/jpeg": (".jpg", ".jpeg"),
            "image/webp": (".webp",),
        }
        if not self.content_path.lower().endswith(expected_extensions[self.media_type]):
            raise ValueError("content_path extension must match media_type")
        api_match = re.fullmatch(
            r"/api/v1/map-assets/([A-Za-z0-9][A-Za-z0-9_-]{0,127})/content\.(?:png|jpg|webp)",
            self.content_path,
        )
        if api_match is not None and api_match.group(1) != self.asset_id:
            raise ValueError("content_path asset identity must match asset_id")
        return self


class SceneMapMetadata(_StrictSceneLibraryModel):
    """Portable map calibration metadata with an optional safe image reference."""

    schema_version: Literal[SCENE_MAP_METADATA_SCHEMA_VERSION] = SCENE_MAP_METADATA_SCHEMA_VERSION
    name: str
    width_px: PositivePixelDimension
    height_px: PositivePixelDimension
    grid_size_px: GridPixelSize
    gridless: bool
    calibration: BoardCalibration
    asset: SceneMapAssetReference | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_grid_fields(cls, value: Any) -> Any:
        if not isinstance(value, Mapping) or "calibration" in value:
            return value
        grid_size = value.get("grid_size_px")
        gridless = value.get("gridless")
        if type(grid_size) is not float or not isinstance(gridless, bool):
            return value
        return {
            **value,
            "calibration": {
                "schema_version": "vtt.board_calibration.v1",
                "topology": "gridless" if gridless else "square",
                "origin_x_px": grid_size / 2.0,
                "origin_y_px": grid_size / 2.0,
                "cell_extent_px": grid_size,
                "distance_ft": 5.0,
            },
        }

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _canonical_text(value, field_name="name", maximum_length=160)

    @field_validator("gridless", mode="before")
    @classmethod
    def validate_gridless(cls, value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError("gridless must be a boolean")
        return value

    @model_validator(mode="after")
    def validate_calibration_consistency(self) -> Self:
        if self.grid_size_px != self.calibration.cell_extent_px:
            raise ValueError("grid_size_px must match the calibration cell extent")
        if self.gridless != (self.calibration.topology == "gridless"):
            raise ValueError("gridless must match the calibration topology")
        self.calibration.require_usable_map(
            width_px=self.width_px,
            height_px=self.height_px,
        )
        return self

    @model_serializer(mode="wrap")
    def serialize_without_empty_asset(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> dict[str, Any]:
        """Keep pre-asset canonical JSON byte-compatible when no asset is attached."""

        serialized = dict(handler(self))
        if self.asset is None:
            serialized.pop("asset", None)
        return serialized


class SceneRecord(_StrictSceneLibraryModel):
    """One immutable scene definition independent of table lifecycle state."""

    schema_version: Literal[SCENE_RECORD_SCHEMA_VERSION] = SCENE_RECORD_SCHEMA_VERSION
    scene_id: str
    map_metadata: SceneMapMetadata

    @field_validator("scene_id")
    @classmethod
    def validate_scene_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="scene_id")


class SceneLibraryEntry(_StrictSceneLibraryModel):
    scene: SceneRecord
    archived: bool = False

    @field_validator("archived", mode="before")
    @classmethod
    def validate_archived(cls, value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError("archived must be a boolean")
        return value


class SceneLibraryView(_StrictSceneLibraryModel):
    """A deterministic table projection with exactly one active available scene."""

    schema_version: Literal[SCENE_LIBRARY_VIEW_SCHEMA_VERSION] = SCENE_LIBRARY_VIEW_SCHEMA_VERSION
    table_id: str
    revision: NonNegativeInt
    active_scene_id: str | None = None
    scenes: tuple[SceneLibraryEntry, ...] = ()

    @field_validator("table_id")
    @classmethod
    def validate_table_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="table_id")

    @field_validator("active_scene_id")
    @classmethod
    def validate_active_scene_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _canonical_text(value, field_name="active_scene_id")

    @model_validator(mode="after")
    def validate_identity_order_and_active_scene(self) -> Self:
        scene_ids = tuple(entry.scene.scene_id for entry in self.scenes)
        if scene_ids != tuple(sorted(set(scene_ids))):
            raise ValueError("scenes must have unique scene IDs in sorted order")
        available_ids = {entry.scene.scene_id for entry in self.scenes if not entry.archived}
        if not available_ids:
            if self.active_scene_id is not None:
                raise ValueError("active_scene_id must be absent without an available scene")
            return self
        if self.active_scene_id not in available_ids:
            raise ValueError("active_scene_id must identify one available scene")
        return self

    def scene(self, scene_id: str) -> SceneLibraryEntry | None:
        normalized = _canonical_text(scene_id, field_name="scene_id")
        return next(
            (entry for entry in self.scenes if entry.scene.scene_id == normalized),
            None,
        )


class SceneExportBundle(_StrictSceneLibraryModel):
    """A portable metadata-only artifact for one scene."""

    schema_version: Literal[SCENE_EXPORT_SCHEMA_VERSION] = SCENE_EXPORT_SCHEMA_VERSION
    scene: SceneRecord


class _SceneCommandBase(_StrictSceneLibraryModel):
    schema_version: Literal[SCENE_COMMAND_SCHEMA_VERSION] = SCENE_COMMAND_SCHEMA_VERSION
    table_id: str
    command_id: str
    expected_revision: NonNegativeInt

    @field_validator("table_id", "command_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)


class SceneCreateCommand(_SceneCommandBase):
    command_type: Literal["create"] = "create"
    scene: SceneRecord


class SceneDuplicateCommand(_SceneCommandBase):
    command_type: Literal["duplicate"] = "duplicate"
    source_scene_id: str
    new_scene_id: str
    new_name: str

    @field_validator("source_scene_id", "new_scene_id")
    @classmethod
    def validate_scene_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @field_validator("new_name")
    @classmethod
    def validate_new_name(cls, value: str) -> str:
        return _canonical_text(value, field_name="new_name", maximum_length=160)

    @model_validator(mode="after")
    def validate_distinct_scene_ids(self) -> Self:
        if self.source_scene_id == self.new_scene_id:
            raise ValueError("new_scene_id must differ from source_scene_id")
        return self


class SceneUpdateCommand(_SceneCommandBase):
    command_type: Literal["update"] = "update"
    scene_id: str
    map_metadata: SceneMapMetadata

    @field_validator("scene_id")
    @classmethod
    def validate_scene_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="scene_id")


class SceneActivateCommand(_SceneCommandBase):
    command_type: Literal["activate"] = "activate"
    scene_id: str

    @field_validator("scene_id")
    @classmethod
    def validate_scene_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="scene_id")


class SceneArchiveCommand(_SceneCommandBase):
    command_type: Literal["archive"] = "archive"
    scene_id: str
    successor_scene_id: str | None = None

    @field_validator("scene_id", "successor_scene_id")
    @classmethod
    def validate_scene_id(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _canonical_text(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_distinct_successor(self) -> Self:
        if self.successor_scene_id == self.scene_id:
            raise ValueError("successor_scene_id must differ from scene_id")
        return self


class SceneImportCommand(_SceneCommandBase):
    command_type: Literal["import"] = "import"
    bundle: SceneExportBundle


SceneMutationCommand: TypeAlias = Annotated[
    SceneCreateCommand
    | SceneDuplicateCommand
    | SceneUpdateCommand
    | SceneActivateCommand
    | SceneArchiveCommand
    | SceneImportCommand,
    Field(discriminator="command_type"),
]


class _SceneEventBase(_StrictSceneLibraryModel):
    schema_version: Literal[SCENE_EVENT_SCHEMA_VERSION] = SCENE_EVENT_SCHEMA_VERSION
    table_id: str
    event_id: str
    sequence: PositiveInt
    revision: PositiveInt
    command_id: str

    @field_validator("table_id", "command_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="event_id", maximum_length=512)

    @model_validator(mode="after")
    def validate_sequence_revision(self) -> Self:
        if self.sequence != self.revision:
            raise ValueError("sequence must match revision")
        return self


class SceneCreatedEvent(_SceneEventBase):
    event_type: Literal["created"] = "created"
    scene: SceneRecord
    became_active: bool


class SceneDuplicatedEvent(_SceneEventBase):
    event_type: Literal["duplicated"] = "duplicated"
    source_scene_id: str
    scene: SceneRecord
    became_active: bool = False

    @field_validator("source_scene_id")
    @classmethod
    def validate_source_scene_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="source_scene_id")


class SceneUpdatedEvent(_SceneEventBase):
    event_type: Literal["updated"] = "updated"
    scene: SceneRecord
    active: bool

    @field_validator("active", mode="before")
    @classmethod
    def validate_active(cls, value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError("active must be a boolean")
        return value


class SceneActivatedEvent(_SceneEventBase):
    event_type: Literal["activated"] = "activated"
    scene_id: str
    previous_scene_id: str

    @field_validator("scene_id", "previous_scene_id")
    @classmethod
    def validate_scene_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)


class SceneArchivedEvent(_SceneEventBase):
    event_type: Literal["archived"] = "archived"
    scene_id: str
    successor_scene_id: str | None = None
    active_scene_id: str

    @field_validator("scene_id", "successor_scene_id", "active_scene_id")
    @classmethod
    def validate_scene_id(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _canonical_text(value, field_name=info.field_name)


class SceneImportedEvent(_SceneEventBase):
    event_type: Literal["imported"] = "imported"
    scene: SceneRecord
    became_active: bool


SceneMutationEvent: TypeAlias = Annotated[
    SceneCreatedEvent
    | SceneDuplicatedEvent
    | SceneUpdatedEvent
    | SceneActivatedEvent
    | SceneArchivedEvent
    | SceneImportedEvent,
    Field(discriminator="event_type"),
]


class SceneMutationReceipt(_StrictSceneLibraryModel):
    schema_version: Literal[SCENE_RECEIPT_SCHEMA_VERSION] = SCENE_RECEIPT_SCHEMA_VERSION
    table_id: str
    command_id: str
    revision: PositiveInt
    event: SceneMutationEvent

    @field_validator("table_id", "command_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_event_identity(self) -> Self:
        if self.event.table_id != self.table_id:
            raise ValueError("event.table_id must match table_id")
        if self.event.command_id != self.command_id:
            raise ValueError("event.command_id must match command_id")
        if self.event.revision != self.revision:
            raise ValueError("event.revision must match revision")
        return self


_COMMAND_ADAPTER = TypeAdapter(SceneMutationCommand)


def parse_scene_command(value: Any) -> SceneMutationCommand:
    return _COMMAND_ADAPTER.validate_python(value)


def parse_scene_command_json(value: str | bytes | bytearray) -> SceneMutationCommand:
    return _COMMAND_ADAPTER.validate_json(value)


def parse_scene_export(value: Any) -> SceneExportBundle:
    return SceneExportBundle.model_validate(value)


def parse_scene_export_json(value: str | bytes | bytearray) -> SceneExportBundle:
    return SceneExportBundle.model_validate_json(value)


__all__ = [
    "MAX_GRID_SIZE_PX",
    "MAX_MAP_DIMENSION_PX",
    "SCENE_COMMAND_SCHEMA_VERSION",
    "SCENE_EVENT_SCHEMA_VERSION",
    "SCENE_EXPORT_SCHEMA_VERSION",
    "SCENE_LIBRARY_VIEW_SCHEMA_VERSION",
    "SCENE_MAP_METADATA_SCHEMA_VERSION",
    "SCENE_RECEIPT_SCHEMA_VERSION",
    "SCENE_RECORD_SCHEMA_VERSION",
    "SceneActivateCommand",
    "SceneActivatedEvent",
    "SceneArchiveCommand",
    "SceneArchivedEvent",
    "SceneCreateCommand",
    "SceneCreatedEvent",
    "SceneDuplicateCommand",
    "SceneDuplicatedEvent",
    "SceneExportBundle",
    "SceneImportCommand",
    "SceneImportedEvent",
    "SceneLibraryEntry",
    "SceneLibraryView",
    "SceneMapMetadata",
    "SceneMutationCommand",
    "SceneMutationEvent",
    "SceneMutationReceipt",
    "SceneRecord",
    "parse_scene_command",
    "parse_scene_command_json",
    "parse_scene_export",
    "parse_scene_export_json",
]
