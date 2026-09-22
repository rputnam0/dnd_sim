from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dnd_sim.interactive import DndCombatEncounterDriver
from dnd_sim.interactive.dnd_encounter_driver import START_ENCOUNTER_COMMAND_KIND
from dnd_sim.vtt.access import TableAccessPolicy
from dnd_sim.vtt.board_calibration import AxialHexCell, BoardCalibration
from dnd_sim.vtt.event_store import SQLiteSessionEventStore
from dnd_sim.vtt.http_api import create_vtt_app
from dnd_sim.vtt.participants import (
    PARTICIPANT_SCHEMA_VERSION,
    ROSTER_SCHEMA_VERSION,
    TableParticipant,
    TableRoster,
)
from dnd_sim.vtt.scene import FeetPosition
from dnd_sim.vtt.scene_library_contracts import SceneCreateCommand, SceneMapMetadata, SceneRecord
from dnd_sim.vtt.scene_library_store import SQLiteSceneLibrary
from dnd_sim.vtt.session_service import VTTSessionService
from dnd_sim.vtt.solo_table import build_solo_table_fixture


def _declaration(
    *,
    command_id: str,
    mode: str,
    path: list[list[float]],
) -> dict[str, object]:
    return {
        "schema_version": "vtt.command.v1",
        "command_id": command_id,
        "session_id": "hex-session",
        "actor_id": "vela_quill",
        "expected_revision": 1,
        "mode": mode,
        "kind": "dnd.declare_turn.v1",
        "payload": {
            "movement_path": path,
            "action": None,
            "bonus_action": None,
            "reaction_policy": {"mode": "auto", "rationale": {}},
            "ready": None,
            "rationale": {},
        },
        "intent_metadata": {},
    }


