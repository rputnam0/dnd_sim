from __future__ import annotations

from dnd_sim.engine_runtime import (
    _action_available,
    _build_character_actions,
    _execute_action,
    _spend_resources,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState


class SequenceRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self.values:
            raise AssertionError("RNG exhausted")
        return self.values.pop(0)


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
        cha_mod=4,
        save_mods={"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def _combat_state(*actors: ActorRuntimeState) -> tuple[
    dict[str, ActorRuntimeState],
    dict[str, int],
    dict[str, int],
    dict[str, int],
    dict[str, dict[str, int]],
]:
    by_id = {actor.actor_id: actor for actor in actors}
    damage_dealt = {actor.actor_id: 0 for actor in actors}
    damage_taken = {actor.actor_id: 0 for actor in actors}
    threat_scores = {actor.actor_id: 0 for actor in actors}
    resources_spent = {actor.actor_id: {} for actor in actors}
    return by_id, damage_dealt, damage_taken, threat_scores, resources_spent


def test_build_character_actions_expands_metamagic_legality_matrix() -> None:
    character = {
        "character_id": "sorc",
        "name": "Sorcerer",
        "class_levels": {"sorcerer": 10},
        "max_hp": 50,
        "ac": 14,
        "speed_ft": 30,
        "ability_scores": {"str": 10, "dex": 14, "con": 14, "int": 12, "wis": 12, "cha": 18},
        "save_mods": {"str": 0, "dex": 2, "con": 2, "int": 1, "wis": 1, "cha": 4},
        "skill_mods": {},
        "attacks": [],
        "resources": {"sorcery_points": {"max": 10}, "spell_slots": {"1": 4, "2": 3, "3": 3}},
        "traits": [
            "Careful Spell",
            "Distant Spell",
            "Empowered Spell",
            "Extended Spell",
            "Heightened Spell",
            "Quickened Spell",
            "Subtle Spell",
            "Twinned Spell",
        ],
        "spells": [
            {
                "name": "Chromatic Orb",
                "level": 1,
                "action_type": "attack",
                "to_hit": 8,
                "damage": "3d8",
                "damage_type": "acid",
                "range_ft": 90,
                "target_mode": "single_enemy",
            },
            {
                "name": "Fireball",
                "level": 3,
                "action_type": "save",
                "save_dc": 16,
                "save_ability": "dex",
                "damage": "8d6",
                "damage_type": "fire",
                "half_on_save": True,
                "range_ft": 150,
                "aoe_type": "sphere",
                "aoe_size_ft": 20,
                "target_mode": "all_creatures",
            },
            {
                "name": "Invisibility",
                "level": 2,
                "action_type": "utility",
                "action_cost": "action",
                "target_mode": "single_ally",
                "range_ft": 30,
                "concentration": True,
            },
        ],
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }

    actions = _build_character_actions(character)

    chromatic_options = {
        tag.split(":", 1)[1]
        for action in actions
        if action.name.startswith("Chromatic Orb [")
        for tag in action.tags
        if tag.startswith("metamagic:")
    }
    fireball_options = {
        tag.split(":", 1)[1]
        for action in actions
        if action.name.startswith("Fireball [")
        for tag in action.tags
        if tag.startswith("metamagic:")
    }
    invis_options = {
        tag.split(":", 1)[1]
        for action in actions
        if action.name.startswith("Invisibility [")
        for tag in action.tags
        if tag.startswith("metamagic:")
    }

    assert chromatic_options == {"distant", "empowered", "quickened", "subtle", "twinned"}
    assert fireball_options == {
        "careful",
        "distant",
        "empowered",
        "heightened",
        "quickened",
        "subtle",
    }
    assert invis_options == {"distant", "extended", "quickened", "subtle", "twinned"}

    twinned_orb = next(action for action in actions if action.name == "Chromatic Orb [Twinned]")
    assert twinned_orb.target_mode == "n_enemies"
    assert twinned_orb.max_targets == 2
    assert twinned_orb.resource_cost["sorcery_points"] == 1

    quickened_fireball = next(action for action in actions if action.name == "Fireball [Quickened]")
    assert quickened_fireball.action_cost == "bonus"
    assert quickened_fireball.resource_cost["sorcery_points"] == 2


def test_build_character_actions_adds_font_of_magic_conversion_actions() -> None:
    character = {
        "character_id": "sorc",
        "name": "Sorcerer",
        "class_levels": {"sorcerer": 12},
        "max_hp": 60,
        "ac": 15,
        "speed_ft": 30,
        "ability_scores": {"str": 10, "dex": 14, "con": 14, "int": 12, "wis": 12, "cha": 20},
        "save_mods": {"str": 0, "dex": 2, "con": 2, "int": 1, "wis": 1, "cha": 5},
        "skill_mods": {},
        "attacks": [],
        "resources": {
            "sorcery_points": {"max": 12},
            "spell_slots": {"1": 4, "2": 3, "3": 3, "6": 1},
        },
        "traits": [],
        "spells": [],
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }

    actions = _build_character_actions(character)
    by_name = {action.name: action for action in actions}

    assert "font_of_magic_create_slot_5" in by_name
    assert "font_of_magic_create_slot_6" not in by_name
    assert by_name["font_of_magic_create_slot_5"].resource_cost == {"sorcery_points": 7}

    assert "font_of_magic_convert_slot_1" in by_name
    assert "font_of_magic_convert_slot_6" in by_name
    assert by_name["font_of_magic_convert_slot_6"].resource_cost == {"spell_slot_6": 1}


def test_slot_to_points_conversion_action_respects_sorcery_point_cap() -> None:
    actor = _base_actor(actor_id="sorc", team="party")
    actor.resources = {"sorcery_points": 5, "spell_slot_2": 1}
    actor.max_resources = {"sorcery_points": 6, "spell_slot_2": 3}

    convert_slot = ActionDefinition(
        name="font_of_magic_convert_slot_2",
        action_type="utility",
        action_cost="bonus",
        target_mode="self",
        resource_cost={"spell_slot_2": 1},
        tags=["font_of_magic", "conversion:slot_to_points", "slot_level:2"],
    )

    assert _action_available(actor, convert_slot) is False
    actor.resources["sorcery_points"] = 4
    assert _action_available(actor, convert_slot) is True


def test_execute_font_of_magic_conversion_actions_updates_resources() -> None:
    sorcerer = _base_actor(actor_id="sorc", team="party")
    sorcerer.resources = {"sorcery_points": 7, "spell_slot_2": 1, "spell_slot_5": 0}
    sorcerer.max_resources = {"sorcery_points": 20, "spell_slot_2": 3, "spell_slot_5": 2}
    actors, damage_dealt, damage_taken, threat_scores, resources_spent = _combat_state(sorcerer)

    create_slot = ActionDefinition(
        name="font_of_magic_create_slot_5",
        action_type="utility",
        action_cost="bonus",
        target_mode="self",
        resource_cost={"sorcery_points": 7},
        tags=["font_of_magic", "conversion:points_to_slot", "slot_level:5"],
    )
    spent = _spend_resources(sorcerer, create_slot.resource_cost)
    assert spent == {"sorcery_points": 7}
    _execute_action(
        rng=SequenceRng([]),
        actor=sorcerer,
        action=create_slot,
        targets=[sorcerer],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    assert sorcerer.resources["sorcery_points"] == 0
    assert sorcerer.resources["spell_slot_5"] == 1

    convert_slot = ActionDefinition(
        name="font_of_magic_convert_slot_2",
        action_type="utility",
        action_cost="bonus",
        target_mode="self",
        resource_cost={"spell_slot_2": 1},
        tags=["font_of_magic", "conversion:slot_to_points", "slot_level:2"],
    )
    spent = _spend_resources(sorcerer, convert_slot.resource_cost)
    assert spent == {"spell_slot_2": 1}
    _execute_action(
        rng=SequenceRng([]),
        actor=sorcerer,
        action=convert_slot,
        targets=[sorcerer],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    assert sorcerer.resources["spell_slot_2"] == 0
    assert sorcerer.resources["sorcery_points"] == 2


def test_subtle_spell_bypasses_counterspell_reaction() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")
    enemy.resources = {"spell_slot_3": 1}
    enemy.actions = [
        ActionDefinition(
            name="counterspell",
            action_type="utility",
            action_cost="reaction",
            tags=["spell"],
        )
    ]
    caster.position = (0.0, 0.0, 0.0)
    enemy.position = (30.0, 0.0, 0.0)

    subtle_spell = ActionDefinition(
        name="mind sliver",
        action_type="save",
        save_dc=20,
        save_ability="int",
        damage="1",
        damage_type="psychic",
        tags=["spell", "metamagic:subtle"],
    )

    actors, damage_dealt, damage_taken, threat_scores, resources_spent = _combat_state(
        caster, enemy
    )
    _execute_action(
        rng=SequenceRng([1]),
        actor=caster,
        action=subtle_spell,
        targets=[enemy],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert enemy.hp == 29
    assert enemy.resources["spell_slot_3"] == 1
    assert enemy.reaction_available is True


def test_heightened_spell_applies_disadvantage_to_first_target_save() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    target_a = _base_actor(actor_id="a", team="enemy")
    target_b = _base_actor(actor_id="b", team="enemy")

    action = ActionDefinition(
        name="mind thunder",
        action_type="save",
        save_dc=15,
        save_ability="wis",
        damage="1d6",
        damage_type="psychic",
        half_on_save=False,
        tags=["spell", "metamagic:heightened"],
    )

    actors, damage_dealt, damage_taken, threat_scores, resources_spent = _combat_state(
        caster, target_a, target_b
    )
    _execute_action(
        rng=SequenceRng([6, 17, 2, 17]),
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
    assert target_b.hp == 30
