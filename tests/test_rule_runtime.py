from __future__ import annotations

import random

from dnd_sim.engine import _run_event_triggered_actions
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


def test_event_triggered_action_runs_and_writes_rule_trace() -> None:
    rng = random.Random(1)
    reactor = _base_actor(actor_id="reactor", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")
    reactor_action = ActionDefinition(
        name="riposte_reaction",
        action_type="attack",
        to_hit=100,
        damage="1",
        action_cost="reaction",
        target_mode="single_enemy",
        event_trigger="after_action",
        tags=["trigger_priority:10"],
    )
    reactor.actions = [reactor_action]
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
        round_number=1,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        rule_trace=trace,
    )

    assert enemy.hp < enemy.max_hp
    assert trace
    assert trace[0]["event"] == "after_action"
    assert trace[0]["actor_id"] == "reactor"
    assert trace[0]["result"] == "executed"


def test_event_triggered_actions_are_deterministic_by_priority_then_actor() -> None:
    rng = random.Random(2)
    alpha = _base_actor(actor_id="alpha", team="party")
    beta = _base_actor(actor_id="beta", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")
    alpha.actions = [
        ActionDefinition(
            name="alpha_trigger",
            action_type="attack",
            to_hit=100,
            damage="1",
            action_cost="reaction",
            target_mode="single_enemy",
            event_trigger="after_action",
            tags=["trigger_priority:5"],
        )
    ]
    beta.actions = [
        ActionDefinition(
            name="beta_trigger",
            action_type="attack",
            to_hit=100,
            damage="1",
            action_cost="reaction",
            target_mode="single_enemy",
            event_trigger="after_action",
            tags=["trigger_priority:10"],
        )
    ]
    actors = {alpha.actor_id: alpha, beta.actor_id: beta, enemy.actor_id: enemy}
    damage_dealt = {alpha.actor_id: 0, beta.actor_id: 0, enemy.actor_id: 0}
    damage_taken = {alpha.actor_id: 0, beta.actor_id: 0, enemy.actor_id: 0}
    threat_scores = {alpha.actor_id: 0, beta.actor_id: 0, enemy.actor_id: 0}
    resources_spent = {alpha.actor_id: {}, beta.actor_id: {}, enemy.actor_id: {}}
    trace: list[dict[str, object]] = []

    _run_event_triggered_actions(
        rng=rng,
        event="after_action",
        trigger_actor=enemy,
        actors=actors,
        round_number=1,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        rule_trace=trace,
    )

    executed = [entry["actor_id"] for entry in trace if entry["result"] == "executed"]
    assert executed == ["beta", "alpha"]
