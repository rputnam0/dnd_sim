from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from dnd_sim.interactive.dnd_contracts import TurnDeclarationPayload
from dnd_sim.strategy_api import DeclaredAction, TargetRef, TurnDeclaration
from dnd_sim.vtt.adventure_app import create_adventure_app
from dnd_sim.vtt.event_store import EventStoreError, SQLiteSessionEventStore


def _choice(view: dict, choice_id: str, command_id: str = "choice-1") -> dict:
    return {
        "schema_version": "vtt.command.v1",
        "command_id": command_id,
        "session_id": view["session_id"],
        "actor_id": None,
        "expected_revision": view["revision"],
        "mode": "commit",
        "kind": "adventure.choose.v1",
        "payload": {"choice_id": choice_id},
        "intent_metadata": {},
    }


def test_adventure_starts_with_original_party_and_available_choices(tmp_path: Path) -> None:
    with TestClient(create_adventure_app(tmp_path / "adventure.sqlite")) as client:
        response = client.get("/api/v1/adventure")
        assert response.status_code == 200
        view = response.json()
        assert view["schema_version"] == "adventure.view.v1"
        assert view["title"] == "The Lantern Below"
        assert view["phase"] == "exploration"
        assert view["revision"] == 0
        assert {actor["actor_id"] for actor in view["party"]} == {"mara", "iven", "sela"}
        assert "enter_hall" in {choice["id"] for choice in view["choices"]}
        assert view["combat"] is None
        assert "rng_state" not in view


def test_saved_choice_survives_restart_and_retry_without_duplicate_mutation(tmp_path: Path) -> None:
    database = tmp_path / "adventure.sqlite"
    with TestClient(create_adventure_app(database)) as client:
        initial = client.get("/api/v1/adventure").json()
        command = _choice(initial, "enter_hall")
        command["intent_metadata"] = {"surface": "lantern-adventure"}
        receipt = client.post("/api/v1/adventure/commands", json=command)
        assert receipt.status_code == 200
        saved = client.get("/api/v1/adventure").json()
        assert saved["revision"] == 1
        assert saved["location"]["id"] == "hall"
    with TestClient(create_adventure_app(database)) as client:
        assert client.get("/api/v1/adventure").json() == saved
        retried = client.post("/api/v1/adventure/commands", json=command)
        assert retried.status_code == 200
        assert retried.json()["replayed"] is True
        assert client.get("/api/v1/adventure").json() == saved


def test_stale_or_unavailable_choices_preserve_the_saved_state(tmp_path: Path) -> None:
    with TestClient(create_adventure_app(tmp_path / "adventure.sqlite")) as client:
        initial = client.get("/api/v1/adventure").json()
        client.post("/api/v1/adventure/commands", json=_choice(initial, "enter_hall"))
        saved = client.get("/api/v1/adventure").json()
        stale = client.post(
            "/api/v1/adventure/commands", json=_choice(initial, "enter_hall", "stale")
        )
        assert stale.status_code == 409
        invalid = client.post(
            "/api/v1/adventure/commands", json=_choice(saved, "restore_beacon", "invalid")
        )
        assert invalid.status_code == 422
        assert client.get("/api/v1/adventure").json() == saved


@pytest.mark.parametrize("mode", ["preview", "admin", "reaction"])
def test_player_api_does_not_accept_non_commit_modes(tmp_path: Path, mode: str) -> None:
    with TestClient(create_adventure_app(tmp_path / "adventure.sqlite")) as client:
        view = client.get("/api/v1/adventure").json()
        command = _choice(view, "enter_hall")
        command["mode"] = mode
        response = client.post("/api/v1/adventure/commands", json=command)
        assert response.status_code == 422
        assert client.get("/api/v1/adventure").json() == view


def test_foreign_browser_origin_cannot_read_or_mutate_local_adventure(tmp_path: Path) -> None:
    with TestClient(create_adventure_app(tmp_path / "adventure.sqlite")) as client:
        view = client.get("/api/v1/adventure").json()
        headers = {"origin": "https://unrelated.example"}
        assert client.get("/api/v1/adventure", headers=headers).status_code == 403
        response = client.post(
            "/api/v1/adventure/commands", json=_choice(view, "enter_hall"), headers=headers
        )
        assert response.status_code == 403
        assert client.get("/api/v1/adventure").json() == view


