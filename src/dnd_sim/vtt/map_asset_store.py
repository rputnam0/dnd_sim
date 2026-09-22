"""Restart-safe SQLite storage and media inspection for VTT map assets."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import warnings
from dataclasses import dataclass
from typing import Any

from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from .map_asset_contracts import (
    MAP_ASSET_RECEIPT_SCHEMA_VERSION,
    MAX_MAP_ASSET_DIMENSION_PX,
    MAX_MAP_ASSET_PIXELS,
    MapAssetCatalogView,
    MapAssetRecord,
    MapAssetUploadCommand,
    MapAssetUploadReceipt,
)
from .scene_library_contracts import SceneMapAssetReference

MAP_ASSET_STORE_SCHEMA_VERSION = "vtt.map_asset_store.v1"
_METADATA_TABLE = "_vtt_map_asset_store_metadata"
_ASSETS_TABLE = "_vtt_map_asset"
_COMMANDS_TABLE = "_vtt_map_asset_command_log"


class MapAssetStoreError(RuntimeError):
    """Base failure for durable map asset operations."""


class MapAssetStoreSchemaError(MapAssetStoreError):
    pass


class MapAssetStoreCorruptionError(MapAssetStoreError):
    pass


class MapAssetCommandConflictError(MapAssetStoreError):
    pass


class MapAssetRevisionConflictError(MapAssetStoreError):
    def __init__(self, *, current_revision: int, expected_revision: int) -> None:
        super().__init__(f"expected revision {current_revision}, received {expected_revision}")
        self.current_revision = current_revision
        self.expected_revision = expected_revision


class MapAssetIdConflictError(MapAssetStoreError):
    pass


class MapAssetNotFoundError(MapAssetStoreError):
    pass


class MapAssetInvalidImageError(MapAssetStoreError):
    pass


@dataclass(frozen=True, slots=True)
class MapAssetExecutionResult:
    receipt: MapAssetUploadReceipt
    replayed: bool


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _content_path(asset_id: str, *, image_format: str) -> str:
    extension = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}[image_format]
    return f"/api/v1/map-assets/{asset_id}/content.{extension}"


def _inspect_image(content: bytes, *, asset_id: str, alt_text: str) -> MapAssetRecord:
    digest = hashlib.sha256(content).hexdigest()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                image_format = str(image.format or "").upper()
                if image_format not in {"PNG", "JPEG", "WEBP"}:
                    raise MapAssetInvalidImageError("map asset must be a PNG, JPEG, or WebP image")
                if image_format == "PNG" and not content.endswith(
                    b"\x00\x00\x00\x00IEND\xaeB\x60\x82"
                ):
                    raise MapAssetInvalidImageError("PNG map asset is truncated")
                if image_format == "JPEG" and not content.endswith(b"\xff\xd9"):
                    raise MapAssetInvalidImageError("JPEG map asset is truncated")
                if image_format == "WEBP" and (
                    len(content) < 12
                    or content[:4] != b"RIFF"
                    or content[8:12] != b"WEBP"
                    or int.from_bytes(content[4:8], "little") + 8 != len(content)
                ):
                    raise MapAssetInvalidImageError("WebP map asset is truncated")
                width_px, height_px = image.size
                if width_px < 1 or height_px < 1:
                    raise MapAssetInvalidImageError("map asset dimensions must be positive")
                if (
                    width_px > MAX_MAP_ASSET_DIMENSION_PX
                    or height_px > MAX_MAP_ASSET_DIMENSION_PX
                    or width_px * height_px > MAX_MAP_ASSET_PIXELS
                ):
                    raise MapAssetInvalidImageError("map asset dimensions exceed the allowed limit")
                if (
                    bool(getattr(image, "is_animated", False))
                    or int(getattr(image, "n_frames", 1)) != 1
                ):
                    raise MapAssetInvalidImageError("animated map images are not supported")
                image.verify()
    except MapAssetInvalidImageError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise MapAssetInvalidImageError("map asset dimensions exceed the allowed limit") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise MapAssetInvalidImageError("map asset is malformed or unsupported") from exc

    media_type = {
        "PNG": "image/png",
        "JPEG": "image/jpeg",
        "WEBP": "image/webp",
    }[image_format]
    return MapAssetRecord(
        reference=SceneMapAssetReference(
            asset_id=asset_id,
            media_type=media_type,
            content_path=_content_path(asset_id, image_format=image_format),
            sha256=digest,
            alt_text=alt_text,
        ),
        width_px=width_px,
        height_px=height_px,
        byte_size=len(content),
    )


def _command_identity(command: MapAssetUploadCommand, *, digest: str) -> str:
    return _canonical_json(
        {
            "schema_version": command.schema_version,
            "table_id": command.table_id,
            "command_id": command.command_id,
            "expected_revision": command.expected_revision,
            "asset_id": command.asset_id,
            "alt_text": command.alt_text,
            "content_sha256": digest,
        }
    )


class SQLiteMapAssetStore:
    """One connection-owned map image catalog with idempotent uploads."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        if connection.in_transaction:
            raise MapAssetStoreError("cannot initialize map assets in an active transaction")
        self._connection = connection
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(f"""
                CREATE TABLE IF NOT EXISTS {_METADATA_TABLE} (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    schema_version TEXT NOT NULL
                )
                """)
            row = self._connection.execute(
                f"SELECT schema_version FROM {_METADATA_TABLE} WHERE singleton = 1"
            ).fetchone()
            if row is None:
                self._connection.execute(
                    f"INSERT INTO {_METADATA_TABLE} (singleton, schema_version) VALUES (1, ?)",
                    (MAP_ASSET_STORE_SCHEMA_VERSION,),
                )
            elif str(row[0]) != MAP_ASSET_STORE_SCHEMA_VERSION:
                raise MapAssetStoreSchemaError("unsupported map asset store schema")
            self._connection.execute(f"""
                CREATE TABLE IF NOT EXISTS {_ASSETS_TABLE} (
                    store_schema_version TEXT NOT NULL,
                    table_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    record_json TEXT NOT NULL,
                    content BLOB NOT NULL,
                    PRIMARY KEY (table_id, asset_id),
                    UNIQUE (table_id, revision),
                    CHECK (length(trim(record_json)) > 0),
                    CHECK (length(content) > 0)
                )
                """)
            self._connection.execute(f"""
                CREATE TABLE IF NOT EXISTS {_COMMANDS_TABLE} (
                    store_schema_version TEXT NOT NULL,
                    table_id TEXT NOT NULL,
                    command_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    command_identity TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    PRIMARY KEY (table_id, command_id),
                    UNIQUE (table_id, revision),
                    CHECK (length(trim(command_identity)) > 0),
                    CHECK (length(trim(receipt_json)) > 0)
                )
                """)
            self._connection.commit()
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def execute(self, command: MapAssetUploadCommand) -> MapAssetExecutionResult:
        if not isinstance(command, MapAssetUploadCommand):
            raise TypeError("command must be a MapAssetUploadCommand")
        command = MapAssetUploadCommand.model_validate(command.model_dump(mode="json"))
        content = command.content_bytes()
        record = _inspect_image(content, asset_id=command.asset_id, alt_text=command.alt_text)
        command_identity = _command_identity(command, digest=record.reference.sha256)
        if self._connection.in_transaction:
            raise MapAssetStoreError("execute cannot run inside an active transaction")

        try:
            self._connection.execute("BEGIN IMMEDIATE")
            existing = self._connection.execute(
                f"""
                SELECT store_schema_version, revision, command_identity, receipt_json
                FROM {_COMMANDS_TABLE}
                WHERE table_id = ? AND command_id = ?
                """,
                (command.table_id, command.command_id),
            ).fetchone()
            if existing is not None:
                self._validate_store_schema(str(existing[0]))
                if str(existing[2]) != command_identity:
                    raise MapAssetCommandConflictError(
                        f"command_id '{command.command_id}' has different content"
                    )
                receipt = self._parse_receipt(
                    str(existing[3]),
                    table_id=command.table_id,
                    command_id=command.command_id,
                    revision=int(existing[1]),
                )
                self._connection.commit()
                return MapAssetExecutionResult(receipt=receipt, replayed=True)

            current_revision = self._revision_locked(command.table_id)
            if command.expected_revision != current_revision:
                raise MapAssetRevisionConflictError(
                    current_revision=current_revision,
                    expected_revision=command.expected_revision,
                )
            if (
                self._connection.execute(
                    f"SELECT 1 FROM {_ASSETS_TABLE} WHERE table_id = ? AND asset_id = ?",
                    (command.table_id, command.asset_id),
                ).fetchone()
                is not None
            ):
                raise MapAssetIdConflictError(f"asset_id '{command.asset_id}' was already used")

            revision = current_revision + 1
            receipt = MapAssetUploadReceipt(
                schema_version=MAP_ASSET_RECEIPT_SCHEMA_VERSION,
                table_id=command.table_id,
                command_id=command.command_id,
                revision=revision,
                asset=record,
            )
            self._connection.execute(
                f"""
                INSERT INTO {_ASSETS_TABLE} (
                    store_schema_version, table_id, asset_id, revision, record_json, content
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    MAP_ASSET_STORE_SCHEMA_VERSION,
                    command.table_id,
                    command.asset_id,
                    revision,
                    _canonical_json(record.model_dump(mode="json")),
                    content,
                ),
            )
            self._connection.execute(
                f"""
                INSERT INTO {_COMMANDS_TABLE} (
                    store_schema_version, table_id, command_id, revision,
                    command_identity, receipt_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    MAP_ASSET_STORE_SCHEMA_VERSION,
                    command.table_id,
                    command.command_id,
                    revision,
                    command_identity,
                    _canonical_json(receipt.model_dump(mode="json")),
                ),
            )
            self._connection.commit()
            return MapAssetExecutionResult(receipt=receipt, replayed=False)
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def revision(self, table_id: str) -> int:
        if not isinstance(table_id, str) or not table_id or table_id != table_id.strip():
            raise ValueError("table_id must be canonical non-empty text")
        return self._revision_locked(table_id)

    def _revision_locked(self, table_id: str) -> int:
        row = self._connection.execute(
            f"SELECT COALESCE(MAX(revision), 0) FROM {_COMMANDS_TABLE} WHERE table_id = ?",
            (table_id,),
        ).fetchone()
        if row is None or type(row[0]) is not int or row[0] < 0:
            raise MapAssetStoreCorruptionError("stored map asset revision is invalid")
        return row[0]

    def catalog(self, table_id: str) -> MapAssetCatalogView:
        revision = self.revision(table_id)
        rows = self._connection.execute(
            f"""
            SELECT store_schema_version, asset_id, record_json
            FROM {_ASSETS_TABLE}
            WHERE table_id = ?
            ORDER BY asset_id
            """,
            (table_id,),
        ).fetchall()
        assets: list[MapAssetRecord] = []
        for store_version, asset_id, record_json in rows:
            self._validate_store_schema(str(store_version))
            record = self._parse_record(str(record_json))
            if record.reference.asset_id != str(asset_id):
                raise MapAssetStoreCorruptionError("stored map asset identity is inconsistent")
            assets.append(record)
        return MapAssetCatalogView(table_id=table_id, revision=revision, assets=tuple(assets))

    def content(self, table_id: str, asset_id: str) -> tuple[MapAssetRecord, bytes]:
        if not isinstance(asset_id, str) or not asset_id or asset_id != asset_id.strip():
            raise ValueError("asset_id must be canonical non-empty text")
        row = self._connection.execute(
            f"""
            SELECT store_schema_version, record_json, content
            FROM {_ASSETS_TABLE}
            WHERE table_id = ? AND asset_id = ?
            """,
            (table_id, asset_id),
        ).fetchone()
        if row is None:
            raise MapAssetNotFoundError(f"asset_id '{asset_id}' is missing")
        self._validate_store_schema(str(row[0]))
        record = self._parse_record(str(row[1]))
        content = bytes(row[2])
        if (
            record.reference.asset_id != asset_id
            or record.byte_size != len(content)
            or record.reference.sha256 != hashlib.sha256(content).hexdigest()
        ):
            raise MapAssetStoreCorruptionError("stored map asset content is inconsistent")
        return record, content

    @staticmethod
    def _validate_store_schema(value: str) -> None:
        if value != MAP_ASSET_STORE_SCHEMA_VERSION:
            raise MapAssetStoreSchemaError("unsupported stored map asset schema")

    @staticmethod
    def _parse_record(encoded: str) -> MapAssetRecord:
        try:
            return MapAssetRecord.model_validate_json(encoded)
        except (ValidationError, ValueError) as exc:
            raise MapAssetStoreCorruptionError("stored map asset record is invalid") from exc

    @staticmethod
    def _parse_receipt(
        encoded: str,
        *,
        table_id: str,
        command_id: str,
        revision: int,
    ) -> MapAssetUploadReceipt:
        try:
            receipt = MapAssetUploadReceipt.model_validate_json(encoded)
        except (ValidationError, ValueError) as exc:
            raise MapAssetStoreCorruptionError("stored map asset receipt is invalid") from exc
        if (
            receipt.table_id != table_id
            or receipt.command_id != command_id
            or receipt.revision != revision
        ):
            raise MapAssetStoreCorruptionError("stored map asset receipt identity is invalid")
        return receipt
