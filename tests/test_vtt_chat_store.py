from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from dnd_sim.vtt.chat_contracts import (
    CHAT_COMMAND_SCHEMA_VERSION,
    CHAT_MESSAGE_SCHEMA_VERSION,
    ChatDeleteCommand,
    ChatMessage,
    ChatPostCommand,
    ChatPostedEvent,
    ChatResponse,
    parse_chat_command,
    parse_chat_command_json,
)
from dnd_sim.vtt.chat_store import (
    ChatCommandConflictError,
    ChatMessageConflictError,
    ChatMessageNotFoundError,
    ChatRevisionConflictError,
    ChatStoreCorruptionError,
    SQLiteChatLog,
)


def _message(
    message_id: str,
    *,
    author_id: str = "player-1",
    audience: tuple[str, ...] = ("all",),
    text: str = "Hello, table!",
) -> ChatMessage:
    return ChatMessage(
        schema_version=CHAT_MESSAGE_SCHEMA_VERSION,
        message_id=message_id,
        author_id=author_id,
        audience=audience,
        text=text,
    )


def _post(
    command_id: str,
    *,
    expected_revision: int,
    message: ChatMessage,
    table_id: str = "table-a",
) -> ChatPostCommand:
    return ChatPostCommand(
        schema_version=CHAT_COMMAND_SCHEMA_VERSION,
        table_id=table_id,
        command_id=command_id,
        expected_revision=expected_revision,
        message=message,
    )


def test_chat_contracts_are_strict_plain_text_and_have_no_clock_or_rendering_fields() -> None:
    message = _message(
        "message-1",
        text="<b>literal HTML</b> and **literal Markdown**\nsecond line",
    )
    command = _post("post-1", expected_revision=0, message=message)

    assert parse_chat_command(command.model_dump(mode="json")) == command
    assert parse_chat_command_json(command.model_dump_json()) == command
    assert message.model_dump(mode="json") == {
        "schema_version": CHAT_MESSAGE_SCHEMA_VERSION,
        "message_id": "message-1",
        "author_id": "player-1",
        "audience": ["all"],
        "text": "<b>literal HTML</b> and **literal Markdown**\nsecond line",
    }
    assert "timestamp" not in message.model_dump(mode="json")
    assert "html" not in message.model_dump(mode="json")

    with pytest.raises(ValidationError):
        ChatMessage(
            schema_version=CHAT_MESSAGE_SCHEMA_VERSION,
            message_id="blank",
            author_id="player-1",
            audience=("all",),
            text="   ",
        )
    with pytest.raises(ValidationError):
        ChatMessage(
            schema_version=CHAT_MESSAGE_SCHEMA_VERSION,
            message_id="too-long",
            author_id="player-1",
            audience=("all",),
            text="x" * 2_001,
        )
    with pytest.raises(ValidationError):
        ChatMessage(
            schema_version=CHAT_MESSAGE_SCHEMA_VERSION,
            message_id="control",
            author_id="player-1",
            audience=("all",),
            text="bad\x00text",
        )


@pytest.mark.parametrize("control", ("\x7f", "\x85"))
def test_chat_plain_text_rejects_del_and_c1_controls(control: str) -> None:
    with pytest.raises(ValidationError):
        _message("unsupported-control", text=f"bad{control}text")


def test_chat_event_and_response_contracts_enforce_transport_identity() -> None:
    event = ChatPostedEvent(
        table_id="table-a",
        event_id="table-a:chat:1",
        sequence=1,
        revision=1,
        command_id="post-1",
        message_id="message-1",
        message=_message("message-1"),
    )
    with pytest.raises(ValidationError):
        ChatPostedEvent.model_validate(
            {
                **event.model_dump(mode="json"),
                "revision": 2,
            }
        )

    valid = {
        "session_id": "session-a",
        "table_id": "table-a",
        "command_id": "post-1",
        "revision": 1,
        "replayed": False,
        "event": event.model_dump(mode="json"),
    }
    for field, mismatched in (
        ("table_id", "other-table"),
        ("command_id", "other-command"),
        ("revision", 2),
    ):
        with pytest.raises(ValidationError):
            ChatResponse.model_validate({**valid, field: mismatched})


