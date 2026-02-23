from __future__ import annotations

import random

from dnd_sim.engine import (
    _apply_effect,
    _action_available,
    _build_actor_from_character,
    _build_round_metadata,
    _execute_action,
    _run_legendary_actions,
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


def test_build_actor_respects_current_hp_override_after_passives() -> None:
    character = {
        "character_id": "hero",
        "name": "Hero",
        "class_level": "Fighter 8",
        "max_hp": 20,
        "current_hp": 18,
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
    assert actor.hp == 18


def test_build_actor_applies_current_resources_override() -> None:
    character = {
        "character_id": "hero",
        "name": "Hero",
        "class_level": "Monk 8",
        "max_hp": 20,
        "ac": 15,
        "speed_ft": 30,
        "ability_scores": {
            "str": 10,
            "dex": 16,
            "con": 14,
            "int": 10,
            "wis": 14,
            "cha": 10,
        },
        "save_mods": {"str": 0, "dex": 3, "con": 2, "int": 0, "wis": 2, "cha": 0},
        "skill_mods": {},
        "attacks": [
            {"name": "Unarmed Strike", "to_hit": 6, "damage": "1d6+3", "damage_type": "bludgeoning"}
        ],
        "resources": {"ki": {"max": 8}},
        "current_resources": {"ki": 3},
        "traits": [],
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }

    actor = _build_actor_from_character(character, traits_db={})

    assert actor.max_resources["ki"] == 8
    assert actor.resources["ki"] == 3


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


def test_forced_movement_effect_updates_position() -> None:
    pusher = _base_actor(actor_id="pusher", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    pusher.position = (0.0, 0.0, 0.0)
    target.position = (0.0, 10.0, 0.0)

    _apply_effect(
        effect={
            "effect_type": "forced_movement",
            "distance_ft": 10,
            "direction": "away_from_source",
            "target": "target",
        },
        rng=random.Random(1),
        actor=pusher,
        target=target,
        damage_dealt={pusher.actor_id: 0, target.actor_id: 0},
        damage_taken={pusher.actor_id: 0, target.actor_id: 0},
        threat_scores={pusher.actor_id: 0, target.actor_id: 0},
        resources_spent={pusher.actor_id: {}, target.actor_id: {}},
        actors={pusher.actor_id: pusher, target.actor_id: target},
        active_hazards=[],
    )
    assert target.position == (0.0, 20.0, 0.0)

    _apply_effect(
        effect={
            "effect_type": "forced_movement",
            "distance_ft": 5,
            "direction": "toward_source",
            "target": "target",
        },
        rng=random.Random(1),
        actor=pusher,
        target=target,
        damage_dealt={pusher.actor_id: 0, target.actor_id: 0},
        damage_taken={pusher.actor_id: 0, target.actor_id: 0},
        threat_scores={pusher.actor_id: 0, target.actor_id: 0},
        resources_spent={pusher.actor_id: {}, target.actor_id: {}},
        actors={pusher.actor_id: pusher, target.actor_id: target},
        active_hazards=[],
    )
    assert target.position == (0.0, 15.0, 0.0)


def test_legendary_action_cost_tag_gates_availability() -> None:
    boss = _base_actor(actor_id="boss", team="enemy")
    boss.legendary_actions_remaining = 1
    expensive = ActionDefinition(
        name="tail_sweep",
        action_type="save",
        action_cost="legendary",
        save_dc=10,
        save_ability="str",
        tags=["legendary_cost:2"],
    )
    assert _action_available(boss, expensive) is False


def test_execute_action_ignores_non_dict_effect_entries() -> None:
    attacker = _base_actor(actor_id="attacker", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    action = ActionDefinition(
        name="legacy_spell",
        action_type="save",
        save_dc=12,
        save_ability="dex",
        damage="2d6",
        half_on_save=True,
        effects=["legacy_effect_string"],  # type: ignore[list-item]
        mechanics=["legacy_mechanic_string"],  # type: ignore[list-item]
    )

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt = {attacker.actor_id: 0, target.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, target.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, target.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=random.Random(11),
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

    assert damage_dealt[attacker.actor_id] >= 0


def test_legendary_action_runner_skips_untargetable_action() -> None:
    rng = random.Random(2)
    hero = _base_actor(actor_id="hero", team="party")
    boss = _base_actor(actor_id="boss", team="enemy")
    boss.legendary_actions_remaining = 1
    hero.ac = 1  # make sure attacks land

    untargetable = ActionDefinition(
        name="winch_pull",
        action_type="utility",
        action_cost="legendary",
        target_mode="single_enemy",
        effects=[{"effect_type": "forced_movement", "distance_ft": 20, "direction": "toward_source"}],
        tags=["requires_condition:grappled"],
    )
    strike = ActionDefinition(
        name="legendary_strike",
        action_type="attack",
        action_cost="legendary",
        to_hit=20,
        damage="1d4+1",
        target_mode="single_enemy",
    )
    boss.actions = [untargetable, strike]

    actors = {hero.actor_id: hero, boss.actor_id: boss}
    damage_dealt = {hero.actor_id: 0, boss.actor_id: 0}
    damage_taken = {hero.actor_id: 0, boss.actor_id: 0}
    threat_scores = {hero.actor_id: 0, boss.actor_id: 0}
    resources_spent = {hero.actor_id: {}, boss.actor_id: {}}

    _run_legendary_actions(
        rng=rng,
        trigger_actor=hero,
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert damage_dealt[boss.actor_id] > 0


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
