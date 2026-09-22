from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

from dnd_sim.vtt.annotations import (
    ANNOTATION_SCHEMA_VERSION,
    MAX_ABSOLUTE_COORDINATE_FT,
    MAX_RULER_WAYPOINTS,
    MAX_DRAWING_PATH_POINTS,
    AnnotationBounds,
    AnnotationPoint,
    ArrowDrawingAnnotation,
    CircleTemplateAnnotation,
    ConeTemplateAnnotation,
    CubeTemplateAnnotation,
    DrawingStyle,
    FreehandDrawingAnnotation,
    LineTemplateAnnotation,
    PingAnnotation,
    RulerAnnotation,
    ShapeDrawingAnnotation,
    TextDrawingAnnotation,
    annotation_bounds_ft,
    chebyshev_distance_ft,
    parse_annotation,
    parse_annotation_json,
    project_annotations,
)


def _base(
    annotation_id: str,
    *,
    scene_id: str = "scene-1",
    audience: tuple[str, ...] | list[str] = ("all",),
) -> dict[str, object]:
    return {
        "schema_version": ANNOTATION_SCHEMA_VERSION,
        "annotation_id": annotation_id,
        "scene_id": scene_id,
        "author_id": "player-1",
        "audience": audience,
    }


def _point(x: float, y: float, z: float = 0.0) -> AnnotationPoint:
    return AnnotationPoint(x_ft=x, y_ft=y, z_ft=z)


def _style() -> DrawingStyle:
    return DrawingStyle(
        stroke_color="#2f6fed",
        fill_color="#dbe7ff",
        opacity=0.75,
        stroke_width_ft=1.0,
        line_style="solid",
    )


def _annotations():
    return (
        RulerAnnotation(
            **_base("ruler-1"),
            annotation_type="ruler",
            waypoints=(_point(0.0, 0.0), _point(15.0, 10.0)),
        ),
        PingAnnotation(
            **_base("ping-1"),
            annotation_type="ping",
            position=_point(5.0, 5.0),
            duration_ms=1_500,
        ),
        CircleTemplateAnnotation(
            **_base("circle-1"),
            annotation_type="circle_template",
            center=_point(10.0, 10.0),
            radius_ft=5.0,
        ),
        ConeTemplateAnnotation(
            **_base("cone-1"),
            annotation_type="cone_template",
            origin=_point(0.0, 0.0),
            direction_degrees=0.0,
            length_ft=10.0,
            angle_degrees=90.0,
        ),
        LineTemplateAnnotation(
            **_base("line-1"),
            annotation_type="line_template",
            start=_point(0.0, 0.0),
            end=_point(10.0, 0.0),
            width_ft=4.0,
        ),
        CubeTemplateAnnotation(
            **_base("cube-1"),
            annotation_type="cube_template",
            center=_point(10.0, 10.0, 5.0),
            size_ft=4.0,
        ),
        FreehandDrawingAnnotation(
            **_base("freehand-1"),
            annotation_type="freehand_drawing",
            layer="over_tokens",
            locked=False,
            style=_style(),
            points=(_point(1.0, 1.0), _point(4.0, 3.0), _point(8.0, 4.0)),
        ),
        ShapeDrawingAnnotation(
            **_base("shape-1"),
            annotation_type="shape_drawing",
            layer="under_tokens",
            locked=True,
            style=_style(),
            shape="ellipse",
            corner_a=_point(2.0, 3.0),
            corner_b=_point(12.0, 9.0),
        ),
        ArrowDrawingAnnotation(
            **_base("arrow-1"),
            annotation_type="arrow_drawing",
            layer="over_tokens",
            locked=False,
            style=_style(),
            start=_point(3.0, 4.0),
            end=_point(13.0, 14.0),
            head_size_ft=2.0,
        ),
        TextDrawingAnnotation(
            **_base("text-1"),
            annotation_type="text_drawing",
            layer="under_tokens",
            locked=False,
            style=_style(),
            anchor=_point(6.0, 7.0),
            text="Door seals\nwhen the bell rings <script>",
            font_size_ft=2.0,
            background_color="#101828",
        ),
    )