def test_chat_log_posts_deletes_and_projects_in_durable_sequence_order() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        log = SQLiteChatLog(connection)
        first = log.execute(_post("post-b", expected_revision=0, message=_message("b")))
        second = log.execute(_post("post-a", expected_revision=1, message=_message("a")))
        deleted = log.execute(
            ChatDeleteCommand(
                table_id="table-a",
                command_id="delete-b",
                expected_revision=2,
                message_id="b",
            )
        )

        assert first.replayed is second.replayed is deleted.replayed is False
        assert [item.message_id for item in log.messages("table-a")] == ["a"]
        assert log.revision("table-a") == 3
        events = log.events_after("table-a", 0)
        assert [event.sequence for event in events] == [1, 2, 3]
        assert [event.revision for event in events] == [1, 2, 3]
        assert events[-1].author_id == "player-1"
        assert events[-1].audience == ("all",)
    finally:
        connection.close()


def test_chat_log_enforces_revision_identity_missing_and_exact_command_retries() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        log = SQLiteChatLog(connection)
        command = _post("post-once", expected_revision=0, message=_message("message-1"))
        first = log.execute(command)
        replay = log.execute(parse_chat_command(command.model_dump(mode="json")))
        assert replay.replayed is True
        assert replay.receipt == first.receipt

        with pytest.raises(ChatRevisionConflictError):
            log.execute(_post("stale", expected_revision=0, message=_message("stale")))
        with pytest.raises(ChatCommandConflictError):
            log.execute(_post("post-once", expected_revision=0, message=_message("different")))
        with pytest.raises(ChatMessageConflictError):
            log.execute(_post("duplicate-id", expected_revision=1, message=_message("message-1")))
        with pytest.raises(ChatMessageNotFoundError):
            log.execute(
                ChatDeleteCommand(
                    table_id="table-a",
                    command_id="missing",
                    expected_revision=1,
                    message_id="missing",
                )
            )
        assert log.revision("table-a") == 1
    finally:
        connection.close()


def test_chat_log_restarts_from_append_only_history(tmp_path: Path) -> None:
    database_path = tmp_path / "chat.sqlite3"
    first_connection = sqlite3.connect(database_path)
    first = SQLiteChatLog(first_connection)
    first.execute(
        _post(
            "private",
            expected_revision=0,
            message=_message(
                "private-message",
                audience=("participant:player-1",),
            ),
        )
    )
    first_connection.close()

    second_connection = sqlite3.connect(database_path)
    try:
        restored = SQLiteChatLog(second_connection)
        assert restored.revision("table-a") == 1
        assert restored.messages("table-a") == (
            _message(
                "private-message",
                audience=("participant:player-1",),
            ),
        )
    finally:
        second_connection.close()


def test_chat_log_rejects_corrupt_stored_command_contracts() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        log = SQLiteChatLog(connection)
        log.execute(_post("post-1", expected_revision=0, message=_message("message-1")))
        connection.execute(
            "UPDATE _vtt_chat_event_log SET command_json = ? WHERE command_id = ?",
            ("{}", "post-1"),
        )
        connection.commit()

        with pytest.raises(ChatStoreCorruptionError):
            log.snapshot("table-a")
    finally:
        connection.close()


def test_chat_log_rejects_historical_message_id_reuse_after_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = sqlite3.connect(":memory:")
    try:
        log = SQLiteChatLog(connection)
        log.execute(_post("post-1", expected_revision=0, message=_message("message-1")))
        log.execute(
            ChatDeleteCommand(
                table_id="table-a",
                command_id="delete-1",
                expected_revision=1,
                message_id="message-1",
            )
        )
        stored = log.events_after("table-a", 0)
        corrupt_repost = ChatPostedEvent(
            table_id="table-a",
            event_id="table-a:chat:3",
            sequence=3,
            revision=3,
            command_id="corrupt-repost",
            message_id="message-1",
            message=_message("message-1", text="reused after delete"),
        )
        monkeypatch.setattr(
            log,
            "_events_locked",
            lambda _table_id: (*stored, corrupt_repost),
        )

        with pytest.raises(ChatStoreCorruptionError):
            log.snapshot("table-a")
    finally:
        connection.close()
