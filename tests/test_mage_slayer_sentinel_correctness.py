from __future__ import annotations

from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.rules_2014 import (
    evaluate_mage_slayer_reaction_window,
    evaluate_sentinel_opportunity_window,
    evaluate_sentinel_reaction_window,
    sentinel_speed_reduction_applies_on_hit,
)


def _actor(*, actor_id: str, team: str, traits: tuple[str, ...] = ()) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=20,
        hp=20,
        temp_hp=0,
        ac=14,
        initiative_mod=0,
        str_mod=2,
        dex_mod=2,
        con_mod=2,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 2, "dex": 2, "con": 2, "int": 0, "wis": 0, "cha": 0},
        actions=[],
        traits={trait: {} for trait in traits},
    )


def test_mage_slayer_window_requires_enemy_spell_cast_within_five_feet() -> None:
    reactor = _actor(actor_id="reactor", team="party", traits=("mage slayer",))
    enemy = _actor(actor_id="enemy", team="enemy")
    spell_action = ActionDefinition(name="fire_bolt", action_type="save", tags=["spell"])

    allowed = evaluate_mage_slayer_reaction_window(
        reactor=reactor,
        trigger_actor=enemy,
        trigger_action=spell_action,
        distance_ft=5.0,
    )
    out_of_range = evaluate_mage_slayer_reaction_window(
        reactor=reactor,
        trigger_actor=enemy,
        trigger_action=spell_action,
        distance_ft=10.0,
    )

    assert allowed.allowed is True
    assert allowed.reason is None
    assert out_of_range.allowed is False
    assert out_of_range.reason == "out_of_range"


def test_mage_slayer_window_rejects_without_required_trait() -> None:
    reactor = _actor(actor_id="reactor", team="party")
    enemy = _actor(actor_id="enemy", team="enemy")
    spell_action = ActionDefinition(name="fire_bolt", action_type="save", tags=["spell"])

    result = evaluate_mage_slayer_reaction_window(
        reactor=reactor,
        trigger_actor=enemy,
        trigger_action=spell_action,
        distance_ft=5.0,
    )

    assert result.allowed is False
    assert result.reason == "missing_trait"


def test_sentinel_window_requires_enemy_attacking_ally_within_five_feet() -> None:
    sentinel = _actor(actor_id="sentinel", team="party", traits=("sentinel",))
    ally = _actor(actor_id="ally", team="party")
    enemy = _actor(actor_id="enemy", team="enemy")
    attack_action = ActionDefinition(name="slash", action_type="attack")

    allowed = evaluate_sentinel_reaction_window(
        reactor=sentinel,
        trigger_actor=enemy,
        trigger_target=ally,
        trigger_action=attack_action,
        distance_ft=5.0,
    )
    illegal_self_target = evaluate_sentinel_reaction_window(
        reactor=sentinel,
        trigger_actor=enemy,
        trigger_target=sentinel,
        trigger_action=attack_action,
        distance_ft=5.0,
    )

    assert allowed.allowed is True
    assert allowed.reason is None
    assert illegal_self_target.allowed is False
    assert illegal_self_target.reason == "invalid_target_window"


def test_sentinel_window_rejects_without_required_trait() -> None:
    reactor = _actor(actor_id="reactor", team="party")
    ally = _actor(actor_id="ally", team="party")
    enemy = _actor(actor_id="enemy", team="enemy")
    attack_action = ActionDefinition(name="slash", action_type="attack")

    result = evaluate_sentinel_reaction_window(
        reactor=reactor,
        trigger_actor=enemy,
        trigger_target=ally,
        trigger_action=attack_action,
        distance_ft=5.0,
    )

    assert result.allowed is False
    assert result.reason == "missing_trait"


def test_sentinel_opportunity_window_obeys_reach_and_forced_movement_rules() -> None:
    sentinel = _actor(actor_id="sentinel", team="party")
    mover = _actor(actor_id="mover", team="enemy")

    allowed = evaluate_sentinel_opportunity_window(
        reactor=sentinel,
        trigger_actor=mover,
        trigger_distance_ft=10.0,
        reach_ft=10.0,
        mover_disengaged=True,
        forced_movement=False,
    )
    forced = evaluate_sentinel_opportunity_window(
        reactor=sentinel,
        trigger_actor=mover,
        trigger_distance_ft=10.0,
        reach_ft=10.0,
        mover_disengaged=False,
        forced_movement=True,
    )
    too_far = evaluate_sentinel_opportunity_window(
        reactor=sentinel,
        trigger_actor=mover,
        trigger_distance_ft=15.0,
        reach_ft=10.0,
        mover_disengaged=False,
        forced_movement=False,
    )

    assert allowed.allowed is True
    assert allowed.reason is None
    assert forced.allowed is False
    assert forced.reason == "forced_movement"
    assert too_far.allowed is False
    assert too_far.reason == "out_of_reach"


def test_reaction_lockout_prevents_illegal_stacking_across_features() -> None:
    reactor = _actor(actor_id="reactor", team="party")
    enemy = _actor(actor_id="enemy", team="enemy")
    ally = _actor(actor_id="ally", team="party")
    spell_action = ActionDefinition(name="misty_step", action_type="utility", tags=["spell"])
    attack_action = ActionDefinition(name="slash", action_type="attack")

    sentinel_locked = evaluate_sentinel_reaction_window(
        reactor=reactor,
        trigger_actor=enemy,
        trigger_target=ally,
        trigger_action=attack_action,
        distance_ft=5.0,
        reaction_lock_active=True,
    )

    reactor.reaction_available = False
    mage_slayer_spent = evaluate_mage_slayer_reaction_window(
        reactor=reactor,
        trigger_actor=enemy,
        trigger_action=spell_action,
        distance_ft=5.0,
    )

    assert sentinel_locked.allowed is False
    assert sentinel_locked.reason == "reaction_lock"
    assert mage_slayer_spent.allowed is False
    assert mage_slayer_spent.reason == "reaction_unavailable"


def test_sentinel_speed_reduction_applies_only_on_opportunity_hit() -> None:
    assert sentinel_speed_reduction_applies_on_hit(hit=True, opportunity_attack=True) is True
    assert sentinel_speed_reduction_applies_on_hit(hit=False, opportunity_attack=True) is False
    assert sentinel_speed_reduction_applies_on_hit(hit=True, opportunity_attack=False) is False
