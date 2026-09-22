from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from dnd_sim.vtt.world_catalog_contracts import (
    WORLD_CATALOG_COMMAND_SCHEMA_VERSION,
    WORLD_CATALOG_VIEW_SCHEMA_VERSION,
    WORLD_RECORD_SCHEMA_VERSION,
    WorldArchiveCommand,
    WorldCatalogEntry,
    WorldCatalogView,
    WorldCreateCommand,
    WorldRecord,
    WorldRenameCommand,
    parse_world_command_json,
)
from dnd_sim.vtt.world_catalog_store import (
    SQLiteWorldCatalog,
    WorldArchivedError,
    WorldCatalogCorruptionError,
    WorldCatalogStoreError,
    WorldCatalogStoreSchemaError,
    WorldCommandConflictError,
    WorldIdConflictError,
    WorldLimitError,
    WorldNameConflictError,
    WorldNameUnchangedError,
    WorldNotFoundError,
    WorldRevisionConflictError,
    WorldTableConflictError,
)


def _world(
    world_id: str,
    *,
    name: str | None = None,
    table_id: str | None = None,
) -> WorldRecord:
    return WorldRecord(
        world_id=world_id,
        name=name or world_id.replace("-", " ").title(),
        system_id="dnd5e",
        table_id=table_id or f"table-{world_id}",
    )


def _create(
    command_id: str,
    world: WorldRecord,
    *,
    expected_revision: int,
) -> WorldCreateCommand:
    return WorldCreateCommand(
        command_id=command_id,
        expected_revision=expected_revision,
        world=world,
    )


def test_world_contracts_are_strict_versioned_and_metadata_only() -> None:
    world = _world("echo-vault", name="Echo Vault", table_id="table-echo")

    assert world.model_dump(mode="json") == {
        "schema_version": WORLD_RECORD_SCHEMA_VERSION,
        "world_id": "echo-vault",
        "name": "Echo Vault",
        "system_id": "dnd5e",
        "table_id": "table-echo",
    }
    command = _create("create-echo", world, expected_revision=0)
    assert parse_world_command_json(command.model_dump_json()) == command

    for extra_field in (
        "access_token",
        "password",
        "credential",
        "actor_snapshots",
        "runtime_state",
        "session_snapshot",
    ):
        with pytest.raises(ValidationError):
            WorldRecord.model_validate(
                {**world.model_dump(mode="json"), extra_field: "must-not-persist"}
            )

    with pytest.raises(ValidationError):
        WorldRecord.model_validate({**world.model_dump(mode="json"), "system_id": "pathfinder2e"})
    with pytest.raises(ValidationError):
        WorldRecord.model_validate(
            {**world.model_dump(mode="json"), "schema_version": "vtt.world_record.v0"}
        )
    with pytest.raises(ValidationError):
        WorldCreateCommand.model_validate(
            {**command.model_dump(mode="json"), "schema_version": "vtt.world_command.v0"}
        )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("world_id", "../world"),
        ("world_id", " world"),
        ("name", ""),
        ("name", " Padded"),
        ("name", "line\nbreak"),
        ("name", "x" * 161),
        ("table_id", "table/one"),
        ("table_id", "token=secret"),
    ],
)
def test_world_record_rejects_unsafe_or_unbounded_identity_fields(
    field_name: str, invalid_value: object
) -> None:
    payload = _world("safe-world").model_dump(mode="json")
    payload[field_name] = invalid_value

    with pytest.raises(ValidationError):
        WorldRecord.model_validate(payload)


@pytest.mark.parametrize("surrogate", ["\ud800", "\udfff"])
def test_world_names_reject_non_scalar_unicode_surrogates(surrogate: str) -> None:
    with pytest.raises(ValidationError, match="unsupported Unicode scalar"):
        _world("unsafe", name=f"Unsafe {surrogate}")

    with pytest.raises(ValidationError, match="unsupported Unicode scalar"):
        WorldRenameCommand(
            command_id="rename-unsafe",
            expected_revision=0,
            world_id="safe",
            name=f"Unsafe {surrogate}",
        )


