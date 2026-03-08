from __future__ import annotations

from dnd_sim.exploration_interaction import (
    ExplorationInteractionState,
    InteractableState,
    resolve_active_search,
    resolve_contested_stealth,
    resolve_encounter_surprise,
    resolve_open_close,
    resolve_transfer_loot,
    resolve_trap_disarm,
    resolve_unlock,
)


def test_resolve_contested_stealth_tracks_detected_and_undetected_observers() -> None:
    state = ExplorationInteractionState()

    result = resolve_contested_stealth(
        state,
        actor_id="rogue",
        stealth_total=16,
        observer_passive_perception={
            "guard": 13,
            "goblin_scout": 16,
        },
    )

    assert result.hidden is True
    assert result.detected_by == ("goblin_scout",)
    assert result.undetected_by == ("guard",)
    assert result.state.awareness["rogue"].hidden is True
    assert result.state.awareness["rogue"].detected_by == ("goblin_scout",)


def test_active_search_reveals_hidden_actor_and_secret_object() -> None:
    state = ExplorationInteractionState(
        awareness={},
        interactables={
            "secret_door": InteractableState(
                object_id="secret_door",
                kind="secret",
                hidden=True,
                discovered=False,
                discovery_dc=15,
            )
        },
    )
    hidden_state = resolve_contested_stealth(
        state,
        actor_id="rogue",
        stealth_total=14,
        observer_passive_perception={"guard": 9},
    ).state

    result = resolve_active_search(
        hidden_state,
        seeker_id="guard",
        search_total=15,
        target_actor_ids=("rogue",),
        target_object_ids=("secret_door",),
    )

    assert result.revealed_actor_ids == ("rogue",)
    assert result.discovered_object_ids == ("secret_door",)
    assert result.state.awareness["rogue"].hidden is False
    assert result.state.interactables["secret_door"].discovered is True
    assert result.state.interactables["secret_door"].hidden is False


def test_surprise_resolution_uses_detection_state() -> None:
    state = ExplorationInteractionState(
        awareness={
            "rogue": resolve_contested_stealth(
                ExplorationInteractionState(),
                actor_id="rogue",
                stealth_total=17,
                observer_passive_perception={"guard": 10},
            ).state.awareness["rogue"],
            "guard": resolve_contested_stealth(
                ExplorationInteractionState(),
                actor_id="guard",
                stealth_total=5,
                observer_passive_perception={"rogue": 14},
            ).state.awareness["guard"],
        }
    )

    result = resolve_encounter_surprise(
        state,
        teams={
            "rogue": "party",
            "guard": "enemy",
        },
    )

    assert result.surprised_actor_ids == ("guard",)
    assert result.state.awareness["guard"].surprised is True
    assert result.state.awareness["rogue"].surprised is False


def test_surprise_resolution_does_not_surprise_visible_ambusher() -> None:
    hidden_rogue = resolve_contested_stealth(
        ExplorationInteractionState(),
        actor_id="rogue",
        stealth_total=17,
        observer_passive_perception={"guard": 10},
    ).state.awareness["rogue"]
    state = ExplorationInteractionState(awareness={"rogue": hidden_rogue})

    result = resolve_encounter_surprise(
        state,
        teams={
            "rogue": "party",
            "guard": "enemy",
        },
    )

    assert result.surprised_actor_ids == ("guard",)
    assert result.state.awareness["rogue"].surprised is False


def test_interactable_lock_trap_and_container_loop_is_persistent() -> None:
    state = ExplorationInteractionState(
        interactables={
            "needle_trap": InteractableState(
                object_id="needle_trap",
                kind="trap",
                hidden=False,
                discovered=True,
                trap_armed=True,
                disarmed=False,
                disarm_dc=15,
                trigger_on_fail=True,
            ),
            "chest_a": InteractableState(
                object_id="chest_a",
                kind="container",
                hidden=False,
                discovered=True,
                open=False,
                locked=True,
                unlock_dc=14,
                contents=("ruby", "potion_healing"),
            ),
        }
    )

    disarm_fail = resolve_trap_disarm(
        state,
        actor_id="rogue",
        object_id="needle_trap",
        check_total=9,
    )
    assert disarm_fail.success is False
    assert disarm_fail.trap_triggered is True
    assert disarm_fail.state.interactables["needle_trap"].triggered is True

    unlock = resolve_unlock(
        disarm_fail.state,
        actor_id="rogue",
        object_id="chest_a",
        check_total=18,
    )
    assert unlock.success is True
    assert unlock.state.interactables["chest_a"].locked is False

    open = resolve_open_close(
        unlock.state,
        actor_id="rogue",
        object_id="chest_a",
        open=True,
    )
    assert open.success is True
    assert open.state.interactables["chest_a"].open is True

    loot = resolve_transfer_loot(
        open.state,
        actor_id="rogue",
        object_id="chest_a",
    )
    assert loot.success is True
    assert loot.loot_item_ids == ("potion_healing", "ruby")
    assert loot.state.interactables["chest_a"].loot_transferred is True
