from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

import dnd_sim.vtt.installation_store as installation_store_module
from dnd_sim.vtt.installation_contracts import (
    ADMIN_PUBLIC_SCHEMA_VERSION,
    INSTALLATION_VIEW_SCHEMA_VERSION,
    SESSION_PUBLIC_SCHEMA_VERSION,
    AdminPublic,
    AuthenticationAttemptBudget,
    InstallationView,
    ScryptParameters,
    SessionPublic,
)
from dnd_sim.vtt.installation_store import (
    AuthenticationError,
    BootstrapClaimError,
    EntropySourceError,
    InstallationAlreadyInitializedError,
    InstallationSafeModeError,
    SQLiteInstallationStore,
    SessionBearerConsumedError,
)

BOOTSTRAP = "setup_BB68hL3m7Ju4xqCtYk52Jw9nPs6ZaFdR"
PASSWORD = "correct horse battery staple"


class SequenceEntropy:
    def __init__(self) -> None:
        self.counter = 0

    def __call__(self, size: int) -> bytes:
        self.counter += 1
        return self.counter.to_bytes(size, "big")


class FixedClock:
    def __init__(self, epoch: int = 1_900_000_000) -> None:
        self.epoch = epoch

    def __call__(self) -> int:
        return self.epoch


def _payload(
    *,
    username: str = "keeper",
    display_name: str = "Table Keeper",
    password: str = PASSWORD,
) -> dict[str, object]:
    return {
        "username": username,
        "display_name": display_name,
        "password": password,
    }


def _new_store(
    connection: sqlite3.Connection | None = None,
    *,
    clock: Callable[[], int] | None = None,
    entropy: Callable[[int], bytes] | None = None,
) -> SQLiteInstallationStore:
    return SQLiteInstallationStore(
        connection or sqlite3.connect(":memory:"),
        bootstrap_claim=BOOTSTRAP,
        clock=clock or FixedClock(),
        random_bytes=entropy or SequenceEntropy(),
    )


def _initialize(store: SQLiteInstallationStore) -> AdminPublic:
    return store.initialize(bootstrap_claim=BOOTSTRAP, admin_payload=_payload())


def _login(store: SQLiteInstallationStore, *, password: str = PASSWORD):
    return store.login(username="keeper", password=password)


def test_public_contracts_are_strict_frozen_versioned_and_secret_free() -> None:
    admin = AdminPublic(
        admin_id="adm_01",
        username="keeper",
        display_name="Table Keeper",
        created_at=1_900_000_000,
    )
    session = SessionPublic(
        session_id="ses_01",
        admin_id=admin.admin_id,
        issued_at=1_900_000_000,
        expires_at=1_900_003_600,
        revoked=False,
    )
    view = InstallationView(
        state="ready",
        revision=1,
        setup_claimed=True,
        active_admin_count=1,
        integrity_status="verified",
    )

    assert admin.schema_version == ADMIN_PUBLIC_SCHEMA_VERSION
    assert session.schema_version == SESSION_PUBLIC_SCHEMA_VERSION
    assert view.schema_version == INSTALLATION_VIEW_SCHEMA_VERSION
    for model in (admin, session, view):
        encoded = model.model_dump_json()
        assert "password" not in encoded
        assert "bootstrap" not in encoded
        assert "bearer" not in encoded
        with pytest.raises(ValidationError):
            type(model).model_validate({**model.model_dump(), "password": "leak"})
        with pytest.raises(ValidationError):
            model.revision = 99  # type: ignore[attr-defined,misc]


def test_new_installation_is_explicitly_uninitialized_and_contains_no_table_data() -> None:
    store = _new_store()

    assert store.view() == InstallationView(
        state="uninitialized",
        revision=0,
        setup_claimed=False,
        active_admin_count=0,
        integrity_status="verified",
    )
    assert store.admins() == ()
    assert "world" not in repr(store.view()).lower()
    assert "table" not in store.view().model_dump_json().lower()


