from __future__ import annotations

import json
from pathlib import Path

import pytest

from dnd_sim.capability_manifest import (
    DEFAULT_SPELLS_DIR,
    build_spell_capability_manifest,
    load_spell_payloads,
)


def _write_spell(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_spell_manifest_imports_canonicalized_spell_payloads(tmp_path: Path) -> None:
    _write_spell(
        tmp_path / "detect_magic.json",
        {
            "name": "Detect Magic",
            "meta": "Detect Magic 1st-level Divination",
            "casting_time": "1 action",
            "range": "30 feet",
            "duration": "Concentration, up to 1 minute",
            "description": "Sense magic around you.",
        },
    )

    payloads = load_spell_payloads(spells_dir=tmp_path)

    assert len(payloads) == 1
    assert payloads[0]["name"] == "Detect Magic"
    assert payloads[0]["level"] == 1
    assert payloads[0]["range_ft"] == 30


def test_spell_manifest_marks_executable_spells_supported() -> None:
    manifest = build_spell_capability_manifest(
        spell_payloads=[
            {
                "name": "Arc Flash",
                "type": "spell",
                "level": 1,
                "casting_time": "1 action",
                "description": "A bolt of force.",
                "mechanics": [{"effect_type": "damage", "damage": "2d6", "target": "single_enemy"}],
            }
        ]
    )

    record = manifest.records[0]
    assert record.content_id == "spell:arc_flash"
    assert record.content_type == "spell"
    assert record.support_state == "supported"
    assert record.states.executable is True
    assert record.states.blocked is False
    assert record.states.unsupported_reason is None


def test_spell_manifest_uses_missing_runtime_mechanics_reason() -> None:
    manifest = build_spell_capability_manifest(
        spell_payloads=[
            {
                "name": "Mystic Utility",
                "type": "spell",
                "level": 1,
                "casting_time": "1 action",
                "description": "Purely narrative effect.",
                "mechanics": [],
            }
        ]
    )

    record = manifest.records[0]
    assert record.support_state == "unsupported"
    assert record.states.blocked is True
    assert record.states.schema_valid is True
    assert record.states.unsupported_reason == "missing_runtime_mechanics"


def test_spell_manifest_uses_unsupported_effect_type_reason() -> None:
    manifest = build_spell_capability_manifest(
        spell_payloads=[
            {
                "name": "Storm Ring",
                "type": "spell",
                "level": 3,
                "casting_time": "1 action",
                "description": "An unsupported area spell stub.",
                "mechanics": [{"effect_type": "quantum_shift", "radius_ft": 20}],
            }
        ]
    )

    record = manifest.records[0]
    assert record.states.blocked is True
    assert record.states.schema_valid is True
    assert record.states.unsupported_reason == "unsupported_effect_type"


@pytest.mark.parametrize(
    "effect_type",
    ["aoe", "ranged_spell_attack", "melee_spell_attack", "save"],
)
def test_spell_manifest_marks_metadata_spell_effect_types_non_executable(effect_type: str) -> None:
    manifest = build_spell_capability_manifest(
        spell_payloads=[
            {
                "name": f"Spell Marker {effect_type}",
                "type": "spell",
                "level": 1,
                "casting_time": "1 action",
                "description": "Metadata-only spell effect marker.",
                "mechanics": [{"effect_type": effect_type}],
            }
        ]
    )

    record = manifest.records[0]
    assert record.support_state == "unsupported"
    assert record.states.executable is False
    assert record.states.blocked is True
    assert record.states.unsupported_reason == "non_executable_mechanics"


@pytest.mark.parametrize(
    "effect_type",
    ["aoe", "ranged_spell_attack", "melee_spell_attack", "save"],
)
def test_spell_manifest_accepts_metadata_effect_types_when_paired_with_runtime_effect(
    effect_type: str,
) -> None:
    manifest = build_spell_capability_manifest(
        spell_payloads=[
            {
                "name": f"Spell Marker + Damage {effect_type}",
                "type": "spell",
                "level": 1,
                "casting_time": "1 action",
                "description": "Metadata marker with executable effect.",
                "mechanics": [
                    {"effect_type": effect_type},
                    {"effect_type": "damage", "damage": "1d8", "target": "single_enemy"},
                ],
            }
        ]
    )

    record = manifest.records[0]
    assert record.support_state == "supported"
    assert record.states.executable is True
    assert record.states.blocked is False
    assert record.states.unsupported_reason is None


def test_spell_manifest_uses_invalid_mechanics_schema_reason() -> None:
    manifest = build_spell_capability_manifest(
        spell_payloads=[
            {
                "name": "Bad Bolt",
                "type": "spell",
                "level": 1,
                "casting_time": "1 action",
                "description": "Malformed damage mechanic.",
                "mechanics": [{"effect_type": "damage"}],
            }
        ]
    )

    record = manifest.records[0]
    assert record.states.blocked is True
    assert record.states.schema_valid is False
    assert record.states.unsupported_reason == "invalid_mechanics_schema"


def test_spell_manifest_canonical_dataset_has_coverage_and_single_reason_codes() -> None:
    manifest = build_spell_capability_manifest(spells_dir=DEFAULT_SPELLS_DIR)

    assert manifest.records
    assert all(record.content_type == "spell" for record in manifest.records)
    assert all(record.content_id.startswith("spell:") for record in manifest.records)
    assert any(record.states.executable for record in manifest.records)

    blocked = [record for record in manifest.records if record.states.blocked]
    assert blocked
    for record in blocked:
        assert record.states.unsupported_reason in {
            "missing_spell_name",
            "malformed_mechanics_payload",
            "missing_runtime_mechanics",
            "unsupported_effect_type",
            "invalid_mechanics_schema",
            "non_executable_mechanics",
        }


def test_spell_manifest_shard_a_cantrip_spell_ids_are_executable() -> None:
    manifest = build_spell_capability_manifest(spells_dir=DEFAULT_SPELLS_DIR)
    by_id = {record.content_id: record for record in manifest.records}

    shard_ids = {
        "spell:acid_splash",
        "spell:frostbite",
        "spell:infestation",
        "spell:mind_sliver",
        "spell:sacred_flame",
        "spell:sapping_sting",
        "spell:sword_burst",
        "spell:thunderclap",
        "spell:toll_the_dead",
        "spell:word_of_radiance",
    }
    for content_id in shard_ids:
        assert by_id[content_id].support_state == "supported"
        assert by_id[content_id].states.executable is True
        assert by_id[content_id].states.blocked is False


def test_spell_manifest_shard_b_spell_ids_are_executable() -> None:
    manifest = build_spell_capability_manifest(spells_dir=DEFAULT_SPELLS_DIR)
    by_id = {record.content_id: record for record in manifest.records}

    shard_ids = {
        "spell:abi_dalzim_s_horrid_wilting",
        "spell:aganazzar_s_scorcher",
        "spell:antagonize",
        "spell:backlash",
        "spell:befuddlement",
        "spell:bones_of_the_earth",
        "spell:cacophonic_shield",
        "spell:catapult",
        "spell:conjure_constructs",
        "spell:dark_star",
        "spell:dawn",
        "spell:dirge",
    }
    for content_id in shard_ids:
        assert by_id[content_id].support_state == "supported"
        assert by_id[content_id].states.executable is True
        assert by_id[content_id].states.blocked is False


def test_spell_manifest_shard_c_spell_ids_are_executable() -> None:
    manifest = build_spell_capability_manifest(spells_dir=DEFAULT_SPELLS_DIR)
    by_id = {record.content_id: record for record in manifest.records}

    shard_ids = {
        "spell:enervation",
        "spell:feeblemind",
        "spell:immolation",
        "spell:laeral_s_silver_lance",
        "spell:lightning_lure",
        "spell:maximilian_s_earthen_grasp",
        "spell:mind_spike",
        "spell:raulothim_s_psychic_lance",
        "spell:tasha_s_mind_whip",
        "spell:wardaway",
        "spell:time_ravage",
        "spell:yolande_s_regal_presence",
    }
    for content_id in shard_ids:
        assert by_id[content_id].support_state == "supported"
        assert by_id[content_id].states.executable is True
        assert by_id[content_id].states.blocked is False
