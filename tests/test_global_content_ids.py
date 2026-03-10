from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from dnd_sim import db_migrations, db_schema
from dnd_sim.io import build_global_content_index, canonical_content_id, load_character_db
from tests.helpers import build_character, write_json


@pytest.mark.parametrize(
    ("kind", "name", "source", "match"),
    [
        ("", "magic_missile", "2014", "unsupported content kind"),
        ("spell", "", "2014", "name must be non-empty"),
        ("spell", "magic_missile", "", "source must be non-empty"),
        ("spell", None, "2014", "name must be a string"),
        ("spell", "magic_missile", None, "source must be a string"),
    ],
)
def test_canonical_content_id_rejects_invalid_inputs(
    kind: str,
    name: str | None,
    source: str | None,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        canonical_content_id(kind=kind, name=name, source=source)  # type: ignore[arg-type]


def test_build_global_content_index_includes_all_supported_content_classes() -> None:
    index = build_global_content_index()

    assert "spell:magic_missile|2014" in index
    assert "trait:alert|2014" in index
    assert "monster:goblin|2014" in index
    assert "feat:alert|PHB" in index
    assert "species:tabaxi|VGM" in index
    assert "background:acolyte|PHB" in index
    assert len(index) == len(set(index))


def test_build_global_content_index_rejects_transitional_alias_id_fields(tmp_path: Path) -> None:
    rules_root = tmp_path / "rules_2014"
    spells_dir = rules_root / "spells"
    spells_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        spells_dir / "magic_missile.json",
        {
            "id": "legacy_magic_missile",
            "name": "Magic Missile",
            "type": "spell",
            "level": 1,
            "school": "Evocation",
            "casting_time": "1 action",
            "description": "Arcane darts of force.",
            "range_ft": 120,
            "concentration": False,
            "ritual": False,
            "duration_rounds": 0,
            "mechanics": [],
        },
    )

    with pytest.raises(ValueError, match="legacy alias field 'id'"):
        build_global_content_index(rules_root=rules_root, include_non_class_catalog=False)


def test_build_global_content_index_supports_item_class_and_subclass_payloads(
    tmp_path: Path,
) -> None:
    rules_root = tmp_path / "rules_2014"
    items_dir = rules_root / "items"
    classes_dir = rules_root / "classes"
    subclasses_dir = rules_root / "subclasses"
    items_dir.mkdir(parents=True, exist_ok=True)
    classes_dir.mkdir(parents=True, exist_ok=True)
    subclasses_dir.mkdir(parents=True, exist_ok=True)

    write_json(
        items_dir / "longsword.json",
        {
            "content_id": "item:longsword|PHB",
            "item_id": "longsword",
            "name": "Longsword",
            "source_book": "PHB",
            "category": "weapon",
        },
    )
    write_json(
        classes_dir / "fighter.json",
        {
            "content_id": "class:fighter|PHB",
            "class_id": "fighter",
            "name": "Fighter",
            "source_book": "PHB",
            "features": [{"name": "Second Wind", "level": 1}],
        },
    )
    write_json(
        subclasses_dir / "battle_master.json",
        {
            "content_id": "subclass:battle_master_fighter|PHB",
            "subclass_id": "battle_master",
            "class_id": "fighter",
            "name": "Battle Master",
            "source_book": "PHB",
            "features": [{"name": "Combat Superiority", "level": 3}],
        },
    )

    index = build_global_content_index(rules_root=rules_root, include_non_class_catalog=False)
    assert "item:longsword|PHB" in index
    assert "class:fighter|PHB" in index
    assert "subclass:battle_master_fighter|PHB" in index


