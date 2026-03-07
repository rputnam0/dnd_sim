from __future__ import annotations

import json
from pathlib import Path

from dnd_sim.capability_manifest import build_spell_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

SPELLS_DIR = Path("db/rules/2014/spells")
OWNED_SPELL_FILES = (
    "alarm.json",
    "chaos_bolt.json",
    "circle_of_death.json",
    "cloud_of_daggers.json",
    "conjure_barrage.json",
    "create_bonfire.json",
    "crown_of_stars.json",
    "death_armor.json",
    "delayed_blast_fireball.json",
    "draconic_transformation.json",
    "erupting_earth.json",
    "evard_s_black_tentacles.json",
    "fire_bolt.json",
    "globe_of_invulnerability.json",
    "guardian_of_faith.json",
    "hail_of_thorns.json",
    "hallucinatory_terrain.json",
    "ice_knife.json",
    "immovable_object.json",
    "light.json",
    "melf_s_acid_arrow.json",
    "mental_prison.json",
    "mordenkainen_s_private_sanctum.json",
    "move_earth.json",
    "negative_energy_flood.json",
    "ravenous_void.json",
    "soul_cage.json",
    "stinking_cloud.json",
    "tenser_s_transformation.json",
    "zephyr_strike.json",
)
OWNED_SPELL_IDS = {
    "spell:alarm",
    "spell:chaos_bolt",
    "spell:circle_of_death",
    "spell:cloud_of_daggers",
    "spell:conjure_barrage",
    "spell:create_bonfire",
    "spell:crown_of_stars",
    "spell:death_armor",
    "spell:delayed_blast_fireball",
    "spell:draconic_transformation",
    "spell:erupting_earth",
    "spell:evard_s_black_tentacles",
    "spell:fire_bolt",
    "spell:globe_of_invulnerability",
    "spell:guardian_of_faith",
    "spell:hail_of_thorns",
    "spell:hallucinatory_terrain",
    "spell:ice_knife",
    "spell:immovable_object",
    "spell:light",
    "spell:melf_s_acid_arrow",
    "spell:mental_prison",
    "spell:mordenkainen_s_private_sanctum",
    "spell:move_earth",
    "spell:negative_energy_flood",
    "spell:ravenous_void",
    "spell:soul_cage",
    "spell:stinking_cloud",
    "spell:tenser_s_transformation",
    "spell:zephyr_strike",
}


def _load_owned_spell_payloads() -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for filename in OWNED_SPELL_FILES:
        payload = json.loads((SPELLS_DIR / filename).read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        payloads.append(payload)
    return payloads


def _load_spell_payload(filename: str) -> dict[str, object]:
    payload = json.loads((SPELLS_DIR / filename).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _find_effect(
    payload: dict[str, object],
    effect_type: str,
    *,
    predicate: object | None = None,
) -> dict[str, object]:
    mechanics = payload.get("mechanics", [])
    assert isinstance(mechanics, list)
    for row in mechanics:
        if not isinstance(row, dict):
            continue
        if row.get("effect_type") != effect_type:
            continue
        if predicate is None or predicate(row):
            return row
    raise AssertionError(f"missing {effect_type!r} mechanic in {payload.get('name')!r}")


def test_w6_par_05l2_owned_spell_records_are_supported() -> None:
    manifest = build_spell_capability_manifest(spell_payloads=_load_owned_spell_payloads())
    by_id = {record.content_id: record for record in manifest.records}

    assert set(by_id) == OWNED_SPELL_IDS
    for content_id in OWNED_SPELL_IDS:
        record = by_id[content_id]
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.schema_valid is True
        assert record.states.executable is True
        assert record.states.unsupported_reason is None


def test_w6_par_05l2_owned_spell_mechanics_are_schema_valid() -> None:
    for payload in _load_owned_spell_payloads():
        assert validate_rule_mechanics_payload(kind="spell", payload=payload) == []


def test_w6_par_05l2_review_fixes_preserve_spell_fidelity() -> None:
    ravenous_void = _load_spell_payload("ravenous_void.json")
    ravenous_damage = _find_effect(
        ravenous_void,
        "damage",
        predicate=lambda row: row.get("damage_type") == "force",
    )
    assert ravenous_void["save_ability"] == "str"
    assert ravenous_damage["save_ability"] == "str"

    move_earth = _load_spell_payload("move_earth.json")
    move_earth_hazard = _find_effect(move_earth, "hazard")
    assert move_earth_hazard["duration_rounds"] == 1200

    create_bonfire = _load_spell_payload("create_bonfire.json")
    bonfire_damage = _find_effect(
        create_bonfire,
        "damage",
        predicate=lambda row: row.get("damage_type") == "fire",
    )
    assert bonfire_damage["scaling"] == [
        {"level": 5, "damage": "2d8"},
        {"level": 11, "damage": "3d8"},
        {"level": 17, "damage": "4d8"},
    ]

    ice_knife = _load_spell_payload("ice_knife.json")
    knife_burst_area = _find_effect(
        ice_knife,
        "aoe",
        predicate=lambda row: row.get("shape") == "sphere",
    )
    knife_burst_damage = _find_effect(
        ice_knife,
        "damage",
        predicate=lambda row: row.get("damage_type") == "cold",
    )
    assert knife_burst_area["radius"] == 5
    assert knife_burst_damage["damage"] == "2d6"
    assert knife_burst_damage["save"] == "dex"
    assert knife_burst_damage["half_on_success"] is True

    alarm = _load_spell_payload("alarm.json")
    alarm_area = _find_effect(
        alarm,
        "aoe",
        predicate=lambda row: row.get("shape") == "cube",
    )
    assert alarm_area["size"] == 20

    guardian_of_faith = _load_spell_payload("guardian_of_faith.json")
    guardian_damage = _find_effect(
        guardian_of_faith,
        "damage",
        predicate=lambda row: row.get("damage_type") == "radiant",
    )
    assert guardian_damage["damage"] == 20

    tenser_s_transformation = _load_spell_payload("tenser_s_transformation.json")
    tenser_temp_hp = _find_effect(tenser_s_transformation, "temp_hp")
    assert tenser_temp_hp["amount"] == 50
    assert isinstance(tenser_temp_hp["amount"], int)

    cloud_of_daggers = _load_spell_payload("cloud_of_daggers.json")
    cloud_hazard = _find_effect(cloud_of_daggers, "hazard")
    cloud_area = _find_effect(
        cloud_of_daggers,
        "aoe",
        predicate=lambda row: row.get("shape") == "cube",
    )
    assert cloud_hazard["radius_ft"] == 0
    assert cloud_hazard["shape"] == "cube"
    assert cloud_hazard["size"] == 5
    assert cloud_area["size"] == 5
