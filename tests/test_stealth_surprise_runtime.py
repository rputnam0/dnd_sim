from __future__ import annotations

from dnd_sim.engine_runtime import (
    _apply_configured_interaction_setup,
    _actor_state_snapshot,
    _build_actor_views,
    _can_act,
    actor_is_incapacitated,
)
from dnd_sim.io_models import ExplorationActionConfig, InteractableConfig, StealthActorConfig
from dnd_sim.models import ActionDefinition, ActorRuntimeState


def _actor(actor_id: str, *, team: str = "party") -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=20,
        hp=20,
        temp_hp=0,
        ac=14,
        initiative_mod=2,
        str_mod=1,
        dex_mod=2,
        con_mod=1,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 1, "dex": 2, "con": 1, "int": 0, "wis": 0, "cha": 0},
        actions=[ActionDefinition(name="basic", action_type="attack", to_hit=5, damage="1d8+3")],
    )


def test_surprised_actor_is_incapacitated_and_cannot_act() -> None:
    actor = _actor("hero")
    actor.surprised = True

    assert actor_is_incapacitated(actor) is True
    assert _can_act(actor) is False


def test_actor_snapshot_and_actor_view_include_visibility_state() -> None:
    actor = _actor("rogue")
    actor.hidden = True
    actor.detected_by = {"guard"}
    actor.surprised = True

    snapshot = _actor_state_snapshot(actor)
    assert snapshot["hidden"] is True
    assert snapshot["detected_by"] == ["guard"]
    assert snapshot["surprised"] is True

    view = _build_actor_views(
        actors={"rogue": actor},
        actor_order=["rogue"],
        round_number=1,
        metadata={},
    )
    assert view.actors["rogue"].hidden is True
    assert view.actors["rogue"].detected_by == {"guard"}
    assert view.actors["rogue"].surprised is True


def test_configured_interaction_setup_updates_actor_and_object_runtime_state() -> None:
    rogue = _actor("rogue")
    guard = _actor("guard", team="enemy")
    actors = {"rogue": rogue, "guard": guard}

    interaction_state = _apply_configured_interaction_setup(
        actors,
        stealth_actors=[
            StealthActorConfig(actor_id="rogue", team="party", hidden=False, detected_by=[]),
            StealthActorConfig(
                actor_id="guard",
                team="enemy",
                hidden=False,
                detected_by=["rogue"],
                passive_perception=10,
            ),
        ],
        interactables=[
            InteractableConfig(
                object_id="chest_a",
                kind="container",
                discovered=True,
                locked=True,
                unlock_dc=14,
                contents=["ruby"],
            )
        ],
        interaction_actions=[
            ExplorationActionConfig(
                action="contested_stealth",
                actor_id="rogue",
                check_total=17,
                target_actor_ids=["guard"],
            ),
            ExplorationActionConfig(
                action="surprise",
                teams={"rogue": "party", "guard": "enemy"},
            ),
            ExplorationActionConfig(
                action="unlock",
                actor_id="rogue",
                object_id="chest_a",
                check_total=18,
            ),
            ExplorationActionConfig(
                action="open",
                actor_id="rogue",
                object_id="chest_a",
            ),
            ExplorationActionConfig(
                action="transfer_loot",
                actor_id="rogue",
                object_id="chest_a",
            ),
        ],
    )

    assert interaction_state.awareness["rogue"].hidden is True
    assert interaction_state.awareness["guard"].surprised is True
    assert interaction_state.interactables["chest_a"].loot_transferred is True
    assert actors["rogue"].hidden is True
    assert actors["rogue"].detected_by == set()
    assert actors["guard"].surprised is True
    assert actor_is_incapacitated(actors["guard"]) is True