def test_drawing_contracts_round_trip_bounded_style_layers_and_plain_text() -> None:
    drawings = _annotations()[-4:]

    for drawing in drawings:
        assert parse_annotation_json(drawing.model_dump_json()) == drawing
        assert parse_annotation(drawing.model_dump(mode="json")) == drawing

    text = drawings[-1]
    assert text.text.endswith("<script>")
    assert text.layer == "under_tokens"
    assert text.style.opacity == 0.75


def test_drawing_contracts_reject_unsafe_style_text_and_unbounded_paths() -> None:
    with pytest.raises(ValidationError, match="lowercase"):
        _style().model_copy(update={"stroke_color": "#ABCDEF"}).model_validate(
            _style().model_copy(update={"stroke_color": "#ABCDEF"}).model_dump()
        )
    with pytest.raises(ValidationError, match="control"):
        TextDrawingAnnotation(
            **_base("bad-text"),
            annotation_type="text_drawing",
            layer="over_tokens",
            locked=False,
            style=_style(),
            anchor=_point(1.0, 1.0),
            text="hidden\x00payload",
            font_size_ft=2.0,
            background_color=None,
        )
    with pytest.raises(ValidationError, match="at most"):
        FreehandDrawingAnnotation(
            **_base("too-long"),
            annotation_type="freehand_drawing",
            layer="over_tokens",
            locked=False,
            style=_style(),
            points=tuple(
                _point(float(index), float(index % 2))
                for index in range(MAX_DRAWING_PATH_POINTS + 1)
            ),
        )
    with pytest.raises(ValidationError, match="unique"):
        FreehandDrawingAnnotation(
            **_base("duplicate-path"),
            annotation_type="freehand_drawing",
            layer="over_tokens",
            locked=False,
            style=_style(),
            points=(_point(1.0, 1.0), _point(1.0, 1.0)),
        )


def test_drawing_geometry_is_planar_nondegenerate_and_has_bounded_feet_extent() -> None:
    style = _style()
    freehand = FreehandDrawingAnnotation(
        **_base("freehand-bounds"),
        annotation_type="freehand_drawing",
        layer="over_tokens",
        locked=False,
        style=style,
        points=(_point(1.0, 2.0), _point(4.0, 8.0)),
    )
    arrow = ArrowDrawingAnnotation(
        **_base("arrow-bounds"),
        annotation_type="arrow_drawing",
        layer="over_tokens",
        locked=False,
        style=style,
        start=_point(5.0, 5.0),
        end=_point(10.0, 10.0),
        head_size_ft=2.0,
    )

    assert annotation_bounds_ft(freehand) == AnnotationBounds(
        min_x_ft=0.5,
        max_x_ft=4.5,
        min_y_ft=1.5,
        max_y_ft=8.5,
        min_z_ft=0.0,
        max_z_ft=0.0,
    )
    assert annotation_bounds_ft(arrow) == AnnotationBounds(
        min_x_ft=3.0,
        max_x_ft=12.0,
        min_y_ft=3.0,
        max_y_ft=12.0,
        min_z_ft=0.0,
        max_z_ft=0.0,
    )
    with pytest.raises(ValidationError, match="opposite corners"):
        ShapeDrawingAnnotation(
            **_base("flat-shape"),
            annotation_type="shape_drawing",
            layer="under_tokens",
            locked=False,
            style=style,
            shape="rectangle",
            corner_a=_point(1.0, 1.0),
            corner_b=_point(1.0, 4.0),
        )
    with pytest.raises(ValidationError, match="distinct"):
        ArrowDrawingAnnotation(
            **_base("zero-arrow"),
            annotation_type="arrow_drawing",
            layer="over_tokens",
            locked=False,
            style=style,
            start=_point(1.0, 1.0),
            end=_point(1.0, 1.0),
            head_size_ft=2.0,
        )
    with pytest.raises(ValidationError, match="unique"):
        FreehandDrawingAnnotation(
            **_base("looping-freehand"),
            annotation_type="freehand_drawing",
            layer="under_tokens",
            locked=False,
            style=style,
            points=(
                _point(1.0, 1.0),
                _point(4.0, 4.0),
                _point(1.0, 1.0),
            ),
        )


