from __future__ import annotations

import random
from dataclasses import replace

import pytest

from dnd_sim.models import ActionDefinition, ActorRuntimeState, SpellCastRequest
from dnd_sim.rules_2014 import CombatTimingEngine
from dnd_sim.spell_runtime import (
    SpellPipelineAdapters,
    mode_requires_explicit_targets,
    resolve_action_targets,
    resolve_spell_cast_request,
    run_spell_declaration_pipeline,
)
from dnd_sim.strategy_api import TargetRef


def _actor(
    *, actor_id: str, team: str, position: tuple[float, float, float] = (0.0, 0.0, 0.0)
) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=24,
        hp=24,
        temp_hp=0,
        ac=13,
        initiative_mod=1,
        str_mod=0,
        dex_mod=1,
        con_mod=1,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 0, "dex": 1, "con": 1, "int": 0, "wis": 0, "cha": 0},
        actions=[],
        position=position,
    )


def _base_spell_action(
    *,
    name: str = "arcane_blast",
    target_mode: str = "single_enemy",
    concentration: bool = False,
) -> ActionDefinition:
    return ActionDefinition(
        name=name,
        action_type="save",
        target_mode=target_mode,
        action_cost="action",
        resource_cost={"spell_slot_3": 1},
        concentration=concentration,
        tags=["spell"],
    )


def test_mode_requires_explicit_targets_map() -> None:
    explicit = {
        "single_enemy",
        "single_ally",
        "n_enemies",
        "n_allies",
        "random_enemy",
        "random_ally",
    }
    for mode in explicit:
        assert mode_requires_explicit_targets(mode) is True

    for mode in {"self", "all_enemies", "all_allies", "all_creatures"}:
        assert mode_requires_explicit_targets(mode) is False


def test_resolve_spell_cast_request_defaults_mode_targets_origin_and_preferred_slot() -> None:
    caster = _actor(actor_id="caster", team="party", position=(1.0, 2.0, 0.0))
    enemy = _actor(actor_id="enemy", team="enemy", position=(5.0, 0.0, 0.0))
    action = _base_spell_action()

    request = resolve_spell_cast_request(
        actor=caster,
        action=action,
        targets=[enemy],
        provided=None,
        required_spell_slot_level=lambda _action: 3,
        preferred_spell_slot_level=lambda _action: 5,
    )

    assert request.mode == "single_enemy"
    assert request.target_actor_ids == ["enemy"]
    assert request.origin == (1.0, 2.0, 0.0)
    assert request.slot_level == 5


def test_resolve_spell_cast_request_rejects_slot_below_required_level() -> None:
    caster = _actor(actor_id="caster", team="party")
    enemy = _actor(actor_id="enemy", team="enemy")
    action = _base_spell_action()

    with pytest.raises(ValueError, match="slot level is below the spell level"):
        resolve_spell_cast_request(
            actor=caster,
            action=action,
            targets=[enemy],
            provided=SpellCastRequest(slot_level=2),
            required_spell_slot_level=lambda _action: 3,
            preferred_spell_slot_level=lambda _action: 3,
        )


def test_resolve_spell_cast_request_rejects_mode_mismatch() -> None:
    caster = _actor(actor_id="caster", team="party")
    enemy = _actor(actor_id="enemy", team="enemy")
    action = _base_spell_action(target_mode="single_enemy")

    with pytest.raises(ValueError, match="mode must match action target mode"):
        resolve_spell_cast_request(
            actor=caster,
            action=action,
            targets=[enemy],
            provided=SpellCastRequest(mode="single_ally", target_actor_ids=["enemy"]),
            required_spell_slot_level=lambda _action: 3,
            preferred_spell_slot_level=lambda _action: 3,
        )


def test_resolve_spell_cast_request_requires_explicit_target_ids_for_targeted_modes() -> None:
    caster = _actor(actor_id="caster", team="party")
    action = _base_spell_action(target_mode="n_enemies")

    with pytest.raises(ValueError, match="requires at least one target"):
        resolve_spell_cast_request(
            actor=caster,
            action=action,
            targets=[],
            provided=SpellCastRequest(mode="n_enemies"),
            required_spell_slot_level=lambda _action: 0,
            preferred_spell_slot_level=lambda _action: None,
        )


