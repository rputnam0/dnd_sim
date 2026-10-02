"""Durable, single-use participant invitations with no stored bearer secrets."""

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from pydantic import ValidationError

from dnd_sim.vtt.world_invitation_store import (
    INVITATION_TTL_SECONDS,
    InvitationAuthenticationError,
    InvitationCommandConflictError,
    InvitationIssueCommand,
    InvitationJoinCommand,
    InvitationLimitError,
    InvitationNotFoundError,
    SQLiteWorldInvitationStore,
    WorldInvitationCorruptionError,
    WorldInvitationSchemaError,
)


@pytest.fixture
def access_store():
    connection = sqlite3.connect(":memory:")
    now = [1_000]
    store = SQLiteWorldInvitationStore(connection, clock=lambda: now[0])
    yield store, connection, now
    connection.close()


def issue(store, command="create-1", role="player", world="world-1", table="table-1"):
    return store.issue(world, table, command, role)


def token(result):
    assert result.invitation_token is not None
    return result.invitation_token.get_secret_value()


def test_issue_stores_only_hash_and_replay_never_recovers_secret(access_store):
    store, connection, now = access_store
    issued = issue(store)
    plaintext = token(issued)
    public = issued.invitation
    assert public.status == "pending"
    assert public.created_at == now[0]
    assert public.expires_at == now[0] + INVITATION_TTL_SECONDS
    assert public.participant is None
    assert plaintext not in repr(issued)
    assert plaintext not in public.model_dump_json()
    dump = "\n".join(connection.iterdump())
    assert plaintext not in dump
    assert hashlib.sha256(plaintext.encode("ascii")).hexdigest() in dump
    replay = issue(store)
    assert replay.invitation == public
    assert replay.replayed
    assert replay.invitation_token is None
    with pytest.raises(InvitationCommandConflictError):
        issue(store, role="spectator")
    assert store.list("world-1", "table-1") == (public,)


def test_authentication_is_non_consuming_and_redemption_is_single_use(access_store):
    store, _, _ = access_store
    issued = issue(store, role="spectator")
    plaintext = token(issued)
    for _ in range(2):
        binding = store.authenticate_invitation(plaintext)
        assert (binding.world_id, binding.table_id) == ("world-1", "table-1")
        assert binding.invitation == issued.invitation
        assert binding.participant is None
    redeemed = store.redeem(plaintext, "River")
    assert redeemed.invitation.status == "redeemed"
    assert redeemed.participant.display_name == "River"
    assert redeemed.participant.role == "spectator"
    assert redeemed.participant.owned_actor_ids == ()
    assert (
        store.authenticate_participant("world-1", "table-1", redeemed.participant.participant_id)
        == redeemed.participant
    )
    with pytest.raises(InvitationAuthenticationError):
        store.redeem(plaintext, "Another person")
    with pytest.raises(InvitationAuthenticationError):
        store.authenticate_invitation(plaintext)
    assert issue(store, role="spectator").invitation_token is None


def test_revoke_is_idempotent_and_revokes_linked_participant(access_store):
    store, _, _ = access_store
    issued = issue(store)
    redeemed = store.redeem(token(issued), "River")
    for _ in range(2):
        store.revoke("world-1", "table-1", issued.invitation.invitation_id)
    revoked = store.list("world-1", "table-1")[0]
    assert revoked.status == "revoked"
    assert revoked.participant == redeemed.participant
    with pytest.raises(InvitationAuthenticationError):
        store.authenticate_participant("world-1", "table-1", redeemed.participant.participant_id)
    pending = issue(store, "create-2")
    store.revoke("world-1", "table-1", pending.invitation.invitation_id)
    with pytest.raises(InvitationAuthenticationError):
        store.authenticate_invitation(token(pending))


def test_expiration_is_exact_and_does_not_expire_redeemed_identity(access_store):
    store, _, now = access_store
    pending = issue(store)
    joined = issue(store, "create-2")
    redeemed = store.redeem(token(joined), "River")
    now[0] = pending.invitation.expires_at - 1
    store.authenticate_invitation(token(pending))
    now[0] += 1
    with pytest.raises(InvitationAuthenticationError):
        store.authenticate_invitation(token(pending))
    assert {entry.status for entry in store.list("world-1", "table-1")} == {
        "expired",
        "redeemed",
    }
    assert store.authenticate_participant("world-1", "table-1", redeemed.participant.participant_id)


