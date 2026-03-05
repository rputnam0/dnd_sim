from __future__ import annotations

from typing import Any

from dnd_sim.strategies.defaults import OptimalExpectedDamageStrategy
from dnd_sim.strategy_api import ActorView, BattleStateView
from dnd_sim.telemetry import AI_TRACE_EVENT_TYPES, TELEMETRY_SCHEMA_VERSION, serialize_event


def _actor(
    *,
    actor_id: str,
    team: str,
    hp: int = 24,
    max_hp: int = 24,
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    resources: dict[str, int] | None = None,
) -> ActorView:
    return ActorView(
        actor_id=actor_id,
        team=team,
        hp=hp,
        max_hp=max_hp,
        ac=14,
        save_mods={"dex": 2, "wis": 1},
        resources=dict(resources or {}),
        conditions=set(),
        position=position,
        speed_ft=30,
        movement_remaining=30.0,
        traits={},
        concentrating=False,
    )


def _state_for_scoring_traces() -> tuple[ActorView, BattleStateView]:
    actor = _actor(actor_id="hero", team="party", resources={"spell_slot_1": 1})
    enemy = _actor(
        actor_id="enemy",
        team="enemy",
        hp=30,
        max_hp=30,
        position=(5.0, 0.0, 0.0),
    )
    state = BattleStateView(
        round_number=2,
        actors={
            actor.actor_id: actor,
            enemy.actor_id: enemy,
        },
        actor_order=[actor.actor_id, enemy.actor_id],
        metadata={
            "available_actions": {
                actor.actor_id: ["basic", "commanding_shout", "expensive_nova"],
            },
            "action_catalog": {
                actor.actor_id: [
                    {
                        "name": "basic",
                        "action_type": "attack",
                        "target_mode": "single_enemy",
                        "range_ft": 5,
                        "to_hit": 6,
                        "damage": "1d8+3",
                        "action_cost": "action",
                    },
                    {
                        "name": "commanding_shout",
                        "action_type": "utility",
                        "target_mode": "single_enemy",
                        "range_ft": 30,
                        "action_cost": "action",
                        "effects": [
                            {
                                "effect_type": "apply_condition",
                                "condition": "frightened",
                            }
                        ],
                    },
                    {
                        "name": "expensive_nova",
                        "action_type": "save",
                        "target_mode": "single_enemy",
                        "range_ft": 60,
                        "save_ability": "dex",
                        "save_dc": 15,
                        "damage": "4d10",
                        "action_cost": "action",
                        "resource_cost": {"spell_slot_9": 1},
                    },
                ]
            },
        },
    )
    return actor, state


def _trace_event(declaration, event_type: str) -> dict[str, Any]:
    action_selection = declaration.rationale.get("action_selection", {})
    trace_events = action_selection.get("trace_events", [])
    for event in trace_events:
        if event.get("event_type") == event_type:
            return event
    raise AssertionError(f"trace event '{event_type}' was not emitted")


def test_candidate_trace_covers_all_catalog_actions_and_exclusions() -> None:
    actor, state = _state_for_scoring_traces()

    declaration = OptimalExpectedDamageStrategy().declare_turn(actor, state)
    candidate_trace = _trace_event(declaration, "ai_candidate_scoring")
    rows = candidate_trace["payload"]["candidate_rows"]

    assert {row["action_name"] for row in rows} == {
        "basic",
        "commanding_shout",
        "expensive_nova",
    }
    expensive = next(row for row in rows if row["action_name"] == "expensive_nova")
    assert expensive["candidate_state"] == "excluded"
    assert expensive["rejection_reason"] == "insufficient_resources"


def test_candidate_trace_includes_score_components_and_selection_states() -> None:
    actor, state = _state_for_scoring_traces()

    declaration = OptimalExpectedDamageStrategy().declare_turn(actor, state)
    candidate_trace = _trace_event(declaration, "ai_candidate_scoring")
    rows = candidate_trace["payload"]["candidate_rows"]

    selected_rows = [row for row in rows if row["candidate_state"] == "selected"]
    assert len(selected_rows) == 1
    selected = selected_rows[0]
    assert {
        "base_score",
        "objective_bonus",
        "lookahead_bonus",
        "total_score",
    } <= set(selected["score_components"])

    rejected_rows = [row for row in rows if row["candidate_state"] == "rejected"]
    assert rejected_rows
    assert all(row["rejection_reason"] == "not_selected" for row in rejected_rows)


def test_ai_rationale_trace_uses_structured_telemetry_schema() -> None:
    actor, state = _state_for_scoring_traces()

    declaration = OptimalExpectedDamageStrategy().declare_turn(actor, state)
    action_selection = declaration.rationale.get("action_selection", {})
    trace_events = action_selection.get("trace_events", [])

    assert {event["event_type"] for event in trace_events} == set(AI_TRACE_EVENT_TYPES)
    for event in trace_events:
        assert event["schema_version"] == TELEMETRY_SCHEMA_VERSION
        assert event["telemetry_type"] == event["event_type"]
        serialize_event(event)

    rationale_trace = _trace_event(declaration, "ai_action_rationale")
    payload = rationale_trace["payload"]
    assert payload["selected_action"] == declaration.action.action_name
    assert payload["strategy"] == "OptimalExpectedDamageStrategy"