def test_setup_authenticates_bootstrap_before_admin_payload_validation() -> None:
    store = _new_store()

    with pytest.raises(BootstrapClaimError, match="setup claim rejected") as rejected:
        store.initialize(
            bootstrap_claim="wrong-claim",
            admin_payload={"unexpected": object()},
        )
    assert "unexpected" not in str(rejected.value)

    with pytest.raises(ValidationError, match="username"):
        store.initialize(
            bootstrap_claim=BOOTSTRAP,
            admin_payload={"username": "", "password": "short"},
        )
    assert store.view().state == "uninitialized"


def test_initialize_claims_setup_exactly_once_and_replay_is_rejected() -> None:
    store = _new_store()

    admin = _initialize(store)

    assert admin.username == "keeper"
    assert admin.display_name == "Table Keeper"
    assert store.view() == InstallationView(
        state="ready",
        revision=1,
        setup_claimed=True,
        active_admin_count=1,
        integrity_status="verified",
    )
    assert store.admins() == (admin,)

    with pytest.raises(InstallationAlreadyInitializedError, match="already initialized"):
        store.initialize(bootstrap_claim=BOOTSTRAP, admin_payload=_payload(username="another"))
    assert store.view().revision == 1


def test_database_and_representations_never_contain_secret_plaintext() -> None:
    connection = sqlite3.connect(":memory:")
    store = _new_store(connection)
    admin = _initialize(store)
    issuance = _login(store)
    bearer = issuance.consume_bearer()

    database_text = "\n".join(connection.iterdump())
    public_text = "\n".join(
        (
            repr(store),
            repr(admin),
            repr(issuance),
            store.view().model_dump_json(),
            store.sessions(admin_bearer=bearer)[0].model_dump_json(),
        )
    )
    for secret in (BOOTSTRAP, PASSWORD, bearer):
        assert secret not in database_text
        assert secret not in public_text


def test_validation_and_authentication_errors_redact_every_secret() -> None:
    store = _new_store()
    invalid_password = "distinct-invalid-password\nsecret"

    with pytest.raises(ValidationError) as invalid_setup:
        store.initialize(
            bootstrap_claim=BOOTSTRAP,
            admin_payload=_payload(password=invalid_password),
        )
    assert invalid_password not in str(invalid_setup.value)
    assert BOOTSTRAP not in str(invalid_setup.value)

    _initialize(store)
    issuance = _login(store)
    bearer = issuance.consume_bearer()
    with pytest.raises(ValidationError) as invalid_change:
        store.change_password(bearer, new_password=invalid_password)
    assert invalid_password not in str(invalid_change.value)
    assert bearer not in str(invalid_change.value)

    with pytest.raises(AuthenticationError) as invalid_session:
        store.authenticate_session("\ud800")
    assert "\ud800" not in str(invalid_session.value)


def test_persisted_scrypt_verifiers_have_explicit_parameters_and_unique_salts() -> None:
    connection = sqlite3.connect(":memory:")
    store = _new_store(connection)
    _initialize(store)

    metadata = connection.execute("""
        SELECT bootstrap_salt_hex, bootstrap_verifier_hex, bootstrap_scrypt_json
        FROM _vtt_installation_metadata
        """).fetchone()
    assert metadata is not None
    bootstrap_salt, bootstrap_verifier, bootstrap_parameters = metadata
    initialized_event = connection.execute(
        "SELECT event_json FROM _vtt_installation_events WHERE revision = 1"
    ).fetchone()
    assert initialized_event is not None
    import json

    event = json.loads(initialized_event[0])
    assert event["password_scrypt"] == ScryptParameters().model_dump(mode="json")
    assert json.loads(bootstrap_parameters) == ScryptParameters().model_dump(mode="json")
    assert event["password_salt_hex"] != bootstrap_salt
    assert len(event["password_salt_hex"]) == len(bootstrap_salt) == 32
    assert len(event["password_verifier_hex"]) == len(bootstrap_verifier) == 64
    assert PASSWORD not in initialized_event[0]