def test_resolve_action_targets_filters_requested_ids_for_declared_spell_targets() -> None:
    caster = _actor(actor_id="caster", team="party")
    enemy_a = _actor(actor_id="enemy_a", team="enemy")
    enemy_b = _actor(actor_id="enemy_b", team="enemy")

    action = _base_spell_action(target_mode="n_enemies")

    resolved = resolve_action_targets(
        rng=random.Random(1),
        actor=caster,
        action=action,
        actors={caster.actor_id: caster, enemy_a.actor_id: enemy_a, enemy_b.actor_id: enemy_b},
        requested=[TargetRef("enemy_a")],
        obstacles=None,
        active_hazards=[],
        light_level="bright",
        spell_cast_request=SpellCastRequest(mode="n_enemies", target_actor_ids=["enemy_a"]),
        resolve_targets_for_action=lambda **_kwargs: [enemy_a, enemy_b],
        filter_targets_in_range=lambda _actor, _action, targets, **_kwargs: targets,
    )

    assert [target.actor_id for target in resolved] == ["enemy_a"]


def _pipeline_adapters() -> SpellPipelineAdapters:
    return SpellPipelineAdapters(
        has_condition=lambda _actor, _condition: False,
        ritual_casting_legal_for_context=lambda _action, turn_token: True,
        spell_casting_legal_this_turn=lambda _actor, _action, turn_token: True,
        can_cast_spell_with_components=lambda _actor, _action: True,
        required_spell_slot_level=lambda _action: 3,
        preferred_spell_slot_level=lambda _action: 3,
        apply_upcast_scaling_for_slot=lambda action, slot_level: replace(
            action,
            tags=[*action.tags, f"upcast_level:{slot_level}"],
        ),
        can_take_reaction=lambda actor: actor.reaction_available,
        action_matches_reaction_spell_id=lambda action, spell_id: action.name == spell_id,
        counterspell_slot_if_legal=lambda **_kwargs: None,
        split_spell_slot_cost=lambda _cost: ({}, 0, []),
        spend_resources=lambda _actor, _cost: {},
        mark_action_cost_used=lambda actor, _action: setattr(actor, "reaction_available", False),
        spellcasting_ability_mod=lambda _actor: 0,
        is_action_cantrip_spell=lambda _action: False,
        break_concentration=lambda _actor, _actors, _hazards: None,
        is_smite_setup_action=lambda _action: False,
    )


def test_run_spell_declaration_pipeline_applies_upcast_and_concentration_state() -> None:
    caster = _actor(actor_id="caster", team="party")
    target = _actor(actor_id="target", team="enemy")
    action = _base_spell_action(name="hold_person", concentration=True)
    actors = {caster.actor_id: caster, target.actor_id: target}

    result = run_spell_declaration_pipeline(
        rng=random.Random(1),
        actor=caster,
        action=action,
        targets=[target],
        actors=actors,
        resources_spent={caster.actor_id: {}, target.actor_id: {}},
        active_hazards=[],
        round_number=1,
        turn_token="1:caster",
        timing_engine=CombatTimingEngine(),
        spell_cast_request=SpellCastRequest(slot_level=5),
        antimagic_suppression_condition="antimagic_suppressed",
        subtle_spell=False,
        light_level="bright",
        adapters=_pipeline_adapters(),
    )

    assert result is not None
    assert result.spell_level == 5
    assert "upcast_level:5" in result.action.tags
    assert caster.concentrating is True
    assert caster.concentrated_spell == "hold_person"
    assert caster.concentrated_spell_level == 5
    assert caster.non_action_cantrip_spell_cast_this_turn is True


def test_run_spell_declaration_pipeline_returns_none_when_counterspelled() -> None:
    caster = _actor(actor_id="caster", team="party")
    target = _actor(actor_id="target", team="enemy")
    enemy = _actor(actor_id="enemy", team="enemy")
    enemy.resources = {"spell_slot_3": 1}
    enemy.actions = [
        ActionDefinition(
            name="counterspell",
            action_type="utility",
            action_cost="reaction",
            target_mode="single_enemy",
            tags=["spell", "counterspell"],
        )
    ]

    adapters = _pipeline_adapters()
    adapters = replace(
        adapters,
        counterspell_slot_if_legal=lambda **_kwargs: ("spell_slot_3", 3),
    )

    result = run_spell_declaration_pipeline(
        rng=random.Random(1),
        actor=caster,
        action=_base_spell_action(name="lightning_bolt"),
        targets=[target],
        actors={caster.actor_id: caster, target.actor_id: target, enemy.actor_id: enemy},
        resources_spent={caster.actor_id: {}, target.actor_id: {}, enemy.actor_id: {}},
        active_hazards=[],
        round_number=1,
        turn_token="1:caster",
        timing_engine=CombatTimingEngine(),
        spell_cast_request=SpellCastRequest(slot_level=3),
        antimagic_suppression_condition="antimagic_suppressed",
        subtle_spell=False,
        light_level="bright",
        adapters=adapters,
    )

    assert result is None
    assert enemy.resources["spell_slot_3"] == 0
    assert caster.non_action_cantrip_spell_cast_this_turn is True