def test_world_and_table_are_exact_authority_boundaries(access_store):
    store, _, _ = access_store
    issued = issue(store)
    redeemed = store.redeem(token(issued), "River")
    assert store.list("world-2", "table-1") == ()
    assert store.list("world-1", "table-2") == ()
    for world, table in (("world-2", "table-1"), ("world-1", "table-2")):
        with pytest.raises(InvitationNotFoundError):
            store.revoke(world, table, issued.invitation.invitation_id)
        with pytest.raises(InvitationAuthenticationError):
            store.authenticate_participant(world, table, redeemed.participant.participant_id)
    with pytest.raises(InvitationCommandConflictError):
        issue(store, world="world-2")


def test_pending_and_redeemed_capacity_is_bounded_per_world(access_store):
    store, _, now = access_store
    records = [issue(store, f"create-{index}") for index in range(10)]
    store.redeem(token(records[0]), "River")
    with pytest.raises(InvitationLimitError):
        issue(store, "overflow")
    other = issue(store, "other-world", world="world-2", table="table-2")
    assert other.invitation.status == "pending"
    store.revoke("world-1", "table-1", records[0].invitation.invitation_id)
    issue(store, "replacement")
    now[0] += INVITATION_TTL_SECONDS
    issue(store, "after-expiry")


def test_historical_capacity_is_bounded_without_dropping_receipts(access_store, monkeypatch):
    import dnd_sim.vtt.world_invitation_store as module

    monkeypatch.setattr(module, "MAX_WORLD_INVITATIONS", 3)
    store, _, _ = access_store
    for index in range(3):
        record = issue(store, f"create-{index}")
        store.revoke("world-1", "table-1", record.invitation.invitation_id)
    with pytest.raises(InvitationLimitError):
        issue(store, "overflow")
    assert issue(store, "create-0").replayed
    assert len(store.list("world-1", "table-1")) == 3


def test_invitation_and_identity_survive_reopen_without_reissuing_secret(tmp_path):
    path = tmp_path / "installation.sqlite3"
    connection = sqlite3.connect(path)
    store = SQLiteWorldInvitationStore(connection, clock=lambda: 1_000)
    pending = issue(store)
    joined = issue(store, "create-2")
    redeemed = store.redeem(token(joined), "River")
    connection.close()
    connection = sqlite3.connect(path)
    store = SQLiteWorldInvitationStore(connection, clock=lambda: 1_001)
    assert store.authenticate_invitation(token(pending)).invitation == pending.invitation
    assert issue(store).invitation_token is None
    assert (
        store.authenticate_participant("world-1", "table-1", redeemed.participant.participant_id)
        == redeemed.participant
    )
    connection.close()


@pytest.mark.parametrize(
    "value", ["", " River", "River ", "x" * 81, "a\nname", "\ud800", "Ｒiver", 7]
)
def test_display_names_are_strict_bounded_canonical_scalar_text(access_store, value):
    store, _, _ = access_store
    invitation = issue(store)
    with pytest.raises((ValueError, ValidationError)):
        InvitationJoinCommand(display_name=value)
    with pytest.raises((ValueError, ValidationError)):
        store.redeem(token(invitation), value)
    assert store.authenticate_invitation(token(invitation))


@pytest.mark.parametrize("value", ["", "a b", "../bad", "x" * 129, "\ud800", 7])
def test_command_ids_are_bounded_url_safe_text(value):
    with pytest.raises((ValueError, ValidationError)):
        InvitationIssueCommand(command_id=value, role="player")


def test_invalid_invitation_precedes_invalid_payload(access_store):
    store, _, _ = access_store
    with pytest.raises(InvitationAuthenticationError, match="authentication failed"):
        store.redeem("invalid", "\ud800")


@pytest.mark.parametrize("token_value", [None, 7, "", "a" * 44, "\ud800", "secret with spaces"])
def test_invalid_tokens_have_safe_generic_failures(access_store, token_value):
    store, _, _ = access_store
    with pytest.raises(InvitationAuthenticationError, match="authentication failed"):
        store.authenticate_invitation(token_value)


def test_incomplete_schema_is_not_reinitialized(access_store):
    _, connection, _ = access_store
    connection.execute("DROP TABLE _vtt_world_invitations")
    connection.commit()
    with pytest.raises(WorldInvitationSchemaError):
        SQLiteWorldInvitationStore(connection)
    assert (
        connection.execute(
            "SELECT name FROM sqlite_master WHERE name = '_vtt_world_invitations'"
        ).fetchone()
        is None
    )


def test_missing_metadata_and_bad_records_fail_closed(access_store):
    store, connection, _ = access_store
    issue(store)
    connection.execute("UPDATE _vtt_world_invitations SET role = 'gm'")
    connection.commit()
    with pytest.raises(WorldInvitationCorruptionError):
        store.list("world-1", "table-1")
    assert not connection.in_transaction
    connection.execute("DELETE FROM _vtt_world_invitation_metadata")
    connection.commit()
    with pytest.raises(WorldInvitationCorruptionError):
        SQLiteWorldInvitationStore(connection)
    assert not connection.in_transaction