def test_ruler_computes_ordered_5e_chebyshev_segments_and_total() -> None:
    ruler = RulerAnnotation(
        **_base("ruler-distance"),
        annotation_type="ruler",
        waypoints=(
            _point(0.0, 0.0, 0.0),
            _point(15.0, 10.0, 5.0),
            _point(20.0, 30.0, 5.0),
        ),
    )

    assert chebyshev_distance_ft(ruler.waypoints[0], ruler.waypoints[1]) == 15.0
    assert ruler.segment_distances_ft == (15.0, 20.0)
    assert ruler.total_distance_ft == 35.0
    assert ruler.model_dump(mode="json")["segment_distances_ft"] == [15.0, 20.0]

    with pytest.raises(ValidationError, match="frozen"):
        ruler.total_distance_ft = 99.0


def test_ruler_rejects_spoofed_computed_distances_and_invalid_waypoints() -> None:
    ruler = RulerAnnotation(
        **_base("ruler-source"),
        annotation_type="ruler",
        waypoints=(_point(0.0, 0.0), _point(5.0, 5.0)),
    )
    payload = ruler.model_dump(mode="json")

    with pytest.raises(ValidationError, match="segment_distances_ft"):
        RulerAnnotation.model_validate({**payload, "segment_distances_ft": [7.0]})
    with pytest.raises(ValidationError, match="total_distance_ft"):
        RulerAnnotation.model_validate({**payload, "total_distance_ft": 7.0})
    with pytest.raises(ValidationError, match="at least two"):
        RulerAnnotation(
            **_base("ruler-short"),
            annotation_type="ruler",
            waypoints=(_point(0.0, 0.0),),
        )
    with pytest.raises(ValidationError, match="consecutive"):
        RulerAnnotation(
            **_base("ruler-duplicate"),
            annotation_type="ruler",
            waypoints=(_point(0.0, 0.0), _point(0.0, 0.0)),
        )
    with pytest.raises(ValidationError, match="at most"):
        RulerAnnotation(
            **_base("ruler-long"),
            annotation_type="ruler",
            waypoints=tuple(_point(float(index), 0.0) for index in range(MAX_RULER_WAYPOINTS + 1)),
        )


def test_annotation_union_round_trips_every_kind_as_strict_json() -> None:
    for annotation in _annotations():
        encoded = annotation.model_dump_json()
        parsed_from_json = parse_annotation_json(encoded)
        parsed_from_object = parse_annotation(json.loads(encoded))

        assert parsed_from_json == annotation
        assert parsed_from_object == annotation
        assert parsed_from_json.schema_version == ANNOTATION_SCHEMA_VERSION
        assert parsed_from_json.annotation_type == annotation.annotation_type

    with pytest.raises(ValidationError):
        parse_annotation({**_base("unknown-1"), "annotation_type": "sphere_template"})


def test_audience_uses_ordered_all_or_explicit_recipient_ids() -> None:
    ping = PingAnnotation(
        **_base("ping-audience", audience=["player-2", "player-1", "player-2"]),
        annotation_type="ping",
        position=_point(1.0, 2.0),
        duration_ms=1_000,
    )

    assert ping.audience == ("player-2", "player-1")

    with pytest.raises(ValidationError, match="all"):
        PingAnnotation(
            **_base("ping-mixed", audience=("all", "player-1")),
            annotation_type="ping",
            position=_point(1.0, 2.0),
            duration_ms=1_000,
        )
    with pytest.raises(ValidationError, match="at least one"):
        PingAnnotation(
            **_base("ping-empty", audience=()),
            annotation_type="ping",
            position=_point(1.0, 2.0),
            duration_ms=1_000,
        )