def test_catalog_view_is_deterministic_and_enforces_active_world_constraints() -> None:
    archived = WorldCatalogEntry(world=_world("archived"), archived=True)
    active = WorldCatalogEntry(world=_world("active"), archived=False)
    view = WorldCatalogView(
        schema_version=WORLD_CATALOG_VIEW_SCHEMA_VERSION,
        revision=2,
        worlds=(active, archived),
    )

    assert view.world("active") == active
    assert view.active_worlds == (active,)
    assert view.archived_worlds == (archived,)

    with pytest.raises(ValidationError, match="sorted"):
        WorldCatalogView(revision=2, worlds=(archived, active))
    with pytest.raises(ValidationError, match="names"):
        WorldCatalogView(
            revision=2,
            worlds=(
                WorldCatalogEntry(world=_world("one", name="Same")),
                WorldCatalogEntry(world=_world("two", name="same")),
            ),
        )
    with pytest.raises(ValidationError, match="table"):
        WorldCatalogView(
            revision=2,
            worlds=(
                WorldCatalogEntry(world=_world("one", table_id="shared-table")),
                WorldCatalogEntry(world=_world("two", table_id="shared-table")),
            ),
        )


def test_create_rename_and_archive_rebuild_a_catalog_projection() -> None:
    connection = sqlite3.connect(":memory:")
    catalog = SQLiteWorldCatalog(connection)

    created = catalog.execute(_create("create-one", _world("one"), expected_revision=0))
    catalog.execute(_create("create-two", _world("two"), expected_revision=1))
    renamed = catalog.execute(
        WorldRenameCommand(
            command_id="rename-two",
            expected_revision=2,
            world_id="two",
            name="Second World",
        )
    )
    archived = catalog.execute(
        WorldArchiveCommand(
            command_id="archive-one",
            expected_revision=3,
            world_id="one",
        )
    )

    assert created.replayed is False
    assert created.receipt.revision == 1
    assert renamed.receipt.event.old_name == "Two"
    assert renamed.receipt.event.new_name == "Second World"
    assert archived.receipt.event.world_id == "one"
    view = catalog.snapshot()
    assert view.revision == 4
    assert [entry.world.world_id for entry in view.worlds] == ["one", "two"]
    assert view.world("one") == WorldCatalogEntry(world=_world("one"), archived=True)
    assert view.world("two") == WorldCatalogEntry(
        world=_world("two").model_copy(update={"name": "Second World"}),
        archived=False,
    )


def test_command_retry_is_canonical_and_conflicting_reuse_is_rejected() -> None:
    connection = sqlite3.connect(":memory:")
    catalog = SQLiteWorldCatalog(connection)
    command = _create("create-one", _world("one"), expected_revision=0)

    original = catalog.execute(command)
    catalog.execute(_create("create-two", _world("two"), expected_revision=1))
    replayed = catalog.execute(
        WorldCreateCommand.model_validate(
            {
                "world": command.world.model_dump(mode="json"),
                "expected_revision": 0,
                "command_id": "create-one",
                "command_type": "create",
                "schema_version": WORLD_CATALOG_COMMAND_SCHEMA_VERSION,
            }
        )
    )

    assert replayed.replayed is True
    assert replayed.receipt == original.receipt
    assert catalog.snapshot().revision == 2

    with pytest.raises(WorldCommandConflictError, match="create-one"):
        catalog.execute(
            _create(
                "create-one",
                _world("different-world"),
                expected_revision=2,
            )
        )
    assert catalog.snapshot().revision == 2


