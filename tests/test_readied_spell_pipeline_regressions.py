from __future__ import annotations

import pytest

import dnd_sim.engine_runtime as engine_module
from dnd_sim.engine import TurnDeclarationValidationError
from dnd_sim.engine_runtime import _execute_action, _execute_declared_turn_or_error
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.rules_2014 import ActionDeclaredEvent, CombatTimingEngine
from dnd_sim.strategy_api import (
    DeclaredAction,
    ReactionDecision,
    ReactionWindowView,
    ReadyDeclaration,
    TurnDeclaration,
)


class _SequenceRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, low: int, high: int) -> int:
        if not self.values:
            raise AssertionError("unexpected RNG consumption")
        value = self.values.pop(0)
        assert low <= value <= high
        return value


def _actor(*, actor_id: str, team: str) -> ActorRuntimeState:
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


def _ready_action() -> ActionDefinition:
    return ActionDefinition(
        name="ready",
        action_type="utility",
        action_cost="action",
        target_mode="self",
    )


def _spell(*, name: str = "held_bolt", concentration: bool = False) -> ActionDefinition:
    return ActionDefinition(
        name=name,
        action_type="attack",
        attack_delivery="ranged_spell_attack",
        action_cost="action",
        target_mode="single_enemy",
        to_hit=100,
        damage="1",
        damage_type="force",
        range_ft=120,
        concentration=concentration,
        resource_cost={"spell_slot_1": 1},
        tags=["spell", "component:verbal"],
    )


def _trackers(
    *actors: ActorRuntimeState,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    return (
        {actor.actor_id: 0 for actor in actors},
        {actor.actor_id: 0 for actor in actors},
        {actor.actor_id: 0 for actor in actors},
        {actor.actor_id: {} for actor in actors},
    )


def _mage_slayer(actor: ActorRuntimeState) -> None:
    actor.actions = [
        ActionDefinition(
            name="sword",
            action_type="attack",
            attack_delivery="melee_weapon_attack",
            action_cost="action",
            target_mode="single_enemy",
            to_hit=5,
            damage="1",
            reach_ft=5,
        )
    ]
    actor.traits = {
        "mage_slayer": {
            "name": "Mage Slayer",
            "source_type": "feat",
            "mechanics": [{"effect_type": "reaction_attack", "trigger": "spell_cast_within_5ft"}],
        }
    }


def test_unavailable_readied_spell_is_rejected_before_movement_and_ready_bookkeeping() -> None:
    caster = _actor(actor_id="caster", team="party")
    caster.movement_remaining = 30.0
    caster.actions = [_ready_action(), _spell()]
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster)

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        _execute_declared_turn_or_error(
            rng=_SequenceRng([]),
            actor=caster,
            declaration=TurnDeclaration(
                movement_path=[(0.0, 0.0, 0.0), (5.0, 0.0, 0.0)],
                action=DeclaredAction(action_name="ready"),
                ready=ReadyDeclaration(
                    trigger="enemy_turn_start",
                    response_action_name="held_bolt",
                ),
            ),
            strategy_name="test",
            actors={caster.actor_id: caster},
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=[],
            round_number=1,
            turn_token="1:caster",
        )

    assert exc_info.value.code == "unavailable_ready_spell"
    assert exc_info.value.field == "ready.response_action_name"
    assert caster.position == (0.0, 0.0, 0.0)
    assert caster.movement_remaining == 30.0
    assert caster.per_action_uses.get("ready", 0) == 0
    assert "readying" not in caster.conditions


