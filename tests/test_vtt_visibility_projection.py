from __future__ import annotations

import dnd_sim.vtt.visibility_projection as visibility_projection
from pydantic import ValidationError
import pytest

from dnd_sim.vtt.active_board import ActiveBoardProjection
from dnd_sim.vtt.board_calibration import BoardCalibration
from dnd_sim.vtt.participants import (
    PARTICIPANT_SCHEMA_VERSION,
    ROSTER_SCHEMA_VERSION,
    TableParticipant,
    TableRoster,
)
from dnd_sim.vtt.scene import FeetPosition, SquareGridScene
from dnd_sim.vtt.scene_library_contracts import SceneMapMetadata
from dnd_sim.vtt.token_contracts import TokenPose, TokenRecord, TokenView
from dnd_sim.vtt.visibility_contracts import (
    FogOperation,
    LightEmitter,
    SceneEnvironment,
    SightBarrier,
    TokenVision,
    VisibilityCatalogView,
    VisibilityPoint,
)
from dnd_sim.vtt.visibility_projection import (
    VisibilityProjectionError,
    project_visibility,
)


def _point(x_ft: float, y_ft: float) -> VisibilityPoint:
    return VisibilityPoint(x_ft=x_ft, y_ft=y_ft)


def _participant(
    participant_id: str,
    *,
    actor_ids: tuple[str, ...] = (),
    role: str = "player",
) -> TableParticipant:
    return TableParticipant(
        schema_version=PARTICIPANT_SCHEMA_VERSION,
        participant_id=participant_id,
        display_name=participant_id.title(),
        role=role,
        owned_actor_ids=actor_ids,
    )


def _roster() -> TableRoster:
    return TableRoster(
        schema_version=ROSTER_SCHEMA_VERSION,
        table_id="table",
        participants=(
            _participant("gm", role="gm"),
            _participant("other", actor_ids=("other-actor",)),
            _participant("owner", actor_ids=("owner-actor",)),
        ),
    )


def _board() -> ActiveBoardProjection:
    calibration = BoardCalibration(
        topology="square",
        origin_x_px=5.0,
        origin_y_px=5.0,
        cell_extent_px=10.0,
        distance_ft=5.0,
    )
    metadata = SceneMapMetadata(
        name="Vault",
        width_px=40,
        height_px=40,
        grid_size_px=10.0,
        gridless=False,
        calibration=calibration,
    )
    return ActiveBoardProjection(
        scene_revision=3,
        scene=SquareGridScene(
            schema_version="vtt.scene.v1",
            scene_id="vault",
            name="Vault",
            cell_size_ft=5.0,
            columns=4,
            rows=4,
            origin_ft=FeetPosition(x_ft=0.0, y_ft=0.0, z_ft=0.0),
        ),
        map_metadata=metadata,
    )


def _token(
    token_id: str,
    x_ft: float,
    y_ft: float,
    *,
    actor_id: str | None = None,
    visibility: str = "public",
) -> TokenRecord:
    return TokenRecord(
        token_id=token_id,
        scene_id="vault",
        actor_id=actor_id,
        name=token_id.title(),
        pose=TokenPose(
            position_ft=FeetPosition(x_ft=x_ft, y_ft=y_ft, z_ft=0.0),
            width_ft=5.0,
            height_ft=5.0,
            rotation_degrees=0.0,
            layer=0,
        ),
        visibility=visibility,
        locked=False,
        nameplate="hover",
        show_hp_bar=False,
        aura_radius_ft=0.0,
        aura_color="#4DD7B3",
        condition_labels=(),
    )


def _environment(
    *, shared_vision: str = "owned_only", darkness: str = "bright"
) -> SceneEnvironment:
    return SceneEnvironment(
        record_id="scene-environment",
        scene_id="vault",
        darkness=darkness,
        shared_vision=shared_vision,
    )


def _vision(
    record_id: str,
    token_id: str,
    *,
    normal_range_ft: float = 100.0,
    darkvision_range_ft: float = 0.0,
) -> TokenVision:
    return TokenVision(
        record_id=record_id,
        scene_id="vault",
        token_id=token_id,
        enabled=True,
        normal_range_ft=normal_range_ft,
        darkvision_range_ft=darkvision_range_ft,
        emitted_bright_radius_ft=0.0,
        emitted_dim_radius_ft=0.0,
    )


def _reveal_all() -> FogOperation:
    return FogOperation(
        record_id="fog-1",
        scene_id="vault",
        operation_index=1,
        operation="reveal",
        polygon=(
            _point(0.0, 0.0),
            _point(20.0, 0.0),
            _point(20.0, 20.0),
            _point(0.0, 20.0),
        ),
    )