def test_session_bearer_is_returned_exactly_once_and_only_hash_is_durable() -> None:
    connection = sqlite3.connect(":memory:")
    store = _new_store(connection)
    _initialize(store)

    issuance = _login(store)
    assert "redacted" in repr(issuance).lower()
    bearer = issuance.consume_bearer()
    assert bearer.startswith("vtt1_")
    with pytest.raises(SessionBearerConsumedError, match="already consumed"):
        issuance.consume_bearer()

    dump = "\n".join(connection.iterdump())
    assert bearer not in dump
    assert "token_hash" in dump
    assert store.authenticate_session(bearer) == issuance.session


def test_login_and_session_failures_are_identity_free_and_constant_message() -> None:
    store = _new_store()
    _initialize(store)

    failures: list[str] = []
    for username, password in (
        ("missing", PASSWORD),
        ("keeper", "incorrect password"),
    ):
        with pytest.raises(AuthenticationError) as rejected:
            store.login(username=username, password=password)
        failures.append(str(rejected.value))
    with pytest.raises(AuthenticationError) as rejected_token:
        store.authenticate_session("vtt1_unknown")
    failures.append(str(rejected_token.value))

    assert failures == ["authentication failed"] * 3
    assert "keeper" not in " ".join(failures)


def test_session_expiry_and_revocation_fail_closed_with_generic_failure() -> None:
    clock = FixedClock()
    store = _new_store(clock=clock)
    _initialize(store)

    first = _login(store)
    first_bearer = first.consume_bearer()
    store.revoke_session(first_bearer)
    with pytest.raises(AuthenticationError, match="^authentication failed$"):
        store.authenticate_session(first_bearer)

    second = _login(store)
    second_bearer = second.consume_bearer()
    clock.epoch = second.session.expires_at
    with pytest.raises(AuthenticationError, match="^authentication failed$"):
        store.authenticate_session(second_bearer)


def test_authenticated_admin_can_revoke_a_specific_session_without_its_bearer() -> None:
    store = _new_store()
    _initialize(store)
    controlling = _login(store)
    controlling_bearer = controlling.consume_bearer()
    target = _login(store)
    target_bearer = target.consume_bearer()

    revoked = store.revoke_session(
        controlling_bearer,
        session_id=target.session.session_id,
    )

    assert revoked.revoked is True
    assert store.authenticate_session(controlling_bearer) == controlling.session
    with pytest.raises(AuthenticationError, match="^authentication failed$"):
        store.authenticate_session(target_bearer)


def test_password_change_requires_auth_and_invalidates_every_existing_session() -> None:
    store = _new_store()
    _initialize(store)
    first = _login(store)
    first_bearer = first.consume_bearer()
    second = _login(store)
    second_bearer = second.consume_bearer()

    with pytest.raises(AuthenticationError, match="^authentication failed$"):
        store.change_password("vtt1_invalid", new_password="a new safer passphrase")

    store.change_password(first_bearer, new_password="a new safer passphrase")
    for stale in (first_bearer, second_bearer):
        with pytest.raises(AuthenticationError, match="^authentication failed$"):
            store.authenticate_session(stale)
    with pytest.raises(AuthenticationError, match="^authentication failed$"):
        _login(store)
    replacement = _login(store, password="a new safer passphrase")
    assert (
        store.authenticate_session(replacement.consume_bearer()).admin_id == first.session.admin_id
    )


