from __future__ import annotations

import random

from dnd_sim.engine import _break_concentration, _dispatch_combat_event, _execute_action
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.spatial import can_see


def _runtime_actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=30,
        hp=30,
        temp_hp=0,
        ac=15,
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


def test_cloud_zone_obscures_vision_and_applies_start_of_turn_effect() -> None:
    clouded = _runtime_actor(actor_id="clouded", team="party")
    enemy = _runtime_actor(actor_id="enemy", team="enemy")
    clouded.position = (0.0, 0.0, 0.0)
    enemy.position = (25.0, 0.0, 0.0)
    actors = {clouded.actor_id: clouded, enemy.actor_id: enemy}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(clouded, enemy)
    active_hazards: list[dict[str, object]] = [
        {
            "type": "cloud",
            "hazard_type": "cloud",
            "zone_instance_id": "cloud:1",
            "position": (0.0, 0.0, 0.0),
            "radius": 10.0,
            "obscures_vision": True,
            "on_start_turn": [
                {
                    "effect_type": "damage",
                    "damage": "1d4",
                    "damage_type": "poison",
                    "target": "target",
                }
            ],
        }
    ]

    assert (
        can_see(
            observer_pos=enemy.position,
            target_pos=clouded.position,
            observer_traits={},
            target_conditions=clouded.conditions,
            active_hazards=active_hazards,
        )
        is False
    )

    _dispatch_combat_event(
        rng=random.Random(1),
        event="turn_start",
        trigger_actor=clouded,
        trigger_target=clouded,
        trigger_action=None,
        actors=actors,
        round_number=1,
        turn_token="1:clouded",
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
        obstacles=[],
        light_level="bright",
    )

    assert clouded.hp < clouded.max_hp
    assert damage_taken[clouded.actor_id] > 0


def test_wall_zone_blocks_movement_and_line_of_effect() -> None:
    attacker = _runtime_actor(actor_id="attacker", team="party")
    target = _runtime_actor(actor_id="target", team="enemy")
    attacker.position = (0.0, 0.0, 0.0)
    target.position = (30.0, 0.0, 0.0)
    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(attacker, target)

    wall_zone = {
        "type": "wall",
        "hazard_type": "wall",
        "zone_instance_id": "wall:1",
        "min_pos": (10.0, -100.0, -5.0),
        "max_pos": (20.0, 100.0, 5.0),
        "blocks_movement": True,
        "blocks_line_of_effect": True,
    }
    active_hazards: list[dict[str, object]] = [wall_zone]

    melee = ActionDefinition(
        name="sword",
        action_type="attack",
        to_hit=8,
        damage="1d8+4",
        damage_type="slashing",
        reach_ft=5,
    )
    _execute_action(
        rng=random.Random(1),
        actor=attacker,
        action=melee,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
        obstacles=[],
    )

    assert attacker.position == (0.0, 0.0, 0.0)
    assert target.hp == target.max_hp

    ranged = ActionDefinition(
        name="longbow",
        action_type="attack",
        to_hit=10,
        damage="1d8+4",
        damage_type="piercing",
        range_ft=150,
    )
    _execute_action(
        rng=random.Random(1),
        actor=attacker,
        action=ranged,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
        obstacles=[],
    )

    assert target.hp == target.max_hp
    assert damage_dealt[attacker.actor_id] == 0


def test_destroyed_or_expired_zone_stops_interacting_immediately() -> None:
    caster = _runtime_actor(actor_id="caster", team="party")
    target = _runtime_actor(actor_id="target", team="enemy")
    caster.position = (0.0, 0.0, 0.0)
    target.position = (10.0, 0.0, 0.0)
    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(caster, target)

    expiring_zone: dict[str, object] = {
        "type": "damaging_surface",
        "hazard_type": "damaging_surface",
        "zone_instance_id": "zone:expiring",
        "position": (0.0, 0.0, 0.0),
        "radius": 10.0,
        "duration": 1,
        "duration_boundary": "turn_start",
        "on_start_turn": [
            {"effect_type": "damage", "damage": "4", "damage_type": "acid", "target": "target"}
        ],
    }
    active_hazards: list[dict[str, object]] = [expiring_zone]

    _dispatch_combat_event(
        rng=random.Random(1),
        event="turn_start",
        trigger_actor=caster,
        trigger_target=caster,
        trigger_action=None,
        actors=actors,
        round_number=1,
        turn_token="1:caster",
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
        obstacles=[],
        light_level="bright",
    )

    assert caster.hp == caster.max_hp
    assert active_hazards == []

    active_hazards.append(
        {
            "type": "cloud",
            "hazard_type": "cloud",
            "zone_instance_id": "zone:destroyed",
            "source_id": caster.actor_id,
            "position": (0.0, 0.0, 0.0),
            "radius": 10.0,
            "obscures_vision": True,
        }
    )
    caster.concentrating = True
    caster.concentrated_spell = "fog_cloud"
    caster.concentrated_spell_level = 1

    assert (
        can_see(
            observer_pos=target.position,
            target_pos=caster.position,
            observer_traits={},
            target_conditions=caster.conditions,
            active_hazards=active_hazards,
        )
        is False
    )

    _break_concentration(caster, actors, active_hazards)

    assert active_hazards == []
    assert (
        can_see(
            observer_pos=target.position,
            target_pos=caster.position,
            observer_traits={},
            target_conditions=caster.conditions,
            active_hazards=active_hazards,
        )
        is True
    )
