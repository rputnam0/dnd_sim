from __future__ import annotations

import random

from dnd_sim.engine import _action_available, _execute_action, _spend_action_resource_cost
from dnd_sim.models import (
    ActionDefinition,
    ActorRuntimeState,
    SpellCastRequest,
    SpellDefinition,
    SpellScaling,
)


class _FixedRng:
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


def test_spell_slot_of_level_or_higher_is_legal() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    caster.resources = {"spell_slot_3": 1}
    resources_spent = {caster.actor_id: {}}

    spell = ActionDefinition(
        name="shield_of_faith",
        action_type="utility",
        action_cost="bonus",
        target_mode="self",
        resource_cost={"spell_slot_1": 1},
        tags=["spell"],
    )
    spell_cast_request = SpellCastRequest()

    assert _action_available(caster, spell) is True
    assert (
        _spend_action_resource_cost(
            caster,
            spell,
            resources_spent,
            spell_cast_request=spell_cast_request,
        )
        is True
    )
    assert spell_cast_request.slot_level == 3
    assert caster.resources["spell_slot_3"] == 0
    assert resources_spent[caster.actor_id]["spell_slot_3"] == 1


def test_upcast_scaling_uses_actual_spent_slot() -> None:
    rng = _FixedRng([14, 2, 3, 4])
    caster = _base_actor(actor_id="caster", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    target.ac = 10
    caster.position = (0.0, 0.0, 0.0)
    target.position = (10.0, 0.0, 0.0)
    caster.resources = {"spell_slot_3": 1}

    spell = ActionDefinition(
        name="chromatic_orb",
        action_type="attack",
        action_cost="action",
        target_mode="single_enemy",
        to_hit=6,
        damage="1d4",
        damage_type="acid",
        resource_cost={"spell_slot_1": 1},
        tags=["spell"],
        spell=SpellDefinition(
            name="chromatic_orb",
            level=1,
            scaling=SpellScaling(upcast_dice_per_level="1d4"),
        ),
    )

    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)
    spell_cast_request = SpellCastRequest()

    assert (
        _spend_action_resource_cost(
            caster,
            spell,
            resources_spent,
            spell_cast_request=spell_cast_request,
        )
        is True
    )
    assert spell_cast_request.slot_level == 3
    assert resources_spent[caster.actor_id] == {"spell_slot_3": 1}

    _execute_action(
        rng=rng,
        actor=caster,
        action=spell,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        spell_cast_request=spell_cast_request,
    )

    assert target.hp == target.max_hp - 9


def test_lower_slot_only_cannot_cast_higher_level_spell() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    caster.resources = {"spell_slot_1": 1}
    resources_spent = {caster.actor_id: {}}

    spell = ActionDefinition(
        name="hold_person",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        resource_cost={"spell_slot_2": 1},
        tags=["spell"],
    )

    assert _action_available(caster, spell) is False
    assert _spend_action_resource_cost(caster, spell, resources_spent) is False
    assert caster.resources["spell_slot_1"] == 1
    assert resources_spent[caster.actor_id] == {}


def test_bonus_action_spell_plus_leveled_action_spell_is_illegal() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    caster.resources = {"spell_slot_1": 2}

    bonus_spell = ActionDefinition(
        name="healing_word",
        action_type="utility",
        action_cost="bonus",
        target_mode="self",
        resource_cost={"spell_slot_1": 1},
        tags=["spell"],
        effects=[{"effect_type": "apply_condition", "condition": "bolstered", "target": "source"}],
    )
    leveled_action_spell = ActionDefinition(
        name="guiding_bolt",
        action_type="attack",
        action_cost="action",
        target_mode="single_enemy",
        to_hit=7,
        damage="4d6",
        damage_type="radiant",
        resource_cost={"spell_slot_1": 1},
        tags=["spell"],
    )

    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)

    assert (
        _spend_action_resource_cost(
            caster,
            bonus_spell,
            resources_spent,
            turn_token="1:caster",
        )
        is True
    )
    _execute_action(
        rng=random.Random(7),
        actor=caster,
        action=bonus_spell,
        targets=[caster],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:caster",
    )

    assert _action_available(caster, leveled_action_spell, turn_token="1:caster") is False
    assert (
        _spend_action_resource_cost(
            caster,
            leveled_action_spell,
            resources_spent,
            turn_token="1:caster",
        )
        is False
    )


def test_bonus_action_spell_plus_action_cantrip_is_legal() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    caster.resources = {"spell_slot_1": 1}

    bonus_spell = ActionDefinition(
        name="healing_word",
        action_type="utility",
        action_cost="bonus",
        target_mode="self",
        resource_cost={"spell_slot_1": 1},
        tags=["spell"],
        effects=[{"effect_type": "apply_condition", "condition": "bolstered", "target": "source"}],
    )
    action_cantrip = ActionDefinition(
        name="fire_bolt",
        action_type="attack",
        action_cost="action",
        target_mode="single_enemy",
        to_hit=7,
        damage="1d10",
        damage_type="fire",
        tags=["spell", "cantrip"],
    )

    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)

    assert (
        _spend_action_resource_cost(
            caster,
            bonus_spell,
            resources_spent,
            turn_token="1:caster",
        )
        is True
    )
    _execute_action(
        rng=random.Random(17),
        actor=caster,
        action=bonus_spell,
        targets=[caster],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:caster",
    )

    assert _action_available(caster, action_cantrip, turn_token="1:caster") is True
    assert (
        _spend_action_resource_cost(
            caster,
            action_cantrip,
            resources_spent,
            turn_token="1:caster",
        )
        is True
    )


def test_reaction_spell_on_other_turn_after_bonus_action_spell_is_legal() -> None:
    attacker = _base_actor(actor_id="attacker", team="enemy")
    defender = _base_actor(actor_id="defender", team="party")
    defender.resources = {"spell_slot_1": 2}

    bonus_spell = ActionDefinition(
        name="healing_word",
        action_type="utility",
        action_cost="bonus",
        target_mode="self",
        resource_cost={"spell_slot_1": 1},
        tags=["spell"],
        effects=[{"effect_type": "apply_condition", "condition": "bolstered", "target": "source"}],
    )
    reaction_spell = ActionDefinition(
        name="hellish_rebuke",
        action_type="attack",
        action_cost="reaction",
        target_mode="single_enemy",
        to_hit=7,
        damage="2d10",
        damage_type="fire",
        resource_cost={"spell_slot_1": 1},
        tags=["spell"],
    )

    actors = {attacker.actor_id: attacker, defender.actor_id: defender}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(attacker, defender)

    assert (
        _spend_action_resource_cost(
            defender,
            bonus_spell,
            resources_spent,
            turn_token="1:defender",
        )
        is True
    )
    _execute_action(
        rng=random.Random(23),
        actor=defender,
        action=bonus_spell,
        targets=[defender],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:defender",
    )

    assert _action_available(defender, reaction_spell, turn_token="1:defender") is False
    assert _action_available(defender, reaction_spell, turn_token="1:attacker") is True
    assert (
        _spend_action_resource_cost(
            defender,
            reaction_spell,
            resources_spent,
            turn_token="1:attacker",
        )
        is True
    )