def test_durable_hashed_sessions_survive_restart_until_expiry(tmp_path: Path) -> None:
    database = tmp_path / "installation.sqlite3"
    clock = FixedClock()
    entropy = SequenceEntropy()
    first_connection = sqlite3.connect(database)
    first = _new_store(first_connection, clock=clock, entropy=entropy)
    _initialize(first)
    issuance = _login(first)
    bearer = issuance.consume_bearer()
    first_connection.close()

    second_connection = sqlite3.connect(database)
    restarted = SQLiteInstallationStore(
        second_connection,
        clock=clock,
        random_bytes=entropy,
    )

    assert restarted.view().state == "ready"
    assert restarted.authenticate_session(bearer) == issuance.session
    with pytest.raises(InstallationAlreadyInitializedError):
        restarted.initialize(bootstrap_claim=BOOTSTRAP, admin_payload=_payload())


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("username", " keeper"),
        ("username", "ke\neper"),
        ("username", "x" * 65),
        ("username", "Keeper"),
        ("display_name", ""),
        ("display_name", "name\x00"),
        ("display_name", "x" * 81),
        ("password", "short"),
        ("password", "password\nwith control"),
        ("password", "x" * 257),
    ],
)
def test_admin_payload_rejects_unsafe_unicode_control_and_sizes(
    field_name: str, value: str
) -> None:
    store = _new_store()
    payload = _payload()
    payload[field_name] = value

    with pytest.raises(ValidationError):
        store.initialize(bootstrap_claim=BOOTSTRAP, admin_payload=payload)
    assert store.view().state == "uninitialized"


def test_admin_payload_accepts_canonical_unicode_without_persisting_password() -> None:
    connection = sqlite3.connect(":memory:")
    store = _new_store(connection)
    admin = store.initialize(
        bootstrap_claim=BOOTSTRAP,
        admin_payload=_payload(
            username="maître",
            display_name="Maître du Donjon",
            password="épée-bouclier-dragon-2026",
        ),
    )

    assert admin.username == "maître"
    assert "épée-bouclier-dragon-2026" not in "\n".join(connection.iterdump())


def test_scrypt_parameters_are_explicit_strict_and_bounded() -> None:
    parameters = ScryptParameters()
    assert parameters.n == 2**14
    assert parameters.r == 8
    assert parameters.p == 1
    assert parameters.dklen == 32

    for changes in (
        {"n": 2**13},
        {"n": 2**14 + 1},
        {"n": 2**18},
        {"r": 7},
        {"p": 0},
        {"p": 5},
        {"dklen": 16},
        {"dklen": 65},
    ):
        with pytest.raises(ValidationError):
            ScryptParameters(**changes)


def test_injected_entropy_produces_unique_deterministic_admin_session_and_bearers() -> None:
    entropy = SequenceEntropy()
    store = _new_store(entropy=entropy)
    admin = _initialize(store)
    first = _login(store)
    second = _login(store)
    first_bearer = first.consume_bearer()
    second_bearer = second.consume_bearer()

    assert admin.admin_id.startswith("adm_")
    assert first.session.session_id != second.session.session_id
    assert first_bearer != second_bearer
    assert store.authenticate_session(first_bearer) == first.session
    assert store.authenticate_session(second_bearer) == second.session


def test_repeating_entropy_fails_closed_instead_of_reusing_a_salt_or_identity() -> None:
    store = _new_store(entropy=lambda size: b"x" * size)

    with pytest.raises(EntropySourceError, match="unique"):
        _initialize(store)
    assert store.view().state == "uninitialized"


def test_initialize_rolls_back_on_base_exception_and_claim_remains_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SimulatedAbort(BaseException):
        pass

    store = _new_store()
    original_append = store._append_event_locked

    def abort_after_append(*args: object, **kwargs: object) -> object:
        original_append(*args, **kwargs)
        raise SimulatedAbort

    monkeypatch.setattr(store, "_append_event_locked", abort_after_append)
    with pytest.raises(SimulatedAbort):
        _initialize(store)
    assert store.view().state == "uninitialized"

    monkeypatch.setattr(store, "_append_event_locked", original_append)
    assert _initialize(store).username == "keeper"


