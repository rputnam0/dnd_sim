from __future__ import annotations

import pytest

from dnd_sim.persistence import deserialize_world_state, serialize_world_state
from dnd_sim.world_state import (
    FactionState,
    QuestState,
    apply_faction_reputation_delta,
    create_world_state,
    transition_quest_state,
    transition_world_flag,
)


def test_world_flag_lifecycle_transitions_and_turn_advancement() -> None:
    state = create_world_state()

    activated = transition_world_flag(
        state,
        flag_id="bridge_repaired",
        to_status="active",
    )
    resolved = transition_world_flag(
        activated,
        flag_id="bridge_repaired",
        to_status="resolved",
    )
    archived = transition_world_flag(
        resolved,
        flag_id="bridge_repaired",
        to_status="archived",
    )

    assert activated.turn_index == 1
    assert resolved.turn_index == 2
    assert archived.turn_index == 3
    assert archived.world_flags["bridge_repaired"] == "archived"


def test_world_flag_rejects_illegal_transition() -> None:
    state = create_world_state(world_flags={"bridge_repaired": "inactive"})

    with pytest.raises(ValueError, match="Illegal flag transition"):
        transition_world_flag(
            state,
            flag_id="bridge_repaired",
            to_status="resolved",
        )


def test_quest_lifecycle_stage_and_objective_updates() -> None:
    state = create_world_state(
        quests={
            "guild_charter": QuestState(
                quest_id="guild_charter",
                status="not_started",
                stage_id="briefing",
            )
        }
    )

    active = transition_quest_state(
        state,
        quest_id="guild_charter",
        to_status="active",
        objective_updates={"deliver_writ": False, "speak_to_steward": True},
    )
    completed = transition_quest_state(
        active,
        quest_id="guild_charter",
        to_status="completed",
        objective_updates={"deliver_writ": True},
    )

    quest = completed.quests["guild_charter"]
    assert completed.turn_index == 2
    assert quest.status == "completed"
    assert quest.stage_id == "briefing"
    assert quest.objective_flags == {
        "deliver_writ": True,
        "speak_to_steward": True,
    }


def test_quest_rejects_illegal_transition() -> None:
    state = create_world_state(
        quests={"guild_charter": QuestState(quest_id="guild_charter", status="not_started")}
    )

    with pytest.raises(ValueError, match="Illegal quest transition"):
        transition_quest_state(
            state,
            quest_id="guild_charter",
            to_status="completed",
        )


def test_faction_reputation_clamps_and_updates_standing() -> None:
    state = create_world_state(
        factions={"river_guild": FactionState(faction_id="river_guild", reputation=70)}
    )

    allied = apply_faction_reputation_delta(
        state,
        faction_id="river_guild",
        delta=40,
    )
    hostile = apply_faction_reputation_delta(
        allied,
        faction_id="river_guild",
        delta=-220,
    )

    assert allied.factions["river_guild"].reputation == 100
    assert allied.factions["river_guild"].standing == "allied"
    assert hostile.factions["river_guild"].reputation == -100
    assert hostile.factions["river_guild"].standing == "hostile"


def test_world_state_round_trip_serialization_preserves_lifecycle_data() -> None:
    state = create_world_state(
        turn_index=6,
        world_flags={"gate_alarm": "resolved"},
        quests={
            "guild_charter": QuestState(
                quest_id="guild_charter",
                status="active",
                stage_id="council_hall",
                objective_flags={"deliver_writ": False},
            )
        },
        factions={"river_guild": FactionState(faction_id="river_guild", reputation=28)},
    )

    payload = serialize_world_state(state)
    restored = deserialize_world_state(payload)

    assert restored == state


def test_deserialize_world_state_rejects_missing_quest_identifier() -> None:
    with pytest.raises(ValueError, match="quest_id must be a string"):
        deserialize_world_state(
            {
                "turn_index": 0,
                "world_flags": {},
                "quests": [{"status": "active"}],
                "factions": [],
            }
        )


def test_deserialize_world_state_rejects_non_integer_reputation() -> None:
    with pytest.raises(ValueError, match="reputation must be an integer"):
        deserialize_world_state(
            {
                "turn_index": 0,
                "world_flags": {},
                "quests": [],
                "factions": [{"faction_id": "river_guild", "reputation": "high"}],
            }
        )
