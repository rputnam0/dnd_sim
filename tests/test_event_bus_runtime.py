from __future__ import annotations

import random

from dnd_sim.engine import _dispatch_combat_event
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


def test_dispatch_combat_event_supports_phase1_hook_names() -> None:
    rng = random.Random(10)
    reactor = _base_actor(actor_id="reactor", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")
    hook_names = ["turn_start", "turn_end", "on_hit", "on_miss", "on_save", "on_move", "on_down"]
    reactor.actions = [
        ActionDefinition(
            name=f"hook_{event_name}",
            action_type="utility",
            event_trigger=event_name,
            target_mode="self",
        )
        for event_name in hook_names
    ]

    actors = {reactor.actor_id: reactor, enemy.actor_id: enemy}
    damage_dealt = {reactor.actor_id: 0, enemy.actor_id: 0}
    damage_taken = {reactor.actor_id: 0, enemy.actor_id: 0}
    threat_scores = {reactor.actor_id: 0, enemy.actor_id: 0}
    resources_spent = {reactor.actor_id: {}, enemy.actor_id: {}}
    trace: list[dict[str, object]] = []

    for event_name in hook_names:
        _dispatch_combat_event(
            rng=rng,
            event=event_name,
            trigger_actor=enemy,
            trigger_target=reactor,
            trigger_action=None,
            actors=actors,
            round_number=1,
            turn_token=f"1:{event_name}",
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=[],
            rule_trace=trace,
        )

    executed = [entry["event"] for entry in trace if entry.get("result") == "executed"]
    assert executed == hook_names


def test_dispatch_combat_event_enforces_duration_per_turn_and_round_locks() -> None:
    rng = random.Random(11)
    reactor = _base_actor(actor_id="reactor", team="party")
    enemy = _base_actor(actor_id="enemy", team="enemy")
    reactor.actions = [
        ActionDefinition(
            name="single_round_reaction",
            action_type="attack",
            to_hit=100,
            damage="1",
            action_cost="reaction",
            event_trigger="on_hit",
            target_mode="single_enemy",
            trigger_duration_rounds=1,
            trigger_limit_per_turn=1,
            trigger_once_per_round=True,
        )
    ]
    actors = {reactor.actor_id: reactor, enemy.actor_id: enemy}
    damage_dealt = {reactor.actor_id: 0, enemy.actor_id: 0}
    damage_taken = {reactor.actor_id: 0, enemy.actor_id: 0}
    threat_scores = {reactor.actor_id: 0, enemy.actor_id: 0}
    resources_spent = {reactor.actor_id: {}, enemy.actor_id: {}}
    trace: list[dict[str, object]] = []

    _dispatch_combat_event(
        rng=rng,
        event="on_hit",
        trigger_actor=enemy,
        trigger_target=reactor,
        trigger_action=None,
        actors=actors,
        round_number=1,
        turn_token="1:enemy",
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        rule_trace=trace,
    )
    first_executed = [row for row in trace if row.get("result") == "executed"]
    assert len(first_executed) == 1

    reactor.reaction_available = True
    _dispatch_combat_event(
        rng=rng,
        event="on_hit",
        trigger_actor=enemy,
        trigger_target=reactor,
        trigger_action=None,
        actors=actors,
        round_number=1,
        turn_token="1:enemy",
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        rule_trace=trace,
    )

    reactor.reaction_available = True
    _dispatch_combat_event(
        rng=rng,
        event="on_hit",
        trigger_actor=enemy,
        trigger_target=reactor,
        trigger_action=None,
        actors=actors,
        round_number=1,
        turn_token="1:enemy_2",
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        rule_trace=trace,
    )

    reactor.reaction_available = True
    _dispatch_combat_event(
        rng=rng,
        event="on_hit",
        trigger_actor=enemy,
        trigger_target=reactor,
        trigger_action=None,
        actors=actors,
        round_number=2,
        turn_token="2:enemy",
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        rule_trace=trace,
    )

    reasons = [str(row.get("reason", "")) for row in trace if row.get("result") == "skipped"]
    assert "per_turn_limit" in reasons
    assert "reaction_lock" in reasons
    assert "expired" in reasons


def test_dispatch_combat_event_runs_trait_handler_for_sentinel_reaction() -> None:
    rng = random.Random(12)
    attacker = _base_actor(actor_id="attacker", team="enemy")
    ally_target = _base_actor(actor_id="ally_target", team="party")
    sentinel = _base_actor(actor_id="sentinel", team="party")
    sentinel.actions = [
        ActionDefinition(
            name="basic",
            action_type="attack",
            to_hit=100,
            damage="1",
            target_mode="single_enemy",
        )
    ]
    sentinel.traits = {"sentinel": {"mechanics": [{"effect_type": "reaction_attack"}]}}
    actors = {
        attacker.actor_id: attacker,
        ally_target.actor_id: ally_target,
        sentinel.actor_id: sentinel,
    }
    damage_dealt = {actor_id: 0 for actor_id in actors}
    damage_taken = {actor_id: 0 for actor_id in actors}
    threat_scores = {actor_id: 0 for actor_id in actors}
    resources_spent = {actor_id: {} for actor_id in actors}
    trace: list[dict[str, object]] = []
    trigger_action = ActionDefinition(
        name="enemy_slash",
        action_type="attack",
        to_hit=5,
        damage="1",
        target_mode="single_enemy",
    )

    _dispatch_combat_event(
        rng=rng,
        event="after_action",
        trigger_actor=attacker,
        trigger_target=ally_target,
        trigger_action=trigger_action,
        actors=actors,
        round_number=1,
        turn_token="1:attacker",
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        rule_trace=trace,
    )

    assert attacker.hp < attacker.max_hp
    assert sentinel.reaction_available is False
    trait_events = [row for row in trace if row.get("handler") == "trait:sentinel_reaction"]
    assert trait_events
