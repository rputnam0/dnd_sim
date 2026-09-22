from __future__ import annotations

import dnd_sim.vtt as vtt


def test_tabletop_domain_contracts_are_available_from_the_public_vtt_package() -> None:
    expected_exports = {
        "ANNOTATION_SCHEMA_VERSION",
        "ANNOTATION_STORE_SCHEMA_VERSION",
        "OPEN_LOCAL_PARTICIPANT_ID",
        "PARTICIPANT_SCHEMA_VERSION",
        "ROSTER_SCHEMA_VERSION",
        "VTT_TABLE_VIEW_SCHEMA_VERSION",
        "AnnotationPoint",
        "AnnotationPutCommand",
        "CircleTemplateAnnotation",
        "ConeTemplateAnnotation",
        "CubeTemplateAnnotation",
        "LineTemplateAnnotation",
        "PingAnnotation",
        "RulerAnnotation",
        "SQLiteAnnotationBoard",
        "TableAccessError",
        "TableAccessPolicy",
        "TableParticipant",
        "TableRoster",
        "VTTTableView",
        "VTTAnnotation",
        "annotation_bounds_ft",
        "audience_allows",
        "parse_annotation",
        "project_annotations",
        "validate_audience_selectors",
    }

    assert expected_exports <= set(vtt.__all__)
    for name in expected_exports:
        assert getattr(vtt, name) is not None
