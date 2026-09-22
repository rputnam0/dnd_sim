from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from dnd_sim.vtt.board_calibration import BoardCalibration
from dnd_sim.vtt.scene_library_contracts import (
    SCENE_COMMAND_SCHEMA_VERSION,
    SCENE_EXPORT_SCHEMA_VERSION,
    SCENE_MAP_ASSET_SCHEMA_VERSION,
    SCENE_MAP_METADATA_SCHEMA_VERSION,
    SCENE_RECORD_SCHEMA_VERSION,
    SceneActivateCommand,
    SceneArchiveCommand,
    SceneCreateCommand,
    SceneDuplicateCommand,
    SceneExportBundle,
    SceneImportCommand,
    SceneMapAssetReference,
    SceneMapMetadata,
    SceneRecord,
    SceneUpdateCommand,
    parse_scene_export_json,
)
from dnd_sim.vtt.scene_library_store import (
    SceneActiveArchiveError,
    SceneArchivedError,
    SceneCommandConflictError,
    SceneIdConflictError,
    SceneImportConflictError,
    SceneLibraryStoreCorruptionError,
    SceneRevisionConflictError,
    SceneSuccessorError,
    SQLiteSceneLibrary,
)


def _scene(
    scene_id: str,
    *,
    name: str | None = None,
    width_px: int = 1_920,
    height_px: int = 1_080,
    grid_size_px: float = 70.0,
    gridless: bool = False,
) -> SceneRecord:
    return SceneRecord(
        schema_version=SCENE_RECORD_SCHEMA_VERSION,
        scene_id=scene_id,
        map_metadata=SceneMapMetadata(
            schema_version=SCENE_MAP_METADATA_SCHEMA_VERSION,
            name=name or scene_id.replace("-", " ").title(),
            width_px=width_px,
            height_px=height_px,
            grid_size_px=grid_size_px,
            gridless=gridless,
        ),
    )


def _create(
    command_id: str,
    scene: SceneRecord,
    *,
    expected_revision: int,
    table_id: str = "table-a",
) -> SceneCreateCommand:
    return SceneCreateCommand(
        schema_version=SCENE_COMMAND_SCHEMA_VERSION,
        table_id=table_id,
        command_id=command_id,
        expected_revision=expected_revision,
        scene=scene,
    )


def test_scene_records_and_exports_are_strict_versioned_portable_contracts() -> None:
    scene = _scene("moon-temple", gridless=True)
    bundle = SceneExportBundle(
        schema_version=SCENE_EXPORT_SCHEMA_VERSION,
        scene=scene,
    )

    assert parse_scene_export_json(bundle.model_dump_json()) == bundle
    assert scene.model_dump(mode="json") == {
        "schema_version": SCENE_RECORD_SCHEMA_VERSION,
        "scene_id": "moon-temple",
        "map_metadata": {
            "schema_version": SCENE_MAP_METADATA_SCHEMA_VERSION,
            "name": "Moon Temple",
            "width_px": 1_920,
            "height_px": 1_080,
            "grid_size_px": 70.0,
            "gridless": True,
            "calibration": {
                "schema_version": "vtt.board_calibration.v1",
                "topology": "gridless",
                "origin_x_px": 35.0,
                "origin_y_px": 35.0,
                "cell_extent_px": 70.0,
                "distance_ft": 5.0,
            },
        },
    }

    for extra_field in ("image_blob", "image_url", "asset_path"):
        with pytest.raises(ValidationError):
            SceneMapMetadata.model_validate(
                {
                    **scene.map_metadata.model_dump(mode="json"),
                    extra_field: "not-part-of-this-contract",
                }
            )
    with pytest.raises(ValidationError):
        SceneRecord.model_validate({**scene.model_dump(mode="json"), "archived": False})
    with pytest.raises(ValidationError):
        SceneRecord.model_validate(
            {**scene.model_dump(mode="json"), "schema_version": "vtt.scene_record.v0"}
        )


