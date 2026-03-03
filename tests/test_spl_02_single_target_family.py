from __future__ import annotations

from typing import Any

from dnd_sim.engine import (
    _break_concentration,
    _build_spell_actions,
    _execute_action,
    _extract_spells_from_raw_fields,
)
from dnd_sim.models import ActorRuntimeState
from dnd_sim.spatial import AABB


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self._values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self._values:
            raise AssertionError("RNG exhausted")
        return self._values.pop(0)


class NoRollRng:
    def randint(self, _a: int, _b: int) -> int:
        raise AssertionError("Spell should be suppressed before rolling")


def _base_actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=24,
        hp=24,
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


def _hold_person_spell_definition() -> dict[str, Any]:
    return {
        "name": "Hold Person",
        "level": 2,
        "casting_time": "1 action",
        "range_ft": 60,
        "concentration": True,
        "duration_rounds": 10,
        "description": (
            "Choose a humanoid that you can see within range. "
            "The target must succeed on a Wisdom saving throw or be paralyzed for the duration."
        ),
        "mechanics": [],
    }


def _hold_person_sheet_payload() -> dict[str, Any]:
    return {
        "class_level": "Wizard 5",
        "ability_scores": {
            "str": 10,
            "dex": 14,
            "con": 12,
            "int": 18,
            "wis": 10,
            "cha": 8,
        },
        "raw_fields": [
            {"field": "spellSaveDC0", "value": "15"},
            {"field": "spellHeader2", "value": "=== 2nd LEVEL ==="},
            {"field": "spellName1", "value": "Hold Person"},
            {"field": "spellPrepared1", "value": "O"},
            {"field": "spellSaveHit1", "value": "WIS 15"},
            {"field": "spellCastingTime1", "value": "1 action"},
            {"field": "spellRange1", "value": "60 ft"},
            {"field": "spellDuration1", "value": "Concentration, up to 1 minute"},
            {"field": "spellComponents1", "value": "V, S, M"},
        ],
    }


def _sheet_payload_for_spell(
    *,
    name: str,
    level_header: str = "=== 1st LEVEL ===",
    save_hit: str = "",
    range_text: str = "60 ft",
    duration_text: str = "1 minute",
) -> dict[str, Any]:
    payload = {
        "class_level": "Cleric 5",
        "ability_scores": {
            "str": 10,
            "dex": 10,
            "con": 12,
            "int": 10,
            "wis": 18,
            "cha": 10,
        },
        "raw_fields": [
            {"field": "spellSaveDC0", "value": "15"},
            {"field": "spellHeader1", "value": level_header},
            {"field": "spellName1", "value": name},
            {"field": "spellPrepared1", "value": "O"},
            {"field": "spellCastingTime1", "value": "1 action"},
            {"field": "spellRange1", "value": range_text},
            {"field": "spellDuration1", "value": duration_text},
            {"field": "spellComponents1", "value": "V, S"},
        ],
    }
    if save_hit:
        payload["raw_fields"].append({"field": "spellSaveHit1", "value": save_hit})
    return payload


def test_extract_single_target_family_adds_condition_and_sight_metadata(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "dnd_sim.engine._load_spell_definition", lambda _name: _hold_person_spell_definition()
    )

    spells = _extract_spells_from_raw_fields(_hold_person_sheet_payload())

    assert len(spells) == 1
    spell = spells[0]
    assert spell["action_type"] == "save"
    assert spell["target_mode"] == "single_enemy"
    assert "spell_family:single_target" in spell["tags"]
    assert "requires_sight" in spell["tags"]
    assert {
        "effect_type": "apply_condition",
        "condition": "paralyzed",
        "target": "target",
        "apply_on": "save_fail",
        "duration_rounds": 10,
    } in spell["mechanics"]


