from __future__ import annotations

from pathlib import Path

from dnd_sim.capability_manifest import (
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
            {"name": "gear_strike", "action_type": "attack", "action_cost": "action"},
        ],
        "reactions": [
            {"name": "parry_protocol", "action_type": "utility", "action_cost": "reaction"}
        ],
        "legendary_actions": [
            {"name": "pulse_step", "action_type": "utility", "action_cost": "legendary"}
        ],
        "lair_actions": [
            {"name": "clockfield_shift", "action_type": "save", "action_cost": "lair"}
        ],
        "innate_spellcasting": [{"spell": "shield", "max_uses": 1}],
    }

    manifest = build_monster_capability_manifest(monster_payloads=[payload])
    by_id = {record.content_id: record for record in manifest.records}

    assert by_id["monster_action:clockwork_sentry:gear_strike:1"].states.executable is True
    assert by_id["monster_reaction:clockwork_sentry:parry_protocol:1"].states.executable is True
    assert by_id["monster_legendary_action:clockwork_sentry:pulse_step:1"].states.executable is True
    assert (
        by_id["monster_lair_action:clockwork_sentry:clockfield_shift:1"].states.executable is True
    )
    assert by_id["monster_innate_spellcasting:clockwork_sentry:shield:1"].states.executable is True


def test_monster_action_unsupported_reasons_are_explicit() -> None:
    payload = {
        "identity": {"enemy_id": "void_howler", "name": "Void Howler", "team": "enemy"},
        "stat_block": {"max_hp": 30, "ac": 14},
        "actions": [
            {"name": "timeline_tear", "action_type": "timeline", "action_cost": "action"},
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

    missing_name = by_id["monster_action:void_howler:action_2:2"]
    assert missing_name.states.blocked is True
    assert missing_name.states.unsupported_reason == "missing_action_name"

    missing_spell = by_id["monster_innate_spellcasting:void_howler:innate_spell_1:1"]
    assert missing_spell.states.blocked is True
    assert missing_spell.states.unsupported_reason == "missing_innate_spell_name"
