from __future__ import annotations

import random

import pytest

from dnd_sim.engine import (
    _apply_declared_movement_or_error,
    _apply_effect,
    _process_hazard_start_turn_triggers,
    _tick_hazards_for_actor_turn,
)
from dnd_sim.models import ActorRuntimeState


def _actor(actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=20,
        hp=20,
        temp_hp=0,
        ac=12,
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


def test_hazard_duration_ticks_on_source_turn_and_expires() -> None:
    rng = random.Random(11)
    caster = _actor("caster", "party")
    target = _actor("target", "enemy")
    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt = {caster.actor_id: 0, target.actor_id: 0}
    damage_taken = {caster.actor_id: 0, target.actor_id: 0}
    threat_scores = {caster.actor_id: 0, target.actor_id: 0}
    resources_spent = {caster.actor_id: {}, target.actor_id: {}}
    active_hazards: list[dict[str, object]] = []

    _apply_effect(
        effect={
            "effect_type": "hazard",
            "hazard_type": "acid_cloud",
            "duration": 2,
            "start_turn_effects": [{"effect_type": "damage", "damage": "1", "damage_type": "acid"}],
        },
        rng=rng,
        actor=caster,
        target=target,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=active_hazards,
    )

    assert len(active_hazards) == 1
    assert active_hazards[0]["duration_remaining"] == 2
    assert active_hazards[0]["trigger_effects"] == {
        "start_turn": [{"effect_type": "damage", "damage": "1", "damage_type": "acid"}]
    }

    _tick_hazards_for_actor_turn(
        active_hazards=active_hazards,
        actor=target,
        actors=actors,
        boundary="turn_start",
    )
    assert active_hazards[0]["duration_remaining"] == 2

    _tick_hazards_for_actor_turn(
        active_hazards=active_hazards,
        actor=caster,
        actors=actors,
        boundary="turn_start",
    )
    assert active_hazards[0]["duration_remaining"] == 1

    _tick_hazards_for_actor_turn(
        active_hazards=active_hazards,
        actor=caster,
        actors=actors,
        boundary="turn_start",
    )
    assert active_hazards == []


def test_hazard_lifecycle_integration_enter_leave_and_start_turn_triggers() -> None:
    rng = random.Random(7)
    caster = _actor("caster", "party")
    mover = _actor("mover", "enemy")
    actors = {caster.actor_id: caster, mover.actor_id: mover}
    damage_dealt = {caster.actor_id: 0, mover.actor_id: 0}
    damage_taken = {caster.actor_id: 0, mover.actor_id: 0}
    threat_scores = {caster.actor_id: 0, mover.actor_id: 0}
    resources_spent = {caster.actor_id: {}, mover.actor_id: {}}
    active_hazards: list[dict[str, object]] = []

    caster.position = (0.0, 0.0, 0.0)
    mover.position = (0.0, 0.0, 0.0)

    _apply_effect(
        effect={
            "effect_type": "hazard",
            "hazard_type": "spike_ring",
            "duration": 3,
            "position": (5.0, 0.0, 0.0),
            "radius": 2,
            "start_turn_effects": [
                {"effect_type": "damage", "damage": "1", "damage_type": "piercing"}
            ],
            "enter_effects": [{"effect_type": "damage", "damage": "1", "damage_type": "piercing"}],
            "leave_effects": [{"effect_type": "damage", "damage": "1", "damage_type": "piercing"}],
        },
        rng=rng,
        actor=caster,
        target=mover,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=active_hazards,
    )

    mover.movement_remaining = 30.0
    _apply_declared_movement_or_error(
        rng=rng,
        actor=mover,
        movement_path=[(0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (10.0, 0.0, 0.0)],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert damage_taken[mover.actor_id] == 2
    assert mover.hp == 18
    assert damage_dealt[caster.actor_id] == 2

    mover.position = (5.0, 0.0, 0.0)
    _process_hazard_start_turn_triggers(
        rng=rng,
        actor=mover,
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=active_hazards,
    )

    assert damage_taken[mover.actor_id] == 3
    assert mover.hp == 17
    assert damage_dealt[caster.actor_id] == 3


@pytest.mark.parametrize("duration", [0, -1, "not_a_number"])
def test_hazard_with_non_positive_duration_is_ignored(duration: object) -> None:
    rng = random.Random(5)
    caster = _actor("caster", "party")
    target = _actor("target", "enemy")
    actors = {caster.actor_id: caster, target.actor_id: target}
    damage_dealt = {caster.actor_id: 0, target.actor_id: 0}
    damage_taken = {caster.actor_id: 0, target.actor_id: 0}
    threat_scores = {caster.actor_id: 0, target.actor_id: 0}
    resources_spent = {caster.actor_id: {}, target.actor_id: {}}
    active_hazards: list[dict[str, object]] = []

    _apply_effect(
        effect={
            "effect_type": "hazard",
            "hazard_type": "void_zone",
            "duration": duration,
            "start_turn_effects": [
                {"effect_type": "damage", "damage": "1", "damage_type": "force"}
            ],
        },
        rng=rng,
        actor=caster,
        target=target,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        actors=actors,
        active_hazards=active_hazards,
    )

    assert active_hazards == []
