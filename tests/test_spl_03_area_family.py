from __future__ import annotations

import random
from typing import Any

from dnd_sim.engine import (
    _break_concentration,
    _build_spell_actions,
    _execute_action,
    _extract_spells_from_raw_fields,
    _resolve_targets_for_action,
)
from dnd_sim.models import ActorRuntimeState
from dnd_sim.spatial import AABB
from dnd_sim.strategy_api import TargetRef


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self._values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self._values:
            raise AssertionError("RNG exhausted")
        return self._values.pop(0)


class NoRollRng:
    def randint(self, _a: int, _b: int) -> int:
        raise AssertionError("Action should be suppressed before rolling")


def _base_actor(*, actor_id: str, team: str, hp: int = 30) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=hp,
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
    range_text: str,
    duration_text: str = "Instantaneous",
) -> dict[str, Any]:
    return {
        "class_level": "Wizard 7",
        "ability_scores": {
            "str": 10,
            "dex": 14,
            "con": 12,
            "int": 18,
            "wis": 10,
            "cha": 8,
        },
        "raw_fields": [
            {"field": "spellSaveDC0", "value": "16"},
            {"field": "spellHeader1", "value": level_header},
            {"field": "spellName1", "value": name},
            {"field": "spellPrepared1", "value": "O"},
            {"field": "spellSaveHit1", "value": save_hit},
            {"field": "spellCastingTime1", "value": "1 action"},
            {"field": "spellRange1", "value": range_text},
            {"field": "spellDuration1", "value": duration_text},
            {"field": "spellComponents1", "value": "V, S, M"},
        ],
    }


def test_extract_area_family_infers_template_and_tagging(monkeypatch) -> None:
    monkeypatch.setattr(
        "dnd_sim.engine._load_spell_definition",
        lambda _name: {
            "name": "Fireball",
            "level": 3,
            "casting_time": "1 action",
            "range_ft": 150,
            "description": (
                "A bright streak flashes to a point you choose within range. "
                "Each creature in a 20-foot-radius sphere centered on that point "
                "must make a Dexterity saving throw. A creature takes 8d6 fire damage "
                "on a failed save, or half as much damage on a successful one."
            ),
            "mechanics": [],
        },
    )

    spells = _extract_spells_from_raw_fields(
        _sheet_payload_for_spell(
            name="Fireball",
            level_header="=== 3rd LEVEL ===",
            save_hit="DEX 16",
            range_text="150 ft",
        )
    )

    assert len(spells) == 1
    spell = spells[0]
    tags = set(spell.get("tags", []))
    assert spell["target_mode"] == "single_enemy"
    assert spell["aoe_type"] == "sphere"
    assert spell["aoe_size_ft"] == 20
    assert "spell_family:area" in tags
    assert "requires_sight" in tags
    assert "spell_family:single_target" not in tags


def test_area_family_pipeline_uses_template_resolution_golden(monkeypatch) -> None:
    monkeypatch.setattr(
        "dnd_sim.engine._load_spell_definition",
        lambda _name: {
            "name": "Fireball",
            "level": 3,
            "casting_time": "1 action",
            "range_ft": 150,
            "description": (
                "A bright streak flashes to a point you choose within range. "
                "Each creature in a 20-foot-radius sphere centered on that point "
                "must make a Dexterity saving throw. A creature takes 8d6 fire damage "
                "on a failed save, or half as much damage on a successful one."
            ),
            "mechanics": [],
        },
    )
    spell_rows = _extract_spells_from_raw_fields(
        _sheet_payload_for_spell(
            name="Fireball",
            level_header="=== 3rd LEVEL ===",
            save_hit="DEX 16",
            range_text="150 ft",
        )
    )
    action = _build_spell_actions(
        {"spells": spell_rows, "resources": {"spell_slots": {"3": 1}}},
        character_level=7,
    )[0]

    caster = _base_actor(actor_id="caster", team="party")
    primary = _base_actor(actor_id="primary", team="enemy")
    nearby = _base_actor(actor_id="nearby", team="enemy")
    far = _base_actor(actor_id="far", team="enemy")

    caster.position = (0.0, 0.0, 0.0)
    primary.position = (30.0, 0.0, 0.0)
    nearby.position = (40.0, 0.0, 0.0)
    far.position = (70.0, 0.0, 0.0)

    actors = {actor.actor_id: actor for actor in (caster, primary, nearby, far)}
    resolved = _resolve_targets_for_action(
        rng=random.Random(7),
        actor=caster,
        action=action,
        actors=actors,
        requested=[TargetRef("primary")],
    )

    assert {target.actor_id for target in resolved} == {"primary", "nearby"}


