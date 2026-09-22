from __future__ import annotations

import json
import sqlite3

import pytest
from pydantic import ValidationError

from dnd_sim.vtt import journal_store
from dnd_sim.vtt.journal_contracts import (
    JournalDeleteDocumentCommand,
    JournalDeleteFolderCommand,
    JournalDocument,
    JournalFolder,
    JournalPutDocumentCommand,
    JournalPutFolderCommand,
    JournalTextBlock,
    JournalView,
    MapPin,
    parse_journal_command_json,
)
from dnd_sim.vtt.journal_store import (
    JournalCommandConflictError,
    JournalCapacityError,
    JournalDocumentLinkError,
    JournalFolderCycleError,
    JournalStoreCorruptionError,
    JournalFolderNotEmptyError,
    JournalLinkedDocumentError,
    JournalRevisionConflictError,
    SQLiteJournalStore,
)


def _folder(folder_id: str, parent: str | None = None) -> JournalFolder:
    return JournalFolder(folder_id=folder_id, parent_folder_id=parent, name=folder_id.title())


def _document(
    document_id: str,
    *,
    folder_id: str | None = None,
    audience: tuple[str, ...] = ("all",),
    links: tuple[str, ...] = (),
) -> JournalDocument:
    blocks = [JournalTextBlock(block_type="paragraph", text=f"Secrets of {document_id}")]
    blocks.extend(
        {
            "schema_version": "vtt.journal_block.v1",
            "block_type": "document_link",
            "document_id": target,
            "label": f"Read {target}",
        }
        for target in links
    )
    return JournalDocument(
        document_id=document_id,
        document_type="handout",
        folder_id=folder_id,
        title=document_id.title(),
        audience=audience,
        tags=("lore",),
        favorite=False,
        blocks=tuple(blocks),
        map_pin=MapPin(
            scene_id="echo-vault",
            position={"x_ft": 5.0, "y_ft": 5.0, "z_ft": 0.0},
            color="#5eead4",
        ),
    )


def test_journal_contracts_are_strict_bounded_and_plain_text_only() -> None:
    document = _document("vault-key")
    assert (
        parse_journal_command_json(
            JournalPutDocumentCommand(
                table_id="table-a",
                command_id="put-doc",
                expected_revision=0,
                document=document,
            ).model_dump_json()
        ).document
        == document
    )
    with pytest.raises(ValidationError, match="control"):
        JournalTextBlock(block_type="paragraph", text="bad\x00payload")
    with pytest.raises(ValidationError, match="sorted"):
        document.model_copy(update={"tags": ("zeta", "alpha")}).model_validate(
            {**document.model_dump(mode="json"), "tags": ["zeta", "alpha"]}
        )
    with pytest.raises(ValidationError, match="self"):
        JournalDocument.model_validate(
            {
                **document.model_dump(mode="json"),
                "blocks": [
                    {
                        "schema_version": "vtt.journal_block.v1",
                        "block_type": "document_link",
                        "document_id": document.document_id,
                        "label": "Self",
                    }
                ],
            }
        )
    with pytest.raises(ValidationError, match="128"):
        JournalDocument.model_validate(
            {
                **document.model_dump(mode="json"),
                "audience": [f"participant:{'x' * 129}"],
            }
        )
    with pytest.raises(ValidationError, match="must not contain"):
        JournalDocument.model_validate(
            {
                **document.model_dump(mode="json"),
                "audience": ["participant:a:b"],
            }
        )
    with pytest.raises(ValidationError, match="ordered"):
        JournalView(
            session_id="session-a",
            table_id="table-a",
            revision=0,
            documents=(_document("zeta"), _document("alpha")),
        )


def test_journal_audience_ids_share_the_codepoint_bound_and_colon_rule() -> None:
    document = _document("shared-fixture")
    exact_codepoint_bound = "🐉" * 128

    for selector_kind in ("participant", "actor"):
        selector = f"{selector_kind}:{exact_codepoint_bound}"
        parsed = JournalDocument.model_validate(
            {**document.model_dump(mode="json"), "audience": [selector]}
        )
        assert parsed.audience == (selector,)

        with pytest.raises(ValidationError, match="must not contain"):
            JournalDocument.model_validate(
                {
                    **document.model_dump(mode="json"),
                    "audience": [f"{selector_kind}:a:b"],
                }
            )