def test_global_pre_auth_budget_is_shared_and_skips_kdf_until_window_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FixedClock()
    store = SQLiteInstallationStore(
        sqlite3.connect(":memory:"),
        bootstrap_claim=BOOTSTRAP,
        clock=clock,
        random_bytes=SequenceEntropy(),
        attempt_budget=AuthenticationAttemptBudget(
            maximum_failures=5,
            window_seconds=60,
            maximum_principals=16,
            global_maximum_failures=2,
            global_window_seconds=60,
        ),
    )
    original_derive = installation_store_module._derive_secret
    kdf_calls = 0

    def counted_derive(*args: object, **kwargs: object) -> bytes:
        nonlocal kdf_calls
        kdf_calls += 1
        return original_derive(*args, **kwargs)

    monkeypatch.setattr(installation_store_module, "_derive_secret", counted_derive)

    with pytest.raises(BootstrapClaimError, match="^setup claim rejected$"):
        store.initialize(bootstrap_claim="wrong-bootstrap-value-000", admin_payload=object())
    with pytest.raises(AuthenticationError, match="^authentication failed$"):
        store.login(username="missing", password="wrong password value")
    assert kdf_calls == 2

    with pytest.raises(BootstrapClaimError, match="^setup claim rejected$"):
        store.initialize(bootstrap_claim=BOOTSTRAP, admin_payload=_payload())
    assert kdf_calls == 2
    assert store.view().state == "uninitialized"

    clock.epoch += 61
    _initialize(store)
    assert kdf_calls == 4

    for username in ("missing-one", "missing-two"):
        with pytest.raises(AuthenticationError, match="^authentication failed$"):
            store.login(username=username, password="wrong password value")
    assert kdf_calls == 6
    with pytest.raises(AuthenticationError, match="^authentication failed$"):
        _login(store)
    assert kdf_calls == 6

    clock.epoch += 61
    assert _login(store).consume_bearer().startswith("vtt1_")
    assert kdf_calls == 7


def test_revocation_tail_deletion_and_head_rewind_cannot_reactivate_session(
    tmp_path: Path,
) -> None:
    database = tmp_path / "revocation-rewind.sqlite3"
    connection = sqlite3.connect(database)
    store = _new_store(connection)
    _initialize(store)
    issuance = _login(store)
    bearer = issuance.consume_bearer()
    store.revoke_session(bearer)
    assert store.view().revision == 3

    revision_two_hash = connection.execute(
        "SELECT entry_hash FROM _vtt_installation_events WHERE revision = 2"
    ).fetchone()[0]
    connection.execute("DELETE FROM _vtt_installation_events WHERE revision = 3")
    connection.execute(
        "UPDATE _vtt_installation_head SET revision = 2, head_hash = ? WHERE singleton = 1",
        (revision_two_hash,),
    )
    connection.commit()
    anchor_count_before = connection.execute(
        "SELECT COUNT(*) FROM _vtt_installation_anchors"
    ).fetchone()[0]
    connection.close()

    damaged_connection = sqlite3.connect(database)
    damaged = SQLiteInstallationStore(damaged_connection)

    assert damaged.view().state == "safe_mode"
    with pytest.raises(InstallationSafeModeError, match="read-only safe mode"):
        damaged.authenticate_session(bearer)
    assert (
        damaged_connection.execute("SELECT COUNT(*) FROM _vtt_installation_anchors").fetchone()[0]
        == anchor_count_before
    )
    assert damaged_connection.execute(
        "SELECT revision FROM _vtt_installation_head WHERE singleton = 1"
    ).fetchone() == (2,)