def test_area_family_invalid_origin_line_of_effect_blocks_cast(monkeypatch) -> None:
    monkeypatch.setattr(
        "dnd_sim.engine._load_spell_definition",
        lambda _name: {
            "name": "Fireball",
            "level": 3,
            "casting_time": "1 action",
            "range_ft": 150,
            "description": (
                "A bright streak flashes to a point you choose within range. "
                "Each creature in a 20-foot-radius sphere centered on that point "
                "must make a Dexterity saving throw."
            ),
            "mechanics": [],
        },
    )
    spell_rows = _extract_spells_from_raw_fields(
        _sheet_payload_for_spell(
            name="Fireball",
            level_header="=== 3rd LEVEL ===",
            save_hit="DEX 16",
            range_text="150 ft",
        )
    )
    action = _build_spell_actions(
        {"spells": spell_rows, "resources": {"spell_slots": {"3": 1}}},
        character_level=7,
    )[0]

    caster = _base_actor(actor_id="caster", team="party")
    primary = _base_actor(actor_id="primary", team="enemy")
    nearby = _base_actor(actor_id="nearby", team="enemy")

    caster.position = (0.0, 0.0, 0.0)
    primary.position = (30.0, 0.0, 0.0)
    nearby.position = (30.0, 10.0, 0.0)
    actors = {actor.actor_id: actor for actor in (caster, primary, nearby)}
    wall = [AABB(min_pos=(10.0, -2.0, -2.0), max_pos=(20.0, 2.0, 2.0), cover_level="TOTAL")]

    resolved = _resolve_targets_for_action(
        rng=random.Random(11),
        actor=caster,
        action=action,
        actors=actors,
        requested=[TargetRef("primary")],
        obstacles=wall,
    )

    assert resolved == []


def test_area_family_suppressed_by_antimagic_invalid_state(monkeypatch) -> None:
    monkeypatch.setattr(
        "dnd_sim.engine._load_spell_definition",
        lambda _name: {
            "name": "Fireball",
            "level": 3,
            "casting_time": "1 action",
            "range_ft": 150,
            "description": (
                "A bright streak flashes to a point you choose within range. "
                "Each creature in a 20-foot-radius sphere centered on that point "
                "must make a Dexterity saving throw. A creature takes 8d6 fire damage "
                "on a failed save, or half as much damage on a successful one."
            ),
            "mechanics": [],
        },
    )
    spell_rows = _extract_spells_from_raw_fields(
        _sheet_payload_for_spell(
            name="Fireball",
            level_header="=== 3rd LEVEL ===",
            save_hit="DEX 16",
            range_text="150 ft",
        )
    )
    action = _build_spell_actions(
        {"spells": spell_rows, "resources": {"spell_slots": {"3": 1}}},
        character_level=7,
    )[0]

    caster = _base_actor(actor_id="caster", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    caster.conditions.add("antimagic_suppressed")
    caster.position = (0.0, 0.0, 0.0)
    target.position = (20.0, 0.0, 0.0)

    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=NoRollRng(),
        actor=caster,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
        round_number=1,
        turn_token="1:caster",
    )

    assert target.hp == target.max_hp
    assert damage_dealt[caster.actor_id] == 0


def test_area_family_concentration_effects_clear_when_concentration_breaks(monkeypatch) -> None:
    monkeypatch.setattr(
        "dnd_sim.engine._load_spell_definition",
        lambda _name: {
            "name": "Grasping Frost",
            "level": 4,
            "casting_time": "1 action",
            "range_ft": 90,
            "concentration": True,
            "duration_rounds": 10,
            "description": (
                "Freezing mist bursts from a point you choose within range. "
                "Each creature in a 10-foot-radius sphere centered on that point "
                "must make a Wisdom saving throw."
            ),
            "mechanics": [
                {
                    "effect_type": "apply_condition",
                    "target": "target",
                    "condition": "restrained",
                    "apply_on": "save_fail",
                    "duration_rounds": 10,
                }
            ],
        },
    )
    spell_rows = _extract_spells_from_raw_fields(
        _sheet_payload_for_spell(
            name="Grasping Frost",
            level_header="=== 4th LEVEL ===",
            save_hit="WIS 16",
            range_text="90 ft",
            duration_text="Concentration, up to 1 minute",
        )
    )
    action = _build_spell_actions(
        {"spells": spell_rows, "resources": {"spell_slots": {"4": 1}}},
        character_level=7,
    )[0]

    caster = _base_actor(actor_id="caster", team="party")
    primary = _base_actor(actor_id="primary", team="enemy")
    nearby = _base_actor(actor_id="nearby", team="enemy")

    caster.position = (0.0, 0.0, 0.0)
    primary.position = (30.0, 0.0, 0.0)
    nearby.position = (35.0, 0.0, 0.0)

    actors = {actor.actor_id: actor for actor in (caster, primary, nearby)}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, primary, nearby)
    active_hazards: list[dict[str, object]] = []

    targets = _resolve_targets_for_action(
        rng=random.Random(17),
        actor=caster,
        action=action,
        actors=actors,
        requested=[TargetRef("primary")],
    )

    _execute_action(
        rng=FixedRng([1, 1]),
        actor=caster,
        action=action,
        targets=targets,
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert caster.concentrating is True
    assert "restrained" in primary.conditions
    assert "restrained" in nearby.conditions

    _break_concentration(caster, actors, active_hazards)

    assert caster.concentrating is False
    assert "restrained" not in primary.conditions
    assert "restrained" not in nearby.conditions
