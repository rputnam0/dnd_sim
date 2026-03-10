from __future__ import annotations

from dnd_sim.class_progression import (
    CharacterProgression,
    ClassCatalog,
    ClassRecord,
    FeatureGrant,
    SpellcastingProfile,
    SubclassRecord,
    build_character_progression,
)
from dnd_sim.engine_runtime import _can_act, actor_is_incapacitated
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
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.snapshot_codecs import (
    deserialize_world_exploration_state,
    serialize_world_exploration_state,
)
from dnd_sim.world_exploration_service import create_exploration_state, run_exploration_turn


def _actor(actor_id: str, *, team: str) -> ActorRuntimeState:
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


def test_crpg_core_scenario_stealth_open_combat_sets_surprise_gate() -> None:
    interaction = ExplorationInteractionState()
    interaction = resolve_contested_stealth(
        interaction,
        actor_id="rogue",
        stealth_total=16,
        observer_passive_perception={"guard": 11},
    ).state
    surprise = resolve_encounter_surprise(
        interaction,
        teams={"rogue": "party", "guard": "enemy"},
    )

    rogue = _actor("rogue", team="party")
    guard = _actor("guard", team="enemy")
    guard.surprised = "guard" in surprise.surprised_actor_ids

    assert guard.surprised is True
    assert actor_is_incapacitated(guard) is True
    assert _can_act(guard) is False
    assert _can_act(rogue) is True


def test_crpg_core_scenario_trap_search_disarm_flow_is_persistent_and_replayable() -> None:
    interaction = ExplorationInteractionState(
        interactables={
            "needle_trap": InteractableState(
                object_id="needle_trap",
                kind="trap",
                hidden=True,
                discovered=False,
                discovery_dc=14,
                trap_armed=True,
                disarm_dc=15,
            )
        }
    )
    state = create_exploration_state(
        day=1,
        hour=8,
        minute=0,
        interaction_state=interaction,
    )

    searched = resolve_active_search(
        state.interaction_state,
        seeker_id="rogue",
        search_total=16,
        target_object_ids=("needle_trap",),
    ).state
    disarmed = resolve_trap_disarm(
        searched,
        actor_id="rogue",
        object_id="needle_trap",
        check_total=17,
    ).state
    turned = run_exploration_turn(
        create_exploration_state(
            day=state.clock.day,
            hour=state.clock.hour,
            minute=state.clock.minute,
            turn_index=state.turn_index,
            light_sources=state.light_sources,
            interaction_state=disarmed,
            location_id=state.location_id,
        ),
        activity="search",
        elapsed_minutes=10,
    ).state

    restored = deserialize_world_exploration_state(serialize_world_exploration_state(turned))
    trap = restored.interaction_state.interactables["needle_trap"]
    assert trap.discovered is True
    assert trap.disarmed is True
    assert trap.trap_armed is False


def test_crpg_core_scenario_locked_container_loot_flow_persists_after_turn() -> None:
    interaction = ExplorationInteractionState(
        interactables={
            "chest_a": InteractableState(
                object_id="chest_a",
                kind="container",
                discovered=True,
                locked=True,
                unlock_dc=14,
                contents=("ruby", "potion_healing"),
            )
        }
    )
    unlocked = resolve_unlock(
        interaction,
        actor_id="rogue",
        object_id="chest_a",
        check_total=18,
    ).state
    opened = resolve_open_close(
        unlocked,
        actor_id="rogue",
        object_id="chest_a",
        open=True,
    ).state
    looted = resolve_transfer_loot(
        opened,
        actor_id="rogue",
        object_id="chest_a",
    ).state

    after_turn = run_exploration_turn(
        create_exploration_state(
            day=1,
            hour=9,
            minute=0,
            interaction_state=looted,
        ),
        activity="loot",
        elapsed_minutes=5,
    ).state
    restored = deserialize_world_exploration_state(serialize_world_exploration_state(after_turn))
    chest = restored.interaction_state.interactables["chest_a"]

    assert chest.locked is False
    assert chest.open is True
    assert chest.loot_transferred is True


def test_crpg_core_scenario_progression_driven_encounter_profile_from_class_subclass() -> None:
    catalog = ClassCatalog(
        classes={
            "fighter": ClassRecord(
                content_id="class:fighter|phb",
                class_id="fighter",
                name="Fighter",
                source_book="phb",
                features=(
                    FeatureGrant(name="Fighting Style", level=1),
                    FeatureGrant(name="Action Surge", level=2),
                    FeatureGrant(name="Martial Archetype", level=3, subclass_unlock=True),
                ),
                spellcasting=SpellcastingProfile(progression="none", pact_slots_by_level={}),
            ),
            "wizard": ClassRecord(
                content_id="class:wizard|phb",
                class_id="wizard",
                name="Wizard",
                source_book="phb",
                features=(FeatureGrant(name="Spellcasting", level=1),),
                spellcasting=SpellcastingProfile(progression="full", pact_slots_by_level={}),
            ),
        },
        subclasses={
            ("fighter", "champion"): SubclassRecord(
                content_id="subclass:champion_fighter|phb",
                subclass_id="champion",
                class_id="fighter",
                name="Champion",
                source_book="phb",
                features=(FeatureGrant(name="Improved Critical", level=3),),
            )
        },
    )
    progression: CharacterProgression = build_character_progression(
        class_levels={"fighter": 3, "wizard": 2},
        subclass_choices={"fighter": "champion"},
        catalog=catalog,
    )

    assert progression.total_level == 5
    assert "action surge" in progression.feature_names
    assert "improved critical" in progression.feature_names
    assert progression.subclass_unlock_levels == {"fighter": 3}
    assert progression.spell_slots == {1: 3}
    assert progression.errors == ()