def test_removed_record_is_detected_without_resetting_metadata(access_store):
    store, connection, _ = access_store
    issue(store)
    connection.execute("DELETE FROM _vtt_world_invitations")
    connection.commit()
    with pytest.raises(WorldInvitationCorruptionError):
        store.list("world-1", "table-1")


def test_write_rolls_back_on_base_exception(access_store, monkeypatch):
    store, connection, _ = access_store
    original = store._read_records_locked
    calls = 0

    def interrupt_after_mutation():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        return original()

    monkeypatch.setattr(store, "_read_records_locked", interrupt_after_mutation)
    with pytest.raises(KeyboardInterrupt):
        issue(store)
    assert not connection.in_transaction
    monkeypatch.setattr(store, "_read_records_locked", original)
    assert store.list("world-1", "table-1") == ()


def test_redemption_rolls_back_identity_and_consumption_together(access_store, monkeypatch):
    store, connection, _ = access_store
    issued = issue(store)
    original = store._read_records_locked
    calls = 0

    def interrupt_after_mutation():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        return original()

    monkeypatch.setattr(store, "_read_records_locked", interrupt_after_mutation)
    with pytest.raises(KeyboardInterrupt):
        store.redeem(token(issued), "River")
    assert not connection.in_transaction
    monkeypatch.setattr(store, "_read_records_locked", original)
    assert store.list("world-1", "table-1") == (issued.invitation,)
    assert store.redeem(token(issued), "River").participant.display_name == "River"


def test_concurrent_connections_cannot_redeem_the_same_invitation_twice(tmp_path):
    path = tmp_path / "installation.sqlite3"
    connection = sqlite3.connect(path)
    store = SQLiteWorldInvitationStore(connection, clock=lambda: 1_000)
    issued = issue(store)
    connection.close()
    ready = Barrier(2)

    def join(name):
        database = sqlite3.connect(path)
        access = SQLiteWorldInvitationStore(database, clock=lambda: 1_001)
        ready.wait(timeout=5)
        try:
            return access.redeem(token(issued), name).participant.display_name
        except InvitationAuthenticationError:
            return "rejected"
        finally:
            database.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(join, ("River", "Brook")))
    assert outcomes.count("rejected") == 1
    connection = sqlite3.connect(path)
    store = SQLiteWorldInvitationStore(connection, clock=lambda: 1_002)
    assert len(store.list("world-1", "table-1")) == 1
    assert store.list("world-1", "table-1")[0].status == "redeemed"
    connection.close()


def test_store_extension_leaves_existing_world_catalog_intact(access_store):
    from dnd_sim.vtt.world_catalog_contracts import WorldCreateCommand, WorldRecord
    from dnd_sim.vtt.world_catalog_store import SQLiteWorldCatalog

    store, connection, _ = access_store
    catalog = SQLiteWorldCatalog(connection)
    catalog.execute(
        WorldCreateCommand(
            command_id="world-create",
            expected_revision=0,
            world=WorldRecord(world_id="world-1", table_id="table-1", name="Original world"),
        )
    )
    before = catalog.snapshot()
    issued = issue(store)
    store.redeem(token(issued), "River")
    store.revoke("world-1", "table-1", issued.invitation.invitation_id)
    assert catalog.snapshot() == before
    assert SQLiteWorldCatalog(connection).snapshot() == before


@pytest.mark.parametrize("value", [True, -1, 1.5, "1000", 1 << 63])
def test_clock_is_strict_and_failed_clock_does_not_leave_transaction(access_store, value):
    store, connection, now = access_store
    now[0] = value
    with pytest.raises(TypeError):
        issue(store)
    assert not connection.in_transaction


def test_unknown_schema_is_preserved_and_refused(access_store):
    store, connection, _ = access_store
    issued = issue(store)
    connection.execute(
        "UPDATE _vtt_world_invitation_metadata SET schema_version = 'future-version'"
    )
    connection.commit()
    with pytest.raises(WorldInvitationSchemaError):
        SQLiteWorldInvitationStore(connection)
    assert (
        connection.execute("SELECT invitation_id FROM _vtt_world_invitations").fetchone()[0]
        == issued.invitation.invitation_id
    )


@pytest.mark.parametrize("role", ["gm", "Player", "", 7, None])
def test_only_player_and_spectator_roles_are_issuable(access_store, role):
    store, _, _ = access_store
    with pytest.raises(ValidationError):
        issue(store, role=role)
    assert store.list("world-1", "table-1") == ()
