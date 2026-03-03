from __future__ import annotations

import random

from dnd_sim.engine import (
    _action_available,
    _create_combat_timing_engine,
    _execute_action,
    _spend_action_resource_cost,
)
from dnd_sim.models import (
    ActionDefinition,
    ActorRuntimeState,
    SpellCastRequest,
    SpellDefinition,
    SpellScaling,
)
from dnd_sim.rules_2014 import ActionDeclaredEvent, ReactionWindowOpenedEvent


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


def test_higher_level_slot_legal_cast() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    caster.resources = {"spell_slot_2": 1}

    spell = ActionDefinition(
        name="shield_of_faith",
        action_type="utility",
        action_cost="bonus",
        target_mode="self",
        resource_cost={"spell_slot_1": 1},
        tags=["spell"],
    )

    resources_spent = {caster.actor_id: {}}

    assert _action_available(caster, spell) is True
    assert _spend_action_resource_cost(caster, spell, resources_spent) is True
    assert caster.resources["spell_slot_2"] == 0
    assert resources_spent[caster.actor_id]["spell_slot_2"] == 1


def test_spent_higher_slot_drives_upcast_scaling_during_resolution() -> None:
    rng = _FixedRng([14, 3, 4])
    caster = _base_actor(actor_id="caster", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    target.ac = 10
    caster.resources = {"spell_slot_2": 1}

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
    assert resources_spent[caster.actor_id]["spell_slot_2"] == 1
    assert spell_cast_request.slot_level == 2

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

    assert target.hp == target.max_hp - 7


def test_bonus_action_leveled_spell_blocks_non_cantrip_action_spell_same_turn() -> None:
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
    action_spell = ActionDefinition(
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

    assert _spend_action_resource_cost(caster, bonus_spell, resources_spent) is True
    _execute_action(
        rng=random.Random(1),
        actor=caster,
        action=bonus_spell,
        targets=[caster],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert _action_available(caster, action_spell) is False
    assert _action_available(caster, action_cantrip) is True


def test_bonus_action_cantrip_blocks_non_cantrip_action_spell_same_turn() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    caster.resources = {"spell_slot_1": 1}

    bonus_cantrip = ActionDefinition(
        name="magic_stone",
        action_type="utility",
        action_cost="bonus",
        target_mode="self",
        tags=["spell", "cantrip"],
        effects=[{"effect_type": "apply_condition", "condition": "armed", "target": "source"}],
    )
    action_spell = ActionDefinition(
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

    _execute_action(
        rng=random.Random(11),
        actor=caster,
        action=bonus_cantrip,
        targets=[caster],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert _action_available(caster, action_spell) is False


def test_counterspell_blocks_before_resolution_with_level_check_logic() -> None:
    rng = _FixedRng([20])
    timing_engine = _create_combat_timing_engine()

    caster = _base_actor(actor_id="caster", team="party")
    ally = _base_actor(actor_id="ally", team="party")
    counterspeller = _base_actor(actor_id="counterspeller", team="enemy")
    counterspeller.cha_mod = 0
    counterspeller.position = (0.0, 30.0, 0.0)
    caster.position = (0.0, 0.0, 0.0)

    cast_spell = ActionDefinition(
        name="greater_blessing",
        action_type="utility",
        action_cost="action",
        target_mode="single_ally",
        resource_cost={"spell_slot_5": 1},
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
    counterspeller.actions = [counterspell]
    counterspeller.resources = {"spell_slot_3": 1}

    observed: list[str] = []

    def _capture_declared(_event: ActionDeclaredEvent) -> None:
        observed.append("declared")

    def _capture_window(event: ReactionWindowOpenedEvent) -> None:
        if event.window == "counterspell":
            observed.append("counterspell_window")

    timing_engine.subscribe(ActionDeclaredEvent, _capture_declared, name="capture_declared")
    timing_engine.subscribe(ReactionWindowOpenedEvent, _capture_window, name="capture_window")

    actors = {
        caster.actor_id: caster,
        ally.actor_id: ally,
        counterspeller.actor_id: counterspeller,
    }
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(
        caster, ally, counterspeller
    )

    _execute_action(
        rng=rng,
        actor=caster,
        action=cast_spell,
        targets=[ally],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        timing_engine=timing_engine,
    )

    assert observed == ["declared", "counterspell_window"]
    assert "blessed" not in ally.conditions
    assert counterspeller.resources["spell_slot_3"] == 0


def test_counterspell_against_attack_spell_emits_declaration_before_window() -> None:
    timing_engine = _create_combat_timing_engine()

    caster = _base_actor(actor_id="caster", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    counterspeller = _base_actor(actor_id="counterspeller", team="enemy")
    caster.position = (0.0, 0.0, 0.0)
    counterspeller.position = (0.0, 30.0, 0.0)
    counterspeller.actions = [
        ActionDefinition(
            name="counterspell",
            action_type="utility",
            action_cost="reaction",
            target_mode="single_enemy",
            tags=["spell", "counterspell"],
        )
    ]
    counterspeller.resources = {"spell_slot_3": 1}

    attack_spell = ActionDefinition(
        name="guiding_bolt",
        action_type="attack",
        action_cost="action",
        target_mode="single_enemy",
        to_hit=7,
        damage="4d6",
        damage_type="radiant",
        resource_cost={"spell_slot_3": 1},
        tags=["spell"],
    )

    observed: list[str] = []

    def _capture_declared(_event: ActionDeclaredEvent) -> None:
        observed.append("declared")

    def _capture_window(event: ReactionWindowOpenedEvent) -> None:
        if event.window == "counterspell":
            observed.append("counterspell_window")

    timing_engine.subscribe(ActionDeclaredEvent, _capture_declared, name="capture_declared")
    timing_engine.subscribe(ReactionWindowOpenedEvent, _capture_window, name="capture_window")

    actors = {
        caster.actor_id: caster,
        target.actor_id: target,
        counterspeller.actor_id: counterspeller,
    }
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(
        caster, target, counterspeller
    )

    _execute_action(
        rng=random.Random(20),
        actor=caster,
        action=attack_spell,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        timing_engine=timing_engine,
    )

    assert observed == ["declared", "counterspell_window"]
    assert target.hp == target.max_hp
    assert counterspeller.resources["spell_slot_3"] == 0


def test_casting_new_concentration_spell_ends_previous_immediately() -> None:
    caster = _base_actor(actor_id="caster", team="party")
    target_a = _base_actor(actor_id="target_a", team="enemy")
    target_b = _base_actor(actor_id="target_b", team="enemy")

    first_spell = ActionDefinition(
        name="hold_person",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        concentration=True,
        tags=["spell"],
        effects=[{"effect_type": "apply_condition", "condition": "paralyzed", "target": "target"}],
    )
    second_spell = ActionDefinition(
        name="suggestion",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        concentration=True,
        tags=["spell"],
        effects=[{"effect_type": "apply_condition", "condition": "charmed", "target": "target"}],
    )

    actors = {caster.actor_id: caster, target_a.actor_id: target_a, target_b.actor_id: target_b}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(
        caster, target_a, target_b
    )

    _execute_action(
        rng=random.Random(2),
        actor=caster,
        action=first_spell,
        targets=[target_a],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )
    assert caster.concentrating is True
    assert "paralyzed" in target_a.conditions

    _execute_action(
        rng=random.Random(3),
        actor=caster,
        action=second_spell,
        targets=[target_b],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert "paralyzed" not in target_a.conditions
    assert "charmed" in target_b.conditions
    assert caster.concentrating is True
    assert caster.concentrated_spell == "suggestion"
