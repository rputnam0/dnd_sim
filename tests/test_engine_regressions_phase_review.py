from __future__ import annotations

import random
from pathlib import Path
from types import SimpleNamespace

import dnd_sim.engine as engine_module
from dnd_sim.engine import (
    _apply_effect,
    _action_available,
    _build_actor_from_character,
    _build_actor_views,
    _build_actor_from_enemy,
    _create_combat_timing_engine,
    _build_round_metadata,
    _execute_action,
    _refresh_legendary_actions_for_turn,
    _run_legendary_actions,
    _tick_conditions_for_actor,
    run_simulation,
)
from dnd_sim.io import load_character_db, load_scenario, load_strategy_registry
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.rules_2014 import DamageRollEvent
from tests.helpers import build_character, build_enemy
from tests.test_engine_integration import _setup_env


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


class _FixedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self.values:
            raise AssertionError("RNG exhausted")
        return self.values.pop(0)


SequenceRng = _FixedRng


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


def test_character_without_attacks_gets_single_copy_of_standard_actions() -> None:
    character = {
        "character_id": "scholar",
        "name": "Scholar",
        "class_level": "Wizard 5",
        "max_hp": 20,
        "ac": 12,
        "speed_ft": 30,
        "ability_scores": {"str": 8, "dex": 14, "con": 12, "int": 16, "wis": 10, "cha": 10},
        "save_mods": {},
        "skill_mods": {},
        "attacks": [],
        "resources": {},
        "traits": [],
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }

    actor = _build_actor_from_character(character, traits_db={})
    names = [action.name for action in actor.actions]
    assert names.count("dodge") == 1
    assert names.count("dash") == 1
    assert names.count("disengage") == 1
    assert names.count("ready") == 1


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