def test_scene_map_asset_reference_is_safe_portable_and_round_trips() -> None:
    asset = SceneMapAssetReference(
        schema_version=SCENE_MAP_ASSET_SCHEMA_VERSION,
        asset_id="echo-vault-original",
        media_type="image/png",
        content_path="/assets/maps/echo-vault-original.png",
        sha256="a" * 64,
        alt_text="A top-down arcane vault chamber.",
    )
    scene = SceneRecord(
        scene_id="echo-vault",
        map_metadata=SceneMapMetadata(
            name="Echo Vault",
            width_px=1_448,
            height_px=1_086,
            grid_size_px=181.0,
            gridless=False,
            asset=asset,
        ),
    )
    bundle = SceneExportBundle(scene=scene)

    assert parse_scene_export_json(bundle.model_dump_json()) == bundle
    assert bundle.model_dump(mode="json")["scene"]["map_metadata"]["asset"] == {
        "schema_version": SCENE_MAP_ASSET_SCHEMA_VERSION,
        "asset_id": "echo-vault-original",
        "media_type": "image/png",
        "content_path": "/assets/maps/echo-vault-original.png",
        "sha256": "a" * 64,
        "alt_text": "A top-down arcane vault chamber.",
    }

    for invalid_path in (
        "https://example.com/map.png",
        "//example.com/map.png",
        "/assets/maps/../secret.png",
        "/assets/maps/map.png?token=secret",
        "/assets/other/map.png",
    ):
        with pytest.raises(ValidationError):
            SceneMapAssetReference.model_validate(
                {**asset.model_dump(mode="json"), "content_path": invalid_path}
            )
    with pytest.raises(ValidationError):
        SceneMapAssetReference.model_validate({**asset.model_dump(mode="json"), "sha256": "A" * 64})
    with pytest.raises(ValidationError):
        SceneMapAssetReference.model_validate(
            {
                **asset.model_dump(mode="json"),
                "media_type": "image/webp",
            }
        )


@pytest.mark.parametrize("topology", ("gridless", "square", "hex_flat", "hex_pointy"))
def test_scene_metadata_embeds_one_explicit_usable_board_calibration(
    topology: str,
) -> None:
    calibration = BoardCalibration(
        topology=topology,
        origin_x_px=100.0,
        origin_y_px=100.0,
        cell_extent_px=50.0,
        distance_ft=5.0,
    )
    metadata = SceneMapMetadata(
        name="Calibrated Board",
        width_px=800,
        height_px=600,
        grid_size_px=50.0,
        gridless=topology == "gridless",
        calibration=calibration,
    )

    assert metadata.calibration == calibration
    assert SceneMapMetadata.model_validate_json(metadata.model_dump_json()) == metadata

    with pytest.raises(ValidationError, match="grid_size_px|cell extent"):
        SceneMapMetadata.model_validate({**metadata.model_dump(mode="json"), "grid_size_px": 60.0})
    with pytest.raises(ValidationError, match="gridless|topology"):
        SceneMapMetadata.model_validate(
            {**metadata.model_dump(mode="json"), "gridless": topology != "gridless"}
        )


def test_scene_metadata_rejects_calibration_without_a_complete_usable_cell() -> None:
    with pytest.raises(ValidationError, match="complete usable cell"):
        SceneMapMetadata(
            name="Degenerate Board",
            width_px=100,
            height_px=80,
            grid_size_px=500.0,
            gridless=False,
            calibration=BoardCalibration(
                topology="hex_pointy",
                origin_x_px=0.0,
                origin_y_px=0.0,
                cell_extent_px=500.0,
                distance_ft=5.0,
            ),
        )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("width_px", 0),
        ("width_px", True),
        ("height_px", -1),
        ("grid_size_px", 0.0),
        ("grid_size_px", math.inf),
        ("gridless", 1),
    ],
)
def test_scene_map_metadata_rejects_invalid_dimensions_and_grid_fields(
    field_name: str, invalid_value: object
) -> None:
    payload = _scene("invalid-map").map_metadata.model_dump(mode="json")
    payload[field_name] = invalid_value

    with pytest.raises(ValidationError):
        SceneMapMetadata.model_validate(payload)


