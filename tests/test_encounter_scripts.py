from __future__ import annotations

import pytest

from dnd_sim.encounter_script import (
    advance_encounter_wave,
    create_encounter_run,
    parse_encounter_script,
    set_encounter_objective,
    trigger_map_hook,
)
from dnd_sim.world_state import QuestState, create_world_state


def _script_payload() -> dict[str, object]:
    return {
        "encounter_id": "blackgate_assault",
        "initial_wave_id": "wave_1",
        "objectives": [
            {
                "objective_id": "seal_gate",
                "description": "Seal the main gate controls.",
                "quest_id": "defend_blackgate",
                "quest_objective_id": "seal_gate_controls",
                "completion_flag": "objective.seal_gate",
            },
            {
                "objective_id": "hold_courtyard",
                "description": "Hold the courtyard through the second wave.",
                "completion_flag": "objective.hold_courtyard",
            },
        ],
        "map_hooks": [
            {
                "hook_id": "open_sluice",
                "trigger": "wave_start",
                "flag_id": "map.sluice_channel",
                "to_status": "active",
            },
            {
                "hook_id": "close_portcullis",
                "trigger": "wave_complete",
                "flag_id": "map.portcullis",
                "to_status": "resolved",
            },
        ],
        "waves": [
            {
                "wave_id": "wave_1",
                "spawn_ids": ["goblin_raider", "hobgoblin_captain"],
                "objective_ids": ["seal_gate"],
                "on_start_hooks": ["open_sluice"],
                "on_complete_hooks": ["close_portcullis"],
                "next_wave_id": "wave_2",
            },
            {
                "wave_id": "wave_2",
                "spawn_ids": ["ogre_brute"],
                "objective_ids": ["hold_courtyard"],
            },
        ],
    }


def test_create_encounter_run_activates_initial_wave_and_start_hook() -> None:
    script = parse_encounter_script(_script_payload())
    state = create_world_state()

    run, next_state = create_encounter_run(script, state)

    assert run.active_wave_id == "wave_1"
    assert run.wave_statuses == {"wave_1": "active", "wave_2": "locked"}
    assert run.status == "active"
    assert next_state.world_flags["encounter.blackgate_assault.status"] == "active"
    assert next_state.world_flags["encounter.blackgate_assault.wave.wave_1"] == "active"
    assert next_state.world_flags["map.sluice_channel"] == "active"


def test_set_encounter_objective_updates_quest_objective_and_completion_flag() -> None:
    script = parse_encounter_script(_script_payload())
    state = create_world_state(
        quests={"defend_blackgate": QuestState(quest_id="defend_blackgate", status="not_started")}
    )
    run, state = create_encounter_run(script, state)

    run, updated = set_encounter_objective(
        script,
        run,
        state,
        objective_id="seal_gate",
        completed=True,
    )

    assert run.objective_statuses["seal_gate"] is True
    assert updated.world_flags["objective.seal_gate"] == "active"
    assert updated.quests["defend_blackgate"].status == "active"
    assert updated.quests["defend_blackgate"].objective_flags["seal_gate_controls"] is True


def test_wave_progression_completes_when_final_wave_objectives_are_done() -> None:
    script = parse_encounter_script(_script_payload())
    run, state = create_encounter_run(script, create_world_state())

    run, state = set_encounter_objective(
        script, run, state, objective_id="seal_gate", completed=True
    )
    run, state = advance_encounter_wave(script, run, state)

    assert run.active_wave_id == "wave_2"
    assert run.wave_statuses["wave_1"] == "completed"
    assert run.wave_statuses["wave_2"] == "active"
    assert state.world_flags["encounter.blackgate_assault.wave.wave_1"] == "resolved"
    assert state.world_flags["encounter.blackgate_assault.wave.wave_2"] == "active"
    assert state.world_flags["map.portcullis"] == "resolved"

    run, state = set_encounter_objective(
        script,
        run,
        state,
        objective_id="hold_courtyard",
        completed=True,
    )
    run, state = advance_encounter_wave(script, run, state)

    assert run.status == "completed"
    assert run.active_wave_id is None
    assert state.world_flags["encounter.blackgate_assault.status"] == "resolved"


def test_advance_encounter_wave_rejects_incomplete_objectives() -> None:
    script = parse_encounter_script(_script_payload())
    run, state = create_encounter_run(script, create_world_state())

    with pytest.raises(ValueError, match="Cannot advance wave with incomplete objectives"):
        advance_encounter_wave(script, run, state)


def test_trigger_map_hook_is_idempotent_after_first_application() -> None:
    script = parse_encounter_script(_script_payload())
    run, state = create_encounter_run(script, create_world_state())

    run_once, state_once = trigger_map_hook(script, run, state, hook_id="close_portcullis")
    run_twice, state_twice = trigger_map_hook(
        script, run_once, state_once, hook_id="close_portcullis"
    )

    assert state_once.world_flags["map.portcullis"] == "resolved"
    assert run_once.triggered_hooks == ("close_portcullis", "open_sluice")
    assert run_twice == run_once
    assert state_twice == state_once


def test_parse_encounter_script_rejects_missing_initial_wave() -> None:
    payload = _script_payload()
    payload["initial_wave_id"] = "wave_99"

    with pytest.raises(ValueError, match="initial_wave_id must reference an existing wave"):
        parse_encounter_script(payload)


def test_parse_encounter_script_rejects_unknown_objective_reference() -> None:
    payload = _script_payload()
    waves = list(payload["waves"])  # type: ignore[arg-type]
    waves[1] = dict(waves[1], objective_ids=["missing_objective"])  # type: ignore[index]
    payload["waves"] = waves

    with pytest.raises(ValueError, match="unknown objective_id"):
        parse_encounter_script(payload)


def test_parse_encounter_script_rejects_unknown_map_hook_reference() -> None:
    payload = _script_payload()
    waves = list(payload["waves"])  # type: ignore[arg-type]
    waves[0] = dict(waves[0], on_start_hooks=["unknown_hook"])  # type: ignore[index]
    payload["waves"] = waves

    with pytest.raises(ValueError, match="unknown map hook"):
        parse_encounter_script(payload)


def test_parse_encounter_script_rejects_invalid_map_hook_status() -> None:
    payload = _script_payload()
    hooks = list(payload["map_hooks"])  # type: ignore[arg-type]
    hooks[0] = dict(hooks[0], to_status="broken")  # type: ignore[index]
    payload["map_hooks"] = hooks

    with pytest.raises(ValueError, match="to_status must be one of"):
        parse_encounter_script(payload)
