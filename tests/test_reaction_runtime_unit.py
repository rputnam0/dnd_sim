from __future__ import annotations

import random

from dnd_sim import reaction_runtime
from dnd_sim.models import ActionDefinition, ActorRuntimeState


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


def test_readied_trigger_matches_supports_reach_aliases() -> None:
    assert reaction_runtime.readied_trigger_matches(
        "enemy_enters_reach",
        trigger_event="enemy_enters_reach",
    )
    assert reaction_runtime.readied_trigger_matches(
        "on_enemy_enters_reach",
        trigger_event="enemy_enters_reach",
    )
    assert reaction_runtime.readied_trigger_matches(
        "enters_reach",
        trigger_event="enemy_enters_reach",
    )
    assert reaction_runtime.readied_trigger_matches(
        "on_enters_reach",
        trigger_event="enemy_enters_reach",
    )


def test_can_take_reaction_rejects_no_reaction_condition() -> None:
    actor = _base_actor(actor_id="reactor", team="party")
    actor.conditions.add("open_hand_no_reactions")

    assert reaction_runtime.can_take_reaction(actor) is False


def test_run_opportunity_attacks_prioritizes_readied_interrupt_before_opportunity() -> None:
    rng = random.Random(7)
    mover = _base_actor(actor_id="mover", team="party")
    reactor = _base_actor(actor_id="reactor", team="enemy")
    mover.position = (20.0, 0.0, 0.0)
    reactor.position = (0.0, 0.0, 0.0)

    basic = ActionDefinition(
        name="basic",
        action_type="attack",
        action_cost="action",
        to_hit=20,
        damage="1",
        damage_type="slashing",
        range_ft=5,
    )
    reactor.actions = [basic]
    reactor.conditions.add("readying")
    reactor.readied_reaction_reserved = True
    reactor.readied_action_name = "basic"
    reactor.readied_trigger = "enemy_enters_reach"

    actors = {mover.actor_id: mover, reactor.actor_id: reactor}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(mover, reactor)

    reaction_runtime.run_opportunity_attacks_for_movement(
        rng=rng,
        mover=mover,
        start_pos=(20.0, 0.0, 0.0),
        end_pos=(30.0, 0.0, 0.0),
        movement_path=[(20.0, 0.0, 0.0), (0.0, 0.0, 0.0), (30.0, 0.0, 0.0)],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    # Readied response consumed the reactor reaction, so no additional exit-reach OA occurs.
    assert mover.hp == mover.max_hp - 1
    assert reactor.reaction_available is False
