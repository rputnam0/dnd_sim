from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import dnd_sim.vtt.visibility_store as visibility_store_module
from dnd_sim.vtt.visibility_contracts import (
    FogOperation,
    SceneEnvironment,
    SightBarrier,
    TokenVision,
    VisibilityDeleteCommand,
    VisibilityDoorStateCommand,
    VisibilityFogUndoCommand,
    VisibilityPoint,
    VisibilityPutCommand,
)
from dnd_sim.vtt.visibility_store import (
    SQLiteVisibilityStore,
    VisibilityCommandConflictError,
    VisibilityLimitError,
    VisibilityRecordConflictError,
    VisibilityRecordNotFoundError,
    VisibilityRevisionConflictError,
    VisibilityStoreCorruptionError,
)


def _point(x_ft: float, y_ft: float) -> VisibilityPoint:
    return VisibilityPoint(x_ft=x_ft, y_ft=y_ft)


def _barrier(
    record_id: str,
    *,
    behavior: str = "wall",
    portal_state: str | None = None,
) -> SightBarrier:
    return SightBarrier(
        record_id=record_id,
        scene_id="vault",
        start=_point(0.0, 0.0),
        end=_point(0.0, 20.0),
        behavior=behavior,
        blocks_sight=True,
        blocks_movement=True,
        portal_state=portal_state,
    )


def _fog(
    record_id: str,
    operation_index: int,
    *,
    operation: str = "reveal",
) -> FogOperation:
    return FogOperation(
        record_id=record_id,
        scene_id="vault",
        operation_index=operation_index,
        operation=operation,
        polygon=(
            _point(0.0, 0.0),
            _point(10.0, 0.0),
            _point(10.0, 10.0),
            _point(0.0, 10.0),
        ),
    )


def _put(
    command_id: str,
    expected_revision: int,
    record: SceneEnvironment | SightBarrier | FogOperation,
) -> VisibilityPutCommand:
    return VisibilityPutCommand(
        table_id="table",
        command_id=command_id,
        expected_revision=expected_revision,
        record=record,
    )


def test_visibility_store_replays_restart_safe_door_and_fog_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "visibility.sqlite3"
    connection = sqlite3.connect(database)
    store = SQLiteVisibilityStore(connection)
    environment = SceneEnvironment(
        record_id="scene-environment",
        scene_id="vault",
        darkness="darkness",
        shared_vision="owned_only",
    )

    assert store.execute(_put("environment", 0, environment)).receipt.revision == 1
    store.execute(_put("wall", 1, _barrier("wall-a")))
    store.execute(
        _put(
            "door",
            2,
            _barrier("door-a", behavior="door", portal_state="closed"),
        )
    )
    store.execute(_put("fog", 3, _fog("fog-1", 1)))
    door_result = store.execute(
        VisibilityDoorStateCommand(
            table_id="table",
            command_id="open-door",
            expected_revision=4,
            scene_id="vault",
            barrier_id="door-a",
            portal_state="open",
        )
    )
    undo_result = store.execute(
        VisibilityFogUndoCommand(
            table_id="table",
            command_id="undo-fog",
            expected_revision=5,
            scene_id="vault",
            target_record_id="fog-1",
            inverse_record_id="fog-2",
        )
    )
    store.execute(
        VisibilityDeleteCommand(
            table_id="table",
            command_id="delete-wall",
            expected_revision=6,
            scene_id="vault",
            record_id="wall-a",
        )
    )

    snapshot = store.snapshot("table", "vault")
    assert snapshot.revision == 7
    assert tuple(record.record_id for record in snapshot.records) == (
        "door-a",
        "fog-1",
        "fog-2",
        "scene-environment",
    )
    door = next(record for record in snapshot.records if record.record_id == "door-a")
    assert isinstance(door, SightBarrier)
    assert door.portal_state == "open"
    fog = tuple(record for record in snapshot.records if isinstance(record, FogOperation))
    assert tuple(operation.operation_index for operation in fog) == (1, 2)
    assert fog[1].operation == "hide"
    assert fog[1].inverse_of == "fog-1"
    assert door_result.receipt.event.operation == "set_door_state"
    assert undo_result.receipt.event.operation == "undo_fog"
    assert tuple(event.sequence for event in store.events_after("table", 4)) == (5, 6, 7)

    connection.close()
    reopened_connection = sqlite3.connect(database)
    reopened = SQLiteVisibilityStore(reopened_connection)
    try:
        assert reopened.snapshot("table", "vault") == snapshot
        assert reopened.revision("table") == 7
        assert reopened.events_after("table", 0)[-1].operation == "delete"
    finally:
        reopened_connection.close()


