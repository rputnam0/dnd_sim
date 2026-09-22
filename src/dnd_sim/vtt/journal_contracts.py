"""Strict renderer-neutral contracts for the durable VTT journal."""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Annotated, Any, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from .annotations import AnnotationPoint
from .participants import validate_audience_selectors

JOURNAL_BLOCK_SCHEMA_VERSION = "vtt.journal_block.v1"
JOURNAL_FOLDER_SCHEMA_VERSION = "vtt.journal_folder.v1"
JOURNAL_DOCUMENT_SCHEMA_VERSION = "vtt.journal_document.v1"
JOURNAL_MAP_PIN_SCHEMA_VERSION = "vtt.journal_map_pin.v1"
JOURNAL_COMMAND_SCHEMA_VERSION = "vtt.journal_command.v1"
JOURNAL_EVENT_SCHEMA_VERSION = "vtt.journal_event.v1"
JOURNAL_RECEIPT_SCHEMA_VERSION = "vtt.journal_receipt.v1"
JOURNAL_VIEW_SCHEMA_VERSION = "vtt.journal_view.v1"
JOURNAL_REQUEST_SCHEMA_VERSION = "vtt.journal_request.v1"
JOURNAL_RESPONSE_SCHEMA_VERSION = "vtt.journal_response.v1"

MAX_JOURNAL_BLOCKS = 256
MAX_JOURNAL_TEXT = 50_000
MAX_JOURNAL_TAGS = 32
MAX_JOURNAL_SEARCH_RESULTS = 200
MAX_JOURNAL_AUDIENCE_SELECTORS = 128
MAX_JOURNAL_FOLDERS = 256
MAX_JOURNAL_DOCUMENTS = 2_000
MAX_JOURNAL_FOLDER_DEPTH = 16

logger = logging.getLogger(__name__)

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _canonical_text(
    value: Any,
    *,
    field_name: str,
    maximum_length: int,
    allow_line_feed: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be nonempty without surrounding whitespace")
    if len(value) > maximum_length:
        raise ValueError(f"{field_name} must be at most {maximum_length} characters")
    if any(
        unicodedata.category(character) == "Cc" and not (allow_line_feed and character == "\n")
        for character in value
    ):
        raise ValueError(f"{field_name} contains an unsupported control character")
    return value


def _canonical_id(value: Any, *, field_name: str) -> str:
    return _canonical_text(value, field_name=field_name, maximum_length=128)


class JournalTextBlock(_StrictModel):
    schema_version: Literal[JOURNAL_BLOCK_SCHEMA_VERSION] = JOURNAL_BLOCK_SCHEMA_VERSION
    block_type: Literal["paragraph"] = "paragraph"
    text: str

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _canonical_text(
            value,
            field_name="paragraph text",
            maximum_length=MAX_JOURNAL_TEXT,
            allow_line_feed=True,
        )


class JournalHeadingBlock(_StrictModel):
    schema_version: Literal[JOURNAL_BLOCK_SCHEMA_VERSION] = JOURNAL_BLOCK_SCHEMA_VERSION
    block_type: Literal["heading"] = "heading"
    level: Annotated[int, Field(strict=True, ge=1, le=3)]
    text: str

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _canonical_text(value, field_name="heading text", maximum_length=500)


class JournalBulletListBlock(_StrictModel):
    schema_version: Literal[JOURNAL_BLOCK_SCHEMA_VERSION] = JOURNAL_BLOCK_SCHEMA_VERSION
    block_type: Literal["bullet_list"] = "bullet_list"
    items: tuple[str, ...]

    @field_validator("items", mode="before")
    @classmethod
    def validate_items(cls, value: Any) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 64:
            raise ValueError("bullet list must contain 1-64 items")
        return tuple(
            _canonical_text(item, field_name="bullet item", maximum_length=2_000) for item in value
        )


class JournalDocumentLinkBlock(_StrictModel):
    schema_version: Literal[JOURNAL_BLOCK_SCHEMA_VERSION] = JOURNAL_BLOCK_SCHEMA_VERSION
    block_type: Literal["document_link"] = "document_link"
    document_id: str
    label: str

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        return _canonical_id(value, field_name="document_id")

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        return _canonical_text(value, field_name="link label", maximum_length=500)


JournalBlock: TypeAlias = Annotated[
    JournalTextBlock | JournalHeadingBlock | JournalBulletListBlock | JournalDocumentLinkBlock,
    Field(discriminator="block_type"),
]


class MapPin(_StrictModel):
    schema_version: Literal[JOURNAL_MAP_PIN_SCHEMA_VERSION] = JOURNAL_MAP_PIN_SCHEMA_VERSION
    scene_id: str
    position: AnnotationPoint
    color: str

    @field_validator("scene_id")
    @classmethod
    def validate_scene_id(cls, value: str) -> str:
        return _canonical_id(value, field_name="scene_id")

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str) -> str:
        if not isinstance(value, str) or re.fullmatch(r"#[0-9a-f]{6}", value) is None:
            raise ValueError("color must be a lowercase #rrggbb value")
        return value