def test_scene_library_create_duplicate_activate_and_archive_lifecycle() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        library = SQLiteSceneLibrary(connection)
        library.execute(_create("create-one", _scene("one"), expected_revision=0))
        library.execute(_create("create-two", _scene("two"), expected_revision=1))
        duplicated = library.execute(
            SceneDuplicateCommand(
                table_id="table-a",
                command_id="duplicate-two",
                expected_revision=2,
                source_scene_id="two",
                new_scene_id="two-copy",
                new_name="Two Copy",
            )
        )

        assert duplicated.replayed is False
        view = library.snapshot("table-a")
        assert view.revision == 3
        assert view.active_scene_id == "one"
        assert [entry.scene.scene_id for entry in view.scenes] == ["one", "two", "two-copy"]
        copied = view.scene("two-copy")
        assert copied is not None
        assert copied.archived is False
        assert copied.scene.map_metadata == _scene("two").map_metadata.model_copy(
            update={"name": "Two Copy"}
        )

        library.execute(
            SceneActivateCommand(
                table_id="table-a",
                command_id="activate-copy",
                expected_revision=3,
                scene_id="two-copy",
            )
        )
        with pytest.raises(SceneActiveArchiveError):
            library.execute(
                SceneArchiveCommand(
                    table_id="table-a",
                    command_id="unsafe-archive",
                    expected_revision=4,
                    scene_id="two-copy",
                )
            )

        archived = library.execute(
            SceneArchiveCommand(
                table_id="table-a",
                command_id="safe-archive",
                expected_revision=4,
                scene_id="two-copy",
                successor_scene_id="two",
            )
        )
        assert archived.receipt.event.active_scene_id == "two"
        view = library.snapshot("table-a")
        assert view.revision == 5
        assert view.active_scene_id == "two"
        assert view.scene("two-copy").archived is True  # type: ignore[union-attr]
        assert (
            sum(
                entry.scene.scene_id == view.active_scene_id and not entry.archived
                for entry in view.scenes
            )
            == 1
        )

        with pytest.raises(SceneSuccessorError):
            library.execute(
                SceneArchiveCommand(
                    table_id="table-a",
                    command_id="irrelevant-successor",
                    expected_revision=5,
                    scene_id="one",
                    successor_scene_id="two",
                )
            )
    finally:
        connection.close()


def test_scene_library_updates_available_metadata_and_preserves_it_on_duplicate() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        library = SQLiteSceneLibrary(connection)
        library.execute(_create("create-one", _scene("one"), expected_revision=0))
        asset = SceneMapAssetReference(
            asset_id="one-map",
            media_type="image/png",
            content_path="/api/v1/map-assets/one-map/content.png",
            sha256="b" * 64,
            alt_text="A top-down stone chamber.",
        )
        metadata = SceneMapMetadata(
            name="One Calibrated",
            width_px=1_600,
            height_px=1_200,
            grid_size_px=200.0,
            gridless=False,
            asset=asset,
        )

        updated = library.execute(
            SceneUpdateCommand(
                table_id="table-a",
                command_id="update-one",
                expected_revision=1,
                scene_id="one",
                map_metadata=metadata,
            )
        )
        assert updated.receipt.event.event_type == "updated"
        assert updated.receipt.event.active is True
        assert library.snapshot("table-a").scene("one").scene.map_metadata == metadata

        library.execute(
            SceneDuplicateCommand(
                table_id="table-a",
                command_id="duplicate-updated",
                expected_revision=2,
                source_scene_id="one",
                new_scene_id="one-copy",
                new_name="One Copy",
            )
        )
        copied = library.snapshot("table-a").scene("one-copy")
        assert copied is not None
        assert copied.scene.map_metadata.asset == asset
        assert copied.scene.map_metadata.name == "One Copy"

        library.execute(
            SceneArchiveCommand(
                table_id="table-a",
                command_id="archive-copy",
                expected_revision=3,
                scene_id="one-copy",
            )
        )
        with pytest.raises(SceneArchivedError):
            library.execute(
                SceneUpdateCommand(
                    table_id="table-a",
                    command_id="update-archived",
                    expected_revision=4,
                    scene_id="one-copy",
                    map_metadata=metadata,
                )
            )
    finally:
        connection.close()