def test_cancelled_readied_spell_declaration_does_not_open_mage_slayer_window() -> None:
    caster = _actor(actor_id="caster", team="party")
    slayer = _actor(actor_id="slayer", team="enemy")
    caster.position = (0.0, 0.0, 0.0)
    slayer.position = (5.0, 0.0, 0.0)
    spell = _spell()
    caster.actions = [_ready_action(), spell]
    caster.resources["spell_slot_1"] = 1
    _mage_slayer(slayer)
    actors = {caster.actor_id: caster, slayer.actor_id: slayer}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, slayer)
    timing_engine = CombatTimingEngine()
    timing_engine.subscribe(
        ActionDeclaredEvent,
        lambda event: event.cancel("test cancellation"),
        name="cancel",
    )
    windows: list[ReactionWindowView] = []

    def pass_reaction(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _execute_action(
        rng=_SequenceRng([]),
        actor=caster,
        action=caster.actions[0],
        targets=[caster],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:caster",
        timing_engine=timing_engine,
        ready_declaration=ReadyDeclaration(
            trigger="enemy_turn_start",
            response_action_name=spell.name,
        ),
        reaction_decision_provider=pass_reaction,
    )

    assert windows == []
    assert caster.readied_spell_held is False
    assert "readying" not in caster.conditions


def test_counterspelled_readied_spell_still_opens_mage_slayer_window() -> None:
    caster = _actor(actor_id="caster", team="party")
    counterspeller = _actor(actor_id="a_counterspeller", team="enemy")
    slayer = _actor(actor_id="z_slayer", team="enemy")
    caster.position = (0.0, 0.0, 0.0)
    counterspeller.position = (30.0, 0.0, 0.0)
    slayer.position = (5.0, 0.0, 0.0)
    spell = _spell()
    caster.actions = [_ready_action(), spell]
    caster.resources["spell_slot_1"] = 1
    counterspeller.actions = [
        ActionDefinition(
            name="counterspell",
            action_type="utility",
            action_cost="reaction",
            target_mode="single_enemy",
            tags=["spell", "counterspell"],
        )
    ]
    counterspeller.resources["spell_slot_3"] = 1
    _mage_slayer(slayer)
    actors = {
        caster.actor_id: caster,
        counterspeller.actor_id: counterspeller,
        slayer.actor_id: slayer,
    }
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(
        caster, counterspeller, slayer
    )
    windows: list[ReactionWindowView] = []

    def pass_reaction(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _execute_action(
        rng=_SequenceRng([]),
        actor=caster,
        action=caster.actions[0],
        targets=[caster],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=1,
        turn_token="1:caster",
        ready_declaration=ReadyDeclaration(
            trigger="enemy_turn_start",
            response_action_name=spell.name,
        ),
        reaction_decision_provider=pass_reaction,
    )

    assert len(windows) == 1
    assert windows[0].reactor_id == slayer.actor_id
    assert counterspeller.resources["spell_slot_3"] == 0
    assert caster.readied_spell_held is False


def test_readied_spell_declaration_has_no_deferred_resolution_target() -> None:
    caster = _actor(actor_id="caster", team="party")
    enemy = _actor(actor_id="enemy", team="enemy")
    spell = _spell()
    caster.actions = [_ready_action(), spell]
    caster.resources["spell_slot_1"] = 1
    actors = {caster.actor_id: caster, enemy.actor_id: enemy}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, enemy)
    timing_engine = CombatTimingEngine()
    declaration_targets: list[ActorRuntimeState | None] = []
    timing_engine.subscribe(
        ActionDeclaredEvent,
        lambda event: declaration_targets.append(event.target),
        name="capture",
    )

    _execute_action(
        rng=_SequenceRng([]),
        actor=caster,
        action=caster.actions[0],
        targets=[caster],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        timing_engine=timing_engine,
        ready_declaration=ReadyDeclaration(
            trigger="enemy_turn_start",
            response_action_name=spell.name,
        ),
    )

    assert declaration_targets == [None]
    assert caster.readied_spell_held is True


def test_readied_multiattack_spell_preserves_each_concentration_linked_effect() -> None:
    caster = _actor(actor_id="caster", team="party")
    enemy = _actor(actor_id="enemy", team="enemy")
    caster.position = (0.0, 0.0, 0.0)
    enemy.position = (30.0, 0.0, 0.0)
    spell = _spell(name="binding_rays", concentration=True)
    spell.attack_count = 2
    spell.effects = [
        {
            "effect_type": "apply_condition",
            "apply_on": "hit",
            "target": "target",
            "condition": "marked",
            "duration_rounds": 2,
            "stack_policy": "independent",
        }
    ]
    caster.actions = [_ready_action(), spell]
    caster.resources["spell_slot_1"] = 1
    actors = {caster.actor_id: caster, enemy.actor_id: enemy}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, enemy)

    _execute_action(
        rng=_SequenceRng([]),
        actor=caster,
        action=caster.actions[0],
        targets=[caster],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        ready_declaration=ReadyDeclaration(
            trigger="enemy_turn_start",
            response_action_name=spell.name,
        ),
    )

    getattr(engine_module, "_trigger_readied_actions")(
        rng=_SequenceRng([10, 10]),
        trigger_actor=enemy,
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    marked_effects = [effect for effect in enemy.effect_instances if effect.condition == "marked"]
    assert len(marked_effects) == 2
    assert caster.concentration_effect_instance_ids == {
        effect.instance_id for effect in marked_effects
    }
