"""Operator-only bootstrap delivery and owned-resource lifecycle checks."""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dnd_sim.vtt import standalone_app


def tracked_connections(monkeypatch: pytest.MonkeyPatch) -> list[sqlite3.Connection]:
    connections: list[sqlite3.Connection] = []
    connect = sqlite3.connect

    def track(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(standalone_app.sqlite3, "connect", track)
    return connections


def assert_closed(connections: list[sqlite3.Connection]) -> None:
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def test_shutdown_closes_both_connections_and_cleanup_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connections = tracked_connections(monkeypatch)
    app = standalone_app.create_standalone_app(
        tmp_path / "standalone.sqlite", bootstrap_claim_delivery=lambda _: None
    )
    assert len(connections) == 2
    with TestClient(app) as client:
        assert client.get("/api/v1/installation").status_code == 200
    assert_closed(connections)
    app.state.close_owned_connections()


@pytest.mark.parametrize("stage", ["delivery", "installation", "second_connection", "routes"])
def test_factory_failures_close_every_opened_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    connections = tracked_connections(monkeypatch)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("injected startup failure")

    callback = fail if stage == "delivery" else lambda _: None
    if stage == "installation":
        monkeypatch.setattr(standalone_app, "SQLiteInstallationStore", fail)
    elif stage == "routes":
        monkeypatch.setattr(standalone_app, "install_administration_routes", fail)
    elif stage == "second_connection":
        connect = standalone_app.sqlite3.connect

        def fail_second(*args: Any, **kwargs: Any) -> sqlite3.Connection:
            if connections:
                raise RuntimeError("injected startup failure")
            return connect(*args, **kwargs)

        monkeypatch.setattr(standalone_app.sqlite3, "connect", fail_second)
    with pytest.raises(RuntimeError, match="injected startup failure"):
        standalone_app.create_standalone_app(
            tmp_path / "standalone.sqlite", bootstrap_claim_delivery=callback
        )
    assert_closed(connections)


def test_failed_delivery_leaves_no_undeliverable_durable_claim(tmp_path: Path) -> None:
    database = tmp_path / "standalone.sqlite"

    def unavailable(_: str) -> None:
        raise RuntimeError("operator channel unavailable")

    with pytest.raises(RuntimeError, match="operator channel unavailable"):
        standalone_app.create_standalone_app(database, bootstrap_claim_delivery=unavailable)
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            == []
        )
    claims: list[str] = []
    with TestClient(
        standalone_app.create_standalone_app(database, bootstrap_claim_delivery=claims.append)
    ):
        assert len(claims) == 1


def test_fresh_database_requires_explicit_operator_delivery_and_closes_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    connections = tracked_connections(monkeypatch)
    with pytest.raises(RuntimeError, match="local operator"):
        standalone_app.create_standalone_app(tmp_path / "standalone.sqlite")
    assert_closed(connections)
    assert capsys.readouterr().out == ""
    assert caplog.text == ""


def test_existing_uninitialized_installation_neither_generates_nor_delivers_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "standalone.sqlite"
    with TestClient(
        standalone_app.create_standalone_app(database, bootstrap_claim_delivery=lambda _: None)
    ):
        pass

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("restart must not generate or deliver a bootstrap claim")

    monkeypatch.setattr(standalone_app.secrets, "token_urlsafe", forbidden)
    with TestClient(
        standalone_app.create_standalone_app(database, bootstrap_claim_delivery=forbidden)
    ) as client:
        assert client.get("/api/v1/installation").json()["state"] == "uninitialized"


def test_existing_non_installation_database_is_not_claimed(tmp_path: Path) -> None:
    database = tmp_path / "unrelated.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE important_data (value TEXT)")
    claims: list[str] = []
    with pytest.raises(RuntimeError, match="refusing to provision"):
        standalone_app.create_standalone_app(database, bootstrap_claim_delivery=claims.append)
    assert claims == []
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall() == [("important_data",)]


def test_cli_defaults_to_loopback_and_closes_when_server_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connections = tracked_connections(monkeypatch)
    claims: list[str] = []
    monkeypatch.setattr(standalone_app, "_deliver_bootstrap_claim", claims.append)
    calls: list[dict[str, Any]] = []

    def fail_server(app: Any, **kwargs: Any) -> None:
        calls.append(kwargs)
        raise RuntimeError("server startup failed")

    monkeypatch.setattr(standalone_app.uvicorn, "run", fail_server)
    with pytest.raises(RuntimeError, match="server startup failed"):
        standalone_app.main(["--database", str(tmp_path / "standalone.sqlite")])
    assert calls == [{"host": "127.0.0.1", "port": 8001}]
    assert len(claims) == 1
    assert_closed(connections)


def test_cli_bootstrap_uses_only_controlling_terminal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, caplog: pytest.LogCaptureFixture
) -> None:
    class Terminal(io.StringIO):
        def close(self) -> None:
            pass

    terminal = Terminal()
    opened: list[tuple] = []

    def open_terminal(*args: Any, **kwargs: Any) -> Terminal:
        opened.append((args, kwargs))
        return terminal

    monkeypatch.setattr("builtins.open", open_terminal)
    secret = "bootstrap-secret-known-only-to-operator"
    standalone_app._deliver_bootstrap_claim(secret)
    assert opened == [(("/dev/tty", "w"), {"encoding": "utf-8"})]
    assert secret in terminal.getvalue()
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err + caplog.text


@pytest.mark.parametrize("port", ["0", "65536", "not-a-port"])
def test_cli_rejects_invalid_ports_before_provisioning(tmp_path: Path, port: str) -> None:
    database = tmp_path / "standalone.sqlite"
    with pytest.raises(SystemExit) as error:
        standalone_app.main(["--database", str(database), "--port", port])
    assert error.value.code == 2
    assert not database.exists()
