from __future__ import annotations

import random

from dnd_sim.engine import _execute_action
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.spatial import AABB, distance_chebyshev


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

class _NoRollRng:
    def randint(self, _a: int, _b: int) -> int:
        raise AssertionError("Attack roll should not be made when no legal route exists")


def _trackers(
    *actors: ActorRuntimeState,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    damage_dealt = {actor.actor_id: 0 for actor in actors}
    damage_taken = {actor.actor_id: 0 for actor in actors}
    threat_scores = {actor.actor_id: 0 for actor in actors}
    resources_spent = {actor.actor_id: {} for actor in actors}
    return damage_dealt, damage_taken, threat_scores, resources_spent


def test_stand_from_prone_consumes_movement() -> None:
    actor = _base_actor(actor_id="attacker", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    actor.position = (0.0, 0.0, 0.0)
    target.position = (20.0, 0.0, 0.0)
    actor.speed_ft = 30
    actor.movement_remaining = 30.0
    actor.conditions.add("prone")

    attack = ActionDefinition(
        name="basic",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1",
        damage_type="piercing",
        range_ft=5,
    )
    actor.actions = [attack]

    actors = {actor.actor_id: actor, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(actor, target)

    _execute_action(
        rng=random.Random(17),
        actor=actor,
        action=attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert actor.position == (15.0, 0.0, 0.0)
    assert actor.movement_remaining == 0.0
    assert "prone" not in actor.conditions


def test_movement_path_does_not_traverse_total_cover_blocked_cells() -> None:
    attacker = _base_actor(actor_id="attacker", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    attacker.position = (0.0, 0.0, 0.0)
    target.position = (10.0, 0.0, 0.0)
    attacker.speed_ft = 5
    attacker.movement_remaining = 5.0

    attack = ActionDefinition(
        name="shortsword",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1d4",
        damage_type="piercing",
        range_ft=5,
    )
    attacker.actions = [attack]

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt = {attacker.actor_id: 0, target.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, target.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, target.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, target.actor_id: {}}

    obstacle = AABB(min_pos=(4.0, -1.0, -1.0), max_pos=(6.0, 1.0, 1.0), cover_level="TOTAL")
    _execute_action(
        rng=random.Random(21),
        actor=attacker,
        action=attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        obstacles=[obstacle],
    )

    in_blocked_cell = (
        obstacle.min_pos[0] <= attacker.position[0] <= obstacle.max_pos[0]
        and obstacle.min_pos[1] <= attacker.position[1] <= obstacle.max_pos[1]
        and obstacle.min_pos[2] <= attacker.position[2] <= obstacle.max_pos[2]
    )
    assert in_blocked_cell is False
    assert distance_chebyshev(attacker.position, target.position) <= 5.0


def test_movement_path_handles_no_legal_route_gracefully() -> None:
    attacker = _base_actor(actor_id="attacker", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    attacker.position = (0.0, 0.0, 0.0)
    target.position = (10.0, 0.0, 0.0)
    attacker.speed_ft = 30
    attacker.movement_remaining = 30.0

    attack = ActionDefinition(
        name="shortsword",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1d8+4",
        damage_type="piercing",
        range_ft=5,
    )
    attacker.actions = [attack]

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt = {attacker.actor_id: 0, target.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, target.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, target.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, target.actor_id: {}}

    # Target is enclosed by impassable terrain in this movement slice.
    wall = AABB(min_pos=(5.0, -10.0, -1.0), max_pos=(15.0, 10.0, 1.0), cover_level="TOTAL")
    _execute_action(
        rng=_NoRollRng(),
        actor=attacker,
        action=attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        obstacles=[wall],
    )

    assert attacker.position == (0.0, 0.0, 0.0)
    assert attacker.movement_remaining == 30.0
    assert target.hp == target.max_hp
    assert damage_dealt[attacker.actor_id] == 0
