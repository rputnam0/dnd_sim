from __future__ import annotations

import json
from pathlib import Path

import pytest

from dnd_sim.engine import _load_spell_definition
from dnd_sim.spells import (
    SpellDatabaseValidationError,
    canonicalize_spell_payload,
    clear_spell_database_cache,
    load_spell_database,
)


def test_canonicalize_spell_payload_normalizes_legacy_spell_record() -> None:
    payload = {
        "name": "Detect Magic",
        "meta": "Detect Magic 1st-level Divination",
        "casting_time": "1 action",
        "range": "30 feet",
        "components": "V, S",
        "duration": "Concentration, up to 1 minute",
        "description": "For the duration, you sense the presence of magic within 30 feet of you.",
    }

    canonical = canonicalize_spell_payload(payload, source_path=Path("legacy_detect_magic.json"))

    assert canonical["name"] == "Detect Magic"
    assert canonical["type"] == "spell"
    assert canonical["level"] == 1
    assert canonical["school"] == "Divination"
    assert canonical["range_ft"] == 30
    assert canonical["concentration"] is True
    assert canonical["duration_rounds"] == 10
    assert canonical["mechanics"] == []


def test_load_spell_database_fails_fast_on_duplicate_lookup_key(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text(
        json.dumps(
            {
                "name": "Melf's Acid Arrow",
                "type": "spell",
                "level": 2,
                "casting_time": "action",
                "description": "A shimmering green arrow streaks toward a target.",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "b.json").write_text(
        json.dumps(
            {
                "name": "Melfs Acid Arrow",
                "type": "spell",
                "level": 2,
                "casting_time": "action",
                "description": "A second, duplicate record.",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SpellDatabaseValidationError, match="Duplicate spell lookup key"):
        load_spell_database(tmp_path)


def test_load_spell_database_prefer_richest_counts_ritual_marker(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text(
        json.dumps(
            {
                "name": "Echo Ward",
                "type": "spell",
                "level": 1,
                "casting_time": "action",
                "ritual": False,
                "description": "A longer baseline duplicate description to win tie-breakers.",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "b.json").write_text(
        json.dumps(
            {
                "name": "Echo Ward",
                "type": "spell",
                "level": 1,
                "casting_time": "action",
                "ritual": True,
                "description": "Short duplicate.",
            }
        ),
        encoding="utf-8",
    )

    database = load_spell_database(tmp_path, duplicate_policy="prefer_richest")

    assert len(database) == 1
    spell = next(iter(database.values()))
    assert spell["name"] == "Echo Ward"
    assert spell["ritual"] is True
    assert spell["description"] == "Short duplicate."


def test_engine_spell_lookup_uses_validated_canonical_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spells_dir = tmp_path / "spells"
    spells_dir.mkdir(parents=True, exist_ok=True)
    (spells_dir / "detect_magic.json").write_text(
        json.dumps(
            {
                "name": "Detect Magic",
                "meta": "Detect Magic 1st-level Divination",
                "casting_time": "1 action",
                "range": "30 feet",
                "components": "V, S",
                "duration": "Concentration, up to 1 minute",
                "description": "For the duration, you sense the presence of magic within 30 feet of you.",
            }
        ),
        encoding="utf-8",
    )

    clear_spell_database_cache()
    monkeypatch.setattr("dnd_sim.engine._spell_root_dir", lambda: spells_dir)

    spell = _load_spell_definition("Detect Magic [R]")

    assert spell is not None
    assert spell["name"] == "Detect Magic"
    assert spell["level"] == 1
    assert spell["range_ft"] == 30
    assert spell["concentration"] is True