def test_revision_conflict_and_domain_failures_do_not_mutate_the_catalog() -> None:
    connection = sqlite3.connect(":memory:")
    catalog = SQLiteWorldCatalog(connection)
    catalog.execute(_create("create-one", _world("one", name="One"), expected_revision=0))
    catalog.execute(_create("create-two", _world("two", name="Two"), expected_revision=1))

    with pytest.raises(WorldRevisionConflictError) as conflict:
        catalog.execute(
            WorldRenameCommand(
                command_id="stale",
                expected_revision=0,
                world_id="one",
                name="Stale",
            )
        )
    assert conflict.value.current_revision == 2
    assert conflict.value.expected_revision == 0

    invalid_commands = (
        (
            WorldRenameCommand(
                command_id="missing",
                expected_revision=2,
                world_id="missing",
                name="Missing",
            ),
            WorldNotFoundError,
        ),
        (
            _create("duplicate-id", _world("one", name="Elsewhere"), expected_revision=2),
            WorldIdConflictError,
        ),
        (
            _create("duplicate-name", _world("three", name="oNe"), expected_revision=2),
            WorldNameConflictError,
        ),
        (
            _create(
                "duplicate-table",
                _world("three", table_id="table-one"),
                expected_revision=2,
            ),
            WorldTableConflictError,
        ),
        (
            WorldRenameCommand(
                command_id="unchanged",
                expected_revision=2,
                world_id="one",
                name="One",
            ),
            WorldNameUnchangedError,
        ),
    )
    for command, expected_error in invalid_commands:
        with pytest.raises(expected_error):
            catalog.execute(command)
        assert catalog.snapshot().revision == 2


def test_active_world_names_use_unicode_normalized_casefold_uniqueness() -> None:
    connection = sqlite3.connect(":memory:")
    catalog = SQLiteWorldCatalog(connection)
    catalog.execute(
        _create(
            "create-one",
            _world("one", name="Caf\N{LATIN SMALL LETTER E WITH ACUTE}"),
            expected_revision=0,
        )
    )

    with pytest.raises(WorldNameConflictError):
        catalog.execute(
            _create(
                "create-two",
                _world("two", name="CAFE\N{COMBINING ACUTE ACCENT}"),
                expected_revision=1,
            )
        )


def test_archived_worlds_are_immutable_and_only_release_their_active_name_claim() -> None:
    connection = sqlite3.connect(":memory:")
    catalog = SQLiteWorldCatalog(connection)
    catalog.execute(_create("create-one", _world("one", name="One"), expected_revision=0))
    catalog.execute(
        WorldArchiveCommand(command_id="archive-one", expected_revision=1, world_id="one")
    )

    with pytest.raises(WorldArchivedError):
        catalog.execute(
            WorldRenameCommand(
                command_id="rename-archived",
                expected_revision=2,
                world_id="one",
                name="Renamed",
            )
        )
    with pytest.raises(WorldArchivedError):
        catalog.execute(
            WorldArchiveCommand(
                command_id="archive-again",
                expected_revision=2,
                world_id="one",
            )
        )

    catalog.execute(
        _create(
            "create-successor",
            _world("successor", name="One", table_id="table-successor"),
            expected_revision=2,
        )
    )
    assert catalog.snapshot().active_worlds[0].world.world_id == "successor"

    with pytest.raises(WorldTableConflictError):
        catalog.execute(
            _create(
                "reuse-archived-table",
                _world("unsafe", table_id="table-one"),
                expected_revision=3,
            )
        )


def test_active_and_total_world_counts_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dnd_sim.vtt.world_catalog_store as store_module

    connection = sqlite3.connect(":memory:")
    catalog = SQLiteWorldCatalog(connection)
    monkeypatch.setattr(store_module, "MAX_ACTIVE_WORLDS", 2)
    catalog.execute(_create("create-one", _world("one"), expected_revision=0))
    catalog.execute(_create("create-two", _world("two"), expected_revision=1))

    with pytest.raises(WorldLimitError, match="active"):
        catalog.execute(_create("create-three", _world("three"), expected_revision=2))
    assert catalog.snapshot().revision == 2

    catalog.execute(
        WorldArchiveCommand(command_id="archive-one", expected_revision=2, world_id="one")
    )
    catalog.execute(_create("create-three", _world("three"), expected_revision=3))
    assert catalog.snapshot().revision == 4

    monkeypatch.setattr(store_module, "MAX_WORLD_RECORDS", 3)
    with pytest.raises(WorldLimitError, match="total"):
        catalog.execute(_create("create-four", _world("four"), expected_revision=4))
    assert catalog.snapshot().revision == 4