def test_scene_library_enforces_revision_id_uniqueness_and_exact_command_retry() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        library = SQLiteSceneLibrary(connection)
        command = _create("create-once", _scene("one"), expected_revision=0)
        first = library.execute(command)
        replay = library.execute(SceneCreateCommand.model_validate(command.model_dump(mode="json")))

        assert replay.replayed is True
        assert replay.receipt == first.receipt
        with pytest.raises(SceneRevisionConflictError) as stale_error:
            library.execute(_create("stale", _scene("stale"), expected_revision=0))
        assert stale_error.value.current_revision == 1
        assert stale_error.value.expected_revision == 0
        with pytest.raises(SceneCommandConflictError):
            library.execute(_create("create-once", _scene("different"), expected_revision=0))
        with pytest.raises(SceneIdConflictError):
            library.execute(_create("reuse-id", _scene("one"), expected_revision=1))
        assert library.snapshot("table-a").revision == 1
    finally:
        connection.close()


def test_scene_export_import_round_trip_is_validated_and_durable() -> None:
    source_connection = sqlite3.connect(":memory:")
    target_connection = sqlite3.connect(":memory:")
    try:
        source = SQLiteSceneLibrary(source_connection)
        source.execute(
            _create(
                "create-gridless",
                _scene(
                    "gridless-cave",
                    name="Gridless Cave",
                    width_px=2_048,
                    height_px=1_536,
                    grid_size_px=96.5,
                    gridless=True,
                ),
                expected_revision=0,
            )
        )
        exported = source.export_scene("table-a", "gridless-cave")
        encoded = exported.model_dump_json()

        target = SQLiteSceneLibrary(target_connection)
        imported = target.execute(
            SceneImportCommand(
                table_id="table-b",
                command_id="import-cave",
                expected_revision=0,
                bundle=parse_scene_export_json(encoded),
            )
        )
        assert imported.receipt.event.scene == exported.scene
        view = target.snapshot("table-b")
        assert view.active_scene_id == "gridless-cave"
        assert view.scene("gridless-cave").scene == exported.scene  # type: ignore[union-attr]

        with pytest.raises(SceneImportConflictError):
            target.execute(
                SceneImportCommand(
                    table_id="table-b",
                    command_id="import-again",
                    expected_revision=1,
                    bundle=exported,
                )
            )
    finally:
        source_connection.close()
        target_connection.close()


def test_scene_event_delta_queries_only_the_requested_sqlite_tail() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        library = SQLiteSceneLibrary(connection)
        library.execute(_create("first", _scene("one"), expected_revision=0))
        library.execute(_create("second", _scene("two"), expected_revision=1))
        traced: list[str] = []
        connection.set_trace_callback(traced.append)

        events = library.events_after("table-a", 1)

        connection.set_trace_callback(None)
        assert [event.sequence for event in events] == [2]
        event_queries = [
            " ".join(statement.split()).lower()
            for statement in traced
            if "_vtt_scene_library_event_log" in statement.lower()
            and statement.lstrip().upper().startswith("SELECT")
        ]
        assert len(event_queries) == 1
        assert "sequence > 1" in event_queries[0]
    finally:
        connection.close()


