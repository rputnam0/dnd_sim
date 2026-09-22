"""Strict renderer-neutral contracts for durable plain-text VTT chat."""

from __future__ import annotations

import unicodedata
from typing import Annotated, Any, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from .participants import validate_audience_selectors

CHAT_MESSAGE_SCHEMA_VERSION = "vtt.chat_message.v1"
CHAT_COMMAND_SCHEMA_VERSION = "vtt.chat_command.v1"
CHAT_EVENT_SCHEMA_VERSION = "vtt.chat_event.v1"
CHAT_RECEIPT_SCHEMA_VERSION = "vtt.chat_receipt.v1"
CHAT_VIEW_SCHEMA_VERSION = "vtt.chat_view.v1"
CHAT_REQUEST_SCHEMA_VERSION = "vtt.chat_request.v1"
CHAT_RESPONSE_SCHEMA_VERSION = "vtt.chat_response.v1"
MAX_CHAT_TEXT_LENGTH = 2_000

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]


class _StrictChatModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _canonical_text(value: str, *, field_name: str, maximum_length: int = 128) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    if len(value) > maximum_length:
        raise ValueError(f"{field_name} must be at most {maximum_length} characters")
    return value


class ChatMessage(_StrictChatModel):
    """One plain-text message with no rendering or wall-clock semantics."""

    schema_version: Literal[CHAT_MESSAGE_SCHEMA_VERSION] = CHAT_MESSAGE_SCHEMA_VERSION
    message_id: str
    author_id: str
    audience: tuple[str, ...] = ("all",)
    text: str

    @field_validator("message_id", "author_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @field_validator("audience", mode="before")
    @classmethod
    def validate_audience(cls, value: Any) -> tuple[str, ...]:
        return validate_audience_selectors(value)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("text must be a string")
        if not value.strip():
            raise ValueError("text must contain a non-whitespace character")
        if len(value) > MAX_CHAT_TEXT_LENGTH:
            raise ValueError(f"text must be at most {MAX_CHAT_TEXT_LENGTH} characters")
        if any(
            unicodedata.category(character) == "Cc" and character not in {"\n", "\t"}
            for character in value
        ):
            raise ValueError("text contains an unsupported control character")
        return value


class _ChatCommandBase(_StrictChatModel):
    schema_version: Literal[CHAT_COMMAND_SCHEMA_VERSION] = CHAT_COMMAND_SCHEMA_VERSION
    table_id: str
    command_id: str
    expected_revision: NonNegativeInt

    @field_validator("table_id", "command_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)


class ChatPostCommand(_ChatCommandBase):
    command_type: Literal["post"] = "post"
    message: ChatMessage


class ChatDeleteCommand(_ChatCommandBase):
    command_type: Literal["delete"] = "delete"
    message_id: str

    @field_validator("message_id")
    @classmethod
    def validate_message_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="message_id")


ChatMutationCommand: TypeAlias = Annotated[
    ChatPostCommand | ChatDeleteCommand,
    Field(discriminator="command_type"),
]


class _ChatEventBase(_StrictChatModel):
    schema_version: Literal[CHAT_EVENT_SCHEMA_VERSION] = CHAT_EVENT_SCHEMA_VERSION
    table_id: str
    event_id: str
    sequence: PositiveInt
    revision: PositiveInt
    command_id: str
    message_id: str

    @field_validator("table_id", "command_id", "message_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="event_id", maximum_length=512)

    @model_validator(mode="after")
    def validate_sequence_revision(self) -> Self:
        if self.sequence != self.revision:
            raise ValueError("sequence must match revision")
        return self


class ChatPostedEvent(_ChatEventBase):
    event_type: Literal["posted"] = "posted"
    message: ChatMessage

    @model_validator(mode="after")
    def validate_message_identity(self) -> Self:
        if self.message.message_id != self.message_id:
            raise ValueError("message.message_id must match message_id")
        return self


class ChatDeletedEvent(_ChatEventBase):
    event_type: Literal["deleted"] = "deleted"
    author_id: str
    audience: tuple[str, ...]

    @field_validator("author_id")
    @classmethod
    def validate_author_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="author_id")

    @field_validator("audience", mode="before")
    @classmethod
    def validate_audience(cls, value: Any) -> tuple[str, ...]:
        return validate_audience_selectors(value)


ChatMutationEvent: TypeAlias = Annotated[
    ChatPostedEvent | ChatDeletedEvent,
    Field(discriminator="event_type"),
]


class ChatMutationReceipt(_StrictChatModel):
    schema_version: Literal[CHAT_RECEIPT_SCHEMA_VERSION] = CHAT_RECEIPT_SCHEMA_VERSION
    table_id: str
    command_id: str
    revision: PositiveInt
    event: ChatMutationEvent

    @field_validator("table_id", "command_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_event_identity(self) -> Self:
        if self.event.table_id != self.table_id:
            raise ValueError("event.table_id must match table_id")
        if self.event.command_id != self.command_id:
            raise ValueError("event.command_id must match command_id")
        if self.event.revision != self.revision:
            raise ValueError("event.revision must match revision")
        return self


class ChatView(_StrictChatModel):
    schema_version: Literal[CHAT_VIEW_SCHEMA_VERSION] = CHAT_VIEW_SCHEMA_VERSION
    session_id: str
    table_id: str
    revision: NonNegativeInt
    messages: tuple[ChatMessage, ...] = ()

    @field_validator("session_id", "table_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_unique_messages(self) -> Self:
        ids = tuple(message.message_id for message in self.messages)
        if len(set(ids)) != len(ids):
            raise ValueError("messages must not contain duplicate message IDs")
        return self


class ChatRequest(_StrictChatModel):
    schema_version: Literal[CHAT_REQUEST_SCHEMA_VERSION] = CHAT_REQUEST_SCHEMA_VERSION
    session_id: str
    command: ChatMutationCommand

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="session_id")


class ChatResponse(_StrictChatModel):
    schema_version: Literal[CHAT_RESPONSE_SCHEMA_VERSION] = CHAT_RESPONSE_SCHEMA_VERSION
    session_id: str
    table_id: str
    command_id: str
    revision: PositiveInt
    replayed: bool
    event: ChatMutationEvent | None

    @field_validator("session_id", "table_id", "command_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_text(value, field_name=info.field_name)

    @field_validator("replayed", mode="before")
    @classmethod
    def validate_replayed(cls, value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError("replayed must be a boolean")
        return value

    @model_validator(mode="after")
    def validate_event_identity(self) -> Self:
        if self.event is None:
            return self
        if (
            self.event.table_id != self.table_id
            or self.event.command_id != self.command_id
            or self.event.revision != self.revision
        ):
            raise ValueError("event identity must match the chat response")
        return self


_COMMAND_ADAPTER = TypeAdapter(ChatMutationCommand)


def parse_chat_command(value: Any) -> ChatMutationCommand:
    return _COMMAND_ADAPTER.validate_python(value)


def parse_chat_command_json(value: str | bytes | bytearray) -> ChatMutationCommand:
    return _COMMAND_ADAPTER.validate_json(value)


__all__ = [
    "CHAT_COMMAND_SCHEMA_VERSION",
    "CHAT_EVENT_SCHEMA_VERSION",
    "CHAT_MESSAGE_SCHEMA_VERSION",
    "CHAT_RECEIPT_SCHEMA_VERSION",
    "CHAT_REQUEST_SCHEMA_VERSION",
    "CHAT_RESPONSE_SCHEMA_VERSION",
    "CHAT_VIEW_SCHEMA_VERSION",
    "MAX_CHAT_TEXT_LENGTH",
    "ChatDeleteCommand",
    "ChatDeletedEvent",
    "ChatMessage",
    "ChatMutationCommand",
    "ChatMutationEvent",
    "ChatMutationReceipt",
    "ChatPostCommand",
    "ChatPostedEvent",
    "ChatRequest",
    "ChatResponse",
    "ChatView",
    "parse_chat_command",
    "parse_chat_command_json",
]