def test_load_character_db_assigns_canonical_character_content_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("dnd_sim.db_schema.execute_query", lambda *_args, **_kwargs: [])

    db_dir = tmp_path / "characters"
    db_dir.mkdir(parents=True, exist_ok=True)

    write_json(
        db_dir / "index.json",
        {
            "characters": [
                {
                    "character_id": "hero",
                    "name": "Hero",
                    "class_level": "Fighter 8",
                    "source_pdf": "fixture.pdf",
                }
            ]
        },
    )
    write_json(
        db_dir / "hero.json",
        build_character(
            character_id="hero",
            name="Hero",
            max_hp=40,
            ac=16,
            to_hit=6,
            damage="1d8+4",
        ),
    )

    loaded = load_character_db(db_dir)
    hero = loaded["hero"]
    assert hero["content_id"] == "character:hero|CUSTOM"
    assert hero["content_type"] == "character"
    assert hero["schema_version"] == "wld11.v1"
    assert hero["source_book"] == "CUSTOM"


def test_backfill_content_records_populates_rows_from_legacy_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "content_records.db"
    monkeypatch.setattr(db_schema, "get_db_path", lambda: db_path)
    db_schema.init_db()

    trait_payload = {
        "name": "Alert",
        "description": "Initiative bonus.",
        "source_type": "feat",
        "mechanics": [],
    }
    character_payload = build_character(
        character_id="hero",
        name="Hero",
        max_hp=40,
        ac=16,
        to_hit=6,
        damage="1d8+4",
    )
    enemy_payload = {
        "identity": {"enemy_id": "goblin", "name": "Goblin", "team": "enemy"},
        "stat_block": {"max_hp": 7, "ac": 15, "initiative_mod": 2, "dex_mod": 2, "con_mod": 0},
        "actions": [],
        "bonus_actions": [],
        "reactions": [],
        "legendary_actions": [],
        "lair_actions": [],
        "innate_spellcasting": [],
        "resources": {},
        "damage_resistances": [],
        "damage_immunities": [],
        "damage_vulnerabilities": [],
        "condition_immunities": [],
        "script_hooks": {},
    }

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO traits (id, name, data_json) VALUES (?, ?, ?)",
            ("alert", "Alert", json.dumps(trait_payload)),
        )
        conn.execute(
            """
            INSERT INTO characters (character_id, name, ac, max_hp, initiative_mod, data_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("hero", "Hero", 16, 40, 2, json.dumps(character_payload)),
        )
        conn.execute(
            """
            INSERT INTO enemies (enemy_id, name, team, cr, ac, max_hp, initiative_mod, data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("goblin", "Goblin", "enemy", 0.25, 15, 7, 2, json.dumps(enemy_payload)),
        )
        conn.commit()

    db_migrations.backfill_content_records()

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT content_id, content_type, source_book FROM content_records ORDER BY content_id"
        ).fetchall()

    assert rows == [
        ("character:hero|CUSTOM", "character", "CUSTOM"),
        ("monster:goblin|2014", "monster", "2014"),
        ("trait:alert|2014", "trait", "2014"),
    ]


def test_backfill_content_records_rejects_duplicate_content_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "duplicate_content_records.db"
    monkeypatch.setattr(db_schema, "get_db_path", lambda: db_path)
    db_schema.init_db()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO traits (id, name, data_json) VALUES (?, ?, ?)",
            (
                "alert",
                "Alert",
                json.dumps(
                    {
                        "content_id": "trait:alert|2014",
                        "name": "Alert",
                        "description": "A",
                        "source_type": "feat",
                        "mechanics": [],
                    }
                ),
            ),
        )
        conn.execute(
            "INSERT INTO traits (id, name, data_json) VALUES (?, ?, ?)",
            (
                "alert_copy",
                "Alert Copy",
                json.dumps(
                    {
                        "content_id": "trait:alert|2014",
                        "name": "Alert Copy",
                        "description": "B",
                        "source_type": "feat",
                        "mechanics": [],
                    }
                ),
            ),
        )
        conn.commit()

    with pytest.raises(ValueError, match="duplicate content_id"):
        db_migrations.backfill_content_records()
