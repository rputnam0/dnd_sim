"""Strict contracts for durable, authenticated VTT map image assets."""

from __future__ import annotations

import base64
import binascii
import re
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .scene_library_contracts import SceneMapAssetReference

MAP_ASSET_UPLOAD_COMMAND_SCHEMA_VERSION = "vtt.map_asset_upload_command.v1"
MAP_ASSET_RECORD_SCHEMA_VERSION = "vtt.map_asset_record.v1"
MAP_ASSET_CATALOG_SCHEMA_VERSION = "vtt.map_asset_catalog.v1"
MAP_ASSET_RECEIPT_SCHEMA_VERSION = "vtt.map_asset_receipt.v1"

MAX_MAP_ASSET_BYTES = 12 * 1024 * 1024
MAX_MAP_ASSET_DIMENSION_PX = 32_768
MAX_MAP_ASSET_PIXELS = 64_000_000
MAX_MAP_ASSET_BASE64_LENGTH = 4 * ((MAX_MAP_ASSET_BYTES + 2) // 3)

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]


class _StrictMapAssetModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _canonical_text(value: str, *, field_name: str, maximum_length: int = 128) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    if len(value) > maximum_length:
        raise ValueError(f"{field_name} must be at most {maximum_length} characters")
    return value


class MapAssetUploadCommand(_StrictMapAssetModel):
    schema_version: Literal[MAP_ASSET_UPLOAD_COMMAND_SCHEMA_VERSION] = (
        MAP_ASSET_UPLOAD_COMMAND_SCHEMA_VERSION
    )
    table_id: str
    command_id: str
    expected_revision: NonNegativeInt
    asset_id: str
    alt_text: str
    content_base64: str

    @field_validator("table_id", "command_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @field_validator("asset_id")
    @classmethod
    def validate_asset_id(cls, value: str) -> str:
        value = _canonical_text(value, field_name="asset_id")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value) is None:
            raise ValueError("asset_id must be a URL-safe identifier")
        return value

    @field_validator("alt_text")
    @classmethod
    def validate_alt_text(cls, value: str) -> str:
        return _canonical_text(value, field_name="alt_text", maximum_length=240)

    @field_validator("content_base64")
    @classmethod
    def validate_content_base64(cls, value: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError("content_base64 must be non-empty canonical base64")
        if len(value) > MAX_MAP_ASSET_BASE64_LENGTH:
            raise ValueError("content_base64 exceeds the map asset size limit")
        try:
            decoded = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("content_base64 must be canonical base64") from exc
        if not decoded or len(decoded) > MAX_MAP_ASSET_BYTES:
            raise ValueError("decoded map asset size is outside the allowed range")
        if base64.b64encode(decoded).decode("ascii") != value:
            raise ValueError("content_base64 must use canonical padding")
        return value

    def content_bytes(self) -> bytes:
        return base64.b64decode(self.content_base64, validate=True)


class MapAssetRecord(_StrictMapAssetModel):
    schema_version: Literal[MAP_ASSET_RECORD_SCHEMA_VERSION] = MAP_ASSET_RECORD_SCHEMA_VERSION
    reference: SceneMapAssetReference
    width_px: PositiveInt
    height_px: PositiveInt
    byte_size: PositiveInt

    @model_validator(mode="after")
    def validate_bounded_dimensions_and_size(self) -> Self:
        if self.width_px > MAX_MAP_ASSET_DIMENSION_PX:
            raise ValueError("width_px exceeds the map asset dimension limit")
        if self.height_px > MAX_MAP_ASSET_DIMENSION_PX:
            raise ValueError("height_px exceeds the map asset dimension limit")
        if self.width_px * self.height_px > MAX_MAP_ASSET_PIXELS:
            raise ValueError("map asset pixel count exceeds the allowed limit")
        if self.byte_size > MAX_MAP_ASSET_BYTES:
            raise ValueError("byte_size exceeds the map asset size limit")
        return self


class MapAssetCatalogView(_StrictMapAssetModel):
    schema_version: Literal[MAP_ASSET_CATALOG_SCHEMA_VERSION] = MAP_ASSET_CATALOG_SCHEMA_VERSION
    table_id: str
    revision: NonNegativeInt
    assets: tuple[MapAssetRecord, ...] = ()

    @field_validator("table_id")
    @classmethod
    def validate_table_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="table_id")

    @model_validator(mode="after")
    def validate_asset_order(self) -> Self:
        asset_ids = tuple(asset.reference.asset_id for asset in self.assets)
        if asset_ids != tuple(sorted(set(asset_ids))):
            raise ValueError("assets must have unique asset IDs in sorted order")
        return self


class MapAssetUploadReceipt(_StrictMapAssetModel):
    schema_version: Literal[MAP_ASSET_RECEIPT_SCHEMA_VERSION] = MAP_ASSET_RECEIPT_SCHEMA_VERSION
    table_id: str
    command_id: str
    revision: PositiveInt
    asset: MapAssetRecord

    @field_validator("table_id", "command_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)