def test_divine_smite_bundle_resolves_weapon_and_radiant_against_slashing_resistance() -> None:
    paladin = _base_actor(actor_id="paladin", team="party")
    paladin.traits = {"divine smite": {}}
    paladin.resources = {"spell_slot_1": 1}

    enemy = _base_actor(actor_id="enemy", team="enemy")
    enemy.ac = 1
    enemy.hp = 30
    enemy.max_hp = 30
    enemy.damage_resistances = {"slashing"}

    action = ActionDefinition(
        name="longsword",
        action_type="attack",
        to_hit=20,
        damage="1",
        damage_type="slashing",
    )

    actors = {paladin.actor_id: paladin, enemy.actor_id: enemy}
    damage_dealt = {paladin.actor_id: 0, enemy.actor_id: 0}
    damage_taken = {paladin.actor_id: 0, enemy.actor_id: 0}
    threat_scores = {paladin.actor_id: 0, enemy.actor_id: 0}
    resources_spent = {paladin.actor_id: {}, enemy.actor_id: {}}

    _execute_action(
        rng=_FixedRng([15, 4, 4]),
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

    # Weapon slashing 1 -> 0 after resistance, smite radiant 2d8 -> 8
    assert damage_dealt[paladin.actor_id] == 8
    assert damage_taken[enemy.actor_id] == 8
    assert enemy.hp == 22
    assert paladin.resources["spell_slot_1"] == 0


def test_legacy_raw_damage_listener_adjustment_is_order_invariant_across_packet_permutations() -> (
    None
):
    def _run(*, reverse_bundle_packets: bool) -> int:
        paladin = _base_actor(actor_id="paladin", team="party")
        paladin.traits = {"divine smite": {}}
        paladin.resources = {"spell_slot_1": 1}

        enemy = _base_actor(actor_id="enemy", team="enemy")
        enemy.ac = 1
        enemy.hp = 30
        enemy.max_hp = 30
        enemy.damage_resistances = {"slashing"}

        action = ActionDefinition(
            name="longsword",
            action_type="attack",
            to_hit=20,
            damage="1",
            damage_type="slashing",
        )

        actors = {paladin.actor_id: paladin, enemy.actor_id: enemy}
        damage_dealt = {paladin.actor_id: 0, enemy.actor_id: 0}
        damage_taken = {paladin.actor_id: 0, enemy.actor_id: 0}
        threat_scores = {paladin.actor_id: 0, enemy.actor_id: 0}
        resources_spent = {paladin.actor_id: {}, enemy.actor_id: {}}
        timing_engine = _create_combat_timing_engine(include_default_rules=False)

        if reverse_bundle_packets:

            def _reverse_listener(event: DamageRollEvent) -> None:
                if event.bundle is None:
                    return
                event.bundle.packets = list(reversed(event.bundle.packets))
                event.raw_damage = event.bundle.raw_total

            timing_engine.subscribe(DamageRollEvent, _reverse_listener, priority=60)

        def _legacy_raw_damage_listener(event: DamageRollEvent) -> None:
            event.raw_damage = max(0, event.raw_damage - 1)

        timing_engine.subscribe(DamageRollEvent, _legacy_raw_damage_listener, priority=50)

        _execute_action(
            rng=_FixedRng([15, 4, 4]),
            actor=paladin,
            action=action,
            targets=[enemy],
            actors=actors,
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=[],
            timing_engine=timing_engine,
        )

        return damage_dealt[paladin.actor_id]

    baseline = _run(reverse_bundle_packets=False)
    permuted = _run(reverse_bundle_packets=True)

    assert baseline == permuted


def test_legacy_raw_listener_and_cutting_words_adjustments_stack_order_invariant() -> None:
    def _run(*, reverse_bundle_packets: bool) -> int:
        paladin = _base_actor(actor_id="paladin", team="party")
        paladin.traits = {"divine smite": {}}
        paladin.resources = {"spell_slot_1": 1}
        paladin.position = (0.0, 0.0, 0.0)

        target = _base_actor(actor_id="target", team="enemy")
        target.ac = 1
        target.hp = 30
        target.max_hp = 30
        target.position = (5.0, 0.0, 0.0)

        enemy_bard = _base_actor(actor_id="enemy_bard", team="enemy")
        enemy_bard.traits = {"cutting words": {}}
        enemy_bard.resources = {"bardic_inspiration": 1}
        enemy_bard.position = (10.0, 0.0, 0.0)

        action = ActionDefinition(
            name="longsword",
            action_type="attack",
            to_hit=20,
            damage="1",
            damage_type="slashing",
        )

        actors = {
            paladin.actor_id: paladin,
            target.actor_id: target,
            enemy_bard.actor_id: enemy_bard,
        }
        damage_dealt = {paladin.actor_id: 0, target.actor_id: 0, enemy_bard.actor_id: 0}
        damage_taken = {paladin.actor_id: 0, target.actor_id: 0, enemy_bard.actor_id: 0}
        threat_scores = {paladin.actor_id: 0, target.actor_id: 0, enemy_bard.actor_id: 0}
        resources_spent = {paladin.actor_id: {}, target.actor_id: {}, enemy_bard.actor_id: {}}
        timing_engine = _create_combat_timing_engine(include_default_rules=True)

        if reverse_bundle_packets:

            def _reverse_listener(event: DamageRollEvent) -> None:
                if event.bundle is None:
                    return
                event.bundle.packets = list(reversed(event.bundle.packets))
                event.raw_damage = event.bundle.raw_total

            timing_engine.subscribe(DamageRollEvent, _reverse_listener, priority=70)

        def _legacy_raw_damage_listener(event: DamageRollEvent) -> None:
            event.raw_damage = max(0, event.raw_damage - 1)

        timing_engine.subscribe(DamageRollEvent, _legacy_raw_damage_listener, priority=60)

        _execute_action(
            rng=_FixedRng([15, 4, 4, 2]),
            actor=paladin,
            action=action,
            targets=[target],
            actors=actors,
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=[],
            timing_engine=timing_engine,
        )

        return damage_dealt[paladin.actor_id]

    baseline = _run(reverse_bundle_packets=False)
    permuted = _run(reverse_bundle_packets=True)

    assert baseline == 6
    assert permuted == 6
    assert baseline == permuted


def test_legacy_raw_listener_and_uncanny_dodge_halving_stack_order_invariant() -> None:
    def _run(*, reverse_bundle_packets: bool) -> int:
        paladin = _base_actor(actor_id="paladin", team="party")
        paladin.traits = {"divine smite": {}}
        paladin.resources = {"spell_slot_1": 1}

        target = _base_actor(actor_id="target", team="enemy")
        target.ac = 1
        target.hp = 30
        target.max_hp = 30
        target.traits = {"uncanny dodge": {}}

        action = ActionDefinition(
            name="longsword",
            action_type="attack",
            to_hit=20,
            damage="1",
            damage_type="slashing",
        )

        actors = {paladin.actor_id: paladin, target.actor_id: target}
        damage_dealt = {paladin.actor_id: 0, target.actor_id: 0}
        damage_taken = {paladin.actor_id: 0, target.actor_id: 0}
        threat_scores = {paladin.actor_id: 0, target.actor_id: 0}
        resources_spent = {paladin.actor_id: {}, target.actor_id: {}}
        timing_engine = _create_combat_timing_engine(include_default_rules=True)

        if reverse_bundle_packets:

            def _reverse_listener(event: DamageRollEvent) -> None:
                if event.bundle is None:
                    return
                event.bundle.packets = list(reversed(event.bundle.packets))
                event.raw_damage = event.bundle.raw_total

            timing_engine.subscribe(DamageRollEvent, _reverse_listener, priority=70)

        def _legacy_raw_damage_listener(event: DamageRollEvent) -> None:
            event.raw_damage = max(0, event.raw_damage - 1)

        timing_engine.subscribe(DamageRollEvent, _legacy_raw_damage_listener, priority=60)

        _execute_action(
            rng=_FixedRng([15, 4, 4]),
            actor=paladin,
            action=action,
            targets=[target],
            actors=actors,
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=[],
            timing_engine=timing_engine,
        )

        return damage_dealt[paladin.actor_id]

    baseline = _run(reverse_bundle_packets=False)
    permuted = _run(reverse_bundle_packets=True)

    assert baseline == 4
    assert permuted == 4
    assert baseline == permuted


def test_empty_bundle_legacy_additive_raw_damage_survives_sync_and_applies() -> None:
    def _run(*, reverse_bundle_packets: bool) -> int:
        attacker = _base_actor(actor_id="attacker", team="party")
        target = _base_actor(actor_id="target", team="enemy")
        target.ac = 1
        target.hp = 30
        target.max_hp = 30

        action = ActionDefinition(
            name="club",
            action_type="attack",
            to_hit=20,
            damage="1",
            damage_type="slashing",
        )

        actors = {attacker.actor_id: attacker, target.actor_id: target}
        damage_dealt = {attacker.actor_id: 0, target.actor_id: 0}
        damage_taken = {attacker.actor_id: 0, target.actor_id: 0}
        threat_scores = {attacker.actor_id: 0, target.actor_id: 0}
        resources_spent = {attacker.actor_id: {}, target.actor_id: {}}
        timing_engine = _create_combat_timing_engine(include_default_rules=True)

        if reverse_bundle_packets:

            def _reverse_listener(event: DamageRollEvent) -> None:
                if event.bundle is None:
                    return
                event.bundle.packets = list(reversed(event.bundle.packets))
                event.raw_damage = event.bundle.raw_total

            timing_engine.subscribe(DamageRollEvent, _reverse_listener, priority=80)

        def _legacy_additive_listener(event: DamageRollEvent) -> None:
            if event.bundle is not None:
                event.bundle.packets = []
            event.raw_damage += 5

        timing_engine.subscribe(DamageRollEvent, _legacy_additive_listener, priority=60)

        _execute_action(
            rng=_FixedRng([15]),
            actor=attacker,
            action=action,
            targets=[target],
            actors=actors,
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=[],
            timing_engine=timing_engine,
        )
        return damage_dealt[attacker.actor_id]

    baseline = _run(reverse_bundle_packets=False)
    permuted = _run(reverse_bundle_packets=True)

    assert baseline == 6
    assert permuted == 6
    assert baseline == permuted


def test_empty_bundle_legacy_additive_then_cutting_words_is_order_invariant() -> None:
    def _run(*, reverse_bundle_packets: bool) -> int:
        attacker = _base_actor(actor_id="attacker", team="party")
        target = _base_actor(actor_id="target", team="enemy")
        target.ac = 1
        target.hp = 30
        target.max_hp = 30
        target.position = (5.0, 0.0, 0.0)
        attacker.position = (0.0, 0.0, 0.0)

        enemy_bard = _base_actor(actor_id="enemy_bard", team="enemy")
        enemy_bard.traits = {"cutting words": {}}
        enemy_bard.resources = {"bardic_inspiration": 1}
        enemy_bard.position = (10.0, 0.0, 0.0)

        action = ActionDefinition(
            name="club",
            action_type="attack",
            to_hit=20,
            damage="1",
            damage_type="slashing",
        )

        actors = {
            attacker.actor_id: attacker,
            target.actor_id: target,
            enemy_bard.actor_id: enemy_bard,
        }
        damage_dealt = {attacker.actor_id: 0, target.actor_id: 0, enemy_bard.actor_id: 0}
        damage_taken = {attacker.actor_id: 0, target.actor_id: 0, enemy_bard.actor_id: 0}
        threat_scores = {attacker.actor_id: 0, target.actor_id: 0, enemy_bard.actor_id: 0}
        resources_spent = {attacker.actor_id: {}, target.actor_id: {}, enemy_bard.actor_id: {}}
        timing_engine = _create_combat_timing_engine(include_default_rules=True)

        if reverse_bundle_packets:

            def _reverse_listener(event: DamageRollEvent) -> None:
                if event.bundle is None:
                    return
                event.bundle.packets = list(reversed(event.bundle.packets))
                event.raw_damage = event.bundle.raw_total

            timing_engine.subscribe(DamageRollEvent, _reverse_listener, priority=80)

        def _legacy_additive_listener(event: DamageRollEvent) -> None:
            if event.bundle is not None:
                event.bundle.packets = []
            event.raw_damage += 5

        timing_engine.subscribe(DamageRollEvent, _legacy_additive_listener, priority=60)

        _execute_action(
            rng=_FixedRng([15, 2]),
            actor=attacker,
            action=action,
            targets=[target],
            actors=actors,
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=[],
            timing_engine=timing_engine,
        )
        return damage_dealt[attacker.actor_id]

    baseline = _run(reverse_bundle_packets=False)
    permuted = _run(reverse_bundle_packets=True)

    assert baseline == 4
    assert permuted == 4
    assert baseline == permuted


def test_empty_bundle_legacy_additive_then_uncanny_dodge_is_order_invariant() -> None:
    def _run(*, reverse_bundle_packets: bool) -> int:
        attacker = _base_actor(actor_id="attacker", team="party")
        target = _base_actor(actor_id="target", team="enemy")
        target.ac = 1
        target.hp = 30
        target.max_hp = 30
        target.traits = {"uncanny dodge": {}}

        action = ActionDefinition(
            name="club",
            action_type="attack",
            to_hit=20,
            damage="1",
            damage_type="slashing",
        )

        actors = {attacker.actor_id: attacker, target.actor_id: target}
        damage_dealt = {attacker.actor_id: 0, target.actor_id: 0}
        damage_taken = {attacker.actor_id: 0, target.actor_id: 0}
        threat_scores = {attacker.actor_id: 0, target.actor_id: 0}
        resources_spent = {attacker.actor_id: {}, target.actor_id: {}}
        timing_engine = _create_combat_timing_engine(include_default_rules=True)

        if reverse_bundle_packets:

            def _reverse_listener(event: DamageRollEvent) -> None:
                if event.bundle is None:
                    return
                event.bundle.packets = list(reversed(event.bundle.packets))
                event.raw_damage = event.bundle.raw_total

            timing_engine.subscribe(DamageRollEvent, _reverse_listener, priority=80)

        def _legacy_additive_listener(event: DamageRollEvent) -> None:
            if event.bundle is not None:
                event.bundle.packets = []
            event.raw_damage += 5

        timing_engine.subscribe(DamageRollEvent, _legacy_additive_listener, priority=60)

        _execute_action(
            rng=_FixedRng([15]),
            actor=attacker,
            action=action,
            targets=[target],
            actors=actors,
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=[],
            timing_engine=timing_engine,
        )
        return damage_dealt[attacker.actor_id]

    baseline = _run(reverse_bundle_packets=False)
    permuted = _run(reverse_bundle_packets=True)

    assert baseline == 3
    assert permuted == 3
    assert baseline == permuted


def test_smite_variant_bonus_damage_is_consumed_on_first_melee_hit() -> None:
    paladin = _base_actor(actor_id="paladin", team="party")
    paladin.resources = {"spell_slot_1": 1}
    target = _base_actor(actor_id="target", team="enemy")
    target.hp = 30
    target.max_hp = 30

    smite_action = ActionDefinition(
        name="Thunderous Smite",
        action_type="utility",
        action_cost="bonus",
        target_mode="self",
        include_self=True,
        concentration=True,
        save_dc=14,
        save_ability="str",
        mechanics=[
            {"effect_type": "extra_damage", "damage": "2d6", "damage_type": "thunder"},
            {"effect_type": "apply_condition", "condition": "prone", "duration": 1},
        ],
        tags=["spell"],
    )
    weapon_attack = ActionDefinition(
        name="warhammer",
        action_type="attack",
        to_hit=7,
        damage="1",
        damage_type="bludgeoning",
    )

    actors = {paladin.actor_id: paladin, target.actor_id: target}
    damage_dealt = {paladin.actor_id: 0, target.actor_id: 0}
    damage_taken = {paladin.actor_id: 0, target.actor_id: 0}
    threat_scores = {paladin.actor_id: 0, target.actor_id: 0}
    resources_spent = {paladin.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=_FixedRng([15]),
        actor=paladin,
        action=smite_action,
        targets=[paladin],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    _execute_action(
        rng=_FixedRng([15, 3, 4, 1]),
        actor=paladin,
        action=weapon_attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    _execute_action(
        rng=_FixedRng([15, 15]),
        actor=paladin,
        action=weapon_attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.hp == 21
    assert "prone" in target.conditions


def test_improved_divine_smite_adds_radiant_damage_without_spending_slots() -> None:
    paladin = _base_actor(actor_id="paladin", team="party")
    paladin.traits = {"improved divine smite": {}}
    paladin.resources = {"spell_slot_1": 0}
    target = _base_actor(actor_id="target", team="enemy")
    target.hp = 25
    target.max_hp = 25

    action = ActionDefinition(
        name="longsword",
        action_type="attack",
        to_hit=7,
        damage="1",
        damage_type="slashing",
    )

    actors = {paladin.actor_id: paladin, target.actor_id: target}
    damage_dealt = {paladin.actor_id: 0, target.actor_id: 0}
    damage_taken = {paladin.actor_id: 0, target.actor_id: 0}
    threat_scores = {paladin.actor_id: 0, target.actor_id: 0}
    resources_spent = {paladin.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=_FixedRng([15, 4]),
        actor=paladin,
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
    assert paladin.resources["spell_slot_1"] == 0
    assert resources_spent[paladin.actor_id].get("spell_slot_1", 0) == 0


def test_smite_of_protection_window_grants_and_expires_half_cover_bonus() -> None:
    paladin = _base_actor(actor_id="paladin", team="party")
    paladin.level = 8
    paladin.traits = {
        "divine smite": {},
        "smite of protection": {},
        "aura of protection": {},
    }
    paladin.resources = {"spell_slot_1": 1}

    ally = _base_actor(actor_id="ally", team="party")
    ally.ac = 12
    ally.position = (5.0, 0.0, 0.0)

    enemy = _base_actor(actor_id="enemy", team="enemy")
    enemy.ac = 1
    enemy.position = (10.0, 0.0, 0.0)

    paladin.position = (0.0, 0.0, 0.0)
    paladin.movement_remaining = 30.0

    smite_attack = ActionDefinition(
        name="warhammer",
        action_type="attack",
        to_hit=10,
        damage="1",
        damage_type="bludgeoning",
    )
    enemy_attack = ActionDefinition(
        name="claw",
        action_type="attack",
        to_hit=3,
        damage="1",
        damage_type="slashing",
    )

    actors = {paladin.actor_id: paladin, ally.actor_id: ally, enemy.actor_id: enemy}
    damage_dealt = {paladin.actor_id: 0, ally.actor_id: 0, enemy.actor_id: 0}
    damage_taken = {paladin.actor_id: 0, ally.actor_id: 0, enemy.actor_id: 0}
    threat_scores = {paladin.actor_id: 0, ally.actor_id: 0, enemy.actor_id: 0}
    resources_spent = {paladin.actor_id: {}, ally.actor_id: {}, enemy.actor_id: {}}

    _execute_action(
        rng=_FixedRng([15, 1, 1]),
        actor=paladin,
        action=smite_attack,
        targets=[enemy],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    assert "smite_of_protection_window" in paladin.conditions

    _execute_action(
        rng=_FixedRng([10]),
        actor=enemy,
        action=enemy_attack,
        targets=[ally],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    assert ally.hp == ally.max_hp

    _tick_conditions_for_actor(_FixedRng([1]), paladin)
    assert "smite_of_protection_window" not in paladin.conditions

    _execute_action(
        rng=_FixedRng([10]),
        actor=enemy,
        action=enemy_attack,
        targets=[ally],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    assert ally.hp == ally.max_hp - 1


def test_lay_on_hands_pool_heals_by_missing_hp_and_tracks_spend() -> None:
    character = {
        "character_id": "paladin",
        "name": "Paladin",
        "class_level": "Paladin 5",
        "max_hp": 40,
        "ac": 16,
        "speed_ft": 30,
        "ability_scores": {
            "str": 16,
            "dex": 10,
            "con": 14,
            "int": 8,
            "wis": 10,
            "cha": 16,
        },
        "save_mods": {"str": 3, "dex": 0, "con": 2, "int": -1, "wis": 0, "cha": 3},
        "skill_mods": {},
        "attacks": [{"name": "mace", "to_hit": 6, "damage": "1d6+3", "damage_type": "bludgeoning"}],
        "resources": {"spell_slots": {"1": 4, "2": 2}},
        "traits": ["Lay on Hands"],
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }
    paladin = _build_actor_from_character(character, traits_db={})
    ally = _base_actor(actor_id="ally", team="party")
    ally.max_hp = 20
    ally.hp = 3

    action = next(a for a in paladin.actions if a.name == "lay_on_hands")

    actors = {paladin.actor_id: paladin, ally.actor_id: ally}
    damage_dealt = {paladin.actor_id: 0, ally.actor_id: 0}
    damage_taken = {paladin.actor_id: 0, ally.actor_id: 0}
    threat_scores = {paladin.actor_id: 0, ally.actor_id: 0}
    resources_spent = {paladin.actor_id: {}, ally.actor_id: {}}

    _execute_action(
        rng=_FixedRng([1]),
        actor=paladin,
        action=action,
        targets=[ally],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert paladin.max_resources["lay_on_hands_pool"] == 25
    assert paladin.resources["lay_on_hands_pool"] == 8
    assert resources_spent[paladin.actor_id]["lay_on_hands_pool"] == 17
    assert ally.hp == 20


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


def test_refresh_legendary_actions_for_turn_uses_explicit_pool_or_default() -> None:
    boss = _base_actor(actor_id="boss", team="enemy")
    boss.actions = [
        ActionDefinition(
            name="tail_tap",
            action_type="attack",
            action_cost="legendary",
            to_hit=8,
            damage="1",
        )
    ]
    boss.resources["legendary_actions"] = 2
    boss.legendary_actions_remaining = 0

    _refresh_legendary_actions_for_turn(boss)
    assert boss.legendary_actions_remaining == 2

    boss.resources["legendary_actions"] = 0
    boss.legendary_actions_remaining = 0

    _refresh_legendary_actions_for_turn(boss)
    assert boss.legendary_actions_remaining == 3


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
        effects=[
            {"effect_type": "forced_movement", "distance_ft": 20, "direction": "toward_source"}
        ],
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


def test_build_actor_views_accepts_extended_actor_fields() -> None:
    actor = _base_actor(actor_id="ranger", team="party")
    actor.speed_ft = 35
    actor.movement_remaining = 20.0
    actor.position = (5.0, 10.0, 0.0)
    actor.traits = {"alert": {}}
    view = _build_actor_views(
        actors={actor.actor_id: actor},
        actor_order=[actor.actor_id],
        round_number=1,
        metadata={},
    )
    assert view.actors[actor.actor_id].speed_ft == 35
    assert view.actors[actor.actor_id].position == (5.0, 10.0, 0.0)


def test_save_action_rolls_damage_once_and_spends_empowered_spell_once() -> None:
    class SequenceRng:
        def __init__(self, values: list[int]) -> None:
            self.values = list(values)

        def randint(self, _a: int, _b: int) -> int:
            if not self.values:
                raise AssertionError("RNG exhausted")
            return self.values.pop(0)

    caster = _base_actor(actor_id="caster", team="party")
    caster.traits = {"empowered_spell": {}}
    caster.cha_mod = 3
    caster.resources = {"sorcery_points": 3}
    target_a = _base_actor(actor_id="a", team="enemy")
    target_b = _base_actor(actor_id="b", team="enemy")
    for target in (target_a, target_b):
        target.save_mods["dex"] = 0

    # rng draws:
    # 1) raw AoE damage 1d6 -> 2
    # 2) reroll lowest die from empowered spell -> 6
    # 3) target A save roll -> 1 (fail)
    # 4) target B save roll -> 1 (fail)
    rng = SequenceRng([2, 6, 1, 1])

    action = ActionDefinition(
        name="fire pulse",
        action_type="save",
        save_dc=15,
        save_ability="dex",
        damage="1d6",
        damage_type="fire",
        tags=["spell"],
    )

    actors = {caster.actor_id: caster, target_a.actor_id: target_a, target_b.actor_id: target_b}
    damage_dealt = {caster.actor_id: 0, target_a.actor_id: 0, target_b.actor_id: 0}
    damage_taken = {caster.actor_id: 0, target_a.actor_id: 0, target_b.actor_id: 0}
    threat_scores = {caster.actor_id: 0, target_a.actor_id: 0, target_b.actor_id: 0}
    resources_spent = {caster.actor_id: {}, target_a.actor_id: {}, target_b.actor_id: {}}

    _execute_action(
        rng=rng,
        actor=caster,
        action=action,
        targets=[target_a, target_b],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target_a.hp == 24
    assert target_b.hp == 24
    assert caster.resources["sorcery_points"] == 2
    assert resources_spent[caster.actor_id]["sorcery_points"] == 1


def test_enemy_builder_prefers_explicit_ability_mods_over_save_mods() -> None:
    enemy = SimpleNamespace(
        identity=SimpleNamespace(enemy_id="ogre", name="Ogre", team="enemy"),
        stat_block=SimpleNamespace(
            max_hp=59,
            ac=11,
            initiative_mod=0,
            str_mod=4,
            dex_mod=-1,
            con_mod=3,
            int_mod=-3,
            wis_mod=-2,
            cha_mod=-2,
            save_mods={"str": 7, "dex": 1, "con": 6, "int": 0, "wis": 1, "cha": 1},
        ),
        actions=[
            SimpleNamespace(
                name="club",
                action_type="attack",
                to_hit=6,
                damage="2d8+4",
                damage_type="bludgeoning",
                attack_count=1,
                save_dc=None,
                save_ability=None,
                half_on_save=False,
                resource_cost={},
                recharge=None,
                max_uses=None,
                action_cost="action",
                target_mode="single_enemy",
                max_targets=None,
                concentration=False,
                include_self=False,
                effects=[],
                tags=[],
            )
        ],
        bonus_actions=[],
        reactions=[],
        legendary_actions=[],
        lair_actions=[],
        resources={},
        damage_resistances=[],
        damage_immunities=[],
        damage_vulnerabilities=[],
        condition_immunities=[],
        script_hooks={},
        traits=[],
    )

    actor = _build_actor_from_enemy(enemy)

    assert actor.str_mod == 4
    assert actor.int_mod == -3
    assert actor.wis_mod == -2
    assert actor.cha_mod == -2


def test_moving_out_of_melee_reach_triggers_opportunity_attack() -> None:
    mover = _base_actor(actor_id="mover", team="party")
    guard = _base_actor(actor_id="guard", team="enemy")
    target = _base_actor(actor_id="target", team="enemy")

    mover.position = (0.0, 0.0, 0.0)
    guard.position = (5.0, 0.0, 0.0)
    target.position = (30.0, 0.0, 0.0)

    mover.speed_ft = 30
    mover.movement_remaining = 30.0
    mover_attack = ActionDefinition(
        name="slash",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1d4",
        damage_type="slashing",
        range_ft=5,
    )
    mover.actions = [mover_attack]
    guard.actions = [
        ActionDefinition(
            name="spear",
            action_type="attack",
            action_cost="action",
            to_hit=20,
            damage="1d4",
            damage_type="piercing",
            range_ft=5,
        )
    ]

    actors = {mover.actor_id: mover, guard.actor_id: guard, target.actor_id: target}
    damage_dealt = {mover.actor_id: 0, guard.actor_id: 0, target.actor_id: 0}
    damage_taken = {mover.actor_id: 0, guard.actor_id: 0, target.actor_id: 0}
    threat_scores = {mover.actor_id: 0, guard.actor_id: 0, target.actor_id: 0}
    resources_spent = {mover.actor_id: {}, guard.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=random.Random(11),
        actor=mover,
        action=mover_attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert mover.position[0] > 0.0
    assert guard.reaction_available is False
    assert mover.hp < mover.max_hp


def test_disengaging_movement_does_not_trigger_opportunity_attack() -> None:
    mover = _base_actor(actor_id="mover", team="party")
    guard = _base_actor(actor_id="guard", team="enemy")
    target = _base_actor(actor_id="target", team="enemy")

    mover.position = (0.0, 0.0, 0.0)
    guard.position = (5.0, 0.0, 0.0)
    target.position = (30.0, 0.0, 0.0)
    mover.conditions.add("disengaging")

    mover.speed_ft = 30
    mover.movement_remaining = 30.0
    mover_attack = ActionDefinition(
        name="slash",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1d4",
        damage_type="slashing",
        range_ft=5,
    )
    mover.actions = [mover_attack]
    guard.actions = [
        ActionDefinition(
            name="spear",
            action_type="attack",
            action_cost="action",
            to_hit=20,
            damage="1d4",
            damage_type="piercing",
            range_ft=5,
        )
    ]

    actors = {mover.actor_id: mover, guard.actor_id: guard, target.actor_id: target}
    damage_dealt = {mover.actor_id: 0, guard.actor_id: 0, target.actor_id: 0}
    damage_taken = {mover.actor_id: 0, guard.actor_id: 0, target.actor_id: 0}
    threat_scores = {mover.actor_id: 0, guard.actor_id: 0, target.actor_id: 0}
    resources_spent = {mover.actor_id: {}, guard.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=random.Random(12),
        actor=mover,
        action=mover_attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert mover.position[0] > 0.0
    assert guard.reaction_available is True
    assert mover.hp == mover.max_hp


def test_attack_out_of_range_after_movement_is_invalidated() -> None:
    class NoRollRng:
        def randint(self, _a: int, _b: int) -> int:
            raise AssertionError("Attack roll should not happen when target remains out of range")

    attacker = _base_actor(actor_id="attacker", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    attacker.position = (0.0, 0.0, 0.0)
    target.position = (100.0, 0.0, 0.0)
    attacker.speed_ft = 30
    attacker.movement_remaining = 30.0

    attack = ActionDefinition(
        name="shortsword",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1d8+4",
        damage_type="piercing",
        range_ft=5,
    )
    attacker.actions = [attack]

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt = {attacker.actor_id: 0, target.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, target.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, target.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=NoRollRng(),
        actor=attacker,
        action=attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.hp == target.max_hp
    assert damage_dealt[attacker.actor_id] == 0
    assert attacker.movement_remaining == 0.0


def test_restrained_actor_cannot_move_to_reach_target() -> None:
    class NoRollRng:
        def randint(self, _a: int, _b: int) -> int:
            raise AssertionError("Restrained actor should not be able to attack out of reach")

    attacker = _base_actor(actor_id="attacker", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    attacker.position = (0.0, 0.0, 0.0)
    target.position = (20.0, 0.0, 0.0)
    attacker.speed_ft = 30
    attacker.movement_remaining = 30.0
    attacker.conditions.add("restrained")

    attack = ActionDefinition(
        name="shortsword",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1d8+4",
        damage_type="piercing",
        range_ft=5,
    )
    attacker.actions = [attack]

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt = {attacker.actor_id: 0, target.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, target.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, target.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=NoRollRng(),
        actor=attacker,
        action=attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert attacker.position == (0.0, 0.0, 0.0)
    assert attacker.movement_remaining == 30.0
    assert target.hp == target.max_hp


def test_prone_actor_stands_then_moves_into_range() -> None:
    actor = _base_actor(actor_id="attacker", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    actor.position = (0.0, 0.0, 0.0)
    target.position = (20.0, 0.0, 0.0)
    actor.speed_ft = 30
    actor.movement_remaining = 30.0
    actor.conditions.add("prone")

    attack = ActionDefinition(
        name="shortsword",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1d4",
        damage_type="piercing",
        range_ft=5,
    )
    actor.actions = [attack]

    actors = {actor.actor_id: actor, target.actor_id: target}
    damage_dealt = {actor.actor_id: 0, target.actor_id: 0}
    damage_taken = {actor.actor_id: 0, target.actor_id: 0}
    threat_scores = {actor.actor_id: 0, target.actor_id: 0}
    resources_spent = {actor.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=random.Random(16),
        actor=actor,
        action=attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert actor.position == (15.0, 0.0, 0.0)
    assert actor.movement_remaining == 0.0
    assert "prone" not in actor.conditions
    assert target.hp < target.max_hp


def test_ready_action_triggers_readied_attack_on_enemy_turn() -> None:
    ready_actor = _base_actor(actor_id="ready_actor", team="party")
    ally = _base_actor(actor_id="ally", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")
    ready_actor.position = (0.0, 0.0, 0.0)
    enemy.position = (5.0, 0.0, 0.0)
    ally.position = (10.0, 0.0, 0.0)

    ready_action = ActionDefinition(name="ready", action_type="utility", action_cost="action")
    basic_attack = ActionDefinition(
        name="basic",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1d4",
        damage_type="slashing",
        range_ft=5,
    )
    ready_actor.actions = [ready_action, basic_attack]

    actors = {ready_actor.actor_id: ready_actor, ally.actor_id: ally, enemy.actor_id: enemy}
    damage_dealt = {ready_actor.actor_id: 0, ally.actor_id: 0, enemy.actor_id: 0}
    damage_taken = {ready_actor.actor_id: 0, ally.actor_id: 0, enemy.actor_id: 0}
    threat_scores = {ready_actor.actor_id: 0, ally.actor_id: 0, enemy.actor_id: 0}
    resources_spent = {ready_actor.actor_id: {}, ally.actor_id: {}, enemy.actor_id: {}}

    _execute_action(
        rng=random.Random(13),
        actor=ready_actor,
        action=ready_action,
        targets=[enemy],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert "readying" in ready_actor.conditions

    trigger_ready = getattr(engine_module, "_trigger_readied_actions")

    trigger_ready(
        rng=random.Random(14),
        trigger_actor=ally,
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    assert enemy.hp == enemy.max_hp
    assert ready_actor.reaction_available is True

    trigger_ready(
        rng=random.Random(15),
        trigger_actor=enemy,
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    assert enemy.hp < enemy.max_hp
    assert ready_actor.reaction_available is False
    assert "readying" not in ready_actor.conditions


def test_moving_through_reach_then_leaving_triggers_opportunity_attack() -> None:
    mover = _base_actor(actor_id="mover", team="party")
    guard = _base_actor(actor_id="guard", team="enemy")
    target = _base_actor(actor_id="target", team="enemy")

    mover.position = (0.0, 0.0, 0.0)
    guard.position = (15.0, 0.0, 0.0)
    target.position = (35.0, 0.0, 0.0)

    mover.speed_ft = 30
    mover.movement_remaining = 30.0
    mover_attack = ActionDefinition(
        name="slash",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1d4",
        damage_type="slashing",
        range_ft=5,
    )
    mover.actions = [mover_attack]
    guard.actions = [
        ActionDefinition(
            name="spear",
            action_type="attack",
            action_cost="action",
            to_hit=20,
            damage="1d4",
            damage_type="piercing",
            range_ft=5,
        )
    ]

    actors = {mover.actor_id: mover, guard.actor_id: guard, target.actor_id: target}
    damage_dealt = {mover.actor_id: 0, guard.actor_id: 0, target.actor_id: 0}
    damage_taken = {mover.actor_id: 0, guard.actor_id: 0, target.actor_id: 0}
    threat_scores = {mover.actor_id: 0, guard.actor_id: 0, target.actor_id: 0}
    resources_spent = {mover.actor_id: {}, guard.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=SequenceRng([15, 3, 15, 3]),
        actor=mover,
        action=mover_attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert guard.reaction_available is False
    assert mover.hp < mover.max_hp


def test_reach_weapon_triggers_opportunity_attack_at_reach_boundary() -> None:
    mover = _base_actor(actor_id="mover", team="party")
    guard = _base_actor(actor_id="guard", team="enemy")
    target = _base_actor(actor_id="target", team="enemy")

    mover.position = (9.0, 0.0, 0.0)
    guard.position = (0.0, 0.0, 0.0)
    target.position = (25.0, 0.0, 0.0)

    mover.speed_ft = 30
    mover.movement_remaining = 30.0
    mover_attack = ActionDefinition(
        name="slash",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1d4",
        damage_type="slashing",
        range_ft=5,
    )
    mover.actions = [mover_attack]
    guard.actions = [
        ActionDefinition(
            name="pike_thrust",
            action_type="attack",
            action_cost="action",
            to_hit=20,
            damage="1d4",
            damage_type="piercing",
            attack_profile_id="attack_guard_pike",
            weapon_id="weapon_pike",
            item_id="item_pike",
            weapon_properties=["reach"],
            reach_ft=10,
            range_ft=10,
            range_normal_ft=10,
            range_long_ft=10,
        )
    ]

    actors = {mover.actor_id: mover, guard.actor_id: guard, target.actor_id: target}
    damage_dealt = {mover.actor_id: 0, guard.actor_id: 0, target.actor_id: 0}
    damage_taken = {mover.actor_id: 0, guard.actor_id: 0, target.actor_id: 0}
    threat_scores = {mover.actor_id: 0, guard.actor_id: 0, target.actor_id: 0}
    resources_spent = {mover.actor_id: {}, guard.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=SequenceRng([15, 3, 15, 3]),
        actor=mover,
        action=mover_attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert guard.reaction_available is False
    assert mover.hp < mover.max_hp


def test_ranged_attack_against_prone_target_has_disadvantage() -> None:
    attacker = _base_actor(actor_id="attacker", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    attacker.position = (0.0, 0.0, 0.0)
    target.position = (30.0, 0.0, 0.0)
    target.conditions.add("prone")

    attack = ActionDefinition(
        name="longbow",
        action_type="attack",
        action_cost="action",
        to_hit=5,
        damage="1d8",
        damage_type="piercing",
        range_ft=150,
    )
    attacker.actions = [attack]

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt = {attacker.actor_id: 0, target.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, target.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, target.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=SequenceRng([2, 19, 8]),
        actor=attacker,
        action=attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.hp == target.max_hp
    assert damage_dealt[attacker.actor_id] == 0


def test_ranged_attack_without_explicit_range_uses_ranged_default() -> None:
    attacker = _base_actor(actor_id="attacker", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    attacker.position = (0.0, 0.0, 0.0)
    target.position = (30.0, 0.0, 0.0)
    attacker.speed_ft = 0
    attacker.movement_remaining = 0.0

    attack = ActionDefinition(
        name="longbow",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1d4",
        damage_type="piercing",
    )
    attacker.actions = [attack]

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt = {attacker.actor_id: 0, target.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, target.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, target.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=SequenceRng([15, 3]),
        actor=attacker,
        action=attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.hp < target.max_hp
    assert damage_dealt[attacker.actor_id] > 0


def test_spell_attack_without_explicit_range_uses_spell_default() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    caster.position = (0.0, 0.0, 0.0)
    target.position = (30.0, 0.0, 0.0)
    caster.speed_ft = 0
    caster.movement_remaining = 0.0

    spell_attack = ActionDefinition(
        name="fire_bolt",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1d10",
        damage_type="fire",
        tags=["spell"],
    )
    caster.actions = [spell_attack]

    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt = {caster.actor_id: 0, target.actor_id: 0}
    damage_taken = {caster.actor_id: 0, target.actor_id: 0}
    threat_scores = {caster.actor_id: 0, target.actor_id: 0}
    resources_spent = {caster.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=SequenceRng([15, 3]),
        actor=caster,
        action=spell_attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.hp < target.max_hp
    assert damage_dealt[caster.actor_id] > 0


def test_enemy_turn_start_triggered_reaction_executes() -> None:
    reactor = _base_actor(actor_id="reactor", team="party")
    trigger = _base_actor(actor_id="trigger", team="enemy")
    reactor.position = (0.0, 0.0, 0.0)
    trigger.position = (5.0, 0.0, 0.0)

    reactor.actions = [
        ActionDefinition(
            name="riposte",
            action_type="attack",
            action_cost="reaction",
            event_trigger="enemy_turn_start",
            to_hit=20,
            damage="1d4",
            damage_type="piercing",
            range_ft=5,
        )
    ]

    actors = {reactor.actor_id: reactor, trigger.actor_id: trigger}
    damage_dealt = {reactor.actor_id: 0, trigger.actor_id: 0}
    damage_taken = {reactor.actor_id: 0, trigger.actor_id: 0}
    threat_scores = {reactor.actor_id: 0, trigger.actor_id: 0}
    resources_spent = {reactor.actor_id: {}, trigger.actor_id: {}}

    trigger_ready = getattr(engine_module, "_trigger_readied_actions")
    trigger_ready(
        rng=SequenceRng([15, 3]),
        trigger_actor=trigger,
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert trigger.hp < trigger.max_hp
    assert reactor.reaction_available is False


def test_run_simulation_invokes_turn_start_reaction_trigger(tmp_path: Path, monkeypatch) -> None:
    party = [build_character("hero", "Hero", 30, 15, 7, "1d8+4")]
    enemies = [build_enemy(enemy_id="boss", name="Boss", hp=40, ac=13, to_hit=5, damage="1d10+3")]

    scenario_path = _setup_env(
        tmp_path,
        party=party,
        enemies=enemies,
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
    )
    loaded = load_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    db = load_character_db(Path(loaded.config.character_db_dir))

    seen = {"count": 0}
    original = getattr(engine_module, "_trigger_readied_actions")

    def wrapped(*args, **kwargs):
        seen["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(engine_module, "_trigger_readied_actions", wrapped)

    run_simulation(loaded, db, {}, registry, trials=1, seed=21, run_id="trigger_check")

    assert seen["count"] > 0
