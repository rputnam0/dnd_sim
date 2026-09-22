"""Standalone administration journeys and trust-boundary regressions."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dnd_sim.vtt.standalone_app import create_standalone_app

ROOT = "/api/v1/installation"
PASSWORD = "a long private administrator password"
ADMIN = {"username": "operator", "display_name": "Local Operator", "password": PASSWORD}


def setup(client: TestClient, claim: str) -> dict:
    response = client.post(ROOT + "/setup", headers={"X-VTT-Setup-Claim": claim}, json=ADMIN)
    assert response.status_code == 201, response.text
    return response.json()


def login(client: TestClient) -> dict:
    response = client.post(ROOT + "/login", json={"username": "operator", "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json()["schema_version"] == "vtt.installation_login.v1"
    return response.json()


def authorization(issuance: dict) -> dict[str, str]:
    return {"Authorization": "Bearer " + issuance["bearer_token"]}


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json() == {
        "schema_version": "vtt.error.v1",
        "code": code,
        "message": response.json()["message"],
        "details": {},
    }
    assert response.headers["cache-control"] == "no-store"


def test_setup_login_world_lifecycle_exact_retries_and_restart(tmp_path: Path) -> None:
    database = tmp_path / "installation.sqlite"
    claims: list[str] = []
    app = create_standalone_app(database, bootstrap_claim_delivery=claims.append)
    assert len(claims) == 1
    with TestClient(app) as client:
        initial = client.get(ROOT)
        assert initial.json()["state"] == "uninitialized"
        assert initial.headers["cache-control"] == "no-store"
        admin = setup(client, claims[0])
        issued = login(client)
        headers = authorization(issued)
        session = client.get(ROOT + "/session", headers=headers)
        assert session.json() == {
            "schema_version": "vtt.installation_session.v1",
            "admin": admin,
            "session": issued["session"],
        }
        dashboard = client.get(ROOT + "/worlds", headers=headers).json()
        assert dashboard == {
            "schema_version": "vtt.world_dashboard.v1",
            "catalog": {"schema_version": "vtt.world_catalog_view.v1", "revision": 0, "worlds": []},
            "launch_supported": True,
            "launch_unavailable_reason": None,
        }
        command = {"command_id": "create-one", "expected_revision": 0, "name": "A New World"}
        created = client.post(ROOT + "/worlds/create", headers=headers, json=command)
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["schema_version"] == "vtt.world_dashboard_mutation.v1"
        assert body["replayed"] is False
        world = body["receipt"]["event"]["world"]
        assert world["world_id"].startswith("world_")
        assert world["table_id"].startswith("table_")
        retry = client.post(ROOT + "/worlds/create", headers=headers, json=command).json()
        assert retry["receipt"] == body["receipt"]
        assert retry["replayed"] is True
        assert_error(
            client.post(
                ROOT + "/worlds/create", headers=headers, json={**command, "name": "Changed"}
            ),
            409,
            "world_command_conflict",
        )
        assert_error(
            client.post(
                ROOT + "/worlds/create", headers=headers, json={**command, "expected_revision": 1}
            ),
            409,
            "world_command_conflict",
        )
        rename = {
            "command_id": "rename-one",
            "expected_revision": 1,
            "world_id": world["world_id"],
            "name": "Renamed",
        }
        renamed = client.post(ROOT + "/worlds/rename", headers=headers, json=rename)
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["dashboard"]["catalog"]["worlds"][0]["world"]["name"] == "Renamed"
        assert (
            client.post(ROOT + "/worlds/rename", headers=headers, json=rename).json()["replayed"]
            is True
        )
        archive = {
            "command_id": "archive-one",
            "expected_revision": 2,
            "world_id": world["world_id"],
        }
        archived = client.post(ROOT + "/worlds/archive", headers=headers, json=archive)
        assert archived.json()["dashboard"]["catalog"]["worlds"][0]["archived"] is True
        assert (
            client.post(ROOT + "/worlds/archive", headers=headers, json=archive).json()["replayed"]
            is True
        )
        assert (
            client.post(ROOT + "/worlds/create", headers=headers, json=command).json()["receipt"]
            == body["receipt"]
        )
        assert client.post(ROOT + "/worlds/launch", headers=headers, json={}).status_code == 404
    restarted = create_standalone_app(database, bootstrap_claim_delivery=claims.append)
    assert len(claims) == 1
    with TestClient(restarted) as client:
        assert client.get(ROOT).json()["state"] == "ready"
        assert client.get(ROOT + "/session", headers=headers).status_code == 200
        retry = client.post(ROOT + "/worlds/create", headers=headers, json=command).json()
        assert retry["receipt"] == body["receipt"]
        assert retry["replayed"] is True
        assert retry["dashboard"]["catalog"]["revision"] == 3
        assert client.post(ROOT + "/logout", headers=headers).status_code == 204
        assert_error(client.get(ROOT + "/session", headers=headers), 401, "authentication_required")
    with sqlite3.connect(database) as connection:
        dump = "\n".join(connection.iterdump())
        table_names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert not any(secret in dump for secret in (claims[0], PASSWORD, issued["bearer_token"]))
    assert all(
        name.startswith(("_vtt_installation_", "_vtt_world_catalog_", "_vtt_world_preparation_"))
        or name == "sqlite_sequence"
        for name in table_names
    )


@pytest.mark.parametrize(
    "content", [b"{broken", b"null", b'{"password":"secret-input"}', b"x" * 20000]
)
def test_authentication_precedes_malformed_payloads(tmp_path: Path, content: bytes) -> None:
    claims: list[str] = []
    app = create_standalone_app(
        tmp_path / "installation.sqlite", bootstrap_claim_delivery=claims.append
    )
    with TestClient(app) as client:
        for path in ("/worlds/create", "/worlds/rename", "/worlds/archive"):
            response = client.post(ROOT + path, content=content)
            assert_error(response, 401, "authentication_required")
            assert "secret-input" not in response.text
        response = client.post(
            ROOT + "/setup", headers={"X-VTT-Setup-Claim": "invalid-claim-secret"}, content=content
        )
        assert_error(response, 401, "setup_claim_rejected")
        assert "invalid-claim-secret" not in response.text
        response = client.post(
            ROOT + "/setup", headers={"X-VTT-Setup-Claim": claims[0]}, content=content
        )
        assert_error(response, 422, "invalid_request")
        assert client.get(ROOT).json()["state"] == "uninitialized"


def test_restart_before_setup_preserves_original_claim(tmp_path: Path) -> None:
    database = tmp_path / "installation.sqlite"
    claims: list[str] = []
    with TestClient(create_standalone_app(database, bootstrap_claim_delivery=claims.append)):
        pass
    with TestClient(
        create_standalone_app(database, bootstrap_claim_delivery=claims.append)
    ) as client:
        setup(client, claims[0])
    assert len(claims) == 1


def test_redacted_validation_and_exact_cors(tmp_path: Path) -> None:
    claims: list[str] = []
    with TestClient(
        create_standalone_app(
            tmp_path / "installation.sqlite", bootstrap_claim_delivery=claims.append
        )
    ) as client:
        setup(client, claims[0])
        headers = authorization(login(client))
        response = client.post(
            ROOT + "/worlds/create",
            headers=headers,
            json={
                "command_id": "valid",
                "expected_revision": True,
                "name": "private-invalid-input",
                "world_id": "injected",
            },
        )
        assert_error(response, 422, "invalid_request")
        assert "private-invalid-input" not in response.text
        assert_error(
            client.post(
                ROOT + "/login",
                json={"username": "absent-private-user", "password": "private-password"},
            ),
            401,
            "authentication_required",
        )
        for origin, allowed in (
            ("http://localhost:3000", True),
            ("http://localhost:3000.evil.example", False),
            ("https://evil.example", False),
        ):
            response = client.options(
                ROOT + "/worlds/create",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type",
                },
            )
            assert (response.headers.get("access-control-allow-origin") == origin) is allowed
            assert response.headers["cache-control"] == "no-store"
            if not allowed:
                assert_error(response, 400, "origin_not_allowed")


def test_installation_corruption_returns_safe_mode_and_blocks_writes(tmp_path: Path) -> None:
    database = tmp_path / "installation.sqlite"
    claims: list[str] = []
    with TestClient(
        create_standalone_app(database, bootstrap_claim_delivery=claims.append)
    ) as client:
        setup(client, claims[0])
        headers = authorization(login(client))
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE _vtt_installation_head SET head_hash = ?", ("0" * 64,))
    with TestClient(create_standalone_app(database)) as client:
        assert client.get(ROOT).json()["state"] == "safe_mode"
        assert_error(client.get(ROOT + "/worlds", headers=headers), 503, "installation_safe_mode")
        assert_error(
            client.post(ROOT + "/worlds/create", headers=headers, content=b"broken"),
            503,
            "installation_safe_mode",
        )
        assert_error(client.post(ROOT + "/login", json=ADMIN), 503, "installation_safe_mode")


@pytest.mark.parametrize("all_tables", [False, True])
def test_missing_catalog_structure_is_not_reinitialized_on_restart(
    tmp_path: Path, all_tables: bool
) -> None:
    database = tmp_path / "installation.sqlite"
    claims: list[str] = []
    with TestClient(
        create_standalone_app(database, bootstrap_claim_delivery=claims.append)
    ) as client:
        setup(client, claims[0])
        headers = authorization(login(client))
        created = client.post(
            ROOT + "/worlds/create",
            headers=headers,
            json={"command_id": "create-one", "expected_revision": 0, "name": "Must not disappear"},
        )
        assert created.status_code == 200
    dropped = ["_vtt_world_catalog_events"]
    if all_tables:
        dropped += ["_vtt_world_catalog_head", "_vtt_world_catalog_metadata"]
    with sqlite3.connect(database) as connection:
        for table in dropped:
            connection.execute(f"DROP TABLE {table}")
    with TestClient(create_standalone_app(database)) as client:
        assert client.get(ROOT).json()["state"] == "ready"
        assert_error(client.get(ROOT + "/worlds", headers=headers), 503, "storage_unavailable")
        assert_error(
            client.post(
                ROOT + "/worlds/create",
                headers=headers,
                json={
                    "command_id": "new-create",
                    "expected_revision": 0,
                    "name": "Never committed",
                },
            ),
            503,
            "storage_unavailable",
        )
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert not tables.intersection(dropped)


def test_concurrent_exact_creates_commit_one_world(tmp_path: Path) -> None:
    claims: list[str] = []
    with TestClient(
        create_standalone_app(
            tmp_path / "installation.sqlite", bootstrap_claim_delivery=claims.append
        )
    ) as client:
        setup(client, claims[0])
        headers = authorization(login(client))
        command = {"command_id": "concurrent-create", "expected_revision": 0, "name": "One World"}

        def create(_: int):
            return client.post(ROOT + "/worlds/create", headers=headers, json=command)

        with ThreadPoolExecutor(max_workers=6) as executor:
            responses = list(executor.map(create, range(6)))
        assert all(response.status_code == 200 for response in responses)
        results = [response.json() for response in responses]
        assert sum(result["replayed"] is False for result in results) == 1
        assert all(result["receipt"] == results[0]["receipt"] for result in results)
        dashboard = client.get(ROOT + "/worlds", headers=headers).json()
        assert dashboard["catalog"]["revision"] == 1
        assert len(dashboard["catalog"]["worlds"]) == 1


def test_world_conflicts_do_not_leak_inputs_or_mutate_catalog(tmp_path: Path) -> None:
    claims: list[str] = []
    with TestClient(
        create_standalone_app(
            tmp_path / "installation.sqlite", bootstrap_claim_delivery=claims.append
        )
    ) as client:
        setup(client, claims[0])
        headers = authorization(login(client))
        command = {"command_id": "original", "expected_revision": 0, "name": "Private World Name"}
        created = client.post(ROOT + "/worlds/create", headers=headers, json=command).json()
        world_id = created["receipt"]["event"]["world"]["world_id"]
        for path, payload, code in (
            (
                "create",
                {**command, "command_id": "stale", "name": "Other"},
                "world_revision_conflict",
            ),
            (
                "create",
                {
                    **command,
                    "command_id": "collision",
                    "expected_revision": 1,
                    "name": "PRIVATE WORLD NAME",
                },
                "world_name_conflict",
            ),
            (
                "rename",
                {
                    "command_id": "unchanged",
                    "expected_revision": 1,
                    "world_id": world_id,
                    "name": "Private World Name",
                },
                "world_name_unchanged",
            ),
            (
                "archive",
                {
                    "command_id": "missing",
                    "expected_revision": 1,
                    "world_id": "world_private_missing",
                },
                "world_not_found",
            ),
            (
                "rename",
                {
                    "command_id": "original",
                    "expected_revision": 0,
                    "world_id": world_id,
                    "name": "Private World Name",
                },
                "world_command_conflict",
            ),
        ):
            response = client.post(ROOT + "/worlds/" + path, headers=headers, json=payload)
            assert_error(response, 409, code)
            assert "Private World Name" not in response.text
            assert world_id not in response.text
        assert client.get(ROOT + "/worlds", headers=headers).json()["catalog"]["revision"] == 1


def test_session_expiry_and_invalid_bearers_are_identity_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dnd_sim.vtt import standalone_app

    now = [1000]
    store = standalone_app.SQLiteInstallationStore

    def timed_store(connection, **kwargs):
        return store(connection, clock=lambda: now[0], session_ttl_seconds=60, **kwargs)

    monkeypatch.setattr(standalone_app, "SQLiteInstallationStore", timed_store)
    claims: list[str] = []
    with TestClient(
        create_standalone_app(
            tmp_path / "installation.sqlite", bootstrap_claim_delivery=claims.append
        )
    ) as client:
        setup(client, claims[0])
        issuance = login(client)
        headers = authorization(issuance)
        assert client.get(ROOT + "/session", headers=headers).status_code == 200
        now[0] = 1060
        expired = client.get(ROOT + "/session", headers=headers)
        assert_error(expired, 401, "authentication_required")
        for bearer in (
            "Bearer nonexistent-secret",
            "Basic other-private-token",
            "Bearer",
            "Bearer two tokens",
        ):
            invalid = client.get(ROOT + "/session", headers={"Authorization": bearer})
            assert invalid.json() == expired.json()
        assert issuance["admin"]["admin_id"] not in expired.text