def _project(
    records: tuple[object, ...],
    tokens: tuple[TokenRecord, ...],
    *,
    participant: TableParticipant | None = None,
    max_samples: int = 16,
):
    return project_visibility(
        active_board=_board(),
        catalog=VisibilityCatalogView(
            table_id="table",
            scene_id="vault",
            revision=7,
            records=tuple(sorted(records, key=lambda record: record.record_id)),
        ),
        tokens=TokenView(
            table_id="table",
            scene_id="vault",
            revision=5,
            tokens=tuple(sorted(tokens, key=lambda token: token.token_id)),
        ),
        participant=participant or _roster().participant("owner"),
        roster=_roster(),
        encounter_revision=11,
        max_samples=max_samples,
    )


def test_projection_returns_only_opaque_mask_and_line_of_sight_tokens() -> None:
    owner = _token("owner", 2.5, 7.5, actor_id="owner-actor", visibility="owners")
    records = (
        _environment(),
        _vision("owner-vision", "owner"),
        _reveal_all(),
        SightBarrier(
            record_id="wall",
            scene_id="vault",
            start=_point(10.0, 0.0),
            end=_point(10.0, 20.0),
            behavior="wall",
            blocks_sight=True,
            blocks_movement=True,
        ),
    )
    projection = _project(
        records,
        (
            _token("behind-wall", 12.5, 7.5),
            _token("gm-secret", 7.5, 7.5, visibility="gm_only"),
            owner,
            _token("seen", 7.5, 7.5),
        ),
    )

    assert (projection.mask_width, projection.mask_height) == (4, 4)
    assert tuple((run.start, run.length) for run in projection.visible_runs) == (
        (0, 2),
        (4, 2),
        (8, 2),
        (12, 2),
    )
    assert tuple(token.token_id for token in projection.tokens) == ("owner", "seen")
    assert projection.scene_revision == 3
    assert projection.token_revision == 5
    assert projection.visibility_revision == 7
    assert projection.encounter_revision == 11
    encoded = projection.model_dump_json()
    for secret in ("wall", "gm-secret", "behind-wall", "owner-vision", "fog-1"):
        assert secret not in encoded


def test_projection_never_tests_movement_only_barriers_for_line_of_sight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _token("owner", 2.5, 7.5, actor_id="owner-actor", visibility="owners")
    movement_only = SightBarrier(
        record_id="movement-only",
        scene_id="vault",
        start=_point(10.0, 0.0),
        end=_point(10.0, 20.0),
        behavior="window",
        blocks_sight=False,
        blocks_movement=True,
    )

    def unexpected_sight_test(*_args: object, **_kwargs: object) -> bool:
        raise AssertionError("movement-only barriers must be pruned before rasterization")

    monkeypatch.setattr(
        visibility_projection,
        "barrier_blocks_sight",
        unexpected_sight_test,
    )

    projection = _project(
        (_environment(), _vision("owner-vision", "owner"), _reveal_all(), movement_only),
        (owner,),
    )

    assert sum(run.length for run in projection.visible_runs) == 16


def test_projection_rejects_combined_work_budget_before_sampling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _token("owner", 2.5, 7.5, actor_id="owner-actor", visibility="owners")
    fog = tuple(
        _reveal_all().model_copy(
            update={
                "record_id": f"fog-{index:03d}",
                "operation_index": index,
            }
        )
        for index in range(1, 101)
    )
    expected_work = 16 * (100 * 4 + 1)

    assert (
        visibility_projection._estimated_projection_work(  # noqa: SLF001
            sample_count=16,
            fog=fog,
            lights=(),
            token_lights=(),
            observers=(
                visibility_projection._Observer(_point(0.0, 0.0), 10.0, 0.0),
            ),  # noqa: SLF001
        )
        == expected_work
    )
    assert (
        visibility_projection._estimated_projection_work(  # noqa: SLF001
            sample_count=65_536,
            fog=fog,
            lights=(),
            token_lights=(),
            observers=(
                visibility_projection._Observer(_point(0.0, 0.0), 10.0, 0.0),
            ),  # noqa: SLF001
        )
        > visibility_projection.MAX_VISIBILITY_PROJECTION_WORK
    )
    one_light = LightEmitter(
        record_id="light",
        scene_id="vault",
        origin=_point(10.0, 10.0),
        bright_radius_ft=5.0,
        dim_radius_ft=10.0,
        shape="circle",
        direction_degrees=0.0,
        angle_degrees=360.0,
        audience=("role:player",),
    )
    assert (
        visibility_projection._estimated_projection_work(  # noqa: SLF001
            sample_count=65_536,
            fog=(),
            lights=(one_light,) * 500,
            token_lights=(),
            observers=(),
        )
        > visibility_projection.MAX_VISIBILITY_PROJECTION_WORK
    )

    monkeypatch.setattr(
        visibility_projection,
        "MAX_VISIBILITY_PROJECTION_WORK",
        expected_work - 1,
    )

    def unexpected_sample(*_args: object, **_kwargs: object) -> bool:
        raise AssertionError("over-budget projection must fail before sampling")

    monkeypatch.setattr(visibility_projection, "_point_is_visible", unexpected_sample)
    with pytest.raises(VisibilityProjectionError, match="work budget"):
        _project(
            (_environment(), _vision("owner-vision", "owner"), *fog),
            (owner,),
        )


