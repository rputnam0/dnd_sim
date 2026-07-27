from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

from dnd_sim.models import ActorRuntimeState
from dnd_sim.vtt import (
    SCENE_PROJECTION_SCHEMA_VERSION,
    SCENE_SCHEMA_VERSION,
    FeetPosition,
    GridCell,
    GridPixelTransform,
    PixelPoint,
    SceneToken,
    SquareGridScene,
    project_scene,
)


def _scene() -> SquareGridScene:
    return SquareGridScene(
        schema_version=SCENE_SCHEMA_VERSION,
        scene_id="training-room",
        name="Training Room",
        cell_size_ft=5.0,
        columns=4,
        rows=3,
        origin_ft=FeetPosition(x_ft=-10.0, y_ft=5.0, z_ft=0.0),
    )


def _actor(
    actor_id: str,
    *,
    position: tuple[float, float, float],
    conditions: set[str] | None = None,
) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team="party" if actor_id == "alpha" else "enemy",
        name=actor_id.title(),
        max_hp=30,
        hp=21,
        temp_hp=7,
        ac=17,
        initiative_mod=3,
        str_mod=1,
        dex_mod=3,
        con_mod=2,
        int_mod=0,
        wis_mod=1,
        cha_mod=-1,
        save_mods={"str": 1, "dex": 3, "con": 2, "int": 0, "wis": 1, "cha": -1},
        actions=[],
        position=position,
        conditions=set(conditions or set()),
        resources={"spell_slot_1": 3},
        traits={"dm_only": {"secret": True}},
        hidden=True,
        detected_by={"gm"},
    )


def test_square_grid_scene_is_strict_and_versioned() -> None:
    scene = _scene()

    assert scene.schema_version == "vtt.scene.v1"
    assert scene.grid_type == "square"
    assert SquareGridScene(
        schema_version=SCENE_SCHEMA_VERSION,
        scene_id="zero-origin",
        name="Zero Origin",
        cell_size_ft=5.0,
        columns=1,
        rows=1,
    ).origin_ft == FeetPosition(x_ft=0.0, y_ft=0.0, z_ft=0.0)

    with pytest.raises(ValidationError):
        SquareGridScene.model_validate({**scene.model_dump(), "schema_version": "vtt.scene.v0"})
    with pytest.raises(ValidationError):
        SquareGridScene.model_validate({**scene.model_dump(), "grid_type": "hex"})
    with pytest.raises(ValidationError):
        SquareGridScene.model_validate({**scene.model_dump(), "columns": True})
    with pytest.raises(ValidationError):
        SquareGridScene.model_validate({**scene.model_dump(), "unknown": "field"})


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("cell_size_ft", 0.0),
        ("cell_size_ft", math.inf),
        ("columns", 0),
        ("rows", -1),
    ],
)
def test_square_grid_scene_rejects_invalid_dimensions(
    field_name: str, invalid_value: float | int
) -> None:
    payload = _scene().model_dump()
    payload[field_name] = invalid_value

    with pytest.raises(ValidationError):
        SquareGridScene.model_validate(payload)


def test_feet_and_grid_cell_conversion_is_deterministic_and_bounded() -> None:
    scene = _scene()

    assert scene.feet_to_grid_cell(FeetPosition(x_ft=-10.0, y_ft=5.0, z_ft=-100.0)) == GridCell(
        column=0, row=0
    )
    assert scene.feet_to_grid_cell(FeetPosition(x_ft=-5.0001, y_ft=9.9999, z_ft=100.0)) == GridCell(
        column=0, row=0
    )
    assert scene.feet_to_grid_cell(FeetPosition(x_ft=-5.0, y_ft=10.0, z_ft=0.0)) == GridCell(
        column=1, row=1
    )
    assert scene.grid_cell_to_feet(GridCell(column=2, row=1), z_ft=7.5) == FeetPosition(
        x_ft=2.5, y_ft=12.5, z_ft=7.5
    )

    for position in (
        FeetPosition(x_ft=-10.0001, y_ft=5.0, z_ft=0.0),
        FeetPosition(x_ft=10.0, y_ft=5.0, z_ft=0.0),
        FeetPosition(x_ft=-10.0, y_ft=20.0, z_ft=0.0),
    ):
        with pytest.raises(ValueError, match="outside scene bounds"):
            scene.feet_to_grid_cell(position)

    with pytest.raises(ValueError, match="outside scene bounds"):
        scene.grid_cell_to_feet(GridCell(column=4, row=0))
    with pytest.raises(ValidationError):
        FeetPosition(x_ft=math.nan, y_ft=0.0, z_ft=0.0)