def test_scene_library_restarts_from_append_only_history(tmp_path: Path) -> None:
    database_path = tmp_path / "scenes.sqlite3"
    first_connection = sqlite3.connect(database_path)
    first = SQLiteSceneLibrary(first_connection)
    first.execute(_create("create-one", _scene("one"), expected_revision=0))
    first.execute(_create("create-two", _scene("two"), expected_revision=1))
    first.execute(
        SceneActivateCommand(
            table_id="table-a",
            command_id="activate-two",
            expected_revision=2,
            scene_id="two",
        )
    )
    first_connection.close()

    second_connection = sqlite3.connect(database_path)
    try:
        restored = SQLiteSceneLibrary(second_connection)
        view = restored.snapshot("table-a")
        assert view.revision == 3
        assert view.active_scene_id == "two"
        assert [event.sequence for event in restored.events_after("table-a", 0)] == [1, 2, 3]
        assert [event.revision for event in restored.events_after("table-a", 1)] == [2, 3]
    finally:
        second_connection.close()


def test_scene_library_restores_and_replays_pre_calibration_history(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-scenes.sqlite3"
    command = _create("create-legacy", _scene("legacy-vault"), expected_revision=0)
    connection = sqlite3.connect(database_path)
    store = SQLiteSceneLibrary(connection)
    created = store.execute(command)

    def strip_calibration(value: object) -> object:
        if isinstance(value, list):
            return [strip_calibration(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: strip_calibration(item) for key, item in value.items()}
        if result.get("schema_version") == "vtt.scene_map_metadata.v1":
            result.pop("calibration", None)
        return result

    row = connection.execute(
        "SELECT command_json, receipt_json FROM _vtt_scene_library_event_log"
    ).fetchone()
    assert row is not None
    legacy_command_json = json.dumps(
        strip_calibration(json.loads(row[0])),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    legacy_receipt_json = json.dumps(
        strip_calibration(json.loads(row[1])),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    connection.execute(
        "UPDATE _vtt_scene_library_event_log SET command_json = ?, receipt_json = ?",
        (legacy_command_json, legacy_receipt_json),
    )
    connection.commit()
    connection.close()

    restored_connection = sqlite3.connect(database_path)
    try:
        restored = SQLiteSceneLibrary(restored_connection)
        view = restored.snapshot("table-a")
        assert view.scenes[0].scene.map_metadata.calibration.topology == "square"
        replay = restored.execute(command)
        assert replay.replayed is True
        assert replay.receipt == created.receipt
        assert restored.revision("table-a") == 1
    finally:
        restored_connection.close()


def test_scene_library_does_not_treat_stripped_nonlegacy_calibration_as_legacy(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "stripped-hex-calibration.sqlite3"
    connection = sqlite3.connect(database_path)
    store = SQLiteSceneLibrary(connection)
    scene = SceneRecord(
        scene_id="hex-vault",
        map_metadata=SceneMapMetadata(
            name="Hex Vault",
            width_px=800,
            height_px=600,
            grid_size_px=80.0,
            gridless=False,
            calibration=BoardCalibration(
                topology="hex_flat",
                origin_x_px=100.0,
                origin_y_px=120.0,
                cell_extent_px=80.0,
                distance_ft=10.0,
            ),
        ),
    )
    store.execute(_create("create-hex", scene, expected_revision=0))
    row = connection.execute("SELECT command_json FROM _vtt_scene_library_event_log").fetchone()
    assert row is not None
    tampered = json.loads(row[0])
    tampered["scene"]["map_metadata"].pop("calibration")
    connection.execute(
        "UPDATE _vtt_scene_library_event_log SET command_json = ?",
        (
            json.dumps(
                tampered,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        ),
    )
    connection.commit()

    with pytest.raises(SceneLibraryStoreCorruptionError):
        store.snapshot("table-a")
    connection.close()
