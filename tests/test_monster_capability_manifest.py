from __future__ import annotations

from pathlib import Path

from dnd_sim.capability_manifest import (
    DEFAULT_MONSTERS_DIR,
    build_monster_capability_manifest,
)
from dnd_sim.parse_monsters import parse_monsters


def _fixture_text(name: str) -> str:
    path = Path(__file__).parent / "fixtures" / "monster_parser" / name
    return path.read_text(encoding="utf-8")


def test_monster_parser_integration_emits_action_family_records() -> None:
    monsters = parse_monsters(_fixture_text("chronal_hydra_srd.txt"))

    manifest = build_monster_capability_manifest(monster_payloads=monsters)
    by_type = {}
    for record in manifest.records:
        by_type.setdefault(record.content_type, []).append(record)

    assert len(by_type["monster"]) == 1
    assert len(by_type["monster_action"]) == 3
    assert len(by_type["monster_reaction"]) == 1
    assert len(by_type["monster_legendary_action"]) == 3
    assert len(by_type["monster_lair_action"]) == 2
    assert len(by_type["monster_recharge"]) == 1

    recharge_ids = {record.content_id for record in by_type["monster_recharge"]}
    assert "monster_recharge:chronal_hydra:time_pulse:3" in recharge_ids


def test_monster_action_support_marks_supported_entries_executable() -> None:
    payload = {
        "identity": {"enemy_id": "clockwork_sentry", "name": "Clockwork Sentry", "team": "enemy"},
        "stat_block": {"max_hp": 42, "ac": 15},
        "actions": [
            {
                "name": "gear_strike",
                "action_type": "attack",
                "action_cost": "action",
                "to_hit": 5,
                "damage": "1d8+3",
            },
            {
                "name": "temporal_burst",
                "action_type": "save",
                "action_cost": "action",
                "recharge": "Recharge 6",
                "save_dc": 14,
                "save_ability": "dex",
                "damage": "2d6",
            },
        ],
        "bonus_actions": [
            {
                "name": "overclock",
                "action_type": "utility",
                "action_cost": "bonus",
                "effects": [{"effect_type": "temp_hp", "amount": "1d6"}],
            }
        ],
        "reactions": [
            {
                "name": "parry_protocol",
                "action_type": "attack",
                "action_cost": "reaction",
                "to_hit": 5,
                "damage": "1d6+3",
            }
        ],
        "legendary_actions": [
            {
                "name": "pulse_step",
                "action_type": "attack",
                "action_cost": "legendary",
                "to_hit": 5,
                "damage": "1d6+3",
            }
        ],
        "lair_actions": [
            {
                "name": "clockfield_shift",
                "action_type": "save",
                "action_cost": "lair",
                "save_dc": 14,
                "save_ability": "wis",
                "damage": "1d6",
            }
        ],
        "innate_spellcasting": [{"spell": "Magic Missile", "max_uses": 1}],
    }

    manifest = build_monster_capability_manifest(monster_payloads=[payload])
    by_id = {record.content_id: record for record in manifest.records}

    assert by_id["monster_action:clockwork_sentry:gear_strike:1"].states.executable is True
    bonus_action = by_id["monster_bonus_action:clockwork_sentry:overclock:1"]
    assert bonus_action.content_type == "monster_bonus_action"
    assert bonus_action.states.executable is True
    assert by_id["monster_reaction:clockwork_sentry:parry_protocol:1"].states.executable is True
    assert by_id["monster_legendary_action:clockwork_sentry:pulse_step:1"].states.executable is True
    assert (
        by_id["monster_lair_action:clockwork_sentry:clockfield_shift:1"].states.executable is True
    )
    assert (
        by_id["monster_innate_spellcasting:clockwork_sentry:magic_missile:1"].states.executable
        is True
    )
    assert by_id["monster_recharge:clockwork_sentry:temporal_burst:2"].states.executable is True
    assert by_id["monster:clockwork_sentry"].states.executable is True


def test_unknown_action_mechanic_blocks_action_and_parent_monster() -> None:
    payload = {
        "identity": {"enemy_id": "rift_mage", "name": "Rift Mage", "team": "enemy"},
        "stat_block": {"max_hp": 40, "ac": 14},
        "actions": [
            {
                "name": "rift_bolt",
                "action_type": "attack",
                "action_cost": "action",
                "mechanics": [{"effect_type": "timeline_snap"}],
            }
        ],
    }

    manifest = build_monster_capability_manifest(monster_payloads=[payload])
    by_id = {record.content_id: record for record in manifest.records}

    action = by_id["monster_action:rift_mage:rift_bolt:1"]
    assert action.states.schema_valid is False
    assert action.states.executable is False
    assert action.states.blocked is True
    assert action.states.unsupported_reason == "unsupported_action_mechanic_effect_type"

    monster = by_id["monster:rift_mage"]
    assert monster.states.schema_valid is False
    assert monster.states.executable is False
    assert monster.states.blocked is True
    assert monster.states.unsupported_reason == "invalid_monster_schema"


