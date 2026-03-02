from __future__ import annotations

import random
from types import SimpleNamespace

from dnd_sim.engine import (
    _apply_effect,
    _action_available,
    _build_actor_from_character,
    _build_actor_views,
    _build_actor_from_enemy,
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


def test_colossus_slayer_adds_extra_damage_once_per_turn() -> None:
    class SequenceRng:
        def __init__(self, values: list[int]) -> None:
            self.values = list(values)

        def randint(self, _a: int, _b: int) -> int:
            if not self.values:
                raise AssertionError("RNG exhausted")
            return self.values.pop(0)

    ranger = _base_actor(actor_id="ranger", team="party")
    ranger.traits = {"colossus slayer": {}}
    enemy = _base_actor(actor_id="enemy", team="enemy")
    enemy.max_hp = 30
    enemy.hp = 20
    enemy.ac = 1

    action = ActionDefinition(
        name="longbow",
        action_type="attack",
        to_hit=8,
        damage="1",
        damage_type="piercing",
        attack_count=2,
    )
    actors = {ranger.actor_id: ranger, enemy.actor_id: enemy}
    damage_dealt = {ranger.actor_id: 0, enemy.actor_id: 0}
    damage_taken = {ranger.actor_id: 0, enemy.actor_id: 0}
    threat_scores = {ranger.actor_id: 0, enemy.actor_id: 0}
    resources_spent = {ranger.actor_id: {}, enemy.actor_id: {}}

    _execute_action(
        rng=SequenceRng([15, 5, 14]),
        actor=ranger,
        action=action,
        targets=[enemy],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert damage_dealt[ranger.actor_id] == 7
    assert enemy.hp == 13


def test_horde_breaker_adds_attack_to_second_nearby_target() -> None:
    class SequenceRng:
        def __init__(self, values: list[int]) -> None:
            self.values = list(values)

        def randint(self, _a: int, _b: int) -> int:
            if not self.values:
                raise AssertionError("RNG exhausted")
            return self.values.pop(0)

    ranger = _base_actor(actor_id="ranger", team="party")
    ranger.traits = {"horde breaker": {}}
    enemy_a = _base_actor(actor_id="enemy_a", team="enemy")
    enemy_b = _base_actor(actor_id="enemy_b", team="enemy")
    enemy_a.ac = 1
    enemy_b.ac = 1
    enemy_a.position = (0.0, 5.0, 0.0)
    enemy_b.position = (0.0, 10.0, 0.0)

    action = ActionDefinition(
        name="longsword",
        action_type="attack",
        to_hit=8,
        damage="1",
        damage_type="slashing",
        attack_count=1,
    )
    actors = {ranger.actor_id: ranger, enemy_a.actor_id: enemy_a, enemy_b.actor_id: enemy_b}
    damage_dealt = {ranger.actor_id: 0, enemy_a.actor_id: 0, enemy_b.actor_id: 0}
    damage_taken = {ranger.actor_id: 0, enemy_a.actor_id: 0, enemy_b.actor_id: 0}
    threat_scores = {ranger.actor_id: 0, enemy_a.actor_id: 0, enemy_b.actor_id: 0}
    resources_spent = {ranger.actor_id: {}, enemy_a.actor_id: {}, enemy_b.actor_id: {}}

    _execute_action(
        rng=SequenceRng([18, 17]),
        actor=ranger,
        action=action,
        targets=[enemy_a, enemy_b],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert damage_dealt[ranger.actor_id] == 2
    assert enemy_a.hp == 29
    assert enemy_b.hp == 29


def test_giant_killer_triggers_reaction_attack_against_large_attacker() -> None:
    class SequenceRng:
        def __init__(self, values: list[int]) -> None:
            self.values = list(values)

        def randint(self, _a: int, _b: int) -> int:
            if not self.values:
                raise AssertionError("RNG exhausted")
            return self.values.pop(0)

    giant = _base_actor(actor_id="giant", team="enemy")
    giant.ac = 1
    giant.traits = {"large": {}}
    ranger = _base_actor(actor_id="ranger", team="party")
    ranger.traits = {"giant killer": {}}
    ranger.actions = [
        ActionDefinition(
            name="basic",
            action_type="attack",
            to_hit=12,
            damage="2",
            damage_type="slashing",
        )
    ]

    action = ActionDefinition(
        name="club",
        action_type="attack",
        to_hit=12,
        damage="1",
        damage_type="bludgeoning",
    )
    actors = {giant.actor_id: giant, ranger.actor_id: ranger}
    damage_dealt = {giant.actor_id: 0, ranger.actor_id: 0}
    damage_taken = {giant.actor_id: 0, ranger.actor_id: 0}
    threat_scores = {giant.actor_id: 0, ranger.actor_id: 0}
    resources_spent = {giant.actor_id: {}, ranger.actor_id: {}}

    _execute_action(
        rng=SequenceRng([15, 14]),
        actor=giant,
        action=action,
        targets=[ranger],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert damage_dealt[ranger.actor_id] == 2
    assert giant.hp == 28
    assert ranger.reaction_available is False


def test_multiattack_defense_applies_ac_bonus_after_first_hit() -> None:
    class SequenceRng:
        def __init__(self, values: list[int]) -> None:
            self.values = list(values)

        def randint(self, _a: int, _b: int) -> int:
            if not self.values:
                raise AssertionError("RNG exhausted")
            return self.values.pop(0)

    attacker = _base_actor(actor_id="attacker", team="enemy")
    defender = _base_actor(actor_id="defender", team="party")
    defender.ac = 15
    defender.traits = {"multiattack defense": {}}

    action = ActionDefinition(
        name="claw",
        action_type="attack",
        to_hit=7,
        damage="1",
        damage_type="slashing",
        attack_count=2,
    )
    actors = {attacker.actor_id: attacker, defender.actor_id: defender}
    damage_dealt = {attacker.actor_id: 0, defender.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, defender.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, defender.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, defender.actor_id: {}}

    _execute_action(
        rng=SequenceRng([10, 10]),
        actor=attacker,
        action=action,
        targets=[defender],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert damage_dealt[attacker.actor_id] == 1
    assert defender.hp == 29


def test_hunter_traits_add_volley_and_whirlwind_actions() -> None:
    character = {
        "character_id": "hunter",
        "name": "Hunter",
        "class_level": "Ranger 11",
        "max_hp": 66,
        "ac": 16,
        "speed_ft": 30,
        "ability_scores": {
            "str": 12,
            "dex": 18,
            "con": 14,
            "int": 10,
            "wis": 14,
            "cha": 10,
        },
        "save_mods": {"str": 1, "dex": 4, "con": 2, "int": 0, "wis": 2, "cha": 0},
        "skill_mods": {},
        "attacks": [{"name": "Longbow", "to_hit": 9, "damage": "1d8+4", "damage_type": "piercing"}],
        "resources": {},
        "traits": ["Volley", "Whirlwind Attack"],
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }
    actor = _build_actor_from_character(character, traits_db={})
    names = {action.name for action in actor.actions}
    assert "volley" in names
    assert "whirlwind_attack" in names


def test_primal_companion_requires_command_to_use_attack_actions() -> None:
    companion = _base_actor(actor_id="companion", team="party")
    companion.traits = {"primal companion": {}}
    attack_action = ActionDefinition(
        name="basic",
        action_type="attack",
        to_hit=5,
        damage="1d8+2",
        damage_type="slashing",
    )
    dodge_action = ActionDefinition(name="dodge", action_type="utility", action_cost="action")

    assert _action_available(companion, attack_action) is False
    assert _action_available(companion, dodge_action) is True

    companion.conditions.add("companion_commanded")
    assert _action_available(companion, attack_action) is True
