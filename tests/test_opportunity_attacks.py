from __future__ import annotations

from dnd_sim.engine import _run_opportunity_attacks_for_movement
from dnd_sim.models import ActionDefinition, ActorRuntimeState


class _DeterministicRng:
    def randint(self, a: int, b: int) -> int:
        return max(a, min(b, 15))


def _base_actor(*, actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=30,
        hp=30,
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


def _trackers(
    *actors: ActorRuntimeState,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    damage_dealt = {actor.actor_id: 0 for actor in actors}
    damage_taken = {actor.actor_id: 0 for actor in actors}
    threat_scores = {actor.actor_id: 0 for actor in actors}
    resources_spent = {actor.actor_id: {} for actor in actors}
    return damage_dealt, damage_taken, threat_scores, resources_spent


def _melee_attack(name: str = "spear") -> ActionDefinition:
    return ActionDefinition(
        name=name,
        action_type="attack",
        action_cost="action",
        to_hit=8,
        damage="1d4",
        damage_type="piercing",
        range_ft=5,
    )


def test_voluntary_movement_out_of_reach_provokes_opportunity_attack() -> None:
    rng = _DeterministicRng()
    mover = _base_actor(actor_id="mover", team="party")
    guard = _base_actor(actor_id="guard", team="enemy")
    mover.position = (0.0, 0.0, 0.0)
    guard.position = (5.0, 0.0, 0.0)
    guard.actions = [_melee_attack()]

    actors = {mover.actor_id: mover, guard.actor_id: guard}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(mover, guard)

    _run_opportunity_attacks_for_movement(
        rng=rng,
        mover=mover,
        start_pos=(0.0, 0.0, 0.0),
        end_pos=(15.0, 0.0, 0.0),
        movement_path=[(0.0, 0.0, 0.0), (15.0, 0.0, 0.0)],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert guard.reaction_available is False
    assert mover.hp < mover.max_hp


def test_disengage_suppresses_opportunity_attack() -> None:
    rng = _DeterministicRng()
    mover = _base_actor(actor_id="mover", team="party")
    guard = _base_actor(actor_id="guard", team="enemy")
    mover.position = (0.0, 0.0, 0.0)
    guard.position = (5.0, 0.0, 0.0)
    mover.conditions.add("disengaging")
    guard.actions = [_melee_attack()]

    actors = {mover.actor_id: mover, guard.actor_id: guard}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(mover, guard)

    _run_opportunity_attacks_for_movement(
        rng=rng,
        mover=mover,
        start_pos=(0.0, 0.0, 0.0),
        end_pos=(15.0, 0.0, 0.0),
        movement_path=[(0.0, 0.0, 0.0), (15.0, 0.0, 0.0)],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert guard.reaction_available is True
    assert mover.hp == mover.max_hp


def test_forced_movement_does_not_provoke_opportunity_attack() -> None:
    rng = _DeterministicRng()
    mover = _base_actor(actor_id="mover", team="party")
    guard = _base_actor(actor_id="guard", team="enemy")
    mover.position = (0.0, 0.0, 0.0)
    guard.position = (5.0, 0.0, 0.0)
    guard.actions = [_melee_attack()]

    actors = {mover.actor_id: mover, guard.actor_id: guard}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(mover, guard)

    _run_opportunity_attacks_for_movement(
        rng=rng,
        mover=mover,
        start_pos=(0.0, 0.0, 0.0),
        end_pos=(15.0, 0.0, 0.0),
        movement_path=[(0.0, 0.0, 0.0), (15.0, 0.0, 0.0)],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        movement_kind="forced",
    )

    assert guard.reaction_available is True
    assert mover.hp == mover.max_hp


def test_reach_weapon_changes_opportunity_trigger_boundary() -> None:
    rng = _DeterministicRng()
    mover = _base_actor(actor_id="mover", team="party")
    short_guard = _base_actor(actor_id="short_guard", team="enemy")
    reach_guard = _base_actor(actor_id="reach_guard", team="enemy")

    mover.position = (9.0, 0.0, 0.0)
    short_guard.position = (0.0, 0.0, 0.0)
    reach_guard.position = (0.0, 0.0, 0.0)

    short_guard.actions = [_melee_attack(name="sword")]
    reach_guard.actions = [
        ActionDefinition(
            name="pike",
            action_type="attack",
            action_cost="action",
            to_hit=8,
            damage="1d4",
            damage_type="piercing",
            weapon_properties=["reach"],
            reach_ft=10,
            range_ft=10,
            range_normal_ft=10,
            range_long_ft=10,
        )
    ]

    actors = {
        mover.actor_id: mover,
        short_guard.actor_id: short_guard,
        reach_guard.actor_id: reach_guard,
    }
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(
        mover, short_guard, reach_guard
    )

    _run_opportunity_attacks_for_movement(
        rng=rng,
        mover=mover,
        start_pos=(9.0, 0.0, 0.0),
        end_pos=(15.0, 0.0, 0.0),
        movement_path=[(9.0, 0.0, 0.0), (15.0, 0.0, 0.0)],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert short_guard.reaction_available is True
    assert reach_guard.reaction_available is False
    assert mover.hp < mover.max_hp