def test_journal_store_restarts_replays_searches_and_guards_references(tmp_path) -> None:
    path = tmp_path / "journal.sqlite3"
    connection = sqlite3.connect(path)
    store = SQLiteJournalStore(connection)
    commands = (
        JournalPutFolderCommand(
            table_id="table-a",
            command_id="put-root",
            expected_revision=0,
            folder=_folder("lore"),
        ),
        JournalPutDocumentCommand(
            table_id="table-a",
            command_id="put-target",
            expected_revision=1,
            document=_document("target", folder_id="lore"),
        ),
        JournalPutDocumentCommand(
            table_id="table-a",
            command_id="put-source",
            expected_revision=2,
            document=_document("source", folder_id="lore", links=("target",)),
        ),
    )
    for command in commands:
        store.execute(command)
    assert store.execute(commands[-1]).replayed is True
    with pytest.raises(JournalCommandConflictError):
        store.execute(commands[-1].model_copy(update={"document": _document("different")}))
    with pytest.raises(JournalRevisionConflictError):
        store.execute(
            JournalPutFolderCommand(
                table_id="table-a",
                command_id="stale",
                expected_revision=0,
                folder=_folder("stale"),
            )
        )
    with pytest.raises(JournalLinkedDocumentError):
        store.execute(
            JournalDeleteDocumentCommand(
                table_id="table-a",
                command_id="delete-target",
                expected_revision=3,
                document_id="target",
            )
        )
    with pytest.raises(JournalFolderNotEmptyError):
        store.execute(
            JournalDeleteFolderCommand(
                table_id="table-a",
                command_id="delete-folder",
                expected_revision=3,
                folder_id="lore",
            )
        )
    assert [item.document_id for item in store.search("table-a", "secrets source")] == ["source"]
    connection.close()

    reopened_connection = sqlite3.connect(path)
    reopened = SQLiteJournalStore(reopened_connection)
    snapshot = reopened.snapshot("table-a")
    assert snapshot.revision == 3
    assert [item.folder_id for item in snapshot.folders] == ["lore"]
    assert [item.document_id for item in snapshot.documents] == ["source", "target"]
    reopened_connection.close()


def test_journal_store_rejects_broken_links_deep_folders_and_capacity_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = sqlite3.connect(":memory:")
    store = SQLiteJournalStore(connection)
    with pytest.raises(JournalDocumentLinkError):
        store.execute(
            JournalPutDocumentCommand(
                table_id="table-a",
                command_id="broken",
                expected_revision=0,
                document=_document("source", links=("missing",)),
            )
        )
    assert store.revision("table-a") == 0

    monkeypatch.setattr(journal_store, "MAX_JOURNAL_FOLDER_DEPTH", 2)
    store.execute(
        JournalPutFolderCommand(
            table_id="table-a",
            command_id="root",
            expected_revision=0,
            folder=_folder("root"),
        )
    )
    store.execute(
        JournalPutFolderCommand(
            table_id="table-a",
            command_id="child",
            expected_revision=1,
            folder=_folder("child", "root"),
        )
    )
    with pytest.raises(JournalFolderCycleError):
        store.execute(
            JournalPutFolderCommand(
                table_id="table-a",
                command_id="too-deep",
                expected_revision=2,
                folder=_folder("grandchild", "child"),
            )
        )
    assert store.revision("table-a") == 2

    monkeypatch.setattr(journal_store, "MAX_JOURNAL_FOLDERS", 2)
    with pytest.raises(JournalCapacityError):
        store.execute(
            JournalPutFolderCommand(
                table_id="table-a",
                command_id="over-capacity",
                expected_revision=2,
                folder=_folder("third"),
            )
        )
    assert store.revision("table-a") == 2
    connection.close()