def test_ids_and_audience_recipients_reject_surrounding_whitespace() -> None:
    with pytest.raises(ValidationError, match="surrounding whitespace"):
        PingAnnotation(
            **_base(" ping-whitespace "),
            annotation_type="ping",
            position=_point(1.0, 2.0),
            duration_ms=1_000,
        )
    with pytest.raises(ValidationError, match="surrounding whitespace"):
        PingAnnotation(
            **_base("ping-recipient-whitespace", audience=(" player-2 ",)),
            annotation_type="ping",
            position=_point(1.0, 2.0),
            duration_ms=1_000,
        )


def test_projection_is_scene_bound_audience_filtered_and_deterministically_sorted() -> None:
    public_z = PingAnnotation(
        **_base("z-public"),
        annotation_type="ping",
        position=_point(1.0, 1.0),
        duration_ms=1_000,
    )
    for_hero = PingAnnotation(
        **_base("a-hero", audience=("hero",)),
        annotation_type="ping",
        position=_point(2.0, 2.0),
        duration_ms=1_000,
    )
    for_other = PingAnnotation(
        **_base("b-other", audience=("other",)),
        annotation_type="ping",
        position=_point(3.0, 3.0),
        duration_ms=1_000,
    )
    other_scene = PingAnnotation(
        **_base("c-scene", scene_id="scene-2"),
        annotation_type="ping",
        position=_point(4.0, 4.0),
        duration_ms=1_000,
    )

    projected = project_annotations(
        [public_z, for_other, other_scene, for_hero],
        scene_id="scene-1",
        recipient_id="hero",
    )
    anonymous = project_annotations(
        [for_hero, public_z],
        scene_id="scene-1",
        recipient_id=None,
    )

    assert [annotation.annotation_id for annotation in projected] == ["a-hero", "z-public"]
    assert anonymous == (public_z,)
    with pytest.raises(ValueError, match="duplicate annotation_id"):
        project_annotations(
            [public_z, public_z],
            scene_id="scene-1",
            recipient_id="hero",
        )


def test_geometry_bounds_are_deterministic_and_feet_only() -> None:
    annotations = {annotation.annotation_type: annotation for annotation in _annotations()}

    ruler = annotation_bounds_ft(annotations["ruler"])
    ping = annotation_bounds_ft(annotations["ping"])
    circle = annotation_bounds_ft(annotations["circle_template"])
    cone = annotation_bounds_ft(annotations["cone_template"])
    line = annotation_bounds_ft(annotations["line_template"])
    cube = annotation_bounds_ft(annotations["cube_template"])

    assert ruler == AnnotationBounds(
        min_x_ft=0.0,
        max_x_ft=15.0,
        min_y_ft=0.0,
        max_y_ft=10.0,
        min_z_ft=0.0,
        max_z_ft=0.0,
    )
    assert ping.min_x_ft == ping.max_x_ft == 5.0
    assert circle.min_x_ft == 5.0
    assert circle.max_y_ft == 15.0
    assert cone.min_x_ft == pytest.approx(0.0)
    assert cone.max_x_ft == pytest.approx(10.0)
    assert cone.min_y_ft == pytest.approx(-math.sqrt(50.0))
    assert cone.max_y_ft == pytest.approx(math.sqrt(50.0))
    assert line.min_x_ft == pytest.approx(0.0)
    assert line.max_x_ft == pytest.approx(10.0)
    assert line.min_y_ft == pytest.approx(-2.0)
    assert line.max_y_ft == pytest.approx(2.0)
    assert cube == AnnotationBounds(
        min_x_ft=8.0,
        max_x_ft=12.0,
        min_y_ft=8.0,
        max_y_ft=12.0,
        min_z_ft=3.0,
        max_z_ft=7.0,
    )


