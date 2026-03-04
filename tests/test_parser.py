from __future__ import annotations

import json
from pathlib import Path

from dnd_sim.parser import parse_characters_from_markdown_file, write_character_db

ROOT = Path(__file__).resolve().parents[1]
SOURCE_MD = ROOT / "river_line" / "character_sheets" / "character_sheets_extracted.md"


def test_parse_three_characters_from_markdown() -> None:
    records = parse_characters_from_markdown_file(SOURCE_MD)
    assert len(records) == 3

    by_id = {record.character_id: record for record in records}
    assert "alabaster_leatherback" in by_id
    assert "furyen_fury" in by_id
    assert "isak_wissa" in by_id

    isak = by_id["isak_wissa"]
    assert isak.name == "Isak Wissa"
    assert isak.class_levels == {"monk": 8}
    assert isak.max_hp == 77
    assert isak.ac == 16
    assert isak.attacks
    assert isak.save_mods["dex"] == 6 or isak.save_mods["dex"] == 7


def test_parser_handles_multiline_values_and_duplicates() -> None:
    records = parse_characters_from_markdown_file(SOURCE_MD)
    druid = next(record for record in records if record.character_id == "alabaster_leatherback")

    features = [
        field.value for field in druid.raw_fields if field.field.startswith("FeaturesTraits")
    ]
    assert features
    assert any("\n" in value for value in features)

    tuples = {(field.page, field.field, field.value) for field in druid.raw_fields}
    assert len(tuples) == len(druid.raw_fields)


def test_character_db_write_is_idempotent(tmp_path: Path) -> None:
    records = parse_characters_from_markdown_file(SOURCE_MD)
    write_character_db(records, tmp_path)

    first_pass = {
        path.name: path.read_text(encoding="utf-8") for path in sorted(tmp_path.glob("*.json"))
    }

    write_character_db(records, tmp_path)
    second_pass = {
        path.name: path.read_text(encoding="utf-8") for path in sorted(tmp_path.glob("*.json"))
    }

    assert first_pass == second_pass
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert len(index["characters"]) == 3
    assert all("class_level" not in row for row in index["characters"])
    assert all(isinstance(row.get("class_levels"), dict) and row["class_levels"] for row in index["characters"])
    character_payload = json.loads((tmp_path / "isak_wissa.json").read_text(encoding="utf-8"))
    assert "class_level" not in character_payload
    assert character_payload["class_levels"] == {"monk": 8}
