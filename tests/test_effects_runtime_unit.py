from __future__ import annotations

import random

from dnd_sim import effects_runtime
from dnd_sim.models import ActionDefinition, ActorRuntimeState


def _actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=30,
        hp=30,
        temp_hp=0,
        ac=14,
        initiative_mod=2,
        str_mod=1,
        dex_mod=2,
        con_mod=1,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 1, "dex": 2, "con": 1, "int": 0, "wis": 0, "cha": 0},
        actions=[ActionDefinition(name="basic", action_type="attack")],
        position=(0.0, 0.0, 0.0),
    )


def test_effect_duration_expires_on_tick_boundary() -> None:
    actor = _actor(actor_id="hero", team="party")
    effects_runtime.apply_condition(
        actor,
        "blinded",
        duration_rounds=1,
        duration_timing="turn_start",
    )

    assert "blinded" in actor.conditions
    effects_runtime.tick_conditions_for_actor(random.Random(1), actor, boundary="turn_start")

    assert "blinded" not in actor.conditions


def test_condition_refresh_stacking_keeps_single_instance_and_longer_duration() -> None:
    actor = _actor(actor_id="hero", team="party")
    first_ids = effects_runtime.apply_condition(
        actor,
        "stunned",
        duration_rounds=2,
        effect_id="stun_effect",
        stack_policy="independent",
    )
    refreshed_ids = effects_runtime.apply_condition(
        actor,
        "stunned",
        duration_rounds=5,
        effect_id="stun_effect",
        stack_policy="refresh",
    )

    stunned_effects = [effect for effect in actor.effect_instances if effect.condition == "stunned"]
    assert len(stunned_effects) == 1
    assert stunned_effects[0].duration_remaining == 5
    assert refreshed_ids == [stunned_effects[0].instance_id]
    assert first_ids == [stunned_effects[0].instance_id]


def test_condition_cleanup_removes_implied_condition_when_last_effect_removed() -> None:
    actor = _actor(actor_id="hero", team="party")
    effects_runtime.apply_condition(actor, "stunned", duration_rounds=3)
    assert "stunned" in actor.conditions
    assert "incapacitated" in actor.conditions

    effects_runtime.remove_condition(actor, "stunned")

    assert "stunned" not in actor.conditions
    assert "incapacitated" not in actor.conditions