def test_derived_cone_and_line_bounds_can_extend_beyond_control_point_limit() -> None:
    cone = ConeTemplateAnnotation(
        **_base("cone-edge"),
        annotation_type="cone_template",
        origin=_point(MAX_ABSOLUTE_COORDINATE_FT, 0.0),
        direction_degrees=0.0,
        length_ft=100_000.0,
        angle_degrees=90.0,
    )
    line = LineTemplateAnnotation(
        **_base("line-edge"),
        annotation_type="line_template",
        start=_point(MAX_ABSOLUTE_COORDINATE_FT, 0.0),
        end=_point(MAX_ABSOLUTE_COORDINATE_FT, 5.0),
        width_ft=100_000.0,
    )

    cone_bounds = annotation_bounds_ft(cone)
    line_bounds = annotation_bounds_ft(line)

    assert cone_bounds.max_x_ft == pytest.approx(MAX_ABSOLUTE_COORDINATE_FT + 100_000.0)
    assert line_bounds.min_x_ft == pytest.approx(MAX_ABSOLUTE_COORDINATE_FT - 50_000.0)
    assert line_bounds.max_x_ft == pytest.approx(MAX_ABSOLUTE_COORDINATE_FT + 50_000.0)


@pytest.mark.parametrize(
    "point",
    [
        {"x_ft": float("nan"), "y_ft": 0.0, "z_ft": 0.0},
        {"x_ft": float("inf"), "y_ft": 0.0, "z_ft": 0.0},
        {"x_ft": 1_000_001.0, "y_ft": 0.0, "z_ft": 0.0},
        {"x_ft": 0, "y_ft": 0.0, "z_ft": 0.0},
    ],
)
def test_points_reject_nonfinite_out_of_bounds_and_coercive_numbers(point) -> None:
    with pytest.raises(ValidationError):
        AnnotationPoint.model_validate(point)


def test_template_and_ping_dimensions_enforce_shape_specific_bounds() -> None:
    with pytest.raises(ValidationError):
        PingAnnotation(
            **_base("ping-duration"),
            annotation_type="ping",
            position=_point(0.0, 0.0),
            duration_ms=60_001,
        )
    with pytest.raises(ValidationError):
        CircleTemplateAnnotation(
            **_base("circle-radius"),
            annotation_type="circle_template",
            center=_point(0.0, 0.0),
            radius_ft=0.0,
        )
    with pytest.raises(ValidationError):
        ConeTemplateAnnotation(
            **_base("cone-direction"),
            annotation_type="cone_template",
            origin=_point(0.0, 0.0),
            direction_degrees=360.0,
            length_ft=10.0,
            angle_degrees=90.0,
        )
    with pytest.raises(ValidationError):
        ConeTemplateAnnotation(
            **_base("cone-angle"),
            annotation_type="cone_template",
            origin=_point(0.0, 0.0),
            direction_degrees=0.0,
            length_ft=10.0,
            angle_degrees=181.0,
        )
    with pytest.raises(ValidationError, match="distinct horizontal"):
        LineTemplateAnnotation(
            **_base("line-zero"),
            annotation_type="line_template",
            start=_point(0.0, 0.0),
            end=_point(0.0, 0.0),
            width_ft=5.0,
        )
    with pytest.raises(ValidationError):
        CubeTemplateAnnotation(
            **_base("cube-size"),
            annotation_type="cube_template",
            center=_point(0.0, 0.0),
            size_ft=100_001.0,
        )


def test_annotation_contracts_have_no_pixel_authority() -> None:
    encoded = json.dumps(
        [annotation.model_dump(mode="json") for annotation in _annotations()],
        sort_keys=True,
    )

    assert "_px" not in encoded
    assert "pixel" not in encoded
    with pytest.raises(ValidationError):
        AnnotationPoint(x_ft=0.0, y_ft=0.0, z_ft=0.0, x_px=10.0)
    with pytest.raises(ValidationError):
        PingAnnotation(
            **_base("ping-pixels"),
            annotation_type="ping",
            position=_point(0.0, 0.0),
            duration_ms=1_000,
            pixels_per_cell=70.0,
        )