class JournalFolder(_StrictModel):
    schema_version: Literal[JOURNAL_FOLDER_SCHEMA_VERSION] = JOURNAL_FOLDER_SCHEMA_VERSION
    folder_id: str
    parent_folder_id: str | None = None
    name: str

    @field_validator("folder_id")
    @classmethod
    def validate_folder_id(cls, value: str) -> str:
        return _canonical_id(value, field_name="folder_id")

    @field_validator("parent_folder_id")
    @classmethod
    def validate_parent(cls, value: str | None) -> str | None:
        return None if value is None else _canonical_id(value, field_name="parent_folder_id")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _canonical_text(value, field_name="folder name", maximum_length=160)

    @model_validator(mode="after")
    def validate_not_self_parent(self) -> Self:
        if self.parent_folder_id == self.folder_id:
            raise ValueError("folder cannot be its own parent")
        return self


class JournalDocument(_StrictModel):
    schema_version: Literal[JOURNAL_DOCUMENT_SCHEMA_VERSION] = JOURNAL_DOCUMENT_SCHEMA_VERSION
    document_id: str
    document_type: Literal["note", "handout"]
    folder_id: str | None = None
    title: str
    audience: tuple[str, ...]
    tags: tuple[str, ...] = ()
    favorite: bool = False
    blocks: tuple[JournalBlock, ...]
    map_pin: MapPin | None = None

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        return _canonical_id(value, field_name="document_id")

    @field_validator("folder_id")
    @classmethod
    def validate_folder_id(cls, value: str | None) -> str | None:
        return None if value is None else _canonical_id(value, field_name="folder_id")

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _canonical_text(value, field_name="title", maximum_length=160)

    @field_validator("audience", mode="before")
    @classmethod
    def validate_audience(cls, value: Any) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)) or len(value) > MAX_JOURNAL_AUDIENCE_SELECTORS:
            raise ValueError(
                f"audience must contain at most {MAX_JOURNAL_AUDIENCE_SELECTORS} selectors"
            )
        selectors = validate_audience_selectors(value)
        for selector in selectors:
            if selector in {"all", "role:gm", "role:player", "role:spectator"}:
                continue
            if selector.startswith("participant:"):
                _canonical_id(
                    selector.removeprefix("participant:"),
                    field_name="audience participant ID",
                )
            elif selector.startswith("actor:"):
                _canonical_id(
                    selector.removeprefix("actor:"),
                    field_name="audience actor ID",
                )
        return selectors

    @field_validator("tags", mode="before")
    @classmethod
    def validate_tags(cls, value: Any) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)) or len(value) > MAX_JOURNAL_TAGS:
            raise ValueError(f"tags must contain at most {MAX_JOURNAL_TAGS} items")
        tags = tuple(_canonical_text(item, field_name="tag", maximum_length=64) for item in value)
        if tags != tuple(sorted(set(tags))):
            raise ValueError("tags must be unique and sorted")
        return tags

    @field_validator("favorite", mode="before")
    @classmethod
    def validate_favorite(cls, value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError("favorite must be a boolean")
        return value

    @field_validator("blocks", mode="before")
    @classmethod
    def validate_blocks_shape(cls, value: Any) -> tuple[Any, ...]:
        if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= MAX_JOURNAL_BLOCKS:
            raise ValueError(f"blocks must contain 1-{MAX_JOURNAL_BLOCKS} items")
        return tuple(value)

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        text_size = len(self.title)
        for block in self.blocks:
            if isinstance(block, (JournalTextBlock, JournalHeadingBlock)):
                text_size += len(block.text)
            elif isinstance(block, JournalBulletListBlock):
                text_size += sum(len(item) for item in block.items)
            else:
                text_size += len(block.label)
                if block.document_id == self.document_id:
                    raise ValueError("document cannot link to itself")
        if text_size > MAX_JOURNAL_TEXT:
            raise ValueError(f"document text must be at most {MAX_JOURNAL_TEXT} characters")
        return self


class _CommandBase(_StrictModel):
    schema_version: Literal[JOURNAL_COMMAND_SCHEMA_VERSION] = JOURNAL_COMMAND_SCHEMA_VERSION
    table_id: str
    command_id: str
    expected_revision: NonNegativeInt

    @field_validator("table_id", "command_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_id(value, field_name=info.field_name)


class JournalPutFolderCommand(_CommandBase):
    command_type: Literal["put_folder"] = "put_folder"
    folder: JournalFolder


class JournalDeleteFolderCommand(_CommandBase):
    command_type: Literal["delete_folder"] = "delete_folder"
    folder_id: str

    @field_validator("folder_id")
    @classmethod
    def validate_folder_id(cls, value: str) -> str:
        return _canonical_id(value, field_name="folder_id")


class JournalPutDocumentCommand(_CommandBase):
    command_type: Literal["put_document"] = "put_document"
    document: JournalDocument


class JournalDeleteDocumentCommand(_CommandBase):
    command_type: Literal["delete_document"] = "delete_document"
    document_id: str

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        return _canonical_id(value, field_name="document_id")


JournalMutationCommand: TypeAlias = Annotated[
    JournalPutFolderCommand
    | JournalDeleteFolderCommand
    | JournalPutDocumentCommand
    | JournalDeleteDocumentCommand,
    Field(discriminator="command_type"),
]


class _EventBase(_StrictModel):
    schema_version: Literal[JOURNAL_EVENT_SCHEMA_VERSION] = JOURNAL_EVENT_SCHEMA_VERSION
    table_id: str
    event_id: str
    sequence: PositiveInt
    revision: PositiveInt
    command_id: str

    @field_validator("table_id", "command_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_id(value, field_name=info.field_name)

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, value: str) -> str:
        return _canonical_text(value, field_name="event_id", maximum_length=512)

    @model_validator(mode="after")
    def validate_revision_identity(self) -> Self:
        if self.sequence != self.revision:
            raise ValueError("event sequence must equal revision")
        if self.event_id != f"{self.table_id}:journal:{self.sequence}":
            raise ValueError("event_id must match table and sequence")
        return self


class JournalFolderPutEvent(_EventBase):
    event_type: Literal["folder_put"] = "folder_put"
    folder: JournalFolder


class JournalFolderDeletedEvent(_EventBase):
    event_type: Literal["folder_deleted"] = "folder_deleted"
    folder: JournalFolder


class JournalDocumentPutEvent(_EventBase):
    event_type: Literal["document_put"] = "document_put"
    document: JournalDocument


class JournalDocumentDeletedEvent(_EventBase):
    event_type: Literal["document_deleted"] = "document_deleted"
    document: JournalDocument


JournalMutationEvent: TypeAlias = Annotated[
    JournalFolderPutEvent
    | JournalFolderDeletedEvent
    | JournalDocumentPutEvent
    | JournalDocumentDeletedEvent,
    Field(discriminator="event_type"),
]


class JournalMutationReceipt(_StrictModel):
    schema_version: Literal[JOURNAL_RECEIPT_SCHEMA_VERSION] = JOURNAL_RECEIPT_SCHEMA_VERSION
    table_id: str
    command_id: str
    revision: PositiveInt
    event: JournalMutationEvent

    @field_validator("table_id", "command_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_id(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if (
            self.event.table_id != self.table_id
            or self.event.command_id != self.command_id
            or self.event.revision != self.revision
        ):
            raise ValueError("event identity must match receipt")
        return self


def journal_document_sort_key(
    document: JournalDocument,
) -> tuple[int, tuple[int, ...], tuple[int, ...]]:
    return (
        0 if document.favorite else 1,
        tuple(ord(character) for character in document.title),
        tuple(ord(character) for character in document.document_id),
    )


def journal_folder_sort_key(
    folder: JournalFolder,
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    return (
        tuple(ord(character) for character in (folder.parent_folder_id or "")),
        tuple(ord(character) for character in folder.name),
        tuple(ord(character) for character in folder.folder_id),
    )


class JournalView(_StrictModel):
    schema_version: Literal[JOURNAL_VIEW_SCHEMA_VERSION] = JOURNAL_VIEW_SCHEMA_VERSION
    session_id: str
    table_id: str
    revision: NonNegativeInt
    folders: tuple[JournalFolder, ...] = ()
    documents: tuple[JournalDocument, ...] = ()

    @field_validator("folders", mode="before")
    @classmethod
    def validate_folder_shape(cls, value: Any) -> tuple[Any, ...]:
        if not isinstance(value, (list, tuple)) or len(value) > MAX_JOURNAL_FOLDERS:
            raise ValueError(f"folders must contain at most {MAX_JOURNAL_FOLDERS} items")
        return tuple(value)

    @field_validator("documents", mode="before")
    @classmethod
    def validate_document_shape(cls, value: Any) -> tuple[Any, ...]:
        if not isinstance(value, (list, tuple)) or len(value) > MAX_JOURNAL_DOCUMENTS:
            raise ValueError(f"documents must contain at most {MAX_JOURNAL_DOCUMENTS} items")
        return tuple(value)

    @field_validator("session_id", "table_id")
    @classmethod
    def validate_id(cls, value: str, info: Any) -> str:
        return _canonical_id(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        if self.folders != tuple(sorted(self.folders, key=journal_folder_sort_key)):
            raise ValueError("folders must be canonically ordered")
        if self.documents != tuple(sorted(self.documents, key=journal_document_sort_key)):
            raise ValueError("documents must be canonically ordered")
        folders = {folder.folder_id: folder for folder in self.folders}
        documents = {document.document_id: document for document in self.documents}
        if len(folders) != len(self.folders) or len(documents) != len(self.documents):
            raise ValueError("journal projection identities must be unique")
        for folder in self.folders:
            current = folder
            seen: set[str] = set()
            depth = 1
            while current.parent_folder_id is not None:
                if current.parent_folder_id not in folders:
                    raise ValueError("journal projection parent folder is missing")
                if current.parent_folder_id in seen:
                    raise ValueError("journal projection folder graph is cyclic")
                seen.add(current.folder_id)
                current = folders[current.parent_folder_id]
                depth += 1
                if depth > MAX_JOURNAL_FOLDER_DEPTH:
                    raise ValueError("journal projection folder depth exceeds limit")
        document_ids = set(documents)
        for document in self.documents:
            if document.folder_id is not None and document.folder_id not in folders:
                raise ValueError("journal projection document folder is missing")
            if any(
                isinstance(block, JournalDocumentLinkBlock)
                and block.document_id not in document_ids
                for block in document.blocks
            ):
                raise ValueError("journal projection link target is missing")
        return self


class JournalRequest(_StrictModel):
    schema_version: Literal[JOURNAL_REQUEST_SCHEMA_VERSION] = JOURNAL_REQUEST_SCHEMA_VERSION
    session_id: str
    command: JournalMutationCommand

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        return _canonical_id(value, field_name="session_id")


class JournalResponse(_StrictModel):
    schema_version: Literal[JOURNAL_RESPONSE_SCHEMA_VERSION] = JOURNAL_RESPONSE_SCHEMA_VERSION
    session_id: str
    replayed: bool
    receipt: JournalMutationReceipt

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        return _canonical_id(value, field_name="session_id")


_COMMAND_ADAPTER = TypeAdapter(JournalMutationCommand)
_EVENT_ADAPTER = TypeAdapter(JournalMutationEvent)


def parse_journal_command(value: Any) -> JournalMutationCommand:
    return _COMMAND_ADAPTER.validate_python(value)


def parse_journal_command_json(value: str | bytes | bytearray) -> JournalMutationCommand:
    return _COMMAND_ADAPTER.validate_json(value)


def parse_journal_event(value: Any) -> JournalMutationEvent:
    return _EVENT_ADAPTER.validate_python(value)


__all__ = [name for name in globals() if name.startswith("JOURNAL_") or name.startswith("Journal")]
__all__ += [
    "MapPin",
    "MAX_JOURNAL_AUDIENCE_SELECTORS",
    "MAX_JOURNAL_BLOCKS",
    "MAX_JOURNAL_DOCUMENTS",
    "MAX_JOURNAL_FOLDER_DEPTH",
    "MAX_JOURNAL_FOLDERS",
    "MAX_JOURNAL_SEARCH_RESULTS",
    "MAX_JOURNAL_TAGS",
    "MAX_JOURNAL_TEXT",
    "journal_document_sort_key",
    "journal_folder_sort_key",
    "parse_journal_command",
    "parse_journal_command_json",
    "parse_journal_event",
]