def test_malformed_and_oversized_input_returns_bounded_errors(tmp_path: Path) -> None:
    with TestClient(create_adventure_app(tmp_path / "adventure.sqlite")) as client:
        wrong_type = client.post("/api/v1/adventure/commands", content="{}")
        assert wrong_type.status_code == 415
        oversized = client.post(
            "/api/v1/adventure/commands",
            content="x" * 65_537,
            headers={"content-type": "application/json"},
        )
        assert oversized.status_code == 413
        invalid = client.post(
            "/api/v1/adventure/commands",
            content="not-json",
            headers={"content-type": "application/json"},
        )
        assert invalid.status_code == 422
        assert "not-json" not in invalid.text


def test_failed_save_preserves_state_and_the_same_action_can_be_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "adventure.sqlite"
    with TestClient(create_adventure_app(database)) as client:
        initial = client.get("/api/v1/adventure").json()
        command = _choice(initial, "enter_hall")

        def fail_save(*_args, **_kwargs):
            raise EventStoreError("injected storage failure")

        with monkeypatch.context() as scoped:
            scoped.setattr(SQLiteSessionEventStore, "append_commit", fail_save)
            response = client.post("/api/v1/adventure/commands", json=command)
            assert response.status_code == 503
            assert "injected storage" not in response.text
            assert client.get("/api/v1/adventure").json() == initial

        assert client.post("/api/v1/adventure/commands", json=command).status_code == 200
        saved = client.get("/api/v1/adventure").json()
        assert saved["revision"] == 1
    with TestClient(create_adventure_app(database)) as client:
        assert client.get("/api/v1/adventure").json() == saved


def test_reusing_a_command_id_for_different_choices_is_a_conflict(tmp_path: Path) -> None:
    with TestClient(create_adventure_app(tmp_path / "adventure.sqlite")) as client:
        initial = client.get("/api/v1/adventure").json()
        command = _choice(initial, "enter_hall")
        assert client.post("/api/v1/adventure/commands", json=command).status_code == 200
        saved = client.get("/api/v1/adventure").json()
        conflict = _choice(saved, "listen_orin")
        assert client.post("/api/v1/adventure/commands", json=conflict).status_code == 409
        assert client.get("/api/v1/adventure").json() == saved


def test_allowed_browser_origin_receives_preflight_commit_and_error_responses(
    tmp_path: Path,
) -> None:
    origin = "http://127.0.0.1:3011"
    with TestClient(
        create_adventure_app(tmp_path / "adventure.sqlite", allowed_origins=(origin,))
    ) as client:
        preflight = client.options(
            "/api/v1/adventure/commands",
            headers={
                "origin": origin,
                "access-control-request-method": "POST",
                "access-control-request-headers": "content-type",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == origin
        initial = client.get("/api/v1/adventure", headers={"origin": origin}).json()
        command = _choice(initial, "enter_hall")
        response = client.post(
            "/api/v1/adventure/commands", json=command, headers={"origin": origin}
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["cache-control"] == "no-store"
        stale = client.post(
            "/api/v1/adventure/commands",
            json=_choice(initial, "enter_hall", "stale"),
            headers={"origin": origin},
        )
        assert stale.status_code == 409
        assert stale.headers["access-control-allow-origin"] == origin


def test_out_of_range_attack_explains_how_to_recover_without_spending_a_turn(
    tmp_path: Path,
) -> None:
    with TestClient(create_adventure_app(tmp_path / "adventure.sqlite")) as client:
        for index, choice in enumerate(("enter_hall", "threaten_orin")):
            view = client.get("/api/v1/adventure").json()
            response = client.post(
                "/api/v1/adventure/commands", json=_choice(view, choice, f"story-{index}")
            )
            assert response.status_code == 200
        before = client.get("/api/v1/adventure").json()
        command = _choice(before, "unused", "attack")
        command.update(
            actor_id="mara",
            kind="dnd.declare_turn.v1",
            payload=TurnDeclarationPayload.from_domain(
                TurnDeclaration(
                    action=DeclaredAction("Guard's blade", targets=[TargetRef("warden_1")])
                )
            ).model_dump(mode="json"),
        )
        rejected = client.post("/api/v1/adventure/commands", json=command)
        assert rejected.status_code == 422
        assert "range" in rejected.json()["message"].lower()
        assert client.get("/api/v1/adventure").json() == before
