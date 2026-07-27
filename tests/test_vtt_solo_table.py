from __future__ import annotations

import json

from dnd_sim.interactive import EngineSession, SessionCommand
from dnd_sim.interactive.dnd_contracts import (
    DECLARATION_COMMAND_KIND,
    TurnDeclarationPayload,
)
from dnd_sim.interactive.dnd_encounter_driver import (
    DND_ENCOUNTER_STATE_SCHEMA_VERSION,
    START_ENCOUNTER_COMMAND_KIND,
    DndCombatEncounterDriver,
)
from dnd_sim.strategy_api import DeclaredAction, TargetRef, TurnDeclaration
from dnd_sim.vtt.scene import FeetPosition, project_scene
from dnd_sim.vtt.solo_table import (
    SOLO_TABLE_CONTENT_VERSION,
    SOLO_TABLE_ENGINE_VERSION,
    SOLO_TABLE_RULES_VERSION,
    SOLO_TABLE_SEED,
    SoloTableFixture,
    build_solo_table_fixture,
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def test_solo_table_fixture_has_stable_original_grid_aligned_content() -> None:
    fixture = build_solo_table_fixture()
    context = fixture.encounter_state.turn.context

    assert isinstance(fixture, SoloTableFixture)
    assert fixture.seed == SOLO_TABLE_SEED == 24_681_357
    assert fixture.version_pins.model_dump(mode="json") == {
        "engine_version": SOLO_TABLE_ENGINE_VERSION,
        "rules_version": SOLO_TABLE_RULES_VERSION,
        "content_version": SOLO_TABLE_CONTENT_VERSION,
    }
    assert fixture.version_pins.model_dump(mode="json") == {
        "engine_version": "dnd-sim@0.1.0",
        "rules_version": "5e_2014_combat_foundation@1.0.0",
        "content_version": "solo-table.echo-vault@1.0.0",
    }
    assert fixture.scene.scene_id == "echo-vault"
    assert fixture.scene.name == "Echo Vault"
    assert context.initiative_order == ["vela_quill", "hushglass_sentry"]
    assert set(context.actors) == set(context.initiative_order)

    for actor in context.actors.values():
        assert actor.actions
        assert all(action.action_cost == "action" for action in actor.actions)
        assert all(action.action_cost != "lair" for action in actor.actions)
        position = FeetPosition(
            x_ft=actor.position[0],
            y_ft=actor.position[1],
            z_ft=actor.position[2],
        )
        cell = fixture.scene.feet_to_grid_cell(position)
        assert fixture.scene.grid_cell_to_feet(cell) == position


def test_solo_table_scene_projection_and_state_encoding_are_canonical() -> None:
    first = build_solo_table_fixture()
    second = build_solo_table_fixture()

    first_projection = project_scene(
        first.scene,
        first.encounter_state.turn.context.actors,
    ).model_dump(mode="json")
    second_projection = project_scene(
        second.scene,
        second.encounter_state.turn.context.actors,
    ).model_dump(mode="json")

    assert first_projection == second_projection
    assert [token["actor_id"] for token in first_projection["tokens"]] == [
        "hushglass_sentry",
        "vela_quill",
    ]
    assert _canonical_json(first_projection) == _canonical_json(second_projection)

    first_driver = DndCombatEncounterDriver(version_pins=first.version_pins)
    second_driver = DndCombatEncounterDriver(version_pins=second.version_pins)
    first_state = first_driver.encode_state(first.encounter_state)
    second_state = second_driver.encode_state(second.encounter_state)

    assert first_state["schema_version"] == DND_ENCOUNTER_STATE_SCHEMA_VERSION
    assert _canonical_json(first_state) == _canonical_json(second_state)
    assert first_driver.encode_state(first_driver.decode_state(first_state)) == first_state


def test_solo_table_builder_returns_a_fresh_independent_object_graph() -> None:
    first = build_solo_table_fixture()
    second = build_solo_table_fixture()
    first_context = first.encounter_state.turn.context
    second_context = second.encounter_state.turn.context

    assert first is not second
    assert first.scene is not second.scene
    assert first.version_pins is not second.version_pins
    assert first.encounter_state is not second.encounter_state
    assert first_context is not second_context
    assert first_context.actors["vela_quill"] is not second_context.actors["vela_quill"]
    assert (
        first_context.actors["vela_quill"].actions
        is not second_context.actors["vela_quill"].actions
    )
    assert first_context.timing_engine is not second_context.timing_engine

    first_context.actors["vela_quill"].hp = 1
    first_context.actors["vela_quill"].conditions.add("frightened")
    first_context.damage_dealt["vela_quill"] = 99
    first_context.initiative_order.reverse()

    assert second_context.actors["vela_quill"].hp == 24
    assert second_context.actors["vela_quill"].conditions == set()
    assert second_context.damage_dealt["vela_quill"] == 0
    assert second_context.initiative_order == ["vela_quill", "hushglass_sentry"]


def test_solo_table_reaches_terminal_outcome_through_real_encounter_driver() -> None:
    fixture = build_solo_table_fixture()
    driver = DndCombatEncounterDriver(version_pins=fixture.version_pins)
    session = EngineSession(
        "echo-vault-session",
        fixture.encounter_state,
        driver,
        seed=fixture.seed,
    )

    started = session.execute(
        SessionCommand(
            command_id="start-echo-vault",
            session_id="echo-vault-session",
            actor_id=None,
            expected_revision=0,
            mode="admin",
            kind=START_ENCOUNTER_COMMAND_KIND,
            version_pins=fixture.version_pins,
            payload={},
        )
    )

    assert started.events[-1].kind == "dnd.turn.prepared"
    assert session.state["turn"]["actor_id"] == "vela_quill"

    declaration = TurnDeclaration(
        action=DeclaredAction(
            action_name="Lattice Lance",
            targets=[TargetRef(actor_id="hushglass_sentry")],
        )
    )
    completed = session.execute(
        SessionCommand(
            command_id="vela-turn-1",
            session_id="echo-vault-session",
            actor_id="vela_quill",
            expected_revision=1,
            mode="commit",
            kind=DECLARATION_COMMAND_KIND,
            version_pins=fixture.version_pins,
            payload=TurnDeclarationPayload.from_domain(declaration).model_dump(mode="json"),
        )
    )

    assert completed.events[-1].kind == "dnd.encounter.completed"
    assert completed.events[-1].payload["outcome"] == "party_victory"
    assert session.state["outcome"] == "party_victory"
    assert session.state["turn"]["phase"] == "complete"