def test_projection_open_door_changes_mask_without_exposing_door() -> None:
    owner = _token("owner", 2.5, 7.5, actor_id="owner-actor", visibility="owners")
    base = (
        _environment(),
        _vision("owner-vision", "owner"),
        _reveal_all(),
    )
    door = SightBarrier(
        record_id="door",
        scene_id="vault",
        start=_point(10.0, 0.0),
        end=_point(10.0, 20.0),
        behavior="door",
        blocks_sight=True,
        blocks_movement=True,
        portal_state="closed",
    )

    closed = _project((*base, door), (owner,))
    opened = _project((*base, door.model_copy(update={"portal_state": "open"})), (owner,))

    assert sum(run.length for run in closed.visible_runs) == 8
    assert opened.visible_runs[0].start == 0
    assert sum(run.length for run in opened.visible_runs) == 16
    assert "door" not in opened.model_dump_json()


def test_darkness_requires_darkvision_or_audience_applicable_light() -> None:
    owner = _token("owner", 2.5, 7.5, actor_id="owner-actor", visibility="owners")
    dark = (_environment(darkness="darkness"), _reveal_all())
    no_darkvision = _project((*dark, _vision("owner-vision", "owner")), (owner,))
    with_darkvision = _project(
        (*dark, _vision("owner-vision", "owner", darkvision_range_ft=6.0)),
        (owner,),
    )
    private_light = LightEmitter(
        record_id="private-light",
        scene_id="vault",
        origin=_point(12.5, 7.5),
        bright_radius_ft=5.0,
        dim_radius_ft=7.0,
        shape="circle",
        direction_degrees=0.0,
        angle_degrees=360.0,
        audience=("participant:other",),
    )
    public_light = private_light.model_copy(
        update={"record_id": "public-light", "audience": ("all",)}
    )
    ignored_light = _project(
        (*dark, _vision("owner-vision", "owner"), private_light),
        (owner,),
    )
    lit = _project(
        (*dark, _vision("owner-vision", "owner"), public_light),
        (owner,),
    )

    assert sum(run.length for run in no_darkvision.visible_runs) == 0
    assert sum(run.length for run in with_darkvision.visible_runs) > 0
    assert sum(run.length for run in ignored_light.visible_runs) == 0
    assert sum(run.length for run in lit.visible_runs) > 0


def test_party_shared_vision_unions_player_observers_without_leaking_token() -> None:
    owner = _token("owner", 2.5, 2.5, actor_id="owner-actor", visibility="owners")
    other = _token("other", 17.5, 17.5, actor_id="other-actor", visibility="owners")
    records = (
        _environment(shared_vision="owned_only"),
        _reveal_all(),
        _vision("other-vision", "other", normal_range_ft=4.0),
        _vision("owner-vision", "owner", normal_range_ft=4.0),
    )
    owned = _project(records, (other, owner))
    party = _project(
        (
            *tuple(record for record in records if not isinstance(record, SceneEnvironment)),
            _environment(shared_vision="party"),
        ),
        (other, owner),
    )

    assert sum(run.length for run in party.visible_runs) > sum(
        run.length for run in owned.visible_runs
    )
    assert 'other"' not in party.model_dump_json()


def test_projection_fails_closed_without_environment_and_enforces_sample_budget() -> None:
    owner = _token("owner", 2.5, 2.5, actor_id="owner-actor", visibility="owners")
    with pytest.raises(VisibilityProjectionError):
        _project((_vision("owner-vision", "owner"), _reveal_all()), (owner,))

    projection = _project(
        (_environment(), _vision("owner-vision", "owner"), _reveal_all()),
        (owner,),
        max_samples=7,
    )
    assert projection.mask_width * projection.mask_height <= 7
    with pytest.raises((ValueError, ValidationError)):
        _project(
            (_environment(), _vision("owner-vision", "owner"), _reveal_all()),
            (owner,),
            max_samples=65_537,
        )