def test_pixel_transform_is_presentation_only_configurable_and_bounded() -> None:
    scene = _scene()
    transform = GridPixelTransform(
        origin_x_px=-32.0,
        origin_y_px=48.0,
        pixels_per_cell=64.0,
    )
    cell = GridCell(column=2, row=1)

    pixel = transform.grid_cell_to_pixel(cell, scene=scene)

    assert pixel == PixelPoint(x_px=128.0, y_px=144.0)
    assert transform.pixel_to_grid_cell(pixel, scene=scene) == cell
    assert "pixel" not in json.dumps(scene.model_dump(mode="json"))

    with pytest.raises(ValueError, match="outside scene bounds"):
        transform.pixel_to_grid_cell(PixelPoint(x_px=-32.001, y_px=48.0), scene=scene)
    with pytest.raises(ValueError, match="outside scene bounds"):
        transform.pixel_to_grid_cell(PixelPoint(x_px=224.0, y_px=48.0), scene=scene)
    with pytest.raises(ValidationError):
        GridPixelTransform(origin_x_px=0.0, origin_y_px=0.0, pixels_per_cell=math.inf)


def test_scene_projection_is_allowlisted_sorted_and_json_safe() -> None:
    scene = _scene()
    zeta = _actor(
        "zeta",
        position=(5.0, 15.0, 0.0),
        conditions={"prone", "blinded"},
    )
    alpha = _actor("alpha", position=(-7.5, 7.5, 0.0), conditions={"invisible"})

    projection = project_scene(scene, {"zeta": zeta, "alpha": alpha})
    reversed_projection = project_scene(scene, {"alpha": alpha, "zeta": zeta})
    payload = projection.model_dump(mode="json")

    assert projection.schema_version == SCENE_PROJECTION_SCHEMA_VERSION
    assert [token.actor_id for token in projection.tokens] == ["alpha", "zeta"]
    assert projection.tokens[1].conditions == ("blinded", "prone")
    assert set(payload) == {"schema_version", "scene_id", "tokens"}
    assert set(payload["tokens"][0]) == {
        "actor_id",
        "team",
        "name",
        "position_ft",
        "hp",
        "max_hp",
        "conditions",
    }
    encoded = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
    assert encoded == json.dumps(
        reversed_projection.model_dump(mode="json"),
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    token_keys = set().union(*(token.keys() for token in payload["tokens"]))
    for forbidden in (
        "resources",
        "traits",
        "hidden",
        "detected_by",
        "actions",
        "temp_hp",
        "ac",
    ):
        assert forbidden not in token_keys


def test_projection_enforces_actor_identity_and_scene_bounds() -> None:
    scene = _scene()
    actor = _actor("alpha", position=(-7.5, 7.5, 0.0))

    with pytest.raises(ValueError, match="actor identity"):
        project_scene(scene, {"different-key": actor})

    actor.position = (10.0, 5.0, 0.0)
    with pytest.raises(ValueError, match="outside scene bounds"):
        project_scene(scene, {"alpha": actor})

    actor.position = (math.nan, 5.0, 0.0)
    with pytest.raises(ValidationError):
        project_scene(scene, {"alpha": actor})


def test_scene_token_contract_rejects_hidden_or_unversioned_fields() -> None:
    payload = {
        "actor_id": "alpha",
        "team": "party",
        "name": "Alpha",
        "position_ft": {"x_ft": 0.0, "y_ft": 0.0, "z_ft": 0.0},
        "hp": 20,
        "max_hp": 30,
        "conditions": (),
    }

    assert SceneToken.model_validate(payload).actor_id == "alpha"
    with pytest.raises(ValidationError):
        SceneToken.model_validate({**payload, "resources": {"spell_slot_1": 3}})
