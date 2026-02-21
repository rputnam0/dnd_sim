from __future__ import annotations

import random

from dnd_sim.engine import (
    _apply_effect,
    _build_actor_from_character,
    _build_round_metadata,
    _execute_action,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState


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
        str_mod=2,
        dex_mod=2,
        con_mod=2,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 2, "dex": 2, "con": 2, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def test_build_actor_applies_passive_max_hp_trait() -> None:
    character = {
        "character_id": "hero",
        "name": "Hero",
        "class_level": "Fighter 8",
        "max_hp": 20,
        "ac": 15,
        "speed_ft": 30,
        "ability_scores": {
            "str": 16,
            "dex": 14,
            "con": 14,
            "int": 10,
            "wis": 10,
            "cha": 10,
        },
        "save_mods": {"str": 3, "dex": 2, "con": 2, "int": 0, "wis": 0, "cha": 0},
        "skill_mods": {},
        "attacks": [
            {"name": "Longsword", "to_hit": 6, "damage": "1d8+3", "damage_type": "slashing"}
        ],
        "resources": {},
        "traits": ["Tough"],
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }
    traits_db = {
        "tough": {
            "name": "Tough",
            "mechanics": [{"effect_type": "max_hp_increase", "calculation": "character_level * 2"}],
        }
    }

    actor = _build_actor_from_character(character, traits_db)

    assert actor.max_hp == 36
    assert actor.hp == 36


def test_grapple_action_executes_without_attribute_or_signature_errors(monkeypatch) -> None:
    monkeypatch.setattr("dnd_sim.rules_2014.run_contested_check", lambda *_args, **_kwargs: True)

    attacker = _base_actor(actor_id="attacker", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    action = ActionDefinition(name="grapple", action_type="grapple", action_cost="action")

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt = {attacker.actor_id: 0, target.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, target.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, target.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=random.Random(1),
        actor=attacker,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert "grappled" in target.conditions


def test_divine_smite_attack_does_not_crash_and_spends_slot() -> None:
    paladin = _base_actor(actor_id="paladin", team="party")
    paladin.traits = {"divine smite": {}}
    paladin.resources = {"spell_slot_1": 1}

    enemy = _base_actor(actor_id="enemy", team="enemy")
    enemy.ac = 1
    enemy.hp = 40
    enemy.max_hp = 40

    action = ActionDefinition(
        name="greatsword",
        action_type="attack",
        to_hit=20,
        damage="2d6+3",
        damage_type="slashing",
    )

    actors = {paladin.actor_id: paladin, enemy.actor_id: enemy}
    damage_dealt = {paladin.actor_id: 0, enemy.actor_id: 0}
    damage_taken = {paladin.actor_id: 0, enemy.actor_id: 0}
    threat_scores = {paladin.actor_id: 0, enemy.actor_id: 0}
    resources_spent = {paladin.actor_id: {}, enemy.actor_id: {}}

    _execute_action(
        rng=random.Random(2),
        actor=paladin,
        action=action,
        targets=[enemy],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert paladin.resources["spell_slot_1"] == 0
    assert damage_dealt[paladin.actor_id] > 0


def test_hazard_effect_uses_type_key_for_spatial_visibility() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    active_hazards: list[dict[str, object]] = []

    _apply_effect(
        effect={"effect_type": "hazard", "hazard_type": "magical_darkness", "duration": 10},
        rng=random.Random(3),
        actor=caster,
        target=target,
        damage_dealt={caster.actor_id: 0, target.actor_id: 0},
        damage_taken={caster.actor_id: 0, target.actor_id: 0},
        threat_scores={caster.actor_id: 0, target.actor_id: 0},
        resources_spent={caster.actor_id: {}, target.actor_id: {}},
        actors={caster.actor_id: caster, target.actor_id: target},
        active_hazards=active_hazards,
    )

    assert active_hazards and active_hazards[0].get("type") == "magical_darkness"


def test_round_metadata_includes_strategy_relevant_action_fields() -> None:
    actor = _base_actor(actor_id="mage", team="party")
    actor.actions = [
        ActionDefinition(
            name="fireball",
            action_type="save",
            save_dc=15,
            save_ability="dex",
            damage="8d6",
            damage_type="fire",
            range_ft=150,
            aoe_type="sphere",
            aoe_size_ft=20,
            mechanics=[
                {"effect_type": "apply_condition", "condition": "burning", "duration_rounds": 1}
            ],
            tags=["spell"],
        )
    ]

    metadata = _build_round_metadata(
        actors={actor.actor_id: actor},
        threat_scores={actor.actor_id: 0},
        burst_round_threshold=3,
    )

    action_row = metadata["action_catalog"][actor.actor_id][0]
    assert action_row["range_ft"] == 150
    assert action_row["aoe_type"] == "sphere"
    assert action_row["aoe_size_ft"] == 20
    assert action_row["mechanics"][0]["effect_type"] == "apply_condition"
    assert action_row["tags"] == ["spell"]
