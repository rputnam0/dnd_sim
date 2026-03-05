from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import dnd_sim.engine as engine_module
from dnd_sim.engine import TurnDeclarationValidationError, run_simulation
from dnd_sim.io import load_character_db, load_scenario
from dnd_sim.strategy_api import BaseStrategy, DeclaredAction, TargetRef, TurnDeclaration
from dnd_sim.telemetry import TURN_TRACE_EVENT_TYPES
from tests.helpers import build_enemy, write_json

_TRACE_TYPES = set(TURN_TRACE_EVENT_TYPES)


class DeclaredBasicTraceStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()
        target = enemies[0]
        return TurnDeclaration(
            movement_path=[actor.position, target.position],
            action=DeclaredAction(
                action_name="basic",
                targets=[TargetRef(actor_id=target.actor_id)],
            ),
        )


class IllegalActionTraceStrategy(BaseStrategy):
    def declare_turn(self, actor, state):
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()
        target = enemies[0]
        return TurnDeclaration(
            movement_path=[actor.position, target.position],
            action=DeclaredAction(
                action_name="not_a_real_action",
                targets=[TargetRef(actor_id=target.actor_id)],
            ),
        )


def _build_action_surge_character(character_id: str) -> dict[str, Any]:
    return {
        "character_id": character_id,
        "name": "Planner",
        "class_level": "Fighter 8",
        "class_levels": {"fighter": 8},
        "max_hp": 34,
        "ac": 15,
        "speed_ft": 30,
        "ability_scores": {
            "str": 16,
            "dex": 14,
            "con": 14,
            "int": 10,
            "wis": 10,
            "cha": 10,
        },
        "save_mods": {
            "str": 3,
            "dex": 2,
            "con": 2,
            "int": 0,
            "wis": 0,
            "cha": 0,
        },
        "skill_mods": {},
        "attacks": [
            {
                "name": "Longsword",
                "to_hit": 7,
                "damage": "1d8+4",
                "damage_type": "slashing",
            }
        ],
        "resources": {},
        "traits": ["Extra Attack", "Action Surge"],
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }


def _setup_env(tmp_path: Path) -> Path:
    db_dir = tmp_path / "db" / "characters"
    db_dir.mkdir(parents=True, exist_ok=True)

    hero = _build_action_surge_character("hero")
    write_json(
        db_dir / "index.json",
        {
            "characters": [
                {
                    "character_id": "hero",
                    "name": "Planner",
                    "class_level": "Fighter 8",
                    "class_levels": {"fighter": 8},
                    "source_pdf": "fixture.pdf",
                }
            ]
        },
    )
    write_json(db_dir / "hero.json", hero)

    encounter_dir = tmp_path / "encounters" / "fixture"
    enemy_dir = encounter_dir / "enemies"
    scenario_dir = encounter_dir / "scenarios"
    enemy_dir.mkdir(parents=True, exist_ok=True)
    scenario_dir.mkdir(parents=True, exist_ok=True)

    enemy = build_enemy(
        enemy_id="boss",
        name="Boss",
        hp=80,
        ac=13,
        to_hit=5,
        damage="1d8+2",
    )
    write_json(enemy_dir / "boss.json", enemy)

    scenario = {
        "scenario_id": "obs02_fixture",
        "encounter_id": "fixture",
        "ruleset": "5e-2014",
        "character_db_dir": str(db_dir),
        "party": ["hero"],
        "enemies": ["boss"],
        "initiative_mode": "individual",
        "battlefield": {},
        "termination_rules": {
            "party_defeat": "all_unconscious_or_dead",
            "enemy_defeat": "all_dead",
            "max_rounds": 1,
        },
        "strategy_modules": [],
        "resource_policy": {"mode": "combat_and_utility", "burst_round_threshold": 1},
        "assumption_overrides": {
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
    }
    scenario_path = scenario_dir / "scenario.json"
    scenario_path.write_text(json.dumps(scenario, indent=2), encoding="utf-8")
    return scenario_path


def _trace_signature(telemetry: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    signature: list[tuple[Any, ...]] = []
    for event in telemetry:
        telemetry_type = event.get("telemetry_type")
        if telemetry_type not in _TRACE_TYPES:
            continue
        signature.append(
            (
                telemetry_type,
                event.get("actor_id"),
                event.get("round"),
                event.get("turn_token"),
                event.get("action_name"),
                event.get("validation_state"),
                event.get("selection_state"),
                event.get("resolution_state"),
                event.get("outcome_state"),
                tuple(event.get("resolved_targets", [])),
            )
        )
    return signature


def test_turn_traces_include_declaration_selection_resolution_and_outcome(
    tmp_path: Path,
) -> None:
    scenario_path = _setup_env(tmp_path)
    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))

    registry = {
        "party_strategy": DeclaredBasicTraceStrategy(),
        "enemy_strategy": DeclaredBasicTraceStrategy(),
    }
    result = run_simulation(loaded, db, {}, registry, trials=1, seed=31, run_id="obs02_complete")

    trace_events = [
        event
        for event in result.trial_results[0].telemetry
        if event.get("telemetry_type") in _TRACE_TYPES
    ]
    assert trace_events
    observed_types = {event["telemetry_type"] for event in trace_events}
    assert observed_types == _TRACE_TYPES

    selected_turns = {
        (event.get("actor_id"), event.get("round"), event.get("turn_token"))
        for event in trace_events
        if event.get("telemetry_type") == "action_selection"
        and event.get("selection_state") == "selected"
    }
    assert selected_turns
    for actor_id, round_number, turn_token in selected_turns:
        turn_events = [
            event
            for event in trace_events
            if event.get("actor_id") == actor_id
            and event.get("round") == round_number
            and event.get("turn_token") == turn_token
            and event.get("telemetry_type") in _TRACE_TYPES
        ]
        ordered_types = [event["telemetry_type"] for event in turn_events]
        assert ordered_types[:4] == [
            "declaration_validation",
            "action_selection",
            "action_resolution",
            "action_outcome",
        ]