def test_visibility_store_exact_replay_and_conflicts_do_not_mutate() -> None:
    connection = sqlite3.connect(":memory:")
    store = SQLiteVisibilityStore(connection)
    command = _put("wall", 0, _barrier("wall-a"))
    first = store.execute(command)
    before = store.snapshot("table", "vault")

    assert store.replay(command) is not None
    assert store.replay(_put("unknown", 1, _barrier("wall-b"))) is None
    replay = store.execute(command)
    assert replay.replayed is True
    assert replay.receipt == first.receipt
    assert store.snapshot("table", "vault") == before

    with pytest.raises(VisibilityCommandConflictError):
        store.execute(_put("wall", 1, _barrier("wall-b")))
    with pytest.raises(VisibilityRevisionConflictError) as stale:
        store.execute(_put("stale", 0, _barrier("wall-b")))
    assert stale.value.current_revision == 1
    assert stale.value.expected_revision == 0
    assert store.snapshot("table", "vault") == before
    assert store.events_after("table", 0) == (first.receipt.event,)


def test_visibility_store_allows_only_one_vision_record_per_token() -> None:
    connection = sqlite3.connect(":memory:")
    store = SQLiteVisibilityStore(connection)

    def vision(record_id: str) -> TokenVision:
        return TokenVision(
            record_id=record_id,
            scene_id="vault",
            token_id="owner-token",
            enabled=True,
            normal_range_ft=60.0,
            darkvision_range_ft=0.0,
            emitted_bright_radius_ft=0.0,
            emitted_dim_radius_ft=0.0,
        )

    store.execute(
        VisibilityPutCommand(
            table_id="table",
            command_id="first-vision",
            expected_revision=0,
            record=vision("vision-a"),
        )
    )
    with pytest.raises(VisibilityRecordConflictError):
        store.execute(
            VisibilityPutCommand(
                table_id="table",
                command_id="second-vision",
                expected_revision=1,
                record=vision("vision-b"),
            )
        )
    assert store.revision("table") == 1


def test_visibility_store_enforces_append_only_fog_and_record_types() -> None:
    connection = sqlite3.connect(":memory:")
    store = SQLiteVisibilityStore(connection)
    store.execute(_put("fog", 0, _fog("fog-1", 1)))

    for command in (
        _put("gap", 1, _fog("fog-3", 3)),
        _put("replace", 1, _fog("fog-1", 2)),
        VisibilityDeleteCommand(
            table_id="table",
            command_id="delete-fog",
            expected_revision=1,
            scene_id="vault",
            record_id="fog-1",
        ),
        _put("type-change", 1, _barrier("fog-1")),
    ):
        with pytest.raises(VisibilityRecordConflictError):
            store.execute(command)
        assert store.revision("table") == 1


def test_visibility_store_rejects_missing_or_redundant_door_changes() -> None:
    connection = sqlite3.connect(":memory:")
    store = SQLiteVisibilityStore(connection)
    missing = VisibilityDoorStateCommand(
        table_id="table",
        command_id="missing",
        expected_revision=0,
        scene_id="vault",
        barrier_id="door-a",
        portal_state="open",
    )
    with pytest.raises(VisibilityRecordNotFoundError):
        store.execute(missing)
    store.execute(_put("door", 0, _barrier("door-a", behavior="door", portal_state="closed")))
    with pytest.raises(VisibilityRecordConflictError):
        store.execute(
            missing.model_copy(
                update={
                    "command_id": "already-closed",
                    "expected_revision": 1,
                    "portal_state": "closed",
                }
            )
        )
    assert store.revision("table") == 1


def test_visibility_store_enforces_bounded_scene_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(visibility_store_module, "MAX_BARRIERS_PER_SCENE", 1)
    connection = sqlite3.connect(":memory:")
    store = SQLiteVisibilityStore(connection)
    store.execute(_put("wall-a", 0, _barrier("wall-a")))

    with pytest.raises(VisibilityLimitError):
        store.execute(_put("wall-b", 1, _barrier("wall-b")))
    assert store.revision("table") == 1
    assert tuple(record.record_id for record in store.snapshot("table", "vault").records) == (
        "wall-a",
    )


def test_visibility_store_detects_corrupt_canonical_history() -> None:
    connection = sqlite3.connect(":memory:")
    store = SQLiteVisibilityStore(connection)
    store.execute(_put("wall", 0, _barrier("wall-a")))
    connection.execute(
        "UPDATE _vtt_visibility_event_log SET command_json = ?",
        ('{"broken":true}',),
    )
    connection.commit()

    with pytest.raises(VisibilityStoreCorruptionError):
        store.snapshot("table", "vault")
