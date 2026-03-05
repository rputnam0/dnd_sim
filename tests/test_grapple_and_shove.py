from __future__ import annotations

import random

from dnd_sim.engine_runtime import _execute_action
from dnd_sim.models import ActionDefinition, ActorRuntimeState


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
        str_mod=2,
        dex_mod=2,
        con_mod=2,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 2, "dex": 2, "con": 2, "int": 0, "wis": 0, "cha": 0},
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


def test_extra_attack_grapple_replaces_only_one_attack(monkeypatch) -> None:
    monkeypatch.setattr("dnd_sim.rules_2014.run_contested_check", lambda *_args, **_kwargs: True)

    attacker = _base_actor(actor_id="attacker", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    target.position = (5.0, 0.0, 0.0)

    grapple = ActionDefinition(name="grapple", action_type="grapple", action_cost="action")
    basic = ActionDefinition(
        name="basic",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1",
        damage_type="bludgeoning",
        attack_count=2,
        range_ft=5,
    )
    attacker.actions = [grapple, basic]

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(attacker, target)

    _execute_action(
        rng=random.Random(7),
        actor=attacker,
        action=grapple,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert "grappled" in target.conditions
    assert damage_dealt[attacker.actor_id] == 1
    assert target.hp == target.max_hp - 1


def test_shove_push_moves_target_five_feet(monkeypatch) -> None:
    monkeypatch.setattr("dnd_sim.rules_2014.run_contested_check", lambda *_args, **_kwargs: True)

    attacker = _base_actor(actor_id="attacker", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    target.position = (5.0, 0.0, 0.0)

    shove = ActionDefinition(
        name="shove",
        action_type="shove",
        action_cost="action",
        tags=["shove_mode:push"],
    )

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(attacker, target)

    _execute_action(
        rng=random.Random(11),
        actor=attacker,
        action=shove,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.position == (10.0, 0.0, 0.0)
    assert "prone" not in target.conditions


def test_grappled_target_can_use_action_to_escape(monkeypatch) -> None:
    monkeypatch.setattr("dnd_sim.rules_2014.run_contested_check", lambda *_args, **_kwargs: True)

    grappler = _base_actor(actor_id="grappler", team="enemy")
    grappled = _base_actor(actor_id="grappled", team="party")
    grappled.conditions.add("grappled")
    grappler.position = (5.0, 0.0, 0.0)
    grappled.position = (0.0, 0.0, 0.0)

    escape = ActionDefinition(
        name="escape_grapple",
        action_type="utility",
        action_cost="action",
        target_mode="self",
        tags=["requires_condition:grappled"],
    )
    grappled.actions = [escape]

    actors = {grappler.actor_id: grappler, grappled.actor_id: grappled}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(grappler, grappled)

    _execute_action(
        rng=random.Random(13),
        actor=grappled,
        action=escape,
        targets=[grappled],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert "grappled" not in grappled.conditions


def test_grapple_follow_up_does_not_inherit_action_surge_attack_volume(monkeypatch) -> None:
    monkeypatch.setattr("dnd_sim.rules_2014.run_contested_check", lambda *_args, **_kwargs: True)

    attacker = _base_actor(actor_id="attacker", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    target.position = (5.0, 0.0, 0.0)

    grapple = ActionDefinition(name="grapple", action_type="grapple", action_cost="action")
    basic = ActionDefinition(
        name="basic",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1",
        damage_type="bludgeoning",
        attack_count=2,
        range_ft=5,
    )
    action_surge = ActionDefinition(
        name="action_surge",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1",
        damage_type="bludgeoning",
        attack_count=4,
        range_ft=5,
        resource_cost={"action_surge": 1},
        tags=["action_surge", "fighter_action_surge"],
    )
    attacker.actions = [grapple, basic, action_surge]
    attacker.resources["action_surge"] = 1

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(attacker, target)

    _execute_action(
        rng=random.Random(17),
        actor=attacker,
        action=grapple,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert "grappled" in target.conditions
    assert damage_dealt[attacker.actor_id] == 1
    assert damage_taken[target.actor_id] == 1
    assert attacker.resources["action_surge"] == 1
    assert resources_spent[attacker.actor_id].get("action_surge", 0) == 0
