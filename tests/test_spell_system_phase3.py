from __future__ import annotations

import random

from dnd_sim.engine import (
    _action_available,
    _break_concentration,
    _build_spell_actions,
    _execute_action,
    _resolve_targets_for_action,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.strategy_api import TargetRef


class FixedRng:
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
        initiative_mod=2,
        str_mod=0,
        dex_mod=2,
        con_mod=1,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 0, "dex": 2, "con": 1, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def test_counterspell_higher_level_spell_requires_ability_check() -> None:
    rng = FixedRng([1])  # low roll to fail DC 15

    caster = _base_actor(actor_id="caster", team="party")
    ally = _base_actor(actor_id="ally", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")

    spell = ActionDefinition(
        name="greater_blessing",
        action_type="utility",
        action_cost="action",
        resource_cost={"spell_slot_5": 1},
        target_mode="single_ally",
        tags=["spell"],
        effects=[{"effect_type": "apply_condition", "condition": "blessed", "target": "target"}],
    )
    counterspell = ActionDefinition(
        name="counterspell",
        action_type="utility",
        action_cost="reaction",
        target_mode="single_enemy",
        tags=["spell", "counterspell"],
    )
    caster.actions = [spell]
    enemy.actions = [counterspell]
    enemy.resources = {"spell_slot_3": 1}
    enemy.max_resources = {"spell_slot_3": 1}
    enemy.position = (0.0, 30.0, 0.0)
    caster.position = (0.0, 0.0, 0.0)
    ally.position = (0.0, 5.0, 0.0)

    actors = {a.actor_id: a for a in (caster, ally, enemy)}
    damage_dealt = {a.actor_id: 0 for a in actors.values()}
    damage_taken = {a.actor_id: 0 for a in actors.values()}
    threat_scores = {a.actor_id: 0 for a in actors.values()}
    resources_spent = {a.actor_id: {} for a in actors.values()}
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=rng,
        actor=caster,
        action=spell,
        targets=[ally],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert "blessed" in ally.conditions
    assert enemy.reaction_available is False
    assert enemy.resources["spell_slot_3"] == 0


def test_new_concentration_spell_replaces_old_summon_effect() -> None:
    rng = random.Random(1)

    caster = _base_actor(actor_id="caster", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")

    summon_spell = ActionDefinition(
        name="summon_spirit",
        action_type="utility",
        action_cost="action",
        target_mode="self",
        concentration=True,
        tags=["spell"],
        effects=[
            {
                "effect_type": "summon",
                "actor_id": "summon_wolf",
                "name": "Wolf Spirit",
                "max_hp": 12,
                "ac": 13,
                "target": "source",
            }
        ],
    )
    hold_spell = ActionDefinition(
        name="hold_person",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        concentration=True,
        tags=["spell"],
        effects=[{"effect_type": "apply_condition", "condition": "paralyzed", "target": "target"}],
    )

    actors = {a.actor_id: a for a in (caster, enemy)}
    damage_dealt = {a.actor_id: 0 for a in actors.values()}
    damage_taken = {a.actor_id: 0 for a in actors.values()}
    threat_scores = {a.actor_id: 0 for a in actors.values()}
    resources_spent = {a.actor_id: {} for a in actors.values()}
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=rng,
        actor=caster,
        action=summon_spell,
        targets=[caster],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    assert "summon_wolf" in actors
    assert actors["summon_wolf"].team == "party"

    _execute_action(
        rng=rng,
        actor=caster,
        action=hold_spell,
        targets=[enemy],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert "summon_wolf" not in actors
    assert caster.concentrating is True
    assert caster.concentrated_spell == "hold_person"


def test_upcasting_builds_higher_slot_spell_variants() -> None:
    character = {
        "spells": [
            {
                "name": "fire_burst",
                "level": 3,
                "action_type": "save",
                "damage": "8d6",
                "damage_type": "fire",
                "save_dc": 15,
                "save_ability": "dex",
                "half_on_save": True,
                "upcast_dice_per_level": "1d6",
            }
        ],
        "resources": {"spell_slots": {"3": 1, "4": 1, "5": 1}},
    }

    actions = _build_spell_actions(character, character_level=10)
    names = {action.name for action in actions}
    by_name = {action.name: action for action in actions}

    assert "fire_burst" in names
    assert "fire_burst (4th level)" in names
    assert "fire_burst (5th level)" in names
    assert by_name["fire_burst (4th level)"].damage == "9d6"
    assert by_name["fire_burst (5th level)"].damage == "10d6"
    assert by_name["fire_burst (5th level)"].resource_cost == {"spell_slot_5": 1}


def test_counterspell_prefers_slot_that_auto_counters_when_available() -> None:
    rng = FixedRng([1])  # would fail if the counterspeller chose a low slot and rolled.

    caster = _base_actor(actor_id="caster", team="party")
    ally = _base_actor(actor_id="ally", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")

    spell = ActionDefinition(
        name="force_surge",
        action_type="utility",
        action_cost="action",
        resource_cost={"spell_slot_5": 1},
        target_mode="single_ally",
        tags=["spell"],
        effects=[{"effect_type": "apply_condition", "condition": "blessed", "target": "target"}],
    )
    counterspell = ActionDefinition(
        name="counterspell",
        action_type="utility",
        action_cost="reaction",
        target_mode="single_enemy",
        tags=["spell", "counterspell"],
    )
    enemy.actions = [counterspell]
    enemy.resources = {"spell_slot_3": 1, "spell_slot_6": 1}
    enemy.max_resources = {"spell_slot_3": 1, "spell_slot_6": 1}
    enemy.position = (0.0, 30.0, 0.0)
    caster.position = (0.0, 0.0, 0.0)
    ally.position = (0.0, 5.0, 0.0)

    actors = {a.actor_id: a for a in (caster, ally, enemy)}
    damage_dealt = {a.actor_id: 0 for a in actors.values()}
    damage_taken = {a.actor_id: 0 for a in actors.values()}
    threat_scores = {a.actor_id: 0 for a in actors.values()}
    resources_spent = {a.actor_id: {} for a in actors.values()}

    _execute_action(
        rng=rng,
        actor=caster,
        action=spell,
        targets=[ally],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert "blessed" not in ally.conditions
    assert enemy.resources["spell_slot_3"] == 1
    assert enemy.resources["spell_slot_6"] == 0


def test_dropped_to_zero_forces_concentration_end_even_if_check_would_succeed() -> None:
    rng = FixedRng([15, 1, 20])  # hit, damage, concentration save roll

    caster = _base_actor(actor_id="caster", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    attacker = _base_actor(actor_id="attacker", team="enemy")
    caster.hp = 1

    hold_person = ActionDefinition(
        name="hold_person",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        concentration=True,
        tags=["spell"],
        effects=[{"effect_type": "apply_condition", "condition": "paralyzed", "target": "target"}],
    )
    strike = ActionDefinition(
        name="spear",
        action_type="attack",
        to_hit=8,
        damage="1d1",
    )

    caster.position = (0.0, 0.0, 0.0)
    target.position = (10.0, 0.0, 0.0)
    attacker.position = (5.0, 0.0, 0.0)

    actors = {a.actor_id: a for a in (caster, target, attacker)}
    damage_dealt = {a.actor_id: 0 for a in actors.values()}
    damage_taken = {a.actor_id: 0 for a in actors.values()}
    threat_scores = {a.actor_id: 0 for a in actors.values()}
    resources_spent = {a.actor_id: {} for a in actors.values()}
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=random.Random(1),
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
    assert caster.concentrating is True
    assert "paralyzed" in target.conditions

    _execute_action(
        rng=rng,
        actor=attacker,
        action=strike,
        targets=[caster],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert caster.hp == 0
    assert caster.concentrating is False
    assert "paralyzed" not in target.conditions


def test_dispel_magic_level_checks_and_upcast_auto_success() -> None:
    rng = FixedRng([1])  # failed ability check for 3rd-level dispel.

    source = _base_actor(actor_id="source", team="enemy")
    dispeller = _base_actor(actor_id="dispeller", team="party")
    victim = _base_actor(actor_id="victim", team="party")

    hold_monster = ActionDefinition(
        name="hold_monster",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        concentration=True,
        resource_cost={"spell_slot_5": 1},
        tags=["spell"],
        effects=[{"effect_type": "apply_condition", "condition": "paralyzed", "target": "target"}],
    )
    dispel_third = ActionDefinition(
        name="dispel_magic",
        action_type="utility",
        action_cost="action",
        target_mode="single_ally",
        resource_cost={"spell_slot_3": 1},
        tags=["spell", "dispel"],
    )
    dispel_fifth = ActionDefinition(
        name="dispel_magic (5th level)",
        action_type="utility",
        action_cost="action",
        target_mode="single_ally",
        resource_cost={"spell_slot_5": 1},
        tags=["spell", "dispel", "upcast_level:5"],
    )

    actors = {a.actor_id: a for a in (source, dispeller, victim)}
    damage_dealt = {a.actor_id: 0 for a in actors.values()}
    damage_taken = {a.actor_id: 0 for a in actors.values()}
    threat_scores = {a.actor_id: 0 for a in actors.values()}
    resources_spent = {a.actor_id: {} for a in actors.values()}
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=random.Random(2),
        actor=source,
        action=hold_monster,
        targets=[victim],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    assert source.concentrating is True
    assert "paralyzed" in victim.conditions

    _execute_action(
        rng=rng,
        actor=dispeller,
        action=dispel_third,
        targets=[victim],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )
    assert source.concentrating is True
    assert "paralyzed" in victim.conditions

    _execute_action(
        rng=random.Random(3),
        actor=dispeller,
        action=dispel_fifth,
        targets=[victim],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert source.concentrating is False
    assert "paralyzed" not in victim.conditions


def test_spell_components_block_unavailable_casting_constraints() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    caster.resources = {"free_hands": 0}
    target = _base_actor(actor_id="target", team="enemy")

    spell = ActionDefinition(
        name="binding_word",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        tags=["spell", "component:verbal", "component:somatic", "component:material"],
        effects=[{"effect_type": "apply_condition", "condition": "restrained", "target": "target"}],
    )

    assert _action_available(caster, spell) is False

    caster.resources["spellcasting_focus"] = 1
    caster.conditions.add("silenced")
    assert _action_available(caster, spell) is False

    caster.conditions.clear()
    assert _action_available(caster, spell) is True

    actors = {caster.actor_id: caster, target.actor_id: target}
    _execute_action(
        rng=random.Random(4),
        actor=caster,
        action=spell,
        targets=[target],
        actors=actors,
        damage_dealt={caster.actor_id: 0, target.actor_id: 0},
        damage_taken={caster.actor_id: 0, target.actor_id: 0},
        threat_scores={caster.actor_id: 0, target.actor_id: 0},
        resources_spent={caster.actor_id: {}, target.actor_id: {}},
        active_hazards=[],
    )
    assert "restrained" in target.conditions


def test_build_spell_actions_maps_component_strings_to_tags() -> None:
    character = {
        "spells": [
            {
                "name": "warding_veil",
                "level": 2,
                "action_type": "utility",
                "components": "V, S, M (a silver thread)",
            }
        ],
        "resources": {"spell_slots": {"2": 2}},
    }

    actions = _build_spell_actions(character, character_level=5)
    tags = set(actions[0].tags)

    assert "component:verbal" in tags
    assert "component:somatic" in tags
    assert "component:material" in tags


def test_target_resolution_templates_are_shape_specific_and_team_consistent() -> None:
    rng = random.Random(1)
    caster = _base_actor(actor_id="caster", team="party")
    ally = _base_actor(actor_id="ally", team="party")
    primary = _base_actor(actor_id="primary", team="enemy")
    inline_enemy = _base_actor(actor_id="inline_enemy", team="enemy")
    flank_enemy = _base_actor(actor_id="flank_enemy", team="enemy")
    rear_enemy = _base_actor(actor_id="rear_enemy", team="enemy")

    caster.position = (0.0, 0.0, 0.0)
    ally.position = (11.0, 0.0, 0.0)
    primary.position = (10.0, 0.0, 0.0)
    inline_enemy.position = (18.0, 0.0, 0.0)
    flank_enemy.position = (18.0, 6.0, 0.0)
    rear_enemy.position = (-6.0, 0.0, 0.0)

    actors = {
        caster.actor_id: caster,
        ally.actor_id: ally,
        primary.actor_id: primary,
        inline_enemy.actor_id: inline_enemy,
        flank_enemy.actor_id: flank_enemy,
        rear_enemy.actor_id: rear_enemy,
    }

    line_action = ActionDefinition(
        name="lightning_line",
        action_type="save",
        save_dc=14,
        save_ability="dex",
        target_mode="single_enemy",
        aoe_type="line",
        aoe_size_ft=20,
        tags=["spell"],
    )
    cone_action = ActionDefinition(
        name="burning_cone",
        action_type="save",
        save_dc=14,
        save_ability="dex",
        target_mode="single_enemy",
        aoe_type="cone",
        aoe_size_ft=20,
        tags=["spell"],
    )

    line_targets = _resolve_targets_for_action(
        rng=rng,
        actor=caster,
        action=line_action,
        actors=actors,
        requested=[TargetRef("primary")],
    )
    line_ids = {target.actor_id for target in line_targets}
    assert line_ids == {"primary", "inline_enemy"}

    cone_targets = _resolve_targets_for_action(
        rng=rng,
        actor=caster,
        action=cone_action,
        actors=actors,
        requested=[TargetRef("primary")],
    )
    cone_ids = {target.actor_id for target in cone_targets}
    assert "ally" not in cone_ids
    assert "rear_enemy" not in cone_ids
    assert {"primary", "inline_enemy"}.issubset(cone_ids)


def test_conjure_effect_uses_summon_lifecycle_and_concentration_cleanup() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    action = ActionDefinition(
        name="conjure_beast",
        action_type="utility",
        action_cost="action",
        target_mode="self",
        concentration=True,
        tags=["spell"],
        effects=[
            {
                "effect_type": "conjure",
                "actor_id": "conjured_wolf",
                "name": "Conjured Wolf",
                "max_hp": 14,
                "ac": 13,
                "target": "source",
            }
        ],
    )

    actors = {caster.actor_id: caster}
    damage_dealt = {caster.actor_id: 0}
    damage_taken = {caster.actor_id: 0}
    threat_scores = {caster.actor_id: 0}
    resources_spent = {caster.actor_id: {}}
    active_hazards: list[dict[str, object]] = []

    _execute_action(
        rng=random.Random(5),
        actor=caster,
        action=action,
        targets=[caster],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert "conjured_wolf" in actors
    assert "summoned" in actors["conjured_wolf"].conditions
    assert caster.concentrating is True

    _break_concentration(caster, actors, active_hazards)
    assert "conjured_wolf" not in actors