def test_single_target_hold_person_applies_condition_and_clears_on_concentration_end(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "dnd_sim.engine._load_spell_definition", lambda _name: _hold_person_spell_definition()
    )

    spell_rows = _extract_spells_from_raw_fields(_hold_person_sheet_payload())
    actions = _build_spell_actions(
        {
            "spells": spell_rows,
            "resources": {"spell_slots": {"2": 1}},
        },
        character_level=5,
    )
    hold_person = next(action for action in actions if action.name == "Hold Person")

    caster = _base_actor(actor_id="caster", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    caster.position = (0.0, 0.0, 0.0)
    target.position = (30.0, 0.0, 0.0)

    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt = {caster.actor_id: 0, target.actor_id: 0}
    damage_taken = {caster.actor_id: 0, target.actor_id: 0}
    threat_scores = {caster.actor_id: 0, target.actor_id: 0}
    resources_spent = {caster.actor_id: {}, target.actor_id: {}}
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=FixedRng([1]),
        actor=caster,
        action=hold_person,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert "paralyzed" in target.conditions
    assert caster.concentrating is True
    assert caster.concentrated_spell == "Hold Person"

    _break_concentration(caster, actors, active_hazards)
    assert caster.concentrating is False
    assert "paralyzed" not in target.conditions


def test_negated_immunity_wording_does_not_infer_apply_condition(monkeypatch) -> None:
    monkeypatch.setattr(
        "dnd_sim.engine._load_spell_definition",
        lambda _name: {
            "name": "Ward of Calm",
            "level": 1,
            "casting_time": "1 action",
            "range_ft": 30,
            "duration_rounds": 10,
            "description": (
                "A friendly creature you can see within range can't be charmed and "
                "cannot be frightened while the spell lasts."
            ),
            "mechanics": [],
        },
    )
    spells = _extract_spells_from_raw_fields(
        _sheet_payload_for_spell(name="Ward of Calm", duration_text="1 minute")
    )

    assert len(spells) == 1
    mechanics = spells[0].get("mechanics", [])
    applied_conditions = {
        str(row.get("condition", "")).lower()
        for row in mechanics
        if isinstance(row, dict) and str(row.get("effect_type", "")).lower() == "apply_condition"
    }
    assert "charmed" not in applied_conditions
    assert "frightened" not in applied_conditions


def test_multi_target_wording_does_not_get_single_target_family_tag(monkeypatch) -> None:
    descriptions = (
        "Up to three creatures of your choice that you can see within range gain 5 temporary hit points.",
        "Choose one or more creatures that you can see within range.",
    )

    for index, description in enumerate(descriptions):
        monkeypatch.setattr(
            "dnd_sim.engine._load_spell_definition",
            lambda _name, _description=description, _index=index: {
                "name": f"Mass Mark {_index}",
                "level": 1,
                "casting_time": "1 action",
                "range_ft": 60,
                "duration_rounds": 10,
                "description": _description,
                "mechanics": [],
            },
        )
        spells = _extract_spells_from_raw_fields(
            _sheet_payload_for_spell(name=f"Mass Mark {index}", duration_text="1 minute")
        )

        assert len(spells) == 1
        tags = set(spells[0].get("tags", []))
        assert "spell_family:single_target" not in tags


def test_single_target_spell_suppressed_by_invalid_state_and_line_of_effect(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "dnd_sim.engine._load_spell_definition", lambda _name: _hold_person_spell_definition()
    )

    spell_rows = _extract_spells_from_raw_fields(_hold_person_sheet_payload())
    action = _build_spell_actions(
        {
            "spells": spell_rows,
            "resources": {"spell_slots": {"2": 1}},
        },
        character_level=5,
    )[0]

    caster = _base_actor(actor_id="caster", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    caster.position = (0.0, 0.0, 0.0)
    target.position = (30.0, 0.0, 0.0)
    actors = {caster.actor_id: caster, target.actor_id: target}
    trackers = {
        "damage_dealt": {caster.actor_id: 0, target.actor_id: 0},
        "damage_taken": {caster.actor_id: 0, target.actor_id: 0},
        "threat_scores": {caster.actor_id: 0, target.actor_id: 0},
        "resources_spent": {caster.actor_id: {}, target.actor_id: {}},
    }

    caster.conditions.add("blinded")
    _execute_action(
        rng=NoRollRng(),
        actor=caster,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=trackers["damage_dealt"],
        damage_taken=trackers["damage_taken"],
        threat_scores=trackers["threat_scores"],
        resources_spent=trackers["resources_spent"],
        active_hazards=[],
        round_number=1,
        turn_token="1:caster",
    )
    assert "paralyzed" not in target.conditions

    caster.conditions.clear()
    total_cover = [AABB(min_pos=(10.0, -1.0, -1.0), max_pos=(20.0, 1.0, 1.0), cover_level="TOTAL")]
    _execute_action(
        rng=NoRollRng(),
        actor=caster,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=trackers["damage_dealt"],
        damage_taken=trackers["damage_taken"],
        threat_scores=trackers["threat_scores"],
        resources_spent=trackers["resources_spent"],
        active_hazards=[],
        obstacles=total_cover,
        round_number=1,
        turn_token="1:caster",
    )
    assert "paralyzed" not in target.conditions