def test_password_change_tail_deletion_and_head_replacement_cannot_restore_password(
    tmp_path: Path,
) -> None:
    database = tmp_path / "password-rewind.sqlite3"
    connection = sqlite3.connect(database)
    store = _new_store(connection)
    _initialize(store)
    issuance = _login(store)
    bearer = issuance.consume_bearer()
    store.change_password(bearer, new_password="a new safer passphrase")
    assert store.view().revision == 3

    revision_two_hash = connection.execute(
        "SELECT entry_hash FROM _vtt_installation_events WHERE revision = 2"
    ).fetchone()[0]
    connection.execute("DELETE FROM _vtt_installation_events WHERE revision = 3")
    connection.execute("DELETE FROM _vtt_installation_head WHERE singleton = 1")
    connection.execute(
        "INSERT INTO _vtt_installation_head (singleton, revision, head_hash) VALUES (1, 2, ?)",
        (revision_two_hash,),
    )
    connection.commit()
    connection.close()

    damaged_connection = sqlite3.connect(database)
    damaged = SQLiteInstallationStore(damaged_connection)

    assert damaged.view().state == "safe_mode"
    with pytest.raises(InstallationSafeModeError, match="read-only safe mode"):
        damaged.login(username="keeper", password=PASSWORD)
    assert damaged_connection.execute(
        "SELECT MAX(revision) FROM _vtt_installation_anchors"
    ).fetchone() == (3,)


def test_monotonic_high_water_detects_coordinated_event_and_anchor_tail_deletion(
    tmp_path: Path,
) -> None:
    database = tmp_path / "high-water-rewind.sqlite3"
    connection = sqlite3.connect(database)
    store = _new_store(connection)
    _initialize(store)
    issuance = _login(store)
    bearer = issuance.consume_bearer()
    store.revoke_session(bearer)

    revision_two_hash = connection.execute(
        "SELECT entry_hash FROM _vtt_installation_events WHERE revision = 2"
    ).fetchone()[0]
    connection.execute("DELETE FROM _vtt_installation_events WHERE revision = 3")
    connection.execute("DELETE FROM _vtt_installation_anchors WHERE revision = 3")
    connection.execute(
        "UPDATE _vtt_installation_head SET revision = 2, head_hash = ? WHERE singleton = 1",
        (revision_two_hash,),
    )
    connection.commit()
    assert connection.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = '_vtt_installation_anchors'"
    ).fetchone() == (3,)
    connection.close()

    damaged = SQLiteInstallationStore(sqlite3.connect(database))
    assert damaged.view().state == "safe_mode"
    with pytest.raises(InstallationSafeModeError, match="read-only safe mode"):
        damaged.authenticate_session(bearer)


def test_tampered_scrypt_cost_is_rejected_before_any_attacker_selected_kdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "scrypt-cost-tamper.sqlite3"
    connection = sqlite3.connect(database)
    store = _new_store(connection)
    assert store.view().state == "uninitialized"
    connection.execute(
        """
        UPDATE _vtt_installation_metadata
        SET bootstrap_scrypt_json = ?
        WHERE singleton = 1
        """,
        ('{"dklen":32,"n":1073741824,"p":1,"r":8,' '"schema_version":"vtt.scrypt_parameters.v1"}',),
    )
    connection.commit()
    connection.close()

    kdf_calls = 0

    def forbidden_kdf(*args: object, **kwargs: object) -> bytes:
        nonlocal kdf_calls
        kdf_calls += 1
        raise AssertionError("tampered KDF parameters must not execute")

    monkeypatch.setattr(installation_store_module, "_derive_secret", forbidden_kdf)
    damaged_connection = sqlite3.connect(database)
    damaged = SQLiteInstallationStore(damaged_connection)

    assert damaged.view().state == "safe_mode"
    assert kdf_calls == 0
    assert (
        "1073741824"
        in damaged_connection.execute(
            "SELECT bootstrap_scrypt_json FROM _vtt_installation_metadata WHERE singleton = 1"
        ).fetchone()[0]
    )


def test_missing_mutable_head_or_anchor_tail_enters_safe_mode_without_repair(
    tmp_path: Path,
) -> None:
    for mutation, table_name in (
        ("head", "_vtt_installation_head"),
        ("anchor", "_vtt_installation_anchors"),
    ):
        database = tmp_path / f"missing-{mutation}.sqlite3"
        connection = sqlite3.connect(database)
        store = _new_store(connection)
        _initialize(store)
        if mutation == "head":
            connection.execute("DELETE FROM _vtt_installation_head")
        else:
            connection.execute("DELETE FROM _vtt_installation_anchors WHERE revision = 1")
        connection.commit()
        connection.close()

        damaged_connection = sqlite3.connect(database)
        damaged = SQLiteInstallationStore(damaged_connection)
        assert damaged.view().state == "safe_mode"
        assert damaged_connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone() == (0,)
        damaged_connection.close()


