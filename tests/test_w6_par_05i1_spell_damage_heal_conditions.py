from __future__ import annotations

import json
from pathlib import Path

from dnd_sim.capability_manifest import build_spell_capability_manifest
from dnd_sim.engine_runtime import (
    _build_spell_actions,
    _execute_action,
    _extract_spells_from_raw_fields,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState

SPELLS_DIR = Path("db/rules/2014/spells")
FIRST_SLICE = (
    "acid_arrow",
    "acid_splash_conjuration",
    "air_bubble",
    "alter_self",
    "antilife_shell",
)


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self._values = list(values)

    def randint(self, a: int, b: int) -> int:
        if not self._values:
            raise AssertionError("RNG exhausted")
        value = self._values.pop(0)
        assert a <= value <= b
        return value


def _load_slice_spell_payloads() -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for slug in FIRST_SLICE:
        payload = json.loads((SPELLS_DIR / f"{slug}.json").read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        payloads.append(payload)
    return payloads


def _spell_payload(slug: str) -> dict[str, object]:
    payload = json.loads((SPELLS_DIR / f"{slug}.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _find_effect(payload: dict[str, object], effect_type: str) -> dict[str, object]:
    mechanics = payload.get("mechanics")
    assert isinstance(mechanics, list)
    for row in mechanics:
        assert isinstance(row, dict)
        if row.get("effect_type") == effect_type:
            return row
    raise AssertionError(f"Missing effect_type={effect_type!r} on {payload['name']}")


def _actor(actor_id: str, team: str, *, hp: int = 30, max_hp: int = 30) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=max_hp,
        hp=hp,
        temp_hp=0,
        ac=12,
        initiative_mod=0,
        str_mod=0,
        dex_mod=0,
        con_mod=0,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def _trackers(
    *actors: ActorRuntimeState,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    damage_dealt = {actor.actor_id: 0 for actor in actors}
    damage_taken = {actor.actor_id: 0 for actor in actors}
    threat_scores = {actor.actor_id: 0 for actor in actors}
    resources_spent = {actor.actor_id: {} for actor in actors}
    return damage_dealt, damage_taken, threat_scores, resources_spent


def _sheet_payload_for_spell(
    *,
    name: str,
    level_header: str,
    save_hit: str,
    duration_text: str,
    range_text: str,
) -> dict[str, object]:
    return {
        "class_levels": {"wizard": 17},
        "ability_scores": {
            "str": 10,
            "dex": 14,
            "con": 14,
            "int": 20,
            "wis": 12,
            "cha": 10,
        },
        "raw_fields": [
            {"field": "spellSaveDC0", "value": "18"},
            {"field": "spellAtkBonus0", "value": "+11"},
            {"field": "spellHeader1", "value": level_header},
            {"field": "spellName1", "value": name},
            {"field": "spellPrepared1", "value": "O"},
            {"field": "spellSaveHit1", "value": save_hit},
            {"field": "spellCastingTime1", "value": "1 action"},
            {"field": "spellRange1", "value": range_text},
            {"field": "spellDuration1", "value": duration_text},
            {"field": "spellComponents1", "value": "V, S"},
        ],
    }


def _extract_action_from_sheet(
    *,
    name: str,
    level_header: str,
    save_hit: str,
    duration_text: str,
    range_text: str,
    spell_level: int,
) -> tuple[dict[str, object], ActionDefinition]:
    spell_rows = _extract_spells_from_raw_fields(
        _sheet_payload_for_spell(
            name=name,
            level_header=level_header,
            save_hit=save_hit,
            duration_text=duration_text,
            range_text=range_text,
        )
    )
    assert len(spell_rows) == 1
    actions = _build_spell_actions(
        {
            "class_levels": {"wizard": 17},
            "spells": spell_rows,
            "resources": {"spell_slots": {str(spell_level): 1}},
        },
        character_level=17,
    )
    return spell_rows[0], next(action for action in actions if action.name == name)


def test_w6_par_05i1_first_slice_records_are_supported() -> None:
    manifest = build_spell_capability_manifest(spell_payloads=_load_slice_spell_payloads())
    blocked = [record.content_id for record in manifest.records if record.states.blocked]

    assert blocked == []


def test_w6_par_05i1_first_slice_uses_canonical_effect_types() -> None:
    acid_arrow = _spell_payload("acid_arrow")
    assert _find_effect(acid_arrow, "damage")["damage"] == "4d4"

    acid_splash = _spell_payload("acid_splash_conjuration")
    assert _find_effect(acid_splash, "damage")["damage"] == "1d6"

    air_bubble = _spell_payload("air_bubble")
    assert _find_effect(air_bubble, "apply_condition")["condition"]

    alter_self = _spell_payload("alter_self")
    assert _find_effect(alter_self, "transform")["condition"]

    antilife_shell = _spell_payload("antilife_shell")
    assert _find_effect(antilife_shell, "hazard")["hazard_type"] == "antilife_shell"


def test_w6_par_05i1_acid_arrow_uses_primary_attack_damage_once() -> None:
    spell_row, action = _extract_action_from_sheet(
        name="Acid Arrow",
        level_header="=== 2nd LEVEL ===",
        save_hit="+11",
        duration_text="Instantaneous",
        range_text="90 ft",
        spell_level=2,
    )

    assert spell_row["damage"] == "4d4"
    assert action.damage == "4d4"
    assert not any(
        isinstance(effect, dict)
        and str(effect.get("effect_type", "")).lower() == "damage"
        and str(effect.get("apply_on", "")).lower() == "hit"
        for effect in action.mechanics
    )

    caster = _actor("caster", "party")
    target = _actor("target", "enemy")
    target.position = (10.0, 0.0, 0.0)
    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)

    _execute_action(
        rng=FixedRng([10, 1, 2, 3, 4]),
        actor=caster,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.hp == 20
    assert damage_dealt[caster.actor_id] == 10
    assert damage_taken[target.actor_id] == 10


def test_w6_par_05i1_acid_splash_uses_primary_save_damage_once() -> None:
    spell_row, action = _extract_action_from_sheet(
        name="Acid Splash Conjuration",
        level_header="=== CANTRIPS ===",
        save_hit="DEX 18",
        duration_text="Instantaneous",
        range_text="60 ft",
        spell_level=0,
    )

    assert spell_row["damage"] == "1d6"
    assert action.damage == "4d6"
    assert not any(
        isinstance(effect, dict) and str(effect.get("effect_type", "")).lower() == "damage"
        for effect in action.mechanics
    )

    caster = _actor("caster", "party")
    target = _actor("target", "enemy")
    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)

    _execute_action(
        rng=FixedRng([1, 1, 1, 1, 1]),
        actor=caster,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.hp == 26
    assert damage_dealt[caster.actor_id] == 4
    assert damage_taken[target.actor_id] == 4
