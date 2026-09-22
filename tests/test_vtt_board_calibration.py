from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from dnd_sim.vtt.board_calibration import (
    BOARD_CALIBRATION_SCHEMA_VERSION,
    AxialHexCell,
    BoardCalibration,
    SquareBoardCell,
    ViewPoint,
)
from dnd_sim.vtt.scene import FeetPosition


@pytest.mark.parametrize("topology", ("square", "hex_flat", "hex_pointy"))
def test_calibrated_cell_centers_round_trip_in_pixels_and_feet(topology: str) -> None:
    calibration = BoardCalibration(
        schema_version=BOARD_CALIBRATION_SCHEMA_VERSION,
        topology=topology,
        origin_x_px=410.25,
        origin_y_px=305.75,
        cell_extent_px=72.0,
        distance_ft=5.0,
    )
    cells = (
        (SquareBoardCell(column=0, row=0), SquareBoardCell(column=3, row=-2))
        if topology == "square"
        else (AxialHexCell(q=0, r=0), AxialHexCell(q=3, r=-2))
    )

    for cell in cells:
        pixel = calibration.cell_to_pixel(cell)
        assert calibration.pixel_to_cell(pixel) == cell
        feet = calibration.cell_to_feet(
            cell,
            origin_ft=FeetPosition(x_ft=-10.0, y_ft=15.0, z_ft=2.0),
        )
        assert (
            calibration.feet_to_cell(
                feet,
                origin_ft=FeetPosition(x_ft=-10.0, y_ft=15.0, z_ft=2.0),
            )
            == cell
        )


@pytest.mark.parametrize("topology", ("hex_flat", "hex_pointy"))
def test_hex_neighbors_and_cube_distance_are_deterministic(topology: str) -> None:
    calibration = BoardCalibration(
        topology=topology,
        origin_x_px=500.0,
        origin_y_px=400.0,
        cell_extent_px=80.0,
        distance_ft=5.0,
    )
    origin = AxialHexCell(q=-2, r=3)
    neighbors = calibration.neighbors(origin)

    assert neighbors == (
        AxialHexCell(q=-1, r=3),
        AxialHexCell(q=-1, r=2),
        AxialHexCell(q=-2, r=2),
        AxialHexCell(q=-3, r=3),
        AxialHexCell(q=-3, r=4),
        AxialHexCell(q=-2, r=4),
    )
    assert all(calibration.cell_distance_ft(origin, neighbor) == 5.0 for neighbor in neighbors)
    distant = AxialHexCell(q=4, r=-1)
    assert calibration.cell_distance_ft(origin, distant) == 30.0
    assert calibration.cell_distance_ft(distant, origin) == 30.0


def test_gridless_calibration_measures_without_exposing_cells() -> None:
    calibration = BoardCalibration(
        topology="gridless",
        origin_x_px=20.0,
        origin_y_px=30.0,
        cell_extent_px=40.0,
        distance_ft=5.0,
    )

    assert (
        calibration.pixel_distance_ft(
            ViewPoint(x_px=20.0, y_px=30.0),
            ViewPoint(x_px=44.0, y_px=62.0),
        )
        == 5.0
    )
    with pytest.raises(ValueError, match="gridless"):
        calibration.pixel_to_cell(ViewPoint(x_px=20.0, y_px=30.0))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("origin_x_px", math.inf),
        ("origin_y_px", math.nan),
        ("cell_extent_px", 0.0),
        ("cell_extent_px", 100_001.0),
        ("distance_ft", -1.0),
    ),
)
def test_calibration_contract_rejects_degenerate_or_unbounded_numbers(
    field: str,
    value: float,
) -> None:
    payload = {
        "schema_version": BOARD_CALIBRATION_SCHEMA_VERSION,
        "topology": "square",
        "origin_x_px": 100.0,
        "origin_y_px": 100.0,
        "cell_extent_px": 50.0,
        "distance_ft": 5.0,
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        BoardCalibration.model_validate(payload)


def test_map_bounds_require_a_complete_cell_or_valid_gridless_origin() -> None:
    square = BoardCalibration(
        topology="square",
        origin_x_px=-25.0,
        origin_y_px=-25.0,
        cell_extent_px=50.0,
        distance_ft=5.0,
    )
    square.require_usable_map(width_px=200, height_px=150)
    with pytest.raises(ValueError, match="complete usable cell"):
        square.model_copy(update={"cell_extent_px": 500.0}).require_usable_map(
            width_px=200,
            height_px=150,
        )

    gridless = BoardCalibration(
        topology="gridless",
        origin_x_px=10.0,
        origin_y_px=10.0,
        cell_extent_px=50.0,
        distance_ft=5.0,
    )
    gridless.require_usable_map(width_px=200, height_px=150)
    with pytest.raises(ValueError, match="origin"):
        gridless.model_copy(update={"origin_x_px": 250.0}).require_usable_map(
            width_px=200,
            height_px=150,
        )


def test_pixel_ties_are_stable_and_codec_forbids_extra_fields() -> None:
    calibration = BoardCalibration(
        topology="hex_pointy",
        origin_x_px=0.0,
        origin_y_px=0.0,
        cell_extent_px=60.0,
        distance_ft=5.0,
    )
    between_q_cells = ViewPoint(x_px=30.0, y_px=0.0)
    assert calibration.pixel_to_cell(between_q_cells) == AxialHexCell(q=1, r=0)
    assert BoardCalibration.model_validate_json(calibration.model_dump_json()) == calibration
    with pytest.raises(ValidationError):
        BoardCalibration.model_validate({**calibration.model_dump(), "grid_color": "#fff"})