def test_restart_recovers_identical_canonical_state(tmp_path: Path) -> None:
    database_path = tmp_path / "worlds.sqlite3"
    with sqlite3.connect(database_path) as connection:
        catalog = SQLiteWorldCatalog(connection)
        catalog.execute(_create("create-one", _world("one"), expected_revision=0))
        catalog.execute(
            WorldRenameCommand(
                command_id="rename-one",
                expected_revision=1,
                world_id="one",
                name="Recovered World",
            )
        )
        before_restart = catalog.snapshot()

    with sqlite3.connect(database_path) as connection:
        recovered = SQLiteWorldCatalog(connection)
        assert recovered.snapshot() == before_restart
        assert recovered.events_after(0) == tuple(
            result.event for result in recovered.receipts_after(0)
        )


def test_valid_unicode_world_name_persists_across_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "unicode-worlds.sqlite3"
    expected_world = _world("dragons-rest", name="Dragon’s Rest 🐉")

    with sqlite3.connect(database_path) as connection:
        catalog = SQLiteWorldCatalog(connection)
        catalog.execute(_create("create-dragons-rest", expected_world, expected_revision=0))

    with sqlite3.connect(database_path) as connection:
        recovered = SQLiteWorldCatalog(connection)
        assert recovered.snapshot().world("dragons-rest") == WorldCatalogEntry(
            world=expected_world,
            archived=False,
        )


def test_separate_connections_observe_optimistic_revision_conflicts(tmp_path: Path) -> None:
    database_path = tmp_path / "worlds.sqlite3"
    with (
        sqlite3.connect(database_path) as connection_one,
        sqlite3.connect(database_path) as connection_two,
    ):
        catalog_one = SQLiteWorldCatalog(connection_one)
        catalog_two = SQLiteWorldCatalog(connection_two)
        assert catalog_one.revision() == catalog_two.revision() == 0

        catalog_one.execute(_create("create-one", _world("one"), expected_revision=0))

        with pytest.raises(WorldRevisionConflictError) as conflict:
            catalog_two.execute(_create("create-two", _world("two"), expected_revision=0))
        assert conflict.value.current_revision == 1
        assert catalog_two.snapshot() == catalog_one.snapshot()


def test_head_update_failure_rolls_back_the_appended_event() -> None:
    connection = sqlite3.connect(":memory:")
    catalog = SQLiteWorldCatalog(connection)
    connection.execute("""
        CREATE TRIGGER reject_world_head_update
        BEFORE UPDATE ON _vtt_world_catalog_head
        BEGIN
            SELECT RAISE(ABORT, 'forced head failure');
        END
        """)
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="forced head failure"):
        catalog.execute(_create("create-one", _world("one"), expected_revision=0))

    assert catalog.snapshot().revision == 0
    assert connection.execute("SELECT COUNT(*) FROM _vtt_world_catalog_events").fetchone() == (0,)


@pytest.mark.parametrize(
    "tamper_sql",
    [
        "UPDATE _vtt_world_catalog_events SET command_json = command_json || ' '",
        "UPDATE _vtt_world_catalog_events SET receipt_json = receipt_json || ' '",
        "UPDATE _vtt_world_catalog_events SET previous_hash = printf('%064d', 1)",
        "UPDATE _vtt_world_catalog_events SET entry_hash = printf('%064d', 2)",
        "DELETE FROM _vtt_world_catalog_events WHERE revision = 1",
        "UPDATE _vtt_world_catalog_head SET head_hash = printf('%064d', 3)",
    ],
)
def test_catalog_detects_modified_or_truncated_history(tamper_sql: str) -> None:
    connection = sqlite3.connect(":memory:")
    catalog = SQLiteWorldCatalog(connection)
    catalog.execute(_create("create-one", _world("one"), expected_revision=0))
    connection.execute(tamper_sql)
    connection.commit()

    with pytest.raises(WorldCatalogCorruptionError):
        catalog.snapshot()


