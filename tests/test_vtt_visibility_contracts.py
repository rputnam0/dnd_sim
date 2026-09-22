from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from dnd_sim.vtt.visibility_contracts import (
    FOG_OPERATION_SCHEMA_VERSION,
    LIGHT_EMITTER_SCHEMA_VERSION,
    SCENE_ENVIRONMENT_SCHEMA_VERSION,
    SIGHT_BARRIER_SCHEMA_VERSION,
    TOKEN_VISION_SCHEMA_VERSION,
    FogOperation,
    LightEmitter,
    SceneEnvironment,
    SightBarrier,
    TokenVision,
    VisibilityPoint,
    VisibilityRecord,
    barrier_blocks_sight,
    barrier_blocks_movement,
    fog_reveals_point,
)


def _point(x_ft: float, y_ft: float) -> VisibilityPoint:
    return VisibilityPoint(x_ft=x_ft, y_ft=y_ft)


def test_visibility_records_are_strict_versioned_and_round_trip() -> None:
    records: tuple[VisibilityRecord, ...] = (
        SightBarrier(
            schema_version=SIGHT_BARRIER_SCHEMA_VERSION,
            record_type="barrier",
            record_id="west-wall",
            scene_id="echo-vault",
            start=_point(10.0, 0.0),
            end=_point(10.0, 30.0),
            behavior="wall",
            blocks_sight=True,
            blocks_movement=True,
            portal_state=None,
        ),
        LightEmitter(
            schema_version=LIGHT_EMITTER_SCHEMA_VERSION,
            record_type="light",
            record_id="vault-lantern",
            scene_id="echo-vault",
            origin=_point(15.0, 15.0),
            bright_radius_ft=20.0,
            dim_radius_ft=40.0,
            shape="circle",
            direction_degrees=0.0,
            angle_degrees=360.0,
            audience=("all",),
        ),
        SceneEnvironment(
            schema_version=SCENE_ENVIRONMENT_SCHEMA_VERSION,
            record_type="environment",
            record_id="scene-environment",
            scene_id="echo-vault",
            darkness="dim",
            shared_vision="owned_only",
        ),
        TokenVision(
            schema_version=TOKEN_VISION_SCHEMA_VERSION,
            record_type="token_vision",
            record_id="vela-vision",
            scene_id="echo-vault",
            token_id="vela-token",
            enabled=True,
            normal_range_ft=60.0,
            darkvision_range_ft=60.0,
            emitted_bright_radius_ft=0.0,
            emitted_dim_radius_ft=0.0,
        ),
        FogOperation(
            schema_version=FOG_OPERATION_SCHEMA_VERSION,
            record_type="fog_operation",
            record_id="reveal-entry",
            scene_id="echo-vault",
            operation_index=1,
            operation="reveal",
            polygon=(_point(0.0, 0.0), _point(20.0, 0.0), _point(0.0, 20.0)),
            inverse_of=None,
        ),
    )
    adapter = TypeAdapter(VisibilityRecord)

    for record in records:
        assert adapter.validate_json(adapter.dump_json(record)) == record
        with pytest.raises(ValidationError):
            adapter.validate_python({**record.model_dump(mode="json"), "secret": True})


@pytest.mark.parametrize(
    "payload",
    (
        {
            "behavior": "door",
            "portal_state": None,
            "blocks_sight": True,
            "blocks_movement": True,
        },
        {
            "behavior": "wall",
            "portal_state": "open",
            "blocks_sight": True,
            "blocks_movement": True,
        },
        {
            "behavior": "window",
            "portal_state": None,
            "blocks_sight": True,
            "blocks_movement": True,
        },
    ),
)
def test_barrier_contract_rejects_inconsistent_behavior(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SightBarrier(
            record_id="invalid",
            scene_id="echo-vault",
            start=_point(0.0, 0.0),
            end=_point(10.0, 0.0),
            **payload,
        )


def test_barrier_sight_intersection_handles_windows_and_door_state() -> None:
    closed_door = SightBarrier(
        record_id="door",
        scene_id="echo-vault",
        start=_point(10.0, 0.0),
        end=_point(10.0, 20.0),
        behavior="door",
        blocks_sight=True,
        blocks_movement=True,
        portal_state="closed",
    )
    ray_start = _point(0.0, 10.0)
    ray_end = _point(20.0, 10.0)

    assert barrier_blocks_sight(closed_door, ray_start, ray_end) is True
    assert (
        barrier_blocks_sight(
            closed_door.model_copy(update={"portal_state": "open"}),
            ray_start,
            ray_end,
        )
        is False
    )
    window = closed_door.model_copy(
        update={
            "behavior": "window",
            "portal_state": None,
            "blocks_sight": False,
        }
    )
    assert barrier_blocks_sight(window, ray_start, ray_end) is False
    assert barrier_blocks_sight(closed_door, _point(0.0, 30.0), _point(20.0, 30.0)) is False


def test_barrier_movement_intersection_honors_policy_and_open_doors() -> None:
    closed_door = SightBarrier(
        record_id="door",
        scene_id="echo-vault",
        start=_point(10.0, 0.0),
        end=_point(10.0, 20.0),
        behavior="door",
        blocks_sight=True,
        blocks_movement=True,
        portal_state="closed",
    )
    start = _point(0.0, 10.0)
    end = _point(20.0, 10.0)

    assert barrier_blocks_movement(closed_door, start, end) is True
    assert (
        barrier_blocks_movement(
            closed_door.model_copy(update={"portal_state": "open"}),
            start,
            end,
        )
        is False
    )
    assert (
        barrier_blocks_movement(
            closed_door.model_copy(update={"blocks_movement": False}),
            start,
            end,
        )
        is False
    )


def test_fog_fold_uses_latest_containing_operation_and_inverse_provenance() -> None:
    polygon = (_point(0.0, 0.0), _point(20.0, 0.0), _point(20.0, 20.0), _point(0.0, 20.0))
    operations = (
        FogOperation(
            record_id="reveal",
            scene_id="echo-vault",
            operation_index=1,
            operation="reveal",
            polygon=polygon,
        ),
        FogOperation(
            record_id="hide-again",
            scene_id="echo-vault",
            operation_index=2,
            operation="hide",
            polygon=(_point(5.0, 5.0), _point(15.0, 5.0), _point(10.0, 15.0)),
            inverse_of="reveal",
        ),
    )

    assert fog_reveals_point(operations, _point(2.0, 2.0)) is True
    assert fog_reveals_point(operations, _point(10.0, 8.0)) is False
    assert fog_reveals_point(operations, _point(30.0, 30.0)) is False


@pytest.mark.parametrize(
    "polygon",
    (
        (_point(0.0, 0.0), _point(1.0, 1.0), _point(2.0, 2.0)),
        (_point(0.0, 0.0), _point(10.0, 10.0), _point(0.0, 10.0), _point(10.0, 0.0)),
        (_point(0.0, 0.0), _point(10.0, 0.0), _point(0.0, 0.0)),
    ),
)
def test_fog_polygon_rejects_degenerate_or_self_intersecting_geometry(
    polygon: tuple[VisibilityPoint, ...],
) -> None:
    with pytest.raises(ValidationError):
        FogOperation(
            record_id="invalid-fog",
            scene_id="echo-vault",
            operation_index=1,
            operation="reveal",
            polygon=polygon,
        )
