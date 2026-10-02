"""HTTP-level continuity and command-boundary checks during adventure combat."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dnd_sim.interactive.dnd_contracts import TurnDeclarationPayload
from dnd_sim.strategy_api import DeclaredAction, TargetRef, TurnDeclaration
from dnd_sim.vtt.adventure_app import create_adventure_app


def _view(client: TestClient) -> dict:
    response = client.get("/api/v1/adventure")
    assert response.status_code == 200
    return response.json()


def _enter_combat(client: TestClient) -> dict:
    for choice in ("enter_hall", "threaten_orin"):
        view = _view(client)
        assert choice in {option["id"] for option in view["choices"]}
        response = client.post(
            "/api/v1/adventure/commands",
            json={
                "schema_version": "vtt.command.v1",
                "command_id": f"choice-{view['revision']}",
                "session_id": view["session_id"],
                "expected_revision": view["revision"],
                "mode": "commit",
                "kind": "adventure.choose.v1",
                "payload": {"choice_id": choice},
                "intent_metadata": {},
            },
        )
        assert response.status_code == 200
    view = _view(client)
    assert view["phase"] == "combat"
    return view


def _available_attack(view: dict) -> dict:
    """Build a turn from the currently advertised action and target choices."""
    combat = view["combat"]
    action = next(
        option
        for option in combat["choices"]["actions"]
        if option["action_cost"] == "action"
        and option["target_mode"] == "single_enemy"
        and option["legal_target_ids"]
    )
    declaration = TurnDeclaration(
        action=DeclaredAction(
            action_name=action["action_name"],
            targets=[TargetRef(actor_id=action["legal_target_ids"][0])],
        )
    )
    return {
        "schema_version": "vtt.command.v1",
        "command_id": f"attack-{view['revision']}",
        "session_id": view["session_id"],
        "actor_id": combat["active_actor_id"],
        "expected_revision": view["revision"],
        "mode": "commit",
        "kind": "dnd.declare_turn.v1",
        "payload": TurnDeclarationPayload.from_domain(declaration).model_dump(mode="json"),
        "intent_metadata": {},
    }


def test_midcombat_reopen_ignores_new_seed_and_retries_the_exact_saved_turn(
    tmp_path: Path,
) -> None:
    database = tmp_path / "journey.sqlite"
    with TestClient(create_adventure_app(database, seed=13)) as client:
        before = _enter_combat(client)
        command = _available_attack(before)
        response = client.post("/api/v1/adventure/commands", json=command)
        assert response.status_code == 200
        receipt = response.json()
        saved = _view(client)
        assert saved["phase"] == "combat"
        assert saved["revision"] == before["revision"] + 1
        assert saved["combat"]["active_actor_id"] != command["actor_id"]
        assert saved["combat"]["actors"] != before["combat"]["actors"]

    with TestClient(create_adventure_app(database, seed=999)) as client:
        assert _view(client) == saved
        response = client.post("/api/v1/adventure/commands", json=command)
        assert response.status_code == 200
        assert response.json() == {**receipt, "replayed": True}
        assert _view(client) == saved


def test_client_cannot_override_authoritative_movement_cost_during_combat(
    tmp_path: Path,
) -> None:
    with TestClient(create_adventure_app(tmp_path / "boundary.sqlite", seed=13)) as client:
        before = _enter_combat(client)
        command = _available_attack(before)
        injected = {
            **command,
            "intent_metadata": {"_vtt_board_movement_distance_ft": 0.0},
        }
        response = client.post("/api/v1/adventure/commands", json=injected)
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_command"
        assert _view(client) == before

        # Rejection must not reserve the ID or alter the next legal turn.
        response = client.post("/api/v1/adventure/commands", json=command)
        assert response.status_code == 200
        assert _view(client)["revision"] == before["revision"] + 1