def test_turn_traces_have_deterministic_ordering_with_fixed_seed(tmp_path: Path) -> None:
    scenario_path = _setup_env(tmp_path)
    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))

    registry = {
        "party_strategy": DeclaredBasicTraceStrategy(),
        "enemy_strategy": DeclaredBasicTraceStrategy(),
    }

    run_a = run_simulation(loaded, db, {}, registry, trials=1, seed=77, run_id="obs02_a")
    run_b = run_simulation(loaded, db, {}, registry, trials=1, seed=77, run_id="obs02_b")

    trace_a = _trace_signature(run_a.trial_results[0].telemetry)
    trace_b = _trace_signature(run_b.trial_results[0].telemetry)

    assert trace_a
    assert trace_a == trace_b


def test_illegal_declared_action_emits_illegal_action_selection_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario_path = _setup_env(tmp_path)
    loaded = load_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))

    captured_payloads: list[dict[str, Any]] = []
    original_append = engine_module._append_telemetry_event

    def _capturing_append(
        telemetry: list[dict[str, Any]] | None,
        *,
        event_type: str,
        payload: dict[str, Any],
        source: str = engine_module.__name__,
    ) -> None:
        captured_payloads.append({"telemetry_type": event_type, **payload})
        original_append(telemetry, event_type=event_type, payload=payload, source=source)

    monkeypatch.setattr(engine_module, "_append_telemetry_event", _capturing_append)

    registry = {
        "party_strategy": IllegalActionTraceStrategy(),
        "enemy_strategy": IllegalActionTraceStrategy(),
    }
    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        run_simulation(loaded, db, {}, registry, trials=1, seed=9, run_id="obs02_illegal")

    assert exc_info.value.code == "unknown_action"
    illegal_selection_events = [
        event
        for event in captured_payloads
        if event.get("telemetry_type") == "action_selection"
        and event.get("selection_state") == "illegal"
    ]
    assert illegal_selection_events
    illegal_event = illegal_selection_events[0]
    assert illegal_event.get("error_code") == "unknown_action"
    assert illegal_event.get("field") == "action.action_name"
