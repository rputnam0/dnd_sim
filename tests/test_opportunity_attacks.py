from __future__ import annotations

import dnd_sim.engine_runtime as engine_module
from dnd_sim.engine_runtime import (
    _apply_declared_movement_or_error,
    _execute_action,
    _run_opportunity_attacks_for_movement,
    _tick_conditions_for_actor,
)
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


def test_sentinel_opportunity_attack_ignores_disengage_and_stops_movement_on_hit() -> None:
    rng = _DeterministicRng()
    mover = _base_actor(actor_id="mover", team="party")
    sentinel = _base_actor(actor_id="sentinel", team="enemy")
    mover.position = (0.0, 0.0, 0.0)
    mover.movement_remaining = 30.0
    mover.conditions.add("disengaging")
    sentinel.position = (5.0, 0.0, 0.0)
    sentinel.traits = {"sentinel": {}}
    sentinel.actions = [_melee_attack()]
    telemetry: list[dict] = []
    rule_trace: list[dict] = []

    actors = {mover.actor_id: mover, sentinel.actor_id: sentinel}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(mover, sentinel)

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
        telemetry=telemetry,
        rule_trace=rule_trace,
    )

    assert sentinel.reaction_available is False
    assert mover.hp < mover.max_hp
    assert mover.movement_remaining == 0.0
    assert mover.position == (10.0, 0.0, 0.0)
    assert "sentinel_speed_zero" in mover.conditions
    assert any(
        row.get("telemetry_type") == "reaction_effect_applied"
        and row.get("effect") == "speed_zero_for_turn"
        for row in telemetry
    )
    assert any(row.get("handler") == "trait:sentinel_speed_zero" for row in rule_trace)

    _execute_action(
        rng=rng,
        actor=mover,
        action=ActionDefinition(
            name="dash",
            action_type="utility",
            action_cost="action",
            target_mode="self",
            tags=["utility_dash"],
        ),
        targets=[mover],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert mover.movement_remaining == 0.0
    _tick_conditions_for_actor(rng, mover)
    assert "sentinel_speed_zero" not in mover.conditions


def test_sentinel_opportunity_attack_miss_does_not_stop_movement() -> None:
    rng = _DeterministicRng()
    mover = _base_actor(actor_id="mover", team="party")
    sentinel = _base_actor(actor_id="sentinel", team="enemy")
    mover.position = (0.0, 0.0, 0.0)
    mover.movement_remaining = 30.0
    sentinel.position = (5.0, 0.0, 0.0)
    sentinel.traits = {"sentinel": {}}
    missed_attack = _melee_attack()
    missed_attack.to_hit = -100
    sentinel.actions = [missed_attack]

    actors = {mover.actor_id: mover, sentinel.actor_id: sentinel}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(mover, sentinel)

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

    assert sentinel.reaction_available is False
    assert mover.hp == mover.max_hp
    assert mover.movement_remaining == 30.0
    assert mover.position == (15.0, 0.0, 0.0)


def test_sentinel_opportunity_hit_stops_a_damage_immune_mover() -> None:
    rng = _DeterministicRng()
    mover = _base_actor(actor_id="mover", team="party")
    sentinel = _base_actor(actor_id="sentinel", team="enemy")
    mover.position = (0.0, 0.0, 0.0)
    mover.movement_remaining = 30.0
    mover.damage_immunities.add("piercing")
    sentinel.position = (5.0, 0.0, 0.0)
    sentinel.traits = {"sentinel": {}}
    sentinel.actions = [_melee_attack()]

    actors = {mover.actor_id: mover, sentinel.actor_id: sentinel}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(mover, sentinel)

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

    assert mover.hp == mover.max_hp
    assert mover.movement_remaining == 0.0
    assert mover.position == (10.0, 0.0, 0.0)


def test_declared_movement_commits_sentinel_interrupt_position() -> None:
    rng = _DeterministicRng()
    mover = _base_actor(actor_id="mover", team="party")
    sentinel = _base_actor(actor_id="sentinel", team="enemy")
    mover.position = (0.0, 0.0, 0.0)
    mover.movement_remaining = 30.0
    sentinel.position = (5.0, 0.0, 0.0)
    sentinel.traits = {"sentinel": {}}
    sentinel.actions = [_melee_attack()]
    actors = {mover.actor_id: mover, sentinel.actor_id: sentinel}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(mover, sentinel)

    _apply_declared_movement_or_error(
        rng=rng,
        actor=mover,
        movement_path=[(0.0, 0.0, 0.0), (15.0, 0.0, 0.0)],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert mover.position == (10.0, 0.0, 0.0)
    assert mover.movement_remaining == 0.0


def test_declared_movement_sends_only_committed_prefix_to_zones_and_hazards(
    monkeypatch,
) -> None:
    rng = _DeterministicRng()
    mover = _base_actor(actor_id="mover", team="party")
    sentinel = _base_actor(actor_id="sentinel", team="enemy")
    mover.position = (0.0, 0.0, 0.0)
    mover.movement_remaining = 30.0
    sentinel.position = (5.0, 0.0, 0.0)
    sentinel.traits = {"sentinel": {}}
    sentinel.actions = [_melee_attack()]
    actors = {mover.actor_id: mover, sentinel.actor_id: sentinel}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(mover, sentinel)
    seen_paths: dict[str, list[tuple[float, float, float]]] = {}

    def capture_zone_path(**kwargs) -> None:
        seen_paths["zones"] = list(kwargs["path"])
        kwargs["actor"].position = kwargs["path"][-1]

    def capture_hazard_path(**kwargs) -> None:
        seen_paths["hazards"] = list(kwargs["movement_path"])

    monkeypatch.setattr(
        engine_module,
        "_update_actor_zone_interactions_for_movement",
        capture_zone_path,
    )
    monkeypatch.setattr(
        engine_module,
        "_process_hazard_movement_triggers",
        capture_hazard_path,
    )

    _apply_declared_movement_or_error(
        rng=rng,
        actor=mover,
        movement_path=[(0.0, 0.0, 0.0), (15.0, 0.0, 0.0)],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert seen_paths["zones"][-1] == (10.0, 0.0, 0.0)
    assert seen_paths["hazards"][-1] == (10.0, 0.0, 0.0)
    assert all(point[0] <= 10.0 for point in seen_paths["zones"])
    assert all(point[0] <= 10.0 for point in seen_paths["hazards"])


def test_sentinel_stop_prevents_later_reactors_from_using_abandoned_path() -> None:
    rng = _DeterministicRng()
    mover = _base_actor(actor_id="mover", team="party")
    sentinel = _base_actor(actor_id="sentinel", team="enemy")
    other_guard = _base_actor(actor_id="other_guard", team="enemy")
    mover.position = (0.0, 0.0, 0.0)
    mover.movement_remaining = 30.0
    sentinel.position = (5.0, 0.0, 0.0)
    other_guard.position = (5.0, 0.0, 0.0)
    sentinel.traits = {"sentinel": {}}
    sentinel.actions = [_melee_attack("sentinel_spear")]
    other_guard.actions = [_melee_attack("guard_spear")]
    actors = {
        mover.actor_id: mover,
        sentinel.actor_id: sentinel,
        other_guard.actor_id: other_guard,
    }
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(
        mover, sentinel, other_guard
    )

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

    assert mover.position == (10.0, 0.0, 0.0)
    assert sentinel.reaction_available is False
    assert other_guard.reaction_available is True


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
