from __future__ import annotations

import json
from pathlib import Path

from dnd_sim.mechanics_schema import (
    EXECUTABLE_EFFECT_TYPES,
    build_mechanics_coverage_report,
    validate_rule_mechanics_payload,
)
from dnd_sim.monster_backfill import backfill_monster_payload
from dnd_sim.parse_monsters import parse_monsters


def _fixture_text(name: str) -> str:
    path = Path(__file__).parent / "fixtures" / "monster_parser" / name
    return path.read_text(encoding="utf-8")


def test_parse_monsters_extracts_full_action_reaction_legendary_and_lair_kits() -> None:
    monsters = parse_monsters(_fixture_text("chronal_hydra_srd.txt"))

    assert len(monsters) == 1
    hydra = monsters[0]

    # Legacy compatibility keys remain available.
    assert hydra["name"] == "Chronal Hydra"
    assert hydra["ac"] == 18
    assert hydra["hp"] == 250
    assert hydra["cr"] == "15"

    assert hydra["identity"]["enemy_id"] == "chronal_hydra"
    assert hydra["stat_block"]["max_hp"] == 250
    assert hydra["resources"]["legendary_actions"] == 3

    action_names = [row["name"] for row in hydra["actions"]]
    assert action_names == ["multiattack", "temporal_bite", "time_pulse"]

    reaction_names = [row["name"] for row in hydra["reactions"]]
    assert reaction_names == ["counter_lash"]
    assert hydra["reactions"][0]["action_cost"] == "reaction"

    legendary_names = [row["name"] for row in hydra["legendary_actions"]]
    assert legendary_names == ["detect", "snap", "rift_burst"]
    assert "legendary_cost:2" in hydra["legendary_actions"][1]["tags"]
    assert "legendary_cost:3" in hydra["legendary_actions"][2]["tags"]

    lair_names = [row["name"] for row in hydra["lair_actions"]]
    assert lair_names == ["gravitic_surge", "temporal_fog"]
    assert hydra["lair_actions"][0]["action_cost"] == "lair"


def test_validate_rule_mechanics_payload_flags_invalid_mechanics_shapes() -> None:
    issues = validate_rule_mechanics_payload(
        kind="trait",
        payload={
            "name": "Broken Trait",
            "type": "feat",
            "mechanics": [{"damage": "1d6"}, "not even a mapping"],
        },
    )

    assert len(issues) == 2
    assert "effect_type" in issues[0]
    assert "must be an object" in issues[1]


def test_validate_rule_mechanics_payload_accepts_known_effect_types() -> None:
    issues = validate_rule_mechanics_payload(
        kind="spell",
        payload={
            "name": "Pulse Bolt",
            "type": "spell",
            "mechanics": [{"effect_type": "damage", "damage": "2d8", "damage_type": "force"}],
        },
    )
    assert issues == []


def test_build_mechanics_coverage_report_counts_executable_and_unsupported(tmp_path: Path) -> None:
    traits_dir = tmp_path / "traits"
    spells_dir = tmp_path / "spells"
    monsters_dir = tmp_path / "monsters"
    traits_dir.mkdir()
    spells_dir.mkdir()
    monsters_dir.mkdir()

    (traits_dir / "trait.json").write_text(
        json.dumps(
            {
                "name": "Reactive Mind",
                "type": "feat",
                "mechanics": [
                    {"effect_type": "sense", "sense": "blindsight", "range_ft": 10},
                    {"effect_type": "quantum_shift"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (spells_dir / "spell.json").write_text(
        json.dumps(
            {
                "name": "Pulse Bolt",
                "type": "spell",
                "mechanics": [{"effect_type": "damage", "damage": "2d8", "damage_type": "force"}],
            }
        ),
        encoding="utf-8",
    )
    (monsters_dir / "monster.json").write_text(
        json.dumps(
            {
                "identity": {"enemy_id": "void_hound", "name": "Void Hound", "team": "enemy"},
                "stat_block": {"max_hp": 22, "ac": 13},
                "actions": [
                    {
                        "name": "warp_bite",
                        "action_type": "attack",
                        "effects": [{"effect_type": "apply_condition", "condition": "frightened"}],
                    },
                    {
                        "name": "timeline_bark",
                        "action_type": "utility",
                        "mechanics": [{"effect_type": "timeline_snap"}],
                    },
                ],
                "reactions": [],
                "legendary_actions": [],
                "lair_actions": [],
            }
        ),
        encoding="utf-8",
    )

    report = build_mechanics_coverage_report(
        traits_dir=traits_dir,
        spells_dir=spells_dir,
        monsters_dir=monsters_dir,
    )

    assert report["totals"]["ingested"] == 5
    assert report["totals"]["executable"] == 3
    assert report["totals"]["unsupported"] == 2
    assert "quantum_shift" in report["unsupported_effect_types"]
    assert "timeline_snap" in report["unsupported_effect_types"]
    assert "damage" in EXECUTABLE_EFFECT_TYPES


def test_backfill_monster_payload_upgrades_legacy_shape_to_enemy_schema() -> None:
    legacy = {
        "name": "Legacy Beast",
        "meta": "Large monstrosity, unaligned",
        "ac": 13,
        "hp": 45,
        "hp_formula": "6d10 + 12",
        "ability_scores": {"str": 16, "dex": 10, "con": 14, "int": 3, "wis": 12, "cha": 6},
        "cr": "3",
        "saving_throws_text": "Con +4, Wis +3",
    }

    migrated = backfill_monster_payload(legacy)

    assert migrated["identity"]["enemy_id"] == "legacy_beast"
    assert migrated["identity"]["name"] == "Legacy Beast"
    assert migrated["stat_block"]["max_hp"] == 45
    assert migrated["stat_block"]["ac"] == 13
    assert migrated["stat_block"]["save_mods"]["con"] == 4
    assert migrated["stat_block"]["save_mods"]["wis"] == 3
    assert migrated["actions"] == []
    assert migrated["reactions"] == []
    assert migrated["legendary_actions"] == []
    assert migrated["lair_actions"] == []
    assert migrated["resources"] == {}


def test_backfill_monster_payload_preserves_existing_enemy_schema() -> None:
    modern = {
        "identity": {"enemy_id": "modern_one", "name": "Modern One", "team": "enemy"},
        "stat_block": {"max_hp": 10, "ac": 12, "save_mods": {"dex": 2}},
        "actions": [{"name": "slam", "action_type": "attack"}],
        "reactions": [],
        "legendary_actions": [],
        "lair_actions": [],
    }

    migrated = backfill_monster_payload(modern)
    assert migrated["identity"]["enemy_id"] == "modern_one"
    assert migrated["actions"][0]["name"] == "slam"
