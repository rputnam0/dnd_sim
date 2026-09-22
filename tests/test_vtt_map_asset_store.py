from __future__ import annotations

import base64
import io
import sqlite3

import pytest
from PIL import Image
from pydantic import ValidationError

from dnd_sim.vtt.map_asset_contracts import (
    MAP_ASSET_UPLOAD_COMMAND_SCHEMA_VERSION,
    MAX_MAP_ASSET_BYTES,
    MapAssetUploadCommand,
)
from dnd_sim.vtt.map_asset_store import (
    MapAssetCommandConflictError,
    MapAssetIdConflictError,
    MapAssetInvalidImageError,
    MapAssetRevisionConflictError,
    SQLiteMapAssetStore,
)


def _image_bytes(
    image_format: str = "PNG",
    *,
    width: int = 8,
    height: int = 6,
) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color=(12, 40, 35)).save(
        output,
        format=image_format,
    )
    return output.getvalue()


def _upload(
    *,
    command_id: str = "upload-map",
    asset_id: str = "moon-temple",
    expected_revision: int = 0,
    content: bytes | None = None,
    alt_text: str = "A top-down moon temple battle map.",
) -> MapAssetUploadCommand:
    return MapAssetUploadCommand(
        schema_version=MAP_ASSET_UPLOAD_COMMAND_SCHEMA_VERSION,
        table_id="table-a",
        command_id=command_id,
        expected_revision=expected_revision,
        asset_id=asset_id,
        alt_text=alt_text,
        content_base64=base64.b64encode(_image_bytes() if content is None else content).decode(
            "ascii"
        ),
    )


def test_upload_command_is_strict_bounded_and_canonical() -> None:
    command = _upload()

    assert command.content_bytes() == _image_bytes()
    with pytest.raises(ValidationError):
        MapAssetUploadCommand.model_validate(
            {**command.model_dump(mode="json"), "asset_id": "../secret"}
        )
    with pytest.raises(ValidationError):
        MapAssetUploadCommand.model_validate(
            {**command.model_dump(mode="json"), "content_base64": "not base64"}
        )
    with pytest.raises(ValidationError):
        MapAssetUploadCommand.model_validate(
            {
                **command.model_dump(mode="json"),
                "content_base64": base64.b64encode(b"x" * (MAX_MAP_ASSET_BYTES + 1)).decode(
                    "ascii"
                ),
            }
        )


@pytest.mark.parametrize(
    ("image_format", "media_type", "extension"),
    (("PNG", "image/png", "png"), ("JPEG", "image/jpeg", "jpg"), ("WEBP", "image/webp", "webp")),
)
def test_store_detects_supported_media_and_persists_exact_content(
    image_format: str,
    media_type: str,
    extension: str,
) -> None:
    connection = sqlite3.connect(":memory:")
    try:
        store = SQLiteMapAssetStore(connection)
        content = _image_bytes(image_format)
        result = store.execute(_upload(content=content))

        assert result.replayed is False
        assert result.receipt.revision == 1
        record = result.receipt.asset
        assert record.width_px == 8
        assert record.height_px == 6
        assert record.byte_size == len(content)
        assert record.reference.media_type == media_type
        assert record.reference.content_path == (
            f"/api/v1/map-assets/moon-temple/content.{extension}"
        )
        assert store.content("table-a", "moon-temple") == (record, content)
        assert store.catalog("table-a").assets == (record,)
    finally:
        connection.close()


def test_store_replays_exact_upload_and_rejects_conflicts_without_mutation() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        store = SQLiteMapAssetStore(connection)
        command = _upload()
        original = store.execute(command)
        replayed = store.execute(command)

        assert replayed.receipt == original.receipt
        assert replayed.replayed is True
        with pytest.raises(MapAssetCommandConflictError):
            store.execute(command.model_copy(update={"alt_text": "A different description."}))
        with pytest.raises(MapAssetRevisionConflictError) as stale:
            store.execute(
                _upload(
                    command_id="upload-second",
                    asset_id="second-map",
                    expected_revision=0,
                )
            )
        assert stale.value.current_revision == 1
        with pytest.raises(MapAssetIdConflictError):
            store.execute(
                _upload(
                    command_id="reuse-id",
                    expected_revision=1,
                    content=_image_bytes(width=10, height=10),
                )
            )
        assert store.catalog("table-a").revision == 1
        assert len(store.catalog("table-a").assets) == 1
    finally:
        connection.close()


@pytest.mark.parametrize(
    "content",
    (
        b"not-an-image",
        _image_bytes()[:-4],
        _image_bytes("GIF"),
    ),
)
def test_store_rejects_malformed_and_unsupported_images_without_mutation(
    content: bytes,
) -> None:
    connection = sqlite3.connect(":memory:")
    try:
        store = SQLiteMapAssetStore(connection)

        with pytest.raises(MapAssetInvalidImageError):
            store.execute(_upload(content=content))
        assert store.catalog("table-a").revision == 0
        assert store.catalog("table-a").assets == ()
    finally:
        connection.close()


def test_store_survives_reopen_with_exact_receipt_and_content(tmp_path) -> None:
    database_path = tmp_path / "assets.sqlite3"
    content = _image_bytes("WEBP", width=24, height=18)
    command = _upload(content=content)

    first_connection = sqlite3.connect(database_path)
    first = SQLiteMapAssetStore(first_connection)
    receipt = first.execute(command).receipt
    first_connection.close()

    second_connection = sqlite3.connect(database_path)
    try:
        restored = SQLiteMapAssetStore(second_connection)
        assert restored.catalog("table-a").assets == (receipt.asset,)
        assert restored.content("table-a", "moon-temple") == (receipt.asset, content)
        assert restored.execute(command).replayed is True
    finally:
        second_connection.close()
