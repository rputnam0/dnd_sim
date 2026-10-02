"""Lead-owned black-box acceptance of independent GM and guest browser authority."""

from pathlib import Path

from fastapi.testclient import TestClient

from dnd_sim.vtt.standalone_app import create_standalone_app
from test_vtt_world_preparation_journey import (
    ADMIN,
    ROOT,
    _author_map_scene,
    _get,
    _headers,
    _launch,
    _login,
    _world,
)


def _issue(client, gm, role="player", command_id="invite-guest"):
    response = client.post(
        gm["workspace_api_path"] + "/api/v1/invitations",
        headers=_headers(gm),
        json={"command_id": command_id, "role": role},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _join(client, issued, name="River Guest"):
    response = client.post(
        ROOT + "/join",
        headers={"Authorization": "Bearer " + issued["invitation_token"]},
        json={"display_name": name},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _initialize(client, claim):
    response = client.post(ROOT + "/setup", headers={"X-VTT-Setup-Claim": claim}, json=ADMIN)
    assert response.status_code == 201, response.text


def test_guest_world_view_revocation_and_content_survive_independent_admin_logout(tmp_path: Path):
    claims = []
    app = create_standalone_app(tmp_path / "journey.sqlite", bootstrap_claim_delivery=claims.append)
    with TestClient(app) as client:
        _initialize(client, claims[0])
        admin = _login(client)
        world = _world(client, admin, "Invited forest", 0)
        gm = _launch(client, admin, world)
        content = _author_map_scene(client, gm, color="green", name="The shared clearing")
        other = _launch(client, admin, _world(client, admin, "Unrelated private world", 1))
        issued = _issue(client, gm)
        guest = _join(client, issued)
        spectator = _join(client, _issue(client, gm, "spectator", "invite-observer"), "Observer")
        assert guest["world"] == world
        assert guest["session_id"] == gm["session_id"]
        principal = guest["table"]["current_participant"]
        assert principal["role"] == "player" and principal["owned_actor_ids"] == []
        assert principal not in spectator["table"]["participants"]
        assert _get(client, guest, "session").status_code == 404  # No fabricated encounter.
        for visitor in (guest, spectator):
            assert _get(client, visitor, "invitations").status_code == 403
            assert client.get(ROOT + "/worlds", headers=_headers(visitor)).status_code == 401
            assert (
                client.get(
                    other["workspace_api_path"] + "/api/v1/scenes", headers=_headers(visitor)
                ).status_code
                == 401
            )
            scenes = _get(client, visitor, "scenes").json()
            assert len(scenes["scenes"]) == 1
            reference = scenes["scenes"][0]["scene"]["map_metadata"]["asset"]
            assert (
                client.get(
                    visitor["workspace_api_path"] + reference["content_path"],
                    headers=_headers(visitor),
                ).content
                == content
            )
        # Guests are table principals, not administrator-session derivatives.
        assert client.post(ROOT + "/logout", headers=_headers(admin)).status_code == 204
        assert _get(client, gm, "table").status_code == 401
        assert _get(client, guest, "table").status_code == 200
        admin = _login(client)
        gm = _launch(client, admin, world)
        before = _get(client, gm, "scenes").json()
        revoke = (
            gm["workspace_api_path"]
            + "/api/v1/invitations/"
            + issued["invitation"]["invitation_id"]
            + "/revoke"
        )
        assert client.post(revoke, headers=_headers(gm)).status_code == 204
        assert client.post(revoke, headers=_headers(gm)).status_code == 204
        for suffix in ("table", "scenes", "map-assets", "scene-events?after=0"):
            response = _get(client, guest, suffix)
            assert response.status_code == 401, response.text
            assert response.json()["details"] == {}
            assert principal["participant_id"] not in response.text
        assert (
            client.get(
                guest["workspace_api_path"] + reference["content_path"], headers=_headers(guest)
            ).status_code
            == 401
        )
        assert _get(client, spectator, "table").status_code == 200
        assert _get(client, gm, "scenes").json() == before
        assert (
            client.post(
                ROOT + f"/worlds/{world['world_id']}/return", headers=_headers(spectator)
            ).status_code
            == 204
        )
        assert _get(client, spectator, "table").status_code == 401
        assert _get(client, gm, "table").status_code == 200


def test_pending_invitation_can_open_existing_world_after_restart_without_gm_session(
    tmp_path: Path,
):
    database = tmp_path / "restart.sqlite"
    claims = []
    with TestClient(
        create_standalone_app(database, bootstrap_claim_delivery=claims.append)
    ) as client:
        _initialize(client, claims[0])
        admin = _login(client)
        world = _world(client, admin, "Persistent guest world", 0)
        gm = _launch(client, admin, world)
        used = _issue(client, gm, command_id="before-restart")
        previous_guest = _join(client, used)
        pending = _issue(client, gm, "spectator", "after-restart")
        assert _get(client, previous_guest, "scenes").json()["scenes"] == []
    with TestClient(create_standalone_app(database)) as client:
        assert _get(client, previous_guest, "table").status_code == 401
        guest = _join(client, pending, "After restart")
        assert guest["world"] == world
        assert guest["session_id"] == gm["session_id"]
        assert _get(client, guest, "scenes").json()["scenes"] == []
        duplicate = client.post(
            ROOT + "/join",
            headers={"Authorization": "Bearer " + pending["invitation_token"]},
            json={"display_name": "Second claimant"},
        )
        assert duplicate.status_code == 401
        assert "Second claimant" not in duplicate.text
        gm = _launch(client, _login(client), world)
        roster = _get(client, gm, "invitations").json()["invitations"]
        assert len(roster) == 2
        assert {entry["participant"]["participant_id"] for entry in roster} == {
            previous_guest["table"]["current_participant"]["participant_id"],
            guest["table"]["current_participant"]["participant_id"],
        }
