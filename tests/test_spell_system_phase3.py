from __future__ import annotations

import random

from dnd_sim.engine import _build_spell_actions, _execute_action
from dnd_sim.models import ActionDefinition, ActorRuntimeState


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