def test_transaction_api_commits_together_rolls_back_together_and_cannot_nest() -> None:
    connection = sqlite3.connect(":memory:")
    catalog = SQLiteWorldCatalog(connection)

    with catalog.transaction() as transaction:
        transaction.execute(_create("create-one", _world("one"), expected_revision=0))
        transaction.execute(_create("create-two", _world("two"), expected_revision=1))
        assert transaction.snapshot().revision == 2
        assert not hasattr(transaction, "connection")
        with pytest.raises(WorldCatalogStoreError, match="active transaction"):
            catalog.execute(_create("nested", _world("nested"), expected_revision=2))

    assert catalog.snapshot().revision == 2

    with pytest.raises(RuntimeError, match="force rollback"):
        with catalog.transaction() as transaction:
            transaction.execute(
                WorldArchiveCommand(
                    command_id="archive-one",
                    expected_revision=2,
                    world_id="one",
                )
            )
            raise RuntimeError("force rollback")

    assert catalog.snapshot().revision == 2
    with pytest.raises(WorldCatalogStoreError, match="closed"):
        transaction.snapshot()


@pytest.mark.parametrize("interrupt_type", [KeyboardInterrupt, SystemExit])
def test_base_exception_rolls_back_and_releases_transaction(
    interrupt_type: type[BaseException],
) -> None:
    connection = sqlite3.connect(":memory:")
    catalog = SQLiteWorldCatalog(connection)

    with pytest.raises(interrupt_type):
        with catalog.transaction() as transaction:
            transaction.execute(_create("interrupted", _world("interrupted"), expected_revision=0))
            raise interrupt_type()

    assert connection.in_transaction is False
    assert catalog.snapshot().revision == 0
    catalog.execute(_create("recovered", _world("recovered"), expected_revision=0))
    assert catalog.snapshot().revision == 1


def test_base_exception_during_public_read_releases_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = sqlite3.connect(":memory:")
    catalog = SQLiteWorldCatalog(connection)

    def interrupt_read() -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr(catalog, "_read_history_locked", interrupt_read)
    with pytest.raises(KeyboardInterrupt):
        catalog.snapshot()
    assert connection.in_transaction is False


def test_base_exception_during_initialization_releases_transaction() -> None:
    class InterruptingCatalog(SQLiteWorldCatalog):
        def _read_history_locked(self) -> object:
            raise KeyboardInterrupt

    connection = sqlite3.connect(":memory:")
    with pytest.raises(KeyboardInterrupt):
        InterruptingCatalog(connection)

    assert connection.in_transaction is False
    assert SQLiteWorldCatalog(connection).snapshot().revision == 0


def test_unknown_store_schema_and_noncanonical_rows_fail_closed() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("""
        CREATE TABLE _vtt_world_catalog_metadata (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            schema_version TEXT NOT NULL
        )
        """)
    connection.execute(
        "INSERT INTO _vtt_world_catalog_metadata (singleton, schema_version) VALUES (1, ?)",
        ("vtt.world_catalog_store.v999",),
    )
    connection.commit()

    with pytest.raises(WorldCatalogStoreSchemaError):
        SQLiteWorldCatalog(connection)


def test_restart_fails_closed_when_catalog_metadata_was_removed(tmp_path: Path) -> None:
    database_path = tmp_path / "worlds.sqlite3"
    with sqlite3.connect(database_path) as connection:
        catalog = SQLiteWorldCatalog(connection)
        catalog.execute(_create("create-one", _world("one"), expected_revision=0))
        connection.execute("DELETE FROM _vtt_world_catalog_metadata")
        connection.commit()

    with sqlite3.connect(database_path) as connection:
        with pytest.raises(WorldCatalogCorruptionError, match="metadata"):
            SQLiteWorldCatalog(connection)


def test_store_refuses_initialization_or_public_calls_inside_foreign_transactions() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("BEGIN")
    with pytest.raises(WorldCatalogStoreError, match="active transaction"):
        SQLiteWorldCatalog(connection)
    connection.rollback()

    catalog = SQLiteWorldCatalog(connection)
    connection.execute("BEGIN")
    with pytest.raises(WorldCatalogStoreError, match="active transaction"):
        catalog.snapshot()
    connection.rollback()
