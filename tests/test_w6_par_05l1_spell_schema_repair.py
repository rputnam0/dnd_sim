from __future__ import annotations

import json
from pathlib import Path

from dnd_sim.capability_manifest import build_spell_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

SPELLS_DIR = Path("db/rules/2014/spells")
OWNED_SPELL_SLUGS = (
    "antipathy_sympathy",
    "chill_touch",
    "dissonant_whispers",
    "gravity_sinkhole",
    "lightning_arrow",
    "shining_smite",
    "sickening_radiance",
    "symbol",
    "synaptic_static",
)


def _load_owned_spell_payloads() -> dict[str, dict[str, object]]:
    payloads: dict[str, dict[str, object]] = {}
    for slug in OWNED_SPELL_SLUGS:
        payload = json.loads((SPELLS_DIR / f"{slug}.json").read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        payloads[slug] = payload
    return payloads


def _find_effect(payload: dict[str, object], effect_type: str) -> dict[str, object]:
    mechanics = payload["mechanics"]
    assert isinstance(mechanics, list)
    for row in mechanics:
        assert isinstance(row, dict)
        if row.get("effect_type") == effect_type:
            return row
    raise AssertionError(f"Missing effect_type={effect_type!r} in {payload['name']}")


def test_w6_par_05l1_owned_spell_records_validate_cleanly() -> None:
    for slug, payload in _load_owned_spell_payloads().items():
        issues = validate_rule_mechanics_payload(kind="spell", payload=payload)
        assert issues == [], f"{slug} should be schema-valid, found: {issues}"


def test_w6_par_05l1_owned_spell_records_are_no_longer_invalid_schema_blockers() -> None:
    manifest = build_spell_capability_manifest(
        spell_payloads=list(_load_owned_spell_payloads().values())
    )
    by_id = {record.content_id: record for record in manifest.records}

    for slug in OWNED_SPELL_SLUGS:
        record = by_id[f"spell:{slug}"]
        assert record.states.schema_valid is True
        assert record.states.unsupported_reason != "invalid_mechanics_schema"


def test_w6_par_05l1_owned_spell_payloads_use_canonical_mechanics_keys() -> None:
    payloads = _load_owned_spell_payloads()

    antipathy_sympathy = payloads["antipathy_sympathy"]
    antipathy_pull = _find_effect(antipathy_sympathy, "forced_movement")
    assert antipathy_pull["distance_ft"] == 60

    chill_touch = payloads["chill_touch"]
    chill_touch_damage = _find_effect(chill_touch, "damage")
    assert chill_touch_damage["damage"] == "1d8"
    assert "dice" not in chill_touch_damage

    dissonant_whispers = payloads["dissonant_whispers"]
    dissonant_damage = _find_effect(dissonant_whispers, "damage")
    assert dissonant_damage["damage"] == "3d6"
    dissonant_movement = _find_effect(dissonant_whispers, "forced_movement")
    assert dissonant_movement["distance_ft"] == 30
    assert "distance" not in dissonant_movement

    gravity_sinkhole = payloads["gravity_sinkhole"]
    gravity_damage = _find_effect(gravity_sinkhole, "damage")
    assert gravity_damage["damage"] == "5d10"

    lightning_arrow = payloads["lightning_arrow"]
    lightning_damage = _find_effect(lightning_arrow, "damage")
    assert lightning_damage["damage"] == "4d8"
    lightning_aoe = _find_effect(lightning_arrow, "aoe")
    assert lightning_aoe["shape"] == "sphere"
    assert lightning_aoe["radius"] == 10

    shining_smite = payloads["shining_smite"]
    shining_damage = _find_effect(shining_smite, "extra_damage")
    assert shining_damage["damage"] == "2d6"
    shining_condition = _find_effect(shining_smite, "apply_condition")
    assert shining_condition["condition"] == "glowing"

    sickening_radiance = payloads["sickening_radiance"]
    sickening_area = _find_effect(sickening_radiance, "aoe")
    assert sickening_area["shape"] == "sphere"
    assert sickening_area["radius"] == 30
    sickening_damage = _find_effect(sickening_radiance, "damage")
    assert sickening_damage["damage"] == "4d10"

    symbol = payloads["symbol"]
    symbol_damage = _find_effect(symbol, "damage")
    assert symbol_damage["damage"] == "10d10"

    synaptic_static = payloads["synaptic_static"]
    synaptic_damage = _find_effect(synaptic_static, "damage")
    assert synaptic_damage["damage"] == "8d6"
    assert "dice" not in synaptic_damage