def test_unknown_innate_spell_blocks_spell_and_parent_monster() -> None:
    payload = {
        "identity": {"enemy_id": "false_seer", "name": "False Seer", "team": "enemy"},
        "stat_block": {"max_hp": 35, "ac": 13},
        "actions": [],
        "innate_spellcasting": [{"spell": "Not A Real Spell", "max_uses": 1}],
    }

    manifest = build_monster_capability_manifest(monster_payloads=[payload])
    by_id = {record.content_id: record for record in manifest.records}

    spell = by_id["monster_innate_spellcasting:false_seer:not_a_real_spell:1"]
    assert spell.states.schema_valid is False
    assert spell.states.executable is False
    assert spell.states.blocked is True
    assert spell.states.unsupported_reason == "unknown_innate_spell_reference"

    monster = by_id["monster:false_seer"]
    assert monster.states.schema_valid is False
    assert monster.states.executable is False
    assert monster.states.blocked is True
    assert monster.states.unsupported_reason == "invalid_monster_schema"


def test_parent_monster_requires_enemy_config_cross_action_validity() -> None:
    payload = {
        "identity": {"enemy_id": "broken_captain", "name": "Broken Captain", "team": "enemy"},
        "stat_block": {"max_hp": 55, "ac": 16},
        "actions": [
            {"name": "saber", "action_type": "attack", "damage": "1d8+3"},
            {
                "name": "multiattack",
                "action_type": "utility",
                "mechanics": [
                    {
                        "effect_type": "attack_sequence",
                        "sequence": [{"action_name": "missing_attack"}],
                    }
                ],
            },
        ],
    }

    manifest = build_monster_capability_manifest(monster_payloads=[payload])
    by_id = {record.content_id: record for record in manifest.records}

    assert by_id["monster_action:broken_captain:multiattack:2"].states.executable is True
    monster = by_id["monster:broken_captain"]
    assert monster.states.schema_valid is False
    assert monster.states.executable is False
    assert monster.states.blocked is True
    assert monster.states.unsupported_reason == "invalid_monster_schema"


def test_monster_action_unsupported_reasons_are_explicit() -> None:
    payload = {
        "identity": {"enemy_id": "void_howler", "name": "Void Howler", "team": "enemy"},
        "stat_block": {"max_hp": 30, "ac": 14},
        "actions": [
            {
                "name": "timeline_tear",
                "action_type": "timeline",
                "action_cost": "action",
                "recharge": "Recharge 6",
            },
            {"name": "", "action_type": "attack", "action_cost": "action"},
        ],
        "reactions": [],
        "legendary_actions": [],
        "lair_actions": [],
        "innate_spellcasting": [{}],
    }

    manifest = build_monster_capability_manifest(monster_payloads=[payload])
    by_id = {record.content_id: record for record in manifest.records}

    unsupported_type = by_id["monster_action:void_howler:timeline_tear:1"]
    assert unsupported_type.states.blocked is True
    assert unsupported_type.states.unsupported_reason == "unsupported_action_type"

    blocked_recharge = by_id["monster_recharge:void_howler:timeline_tear:1"]
    assert blocked_recharge.states.blocked is True
    assert blocked_recharge.states.unsupported_reason == "source_action_blocked"

    missing_name = by_id["monster_action:void_howler:action_2:2"]
    assert missing_name.states.blocked is True
    assert missing_name.states.unsupported_reason == "missing_action_name"

    missing_spell = by_id["monster_innate_spellcasting:void_howler:innate_spell_1:1"]
    assert missing_spell.states.blocked is True
    assert missing_spell.states.unsupported_reason == "missing_innate_spell_name"


def test_monster_base_record_blocks_stat_shell_without_executable_action_kit() -> None:
    payload = {
        "identity": {"enemy_id": "ancient_shell", "name": "Ancient Shell", "team": "enemy"},
        "stat_block": {"max_hp": 546, "ac": 22},
        "actions": [],
        "bonus_actions": [],
        "reactions": [],
        "legendary_actions": [],
        "lair_actions": [],
        "innate_spellcasting": [],
    }

    manifest = build_monster_capability_manifest(monster_payloads=[payload])
    monster = next(record for record in manifest.records if record.content_type == "monster")

    assert monster.states.schema_valid is True
    assert monster.states.executable is False
    assert monster.states.tested is False
    assert monster.states.blocked is True
    assert monster.states.unsupported_reason == "missing_executable_action_kit"


def test_canonical_monster_manifest_does_not_claim_stat_shells_are_executable() -> None:
    manifest = build_monster_capability_manifest(monsters_dir=DEFAULT_MONSTERS_DIR)
    monster_records = [record for record in manifest.records if record.content_type == "monster"]

    assert len(monster_records) == 191
    assert all(record.states.blocked for record in monster_records)
    assert {record.states.unsupported_reason for record in monster_records} == {
        "missing_executable_action_kit"
    }
