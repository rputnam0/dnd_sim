from __future__ import annotations

import pytest

from dnd_sim.campaign_runtime import (
    AdventuringActorState,
    apply_long_rest_to_party,
    apply_short_rest_to_party,
    create_adventuring_day_state,
    current_encounter_id,
    advance_adventuring_day,
)
from dnd_sim.snapshot_codecs import (
    deserialize_adventuring_day_state,
    serialize_adventuring_day_state,
)
from dnd_sim.world_exploration_service import create_exploration_state


def _party() -> dict[str, AdventuringActorState]:
    return {
        "monk": AdventuringActorState(
            actor_id="monk",
            hit_points=18,
            max_hit_points=18,
            resources={"ki": 3},
            max_resources={"ki": 3},
            short_rest_recovery=("ki",),
            conditions=(),
        ),
        "fighter": AdventuringActorState(
            actor_id="fighter",
            hit_points=25,
            max_hit_points=30,
            resources={"action_surge": 1, "second_wind": 1},
            max_resources={"action_surge": 1, "second_wind": 1},
            short_rest_recovery=("action_surge", "second_wind"),
            conditions=("poisoned",),
        ),
    }


def test_multi_encounter_state_round_trip_persists_flow_and_world_time() -> None:
    state = create_adventuring_day_state(
        campaign_id="campaign_alpha",
        day_number=3,
        encounter_order=("encounter_gate", "encounter_bridge"),
        party=_party(),
        world_state=create_exploration_state(day=3, hour=9, minute=0, light_sources={"torch": 60}),
    )

    assert current_encounter_id(state) == "encounter_gate"

    after_first = advance_adventuring_day(
        state,
        encounter_id="encounter_gate",
        outcome="party_victory",
        party_after_encounter={
            "monk": AdventuringActorState(
                actor_id="monk",
                hit_points=12,
                max_hit_points=18,
                resources={"ki": 1},
                max_resources={"ki": 3},
                short_rest_recovery=("ki",),
                conditions=(),
            ),
            "fighter": AdventuringActorState(
                actor_id="fighter",
                hit_points=18,
                max_hit_points=30,
                resources={"action_surge": 0, "second_wind": 0},
                max_resources={"action_surge": 1, "second_wind": 1},
                short_rest_recovery=("action_surge", "second_wind"),
                conditions=("poisoned",),
            ),
        },
        rest="short",
        short_rest_healing=4,
        exploration_activity="travel",
        exploration_minutes=15,
    )

    assert after_first.current_encounter_index == 1
    assert current_encounter_id(after_first) == "encounter_bridge"
    assert after_first.party["monk"].resources["ki"] == 3
    assert after_first.party["fighter"].resources["action_surge"] == 1
    assert after_first.world_state.clock.minute_of_day == (9 * 60) + 15
    assert len(after_first.encounter_history) == 1

    payload = serialize_adventuring_day_state(after_first)
    restored = deserialize_adventuring_day_state(payload)

    assert restored == after_first


def test_short_and_long_rest_recovery_rules_are_deterministic() -> None:
    party = {
        "fighter": AdventuringActorState(
            actor_id="fighter",
            hit_points=10,
            max_hit_points=30,
            resources={"action_surge": 0, "second_wind": 0, "spell_slot_1": 1},
            max_resources={"action_surge": 1, "second_wind": 1, "spell_slot_1": 4},
            short_rest_recovery=("action_surge", "second_wind"),
            conditions=("poisoned", "frightened"),
        )
    }

    rested_short = apply_short_rest_to_party(party, healing=5)
    assert rested_short["fighter"].hit_points == 15
    assert rested_short["fighter"].resources["action_surge"] == 1
    assert rested_short["fighter"].resources["second_wind"] == 1
    assert rested_short["fighter"].resources["spell_slot_1"] == 1
    assert rested_short["fighter"].conditions == ("frightened", "poisoned")

    rested_long = apply_long_rest_to_party(rested_short)
    assert rested_long["fighter"].hit_points == 30
    assert rested_long["fighter"].resources["action_surge"] == 1
    assert rested_long["fighter"].resources["second_wind"] == 1
    assert rested_long["fighter"].resources["spell_slot_1"] == 4
    assert rested_long["fighter"].conditions == ()


def test_resource_carryover_persists_when_no_rest_is_applied() -> None:
    state = create_adventuring_day_state(
        campaign_id="campaign_beta",
        day_number=2,
        encounter_order=("enc_a", "enc_b", "enc_c"),
        party=_party(),
        world_state=create_exploration_state(day=2, hour=10, minute=0),
    )

    after_first = advance_adventuring_day(
        state,
        encounter_id="enc_a",
        outcome="party_victory",
        party_after_encounter={
            "monk": AdventuringActorState(
                actor_id="monk",
                hit_points=14,
                max_hit_points=18,
                resources={"ki": 0},
                max_resources={"ki": 3},
                short_rest_recovery=("ki",),
                conditions=(),
            ),
            "fighter": AdventuringActorState(
                actor_id="fighter",
                hit_points=20,
                max_hit_points=30,
                resources={"action_surge": 0, "second_wind": 1},
                max_resources={"action_surge": 1, "second_wind": 1},
                short_rest_recovery=("action_surge", "second_wind"),
                conditions=("poisoned",),
            ),
        },
        rest="none",
    )

    assert after_first.party["monk"].resources["ki"] == 0
    assert after_first.party["fighter"].resources["action_surge"] == 0
    assert current_encounter_id(after_first) == "enc_b"


def test_advance_adventuring_day_rejects_encounter_mismatch() -> None:
    state = create_adventuring_day_state(
        campaign_id="campaign_gamma",
        day_number=1,
        encounter_order=("encounter_1",),
        party=_party(),
        world_state=create_exploration_state(day=1, hour=8, minute=0),
    )

    with pytest.raises(ValueError, match="encounter_id does not match expected encounter"):
        advance_adventuring_day(
            state,
            encounter_id="encounter_2",
            outcome="party_victory",
            party_after_encounter=_party(),
            rest="none",
        )


def test_deserialize_adventuring_day_state_rejects_non_string_campaign_id() -> None:
    with pytest.raises(ValueError, match="campaign_id must be a string"):
        deserialize_adventuring_day_state(
            {
                "campaign_id": 7,
                "day_number": 1,
                "encounter_order": ["encounter_1"],
                "current_encounter_index": 0,
                "completed": False,
                "party": [],
                "encounter_history": [],
                "world_state": {
                    "turn_index": 0,
                    "clock": {"day": 1, "minute_of_day": 0},
                    "light_sources": [],
                },
            }
        )