def test_journal_store_detects_tampered_command_and_receipt_rows() -> None:
    for field in ("command_json", "receipt_json"):
        connection = sqlite3.connect(":memory:")
        store = SQLiteJournalStore(connection)
        store.execute(
            JournalPutFolderCommand(
                table_id="table-a",
                command_id="root",
                expected_revision=0,
                folder=_folder("root"),
            )
        )
        connection.execute(
            f"UPDATE _vtt_journal_event_log SET {field} = ? WHERE table_id = ?",
            ('{"tampered":true}', "table-a"),
        )
        connection.commit()
        with pytest.raises(JournalStoreCorruptionError):
            store.snapshot("table-a")
        connection.close()


def test_journal_store_rejects_canonical_command_that_does_not_match_its_receipt() -> None:
    connection = sqlite3.connect(":memory:")
    store = SQLiteJournalStore(connection)
    original = JournalPutFolderCommand(
        table_id="table-a",
        command_id="root",
        expected_revision=0,
        folder=_folder("root"),
    )
    store.execute(original)
    forged = original.model_copy(update={"folder": _folder("forged")})
    forged_json = json.dumps(
        forged.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    connection.execute(
        "UPDATE _vtt_journal_event_log SET command_json = ? WHERE table_id = ?",
        (forged_json, "table-a"),
    )
    connection.commit()

    with pytest.raises(JournalStoreCorruptionError):
        store.snapshot("table-a")
    with pytest.raises(JournalStoreCorruptionError):
        store.execute(forged)
    connection.close()


def test_journal_store_rejects_forged_delete_tombstone_on_reconnect() -> None:
    connection = sqlite3.connect(":memory:")
    store = SQLiteJournalStore(connection)
    document = _document("target")
    store.execute(
        JournalPutDocumentCommand(
            table_id="table-a",
            command_id="put-target",
            expected_revision=0,
            document=document,
        )
    )
    store.execute(
        JournalDeleteDocumentCommand(
            table_id="table-a",
            command_id="delete-target",
            expected_revision=1,
            document_id="target",
        )
    )
    row = connection.execute(
        "SELECT receipt_json FROM _vtt_journal_event_log WHERE table_id = ? AND revision = 2",
        ("table-a",),
    ).fetchone()
    assert row is not None
    receipt = json.loads(str(row[0]))
    receipt["event"]["document"]["title"] = "Forged"
    receipt["event"]["document"]["blocks"] = [
        {
            "schema_version": "vtt.journal_block.v1",
            "block_type": "paragraph",
            "text": "Forged body",
        }
    ]
    connection.execute(
        "UPDATE _vtt_journal_event_log SET receipt_json = ? WHERE table_id = ? AND revision = 2",
        (
            json.dumps(
                receipt,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            "table-a",
        ),
    )
    connection.commit()

    with pytest.raises(JournalStoreCorruptionError, match="tombstone"):
        store.events_after("table-a", 1)
    with pytest.raises(JournalStoreCorruptionError, match="tombstone"):
        store.snapshot("table-a")
    connection.close()


def test_journal_store_rejects_forged_folder_tombstone_on_reconnect() -> None:
    connection = sqlite3.connect(":memory:")
    store = SQLiteJournalStore(connection)
    folder = _folder("lore")
    store.execute(
        JournalPutFolderCommand(
            table_id="table-a",
            command_id="put-folder",
            expected_revision=0,
            folder=folder,
        )
    )
    store.execute(
        JournalDeleteFolderCommand(
            table_id="table-a",
            command_id="delete-folder",
            expected_revision=1,
            folder_id="lore",
        )
    )
    row = connection.execute(
        "SELECT receipt_json FROM _vtt_journal_event_log WHERE table_id = ? AND revision = 2",
        ("table-a",),
    ).fetchone()
    assert row is not None
    receipt = json.loads(str(row[0]))
    receipt["event"]["folder"]["name"] = "Forged"
    connection.execute(
        "UPDATE _vtt_journal_event_log SET receipt_json = ? WHERE table_id = ? AND revision = 2",
        (
            json.dumps(
                receipt,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            "table-a",
        ),
    )
    connection.commit()

    with pytest.raises(JournalStoreCorruptionError, match="tombstone"):
        store.events_after("table-a", 1)
    with pytest.raises(JournalStoreCorruptionError, match="tombstone"):
        store.snapshot("table-a")
    connection.close()
