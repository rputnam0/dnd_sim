from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from dnd_sim.parse_monsters import parse_monsters
from dnd_sim.parse_spells import parse_spells


def _load_oss_parser_module():
    root = Path(__file__).resolve().parents[1]
    module_path = root / "scripts" / "oss_parser.py"
    spec = importlib.util.spec_from_file_location("oss_parser", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError("Could not load scripts/oss_parser.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_spells_extracts_spell_entries_from_srd_like_block() -> None:
    raw_text = """
Fireball
Casting Time: 1 action Range: 150 feet Components: V, S, M (bat guano) Duration: Instantaneous
A bright streak flashes from your pointing finger to a point you choose.

Mage Armor
Casting Time: 1 action Range: Touch Components: V, S, M (a piece of cured leather) Duration: 8 hours
You touch a willing creature who isn't wearing armor.
""".strip()

    spells = parse_spells(raw_text)

    assert len(spells) == 2
    assert spells[0]["name"] == "Fireball"
    assert spells[0]["casting_time"] == "1 action"
    assert "bright streak" in spells[0]["description"].lower()
    assert spells[1]["name"] == "Mage Armor"
    assert spells[1]["duration"] == "8 hours"


def test_parse_monsters_extracts_monster_stat_block() -> None:
    raw_text = """
Monsters (A)
Aboleth
Large aberration, lawful evil
Armor Class 17 (natural armor)
Hit Points 135 (18d10 + 36)
Speed 10 ft., swim 40 ft.
STR DEX CON INT WIS CHA
21 (+5) 9 (-1) 15 (+2) 18 (+4) 15 (+2) 18 (+4)
Challenge 10
Saving Throws Con +6, Int +8, Wis +6
Appendix PH-A:
""".strip()

    monsters = parse_monsters(raw_text)

    assert len(monsters) == 1
    monster = monsters[0]
    assert monster["name"] == "Aboleth"
    assert monster["ac"] == 17
    assert monster["hp"] == 135
    assert monster["hp_formula"] == "18d10 + 36"
    assert monster["ability_scores"]["str"] == 21
    assert monster["cr"] == "10"
    assert "Con +6" in monster["saving_throws_text"]


def test_sanitize_name_normalizes_punctuation_and_spacing() -> None:
    module = _load_oss_parser_module()

    assert module.sanitize_name("Melf's Acid Arrow") == "melf_s_acid_arrow"
    assert module.sanitize_name("Tasha: Hideous/Laughter") == "tasha_hideous_laughter"
    assert module.sanitize_name("  Chain-Lightning  ") == "chain_lightning"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_collect_jobs_builds_multi_kind_worklist(tmp_path: Path) -> None:
    module = _load_oss_parser_module()

    _write_json(
        tmp_path / "db" / "raw" / "5etools" / "spells" / "spells-phb.json",
        {"spell": [{"name": "Fireball", "source": "PHB"}]},
    )
    _write_json(
        tmp_path / "db" / "raw" / "5etools" / "feats.json",
        {"feat": [{"name": "Alert", "source": "PHB"}]},
    )
    _write_json(
        tmp_path / "db" / "raw" / "5etools" / "classes" / "class-monk.json",
        {
            "classFeature": [{"name": "Ki", "source": "PHB", "entries": ["text"]}],
            "subclassFeature": [
                {"name": "Open Hand Technique", "source": "PHB", "entries": ["text"]}
            ],
        },
    )
    _write_json(
        tmp_path / "db" / "raw" / "5etools" / "races" / "races.json",
        {
            "race": [
                {
                    "name": "Elf",
                    "source": "PHB",
                    "entries": [{"name": "Fey Ancestry", "entries": ["text"]}],
                }
            ]
        },
    )
    _write_json(
        tmp_path / "db" / "raw" / "5etools" / "backgrounds" / "backgrounds.json",
        {
            "background": [
                {
                    "name": "Acolyte",
                    "source": "PHB",
                    "entries": [
                        {
                            "name": "Feature: Shelter of the Faithful",
                            "entries": ["text"],
                            "data": {"isFeature": True},
                        }
                    ],
                }
            ]
        },
    )

    jobs = module.collect_jobs(
        tmp_path,
        kinds=[
            "spells",
            "feats",
            "class_features",
            "subclass_features",
            "race_traits",
            "background_features",
        ],
        overwrite=False,
        max_items=None,
    )

    assert len(jobs) == 6
    stems = {job.out_path.stem for job in jobs}
    assert "fireball" in stems
    assert "alert" in stems
    assert "ki" in stems
    assert "open_hand_technique" in stems
    assert "fey_ancestry" in stems
    assert "shelter_of_the_faithful" in stems


def test_collect_jobs_skips_existing_outputs_when_not_overwriting(tmp_path: Path) -> None:
    module = _load_oss_parser_module()

    _write_json(
        tmp_path / "db" / "raw" / "5etools" / "spells" / "spells-phb.json",
        {"spell": [{"name": "Fireball", "source": "PHB"}]},
    )
    existing = tmp_path / "db" / "rules" / "2014" / "spells" / "fireball.json"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("{}", encoding="utf-8")

    jobs = module.collect_jobs(
        tmp_path,
        kinds=["spells"],
        overwrite=False,
        max_items=None,
    )
    assert jobs == []

    jobs_overwrite = module.collect_jobs(
        tmp_path,
        kinds=["spells"],
        overwrite=True,
        max_items=None,
    )
    assert len(jobs_overwrite) == 1