@pytest.mark.parametrize(
    ("topology", "neighbor", "distant"),
    (
        ("hex_pointy", AxialHexCell(q=0, r=1), AxialHexCell(q=0, r=7)),
        ("hex_flat", AxialHexCell(q=1, r=0), AxialHexCell(q=7, r=0)),
    ),
)
def test_real_driver_uses_active_hex_cube_cost_for_preview_and_commit(
    tmp_path: Path,
    topology: str,
    neighbor: AxialHexCell,
    distant: AxialHexCell,
) -> None:
    fixture = build_solo_table_fixture()
    actor = fixture.encounter_state.turn.context.actors["vela_quill"]
    actor.speed_ft = 31
    actor.movement_remaining = 31.0
    fixture.encounter_state.turn.context.actors["hushglass_sentry"].position = (
        17.5,
        12.5,
        0.0,
    )
    database = tmp_path / f"{topology}.sqlite3"
    session_connection = sqlite3.connect(database, check_same_thread=False)
    scene_connection = sqlite3.connect(database, check_same_thread=False)
    calibration = BoardCalibration(
        topology=topology,
        origin_x_px=100.0,
        origin_y_px=100.0,
        cell_extent_px=100.0,
        distance_ft=5.0,
    )
    scene_origin = FeetPosition(x_ft=10.0, y_ft=10.0, z_ft=0.0)
    board_origin = FeetPosition(x_ft=12.5, y_ft=12.5, z_ft=0.0)
    start = calibration.cell_to_feet(AxialHexCell(q=0, r=0), origin_ft=board_origin)
    end = calibration.cell_to_feet(neighbor, origin_ft=board_origin)
    over_budget_end = calibration.cell_to_feet(distant, origin_ft=board_origin)
    service = VTTSessionService.open(
        session_id="hex-session",
        initial_state=fixture.encounter_state,
        driver=DndCombatEncounterDriver(version_pins=fixture.version_pins),
        seed=fixture.seed,
        event_store=SQLiteSessionEventStore(session_connection),
    )
    scenes = SQLiteSceneLibrary(scene_connection)
    scenes.execute(
        SceneCreateCommand(
            table_id="hex-table",
            command_id="create-active-hex",
            expected_revision=0,
            scene=SceneRecord(
                scene_id="hex-board",
                map_metadata=SceneMapMetadata(
                    name="Hex Board",
                    width_px=1_200,
                    height_px=1_200,
                    grid_size_px=100.0,
                    gridless=False,
                    calibration=calibration,
                ),
            ),
        )
    )
    policy = TableAccessPolicy(
        roster=TableRoster(
            schema_version=ROSTER_SCHEMA_VERSION,
            table_id="hex-table",
            participants=(
                TableParticipant(
                    schema_version=PARTICIPANT_SCHEMA_VERSION,
                    participant_id="gm",
                    display_name="GM",
                    role="gm",
                    owned_actor_ids=(),
                ),
                TableParticipant(
                    schema_version=PARTICIPANT_SCHEMA_VERSION,
                    participant_id="owner",
                    display_name="Owner",
                    role="player",
                    owned_actor_ids=("vela_quill",),
                ),
            ),
        ),
        bearer_tokens={"gm": "gm-hex-token-1234", "owner": "owner-hex-token-1234"},
    )
    configured_scene = fixture.scene.model_copy(update={"origin_ft": scene_origin})
    app = create_vtt_app(
        service,
        scene=configured_scene,
        access_policy=policy,
        scene_library=scenes,
    )
    auth = {"authorization": "Bearer owner-hex-token-1234"}

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            started = client.post(
                "/api/v1/commands",
                headers={"authorization": "Bearer gm-hex-token-1234"},
                json={
                    "schema_version": "vtt.command.v1",
                    "command_id": "start-hex",
                    "session_id": "hex-session",
                    "actor_id": None,
                    "expected_revision": 0,
                    "mode": "admin",
                    "kind": START_ENCOUNTER_COMMAND_KIND,
                    "payload": {},
                    "intent_metadata": {},
                },
            )
            assert started.status_code == 200
            declaration_payload = _declaration(
                command_id="roll-card-preview",
                mode="preview",
                path=[[start.x_ft, start.y_ft, start.z_ft]],
            )
            declaration_payload["payload"]["action"] = {
                "action_name": "Lattice Lance",
                "targets": [{"actor_id": "hushglass_sentry"}],
                "resource_spend": {"amounts": {}},
                "spell_slot_level": None,
                "rationale": {},
            }
            preview_with_cards = client.post(
                "/api/v1/commands",
                headers=auth,
                json=declaration_payload,
            )
            assert preview_with_cards.status_code == 200, preview_with_cards.text
            roll_events = [
                event
                for event in preview_with_cards.json()["events"]
                if event["kind"] == "vtt.roll.card.v1"
            ]
            assert roll_events
            assert all(event["audience"] == ["all"] for event in roll_events)
            assert all(set(event["payload"]) == {"card"} for event in roll_events)
            assert "engine.roll_record" not in preview_with_cards.text
            assert "roll_projection_required" not in preview_with_cards.text
            assert "audience" not in str(roll_events[0]["payload"]["card"])
            assert (
                client.get("/api/v1/session", headers=auth).json()["scene"]["scene_id"]
                == "hex-board"
            )

            before = service.read_view()
            elevated_paths = (
                [
                    [start.x_ft, start.y_ft, start.z_ft],
                    [start.x_ft, start.y_ft, start.z_ft + 100.0],
                ],
                [
                    [start.x_ft, start.y_ft, start.z_ft],
                    [end.x_ft, end.y_ft, end.z_ft + 100.0],
                ],
            )
            for path_index, elevated_path in enumerate(elevated_paths):
                for mode in ("preview", "commit"):
                    rejected = client.post(
                        "/api/v1/commands",
                        headers=auth,
                        json=_declaration(
                            command_id=(f"elevated-{topology}-{path_index}-{mode}"),
                            mode=mode,
                            path=elevated_path,
                        ),
                    )
                    assert rejected.status_code == 409
                    assert rejected.json() == {
                        "schema_version": "vtt.error.v1",
                        "code": "board_movement_elevation_changed",
                        "message": ("Calibrated hex movement must stay on one elevation."),
                        "details": {},
                    }
                    assert service.read_view() == before

            crafted_path = [
                [start.x_ft, start.y_ft, start.z_ft],
                [over_budget_end.x_ft, over_budget_end.y_ft, over_budget_end.z_ft],
            ]
            for mode in ("preview", "commit"):
                rejected = client.post(
                    "/api/v1/commands",
                    headers=auth,
                    json=_declaration(
                        command_id=f"over-budget-{topology}-{mode}",
                        mode=mode,
                        path=crafted_path,
                    ),
                )
                assert rejected.status_code == 409
                assert rejected.json()["code"] == "board_movement_exceeds_budget"
                assert service.read_view() == before

            legal_path = [
                [start.x_ft, start.y_ft, start.z_ft],
                [end.x_ft, end.y_ft, end.z_ft],
            ]
            preview = client.post(
                "/api/v1/commands",
                headers=auth,
                json=_declaration(
                    command_id=f"neighbor-{topology}-preview",
                    mode="preview",
                    path=legal_path,
                ),
            )
            assert preview.status_code == 200
            assert (
                preview.json()["projection"]["actors"]["vela_quill"]["movement_remaining"] == 26.0
            )
            assert service.revision == 1

            committed = client.post(
                "/api/v1/commands",
                headers=auth,
                json=_declaration(
                    command_id=f"neighbor-{topology}-commit",
                    mode="commit",
                    path=legal_path,
                ),
            )
            assert committed.status_code == 200
            assert (
                service.read_view().projection["actors"]["vela_quill"]["movement_remaining"] == 26.0
            )
            assert service.read_view().projection["actors"]["vela_quill"]["position"] == [
                end.x_ft,
                end.y_ft,
                end.z_ft,
            ]
    finally:
        scene_connection.close()
        session_connection.close()
