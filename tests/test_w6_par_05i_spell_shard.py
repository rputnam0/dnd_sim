from __future__ import annotations

import random

from dnd_sim.engine_runtime import (
    _action_available,
    _break_concentration,
    _build_spell_actions,
    _execute_action,
    _extract_spells_from_raw_fields,
    _tick_conditions_for_actor,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self._values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self._values:
            raise AssertionError("RNG exhausted")
        return self._values.pop(0)


def _base_actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=30,
        hp=30,
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


def test_mind_spike_uses_primary_save_damage_and_tracked_condition() -> None:
    spell_row, action = _extract_action_from_sheet(
        name="Mind Spike",
        level_header="=== 2nd LEVEL ===",
        save_hit="WIS 18",
        duration_text="Concentration, up to 1 hour",
        range_text="60 ft",
        spell_level=2,
    )

    assert spell_row["damage"] == "3d8"
    assert action.damage == "3d8"
    assert not any(
        isinstance(effect, dict) and str(effect.get("effect_type", "")).lower() == "damage"
        for effect in action.mechanics
    )

    caster = _base_actor(actor_id="caster", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=FixedRng([4, 5, 6, 1]),
        actor=caster,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert target.hp == 15
    assert "mind_spiked" in target.conditions
    assert caster.concentrating is True

    _break_concentration(caster, actors, active_hazards)
    assert "mind_spiked" not in target.conditions


def test_tasha_s_mind_whip_uses_primary_save_damage_and_blocks_reactions() -> None:
    spell_row, action = _extract_action_from_sheet(
        name="Tasha's Mind Whip",
        level_header="=== 2nd LEVEL ===",
        save_hit="INT 18",
        duration_text="1 round",
        range_text="90 ft",
        spell_level=2,
    )

    assert spell_row["damage"] == "3d6"
    assert action.damage == "3d6"
    assert not any(
        isinstance(effect, dict) and str(effect.get("effect_type", "")).lower() == "damage"
        for effect in action.mechanics
    )

    caster = _base_actor(actor_id="caster", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    target.actions = [
        ActionDefinition(
            name="riposte",
            action_type="attack",
            action_cost="reaction",
            to_hit=0,
            damage="1",
        )
    ]
    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)

    _execute_action(
        rng=FixedRng([3, 4, 5, 1]),
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

    assert target.hp == 18
    assert "open_hand_no_reactions" in target.conditions
    assert _action_available(target, target.actions[0]) is False

    _tick_conditions_for_actor(random.Random(1), target, boundary="turn_start")
    assert "open_hand_no_reactions" in target.conditions
    _tick_conditions_for_actor(random.Random(2), target, boundary="turn_start")
    assert "open_hand_no_reactions" not in target.conditions


def test_time_ravage_promotes_primary_save_damage_and_applies_aged_condition() -> None:
    spell_row, action = _extract_action_from_sheet(
        name="Time Ravage",
        level_header="=== 9th LEVEL ===",
        save_hit="CON 18",
        duration_text="Instantaneous",
        range_text="90 ft",
        spell_level=9,
    )

    assert spell_row["damage"] == "10d12"
    assert action.damage == "10d12"
    assert not any(
        isinstance(effect, dict) and str(effect.get("effect_type", "")).lower() == "damage"
        for effect in action.mechanics
    )

    caster = _base_actor(actor_id="caster", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)

    _execute_action(
        rng=FixedRng([1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]),
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
    assert "time_ravaged" in target.conditions


def test_enervation_uses_primary_save_damage_without_double_counting() -> None:
    spell_row, action = _extract_action_from_sheet(
        name="Enervation",
        level_header="=== 5th LEVEL ===",
        save_hit="DEX 18",
        duration_text="Concentration, up to 1 minute",
        range_text="60 ft",
        spell_level=5,
    )

    assert spell_row["damage"] == "4d8"
    assert action.damage == "4d8"
    assert not any(
        isinstance(effect, dict) and str(effect.get("effect_type", "")).lower() == "damage"
        for effect in action.mechanics
    )

    caster = _base_actor(actor_id="caster", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)
    active_hazards: list[dict[str, object]] = []

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
        active_hazards=active_hazards,
    )

    assert target.hp == 26
    assert "enervated" in target.conditions
    assert caster.concentrating is True

    _break_concentration(caster, actors, active_hazards)
    assert "enervated" not in target.conditions
