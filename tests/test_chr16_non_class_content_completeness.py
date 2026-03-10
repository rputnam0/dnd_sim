from __future__ import annotations

import json

import pytest

from dnd_sim.io import _load_non_class_content_catalog, load_character_db
from tests.helpers import build_character, write_json


def _write_character_db_fixture(
    *,
    db_dir,
    character_id: str,
    name: str,
    content_refs: list[str],
) -> None:
    character = build_character(
        character_id=character_id,
        name=name,
        max_hp=30,
        ac=14,
        to_hit=5,
        damage="1d8+3",
    )
    character["content_refs"] = list(content_refs)
    write_json(db_dir / f"{character_id}.json", character)


def test_chr16_catalog_exposes_2014_non_class_content_ids() -> None:
    catalog = _load_non_class_content_catalog()

    assert "feat:alert|PHB" in catalog
    assert "feat:elven_accuracy|XGE" in catalog
    assert "feat:fey_touched|TCE" in catalog
    assert "species:tabaxi|VGM" in catalog
    assert "species:warforged|ERLW" in catalog
    assert "background:city_watch|SCAG" in catalog
    assert "background:ruined|BMT" in catalog

    # 2024 content IDs must not appear in the 2014 catalog.
    assert "feat:alert|XPHB" not in catalog
    assert "species:aasimar|XPHB" not in catalog
    assert "background:acolyte|XPHB" not in catalog


def test_chr16_load_character_db_normalizes_multi_source_content_refs(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("dnd_sim.db_schema.execute_query", lambda *_args, **_kwargs: [])

    db_dir = tmp_path / "characters"
    db_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        db_dir / "index.json",
        {
            "characters": [
                {
                    "character_id": "warden",
                    "name": "Warden",
                    "class_level": "Fighter 8",
                    "source_pdf": "fixture.pdf",
                }
            ]
        },
    )
    _write_character_db_fixture(
        db_dir=db_dir,
        character_id="warden",
        name="Warden",
        content_refs=[
            "background:city_watch|SCAG",
            "feat:elven_accuracy|XGE",
            "species:tabaxi|VGM",
            "feat:alert|PHB",
            "background:acolyte|PHB",
            "species:warforged|ERLW",
        ],
    )

    db = load_character_db(db_dir)
    warden = db["warden"]

    assert warden["content_refs"] == [
        "background:acolyte|PHB",
        "background:city_watch|SCAG",
        "feat:alert|PHB",
        "feat:elven_accuracy|XGE",
        "species:tabaxi|VGM",
        "species:warforged|ERLW",
    ]
    assert warden["content_reference_details"] == [
        {
            "content_id": "background:acolyte|PHB",
            "kind": "background",
            "name": "Acolyte",
            "source": "PHB",
        },
        {
            "content_id": "background:city_watch|SCAG",
            "kind": "background",
            "name": "City Watch",
            "source": "SCAG",
        },
        {
            "content_id": "feat:alert|PHB",
            "kind": "feat",
            "name": "Alert",
            "source": "PHB",
        },
        {
            "content_id": "feat:elven_accuracy|XGE",
            "kind": "feat",
            "name": "Elven Accuracy",
            "source": "XGE",
        },
        {
            "content_id": "species:tabaxi|VGM",
            "kind": "species",
            "name": "Tabaxi",
            "source": "VGM",
        },
        {
            "content_id": "species:warforged|ERLW",
            "kind": "species",
            "name": "Warforged",
            "source": "ERLW",
        },
    ]


@pytest.mark.parametrize(
    ("content_refs", "match"),
    [
        (["feat-alert|PHB"], "invalid content_refs.*must match"),
        (["feat:not_a_real_feat|PHB"], "invalid content_refs.*unknown content reference"),
        (
            ["feat:alert|PHB", "feat:Alert|phb"],
            "invalid content_refs.*duplicate content reference",
        ),
    ],
)
def test_chr16_load_character_db_rejects_invalid_content_references(
    tmp_path, monkeypatch, content_refs: list[str], match: str
) -> None:
    monkeypatch.setattr("dnd_sim.db_schema.execute_query", lambda *_args, **_kwargs: [])

    db_dir = tmp_path / "characters"
    db_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        db_dir / "index.json",
        {
            "characters": [
                {
                    "character_id": "broken_refs",
                    "name": "Broken Refs",
                    "class_level": "Fighter 8",
                    "source_pdf": "fixture.pdf",
                }
            ]
        },
    )
    _write_character_db_fixture(
        db_dir=db_dir,
        character_id="broken_refs",
        name="Broken Refs",
        content_refs=content_refs,
    )

    with pytest.raises(ValueError, match=match):
        load_character_db(db_dir)


def test_chr16_load_character_db_rejects_invalid_content_refs_from_sqlite_rows(
    tmp_path, monkeypatch
) -> None:
    valid_character = build_character(
        character_id="valid_from_sqlite",
        name="Valid From SQLite",
        max_hp=20,
        ac=13,
        to_hit=5,
        damage="1d8+2",
    )
    valid_character["content_refs"] = ["feat:alert|PHB"]

    broken_character = build_character(
        character_id="broken_from_sqlite",
        name="Broken From SQLite",
        max_hp=20,
        ac=13,
        to_hit=5,
        damage="1d8+2",
    )
    broken_character["content_refs"] = ["feat:not_a_real_feat|PHB"]

    sqlite_rows = [
        {
            "character_id": "valid_from_sqlite",
            "data_json": json.dumps(valid_character),
        },
        {
            "character_id": "broken_from_sqlite",
            "data_json": json.dumps(broken_character),
        },
    ]
    monkeypatch.setattr("dnd_sim.db_schema.execute_query", lambda *_args, **_kwargs: sqlite_rows)

    with pytest.raises(
        ValueError,
        match="invalid content_refs for broken_from_sqlite: invalid content_refs",
    ):
        load_character_db(tmp_path / "characters")
