from __future__ import annotations

import random

from dnd_sim.engine_runtime import _run_event_triggered_actions
from dnd_sim.models import ActionDefinition, ActorRuntimeState


def _base_actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=20,
        hp=20,
        temp_hp=0,
        ac=10,
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


def test_event_triggered_reaction_is_locked_once_per_round() -> None:
    rng = random.Random(7)
    reactor = _base_actor(actor_id="reactor", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")
    reactor.actions = [
        ActionDefinition(
            name="reactive_strike_a",
            action_type="attack",
            to_hit=100,
            damage="1",
            action_cost="reaction",
            target_mode="single_enemy",
            event_trigger="after_action",
            tags=["trigger_priority:10"],
        ),
        ActionDefinition(
            name="reactive_strike_b",
            action_type="attack",
            to_hit=100,
            damage="1",
            action_cost="reaction",
            target_mode="single_enemy",
            event_trigger="after_action",
            tags=["trigger_priority:5"],
        ),
    ]
    actors = {reactor.actor_id: reactor, enemy.actor_id: enemy}
    damage_dealt = {reactor.actor_id: 0, enemy.actor_id: 0}
    damage_taken = {reactor.actor_id: 0, enemy.actor_id: 0}
    threat_scores = {reactor.actor_id: 0, enemy.actor_id: 0}
    resources_spent = {reactor.actor_id: {}, enemy.actor_id: {}}
    trace: list[dict[str, object]] = []

    _run_event_triggered_actions(
        rng=rng,
        event="after_action",
        trigger_actor=enemy,
        actors=actors,
        round_number=3,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        rule_trace=trace,
    )
    first_round_executed = [entry for entry in trace if entry["result"] == "executed"]
    assert len(first_round_executed) == 1

    reactor.reaction_available = True
    _run_event_triggered_actions(
        rng=rng,
        event="after_action",
        trigger_actor=enemy,
        actors=actors,
        round_number=3,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        rule_trace=trace,
    )
    same_round_executed = [entry for entry in trace if entry["result"] == "executed"]
    assert len(same_round_executed) == 1

    reactor.reaction_available = True
    _run_event_triggered_actions(
        rng=rng,
        event="after_action",
        trigger_actor=enemy,
        actors=actors,
        round_number=4,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        rule_trace=trace,
    )
    next_round_executed = [entry for entry in trace if entry["result"] == "executed"]
    assert len(next_round_executed) == 2