def test_event_or_head_tampering_enters_explicit_read_only_safe_mode(tmp_path: Path) -> None:
    database = tmp_path / "installation.sqlite3"
    connection = sqlite3.connect(database)
    store = _new_store(connection)
    _initialize(store)
    connection.execute(
        "UPDATE _vtt_installation_events SET event_json = ? WHERE revision = 1",
        ('{"tampered":true}',),
    )
    connection.commit()
    connection.close()

    damaged_connection = sqlite3.connect(database)
    damaged = SQLiteInstallationStore(damaged_connection)
    view = damaged.view()

    assert view.state == "safe_mode"
    assert view.integrity_status == "failed"
    assert view.setup_claimed is None
    assert view.active_admin_count is None
    with pytest.raises(InstallationSafeModeError, match="read-only safe mode"):
        damaged.login(username="keeper", password=PASSWORD)
    with pytest.raises(InstallationSafeModeError, match="read-only safe mode"):
        damaged.initialize(bootstrap_claim=BOOTSTRAP, admin_payload=_payload())
    assert damaged_connection.execute(
        "SELECT event_json FROM _vtt_installation_events WHERE revision = 1"
    ).fetchone() == ('{"tampered":true}',)


def test_partial_schema_is_not_reinitialized_and_enters_safe_mode() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE _vtt_installation_metadata (sentinel TEXT)")
    connection.execute("INSERT INTO _vtt_installation_metadata VALUES ('preserve-me')")
    connection.commit()

    store = SQLiteInstallationStore(connection)

    assert store.view().state == "safe_mode"
    assert connection.execute("SELECT sentinel FROM _vtt_installation_metadata").fetchone() == (
        "preserve-me",
    )
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert tables == {"_vtt_installation_metadata"}


def test_metadata_tampering_is_detected_by_genesis_hash(tmp_path: Path) -> None:
    database = tmp_path / "installation.sqlite3"
    connection = sqlite3.connect(database)
    store = _new_store(connection)
    assert store.view().state == "uninitialized"
    connection.execute(
        "UPDATE _vtt_installation_metadata SET bootstrap_verifier_hex = ? WHERE singleton = 1",
        ("0" * 64,),
    )
    connection.commit()
    connection.close()

    damaged = SQLiteInstallationStore(sqlite3.connect(database))
    assert damaged.view().state == "safe_mode"


def test_attempt_budget_is_bounded_and_resets_after_window() -> None:
    clock = FixedClock()
    store = _new_store(clock=clock)
    _initialize(store)

    for _ in range(5):
        with pytest.raises(AuthenticationError, match="^authentication failed$"):
            store.login(username="keeper", password="wrong password value")
    with pytest.raises(AuthenticationError, match="^authentication failed$"):
        store.login(username="keeper", password=PASSWORD)

    clock.epoch += 61
    assert _login(store).consume_bearer().startswith("vtt1_")


def test_constructor_rejects_bad_dependency_outputs_without_leaking_values() -> None:
    with pytest.raises(TypeError, match="clock"):
        SQLiteInstallationStore(
            sqlite3.connect(":memory:"),
            bootstrap_claim=BOOTSTRAP,
            clock=lambda: True,
            random_bytes=SequenceEntropy(),
        )

    with pytest.raises(EntropySourceError, match="entropy source"):
        SQLiteInstallationStore(
            sqlite3.connect(":memory:"),
            bootstrap_claim=BOOTSTRAP,
            clock=FixedClock(),
            random_bytes=lambda size: b"too-short",
        )
