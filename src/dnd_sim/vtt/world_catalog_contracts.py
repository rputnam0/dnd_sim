"""Strict portable contracts for a standalone VTT world catalog."""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

WORLD_RECORD_SCHEMA_VERSION = "vtt.world_record.v1"
WORLD_CATALOG_VIEW_SCHEMA_VERSION = "vtt.world_catalog_view.v1"
WORLD_CATALOG_COMMAND_SCHEMA_VERSION = "vtt.world_catalog_command.v1"
WORLD_CATALOG_EVENT_SCHEMA_VERSION = "vtt.world_catalog_event.v1"
WORLD_CATALOG_RECEIPT_SCHEMA_VERSION = "vtt.world_catalog_receipt.v1"

ENGINE_NATIVE_SYSTEM_ID = "dnd5e"
MAX_WORLD_NAME_LENGTH = 160
MAX_WORLD_RECORDS = 1_024
MAX_ACTIVE_WORLDS = 128

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]


class _StrictWorldCatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _canonical_text(value: Any, *, field_name: str, maximum_length: int) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    if len(value) > maximum_length:
        raise ValueError(f"{field_name} must be at most {maximum_length} characters")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError(f"{field_name} contains an unsupported control character")
    if any(unicodedata.category(character) == "Cs" for character in value):
        raise ValueError(f"{field_name} contains an unsupported Unicode scalar")
    return value


def _url_safe_id(value: Any, *, field_name: str) -> str:
    value = _canonical_text(value, field_name=field_name, maximum_length=128)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value) is None:
        raise ValueError(f"{field_name} must be a URL-safe identifier")
    return value


def world_name_key(value: str) -> str:
    """Return the deterministic comparison key used for active world names."""

    return unicodedata.normalize("NFKC", value).casefold()


class WorldRecord(_StrictWorldCatalogModel):
    """Metadata for one world, linked to table state only by opaque identity."""

    schema_version: Literal[WORLD_RECORD_SCHEMA_VERSION] = WORLD_RECORD_SCHEMA_VERSION
    world_id: str
    name: str
    system_id: Literal[ENGINE_NATIVE_SYSTEM_ID] = ENGINE_NATIVE_SYSTEM_ID
    table_id: str

    @field_validator("world_id", "table_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _url_safe_id(value, field_name=info.field_name)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _canonical_text(
            value,
            field_name="name",
            maximum_length=MAX_WORLD_NAME_LENGTH,
        )


class WorldCatalogEntry(_StrictWorldCatalogModel):
    world: WorldRecord
    archived: bool = False

    @field_validator("archived", mode="before")
    @classmethod
    def validate_archived(cls, value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError("archived must be a boolean")
        return value


class WorldCatalogView(_StrictWorldCatalogModel):
    """A deterministic projection of all retained standalone VTT worlds."""

    schema_version: Literal[WORLD_CATALOG_VIEW_SCHEMA_VERSION] = WORLD_CATALOG_VIEW_SCHEMA_VERSION
    revision: NonNegativeInt
    worlds: tuple[WorldCatalogEntry, ...] = ()

    @model_validator(mode="after")
    def validate_order_bounds_and_active_claims(self) -> "WorldCatalogView":
        world_ids = tuple(entry.world.world_id for entry in self.worlds)
        if world_ids != tuple(sorted(set(world_ids))):
            raise ValueError("worlds must have unique world IDs in sorted order")
        if len(self.worlds) > MAX_WORLD_RECORDS:
            raise ValueError(f"worlds must contain at most {MAX_WORLD_RECORDS} entries")

        active = self.active_worlds
        if len(active) > MAX_ACTIVE_WORLDS:
            raise ValueError(f"catalog must contain at most {MAX_ACTIVE_WORLDS} active worlds")
        active_names = tuple(world_name_key(entry.world.name) for entry in active)
        if len(active_names) != len(set(active_names)):
            raise ValueError("active world names must be unique ignoring case")
        table_ids = tuple(entry.world.table_id for entry in self.worlds)
        if len(table_ids) != len(set(table_ids)):
            raise ValueError("worlds must link to unique table IDs")
        return self

    @property
    def active_worlds(self) -> tuple[WorldCatalogEntry, ...]:
        return tuple(entry for entry in self.worlds if not entry.archived)

    @property
    def archived_worlds(self) -> tuple[WorldCatalogEntry, ...]:
        return tuple(entry for entry in self.worlds if entry.archived)

    def world(self, world_id: str) -> WorldCatalogEntry | None:
        normalized = _url_safe_id(world_id, field_name="world_id")
        return next(
            (entry for entry in self.worlds if entry.world.world_id == normalized),
            None,
        )


class _WorldCommandBase(_StrictWorldCatalogModel):
    schema_version: Literal[WORLD_CATALOG_COMMAND_SCHEMA_VERSION] = (
        WORLD_CATALOG_COMMAND_SCHEMA_VERSION
    )
    command_id: str
    expected_revision: NonNegativeInt

    @field_validator("command_id")
    @classmethod
    def validate_command_id(cls, value: str) -> str:
        return _url_safe_id(value, field_name="command_id")


class WorldCreateCommand(_WorldCommandBase):
    command_type: Literal["create"] = "create"
    world: WorldRecord


class WorldRenameCommand(_WorldCommandBase):
    command_type: Literal["rename"] = "rename"
    world_id: str
    name: str

    @field_validator("world_id")
    @classmethod
    def validate_world_id(cls, value: str) -> str:
        return _url_safe_id(value, field_name="world_id")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _canonical_text(
            value,
            field_name="name",
            maximum_length=MAX_WORLD_NAME_LENGTH,
        )


class WorldArchiveCommand(_WorldCommandBase):
    command_type: Literal["archive"] = "archive"
    world_id: str

    @field_validator("world_id")
    @classmethod
    def validate_world_id(cls, value: str) -> str:
        return _url_safe_id(value, field_name="world_id")


WorldMutationCommand: TypeAlias = Annotated[
    WorldCreateCommand | WorldRenameCommand | WorldArchiveCommand,
    Field(discriminator="command_type"),
]


class _WorldEventBase(_StrictWorldCatalogModel):
    schema_version: Literal[WORLD_CATALOG_EVENT_SCHEMA_VERSION] = WORLD_CATALOG_EVENT_SCHEMA_VERSION
    event_id: str
    sequence: PositiveInt
    revision: PositiveInt
    command_id: str

    @field_validator("event_id", "command_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _url_safe_id(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_sequence_revision(self) -> "_WorldEventBase":
        if self.sequence != self.revision:
            raise ValueError("sequence must match revision")
        return self


class WorldCreatedEvent(_WorldEventBase):
    event_type: Literal["created"] = "created"
    world: WorldRecord


class WorldRenamedEvent(_WorldEventBase):
    event_type: Literal["renamed"] = "renamed"
    world_id: str
    old_name: str
    new_name: str

    @field_validator("world_id")
    @classmethod
    def validate_world_id(cls, value: str) -> str:
        return _url_safe_id(value, field_name="world_id")

    @field_validator("old_name", "new_name")
    @classmethod
    def validate_name(cls, value: str, info: Any) -> str:
        return _canonical_text(
            value,
            field_name=info.field_name,
            maximum_length=MAX_WORLD_NAME_LENGTH,
        )

    @model_validator(mode="after")
    def validate_changed_name(self) -> "WorldRenamedEvent":
        if self.old_name == self.new_name:
            raise ValueError("new_name must differ from old_name")
        return self


class WorldArchivedEvent(_WorldEventBase):
    event_type: Literal["archived"] = "archived"
    world_id: str

    @field_validator("world_id")
    @classmethod
    def validate_world_id(cls, value: str) -> str:
        return _url_safe_id(value, field_name="world_id")


WorldMutationEvent: TypeAlias = Annotated[
    WorldCreatedEvent | WorldRenamedEvent | WorldArchivedEvent,
    Field(discriminator="event_type"),
]


class WorldMutationReceipt(_StrictWorldCatalogModel):
    schema_version: Literal[WORLD_CATALOG_RECEIPT_SCHEMA_VERSION] = (
        WORLD_CATALOG_RECEIPT_SCHEMA_VERSION
    )
    command_id: str
    revision: PositiveInt
    event: WorldMutationEvent

    @field_validator("command_id")
    @classmethod
    def validate_command_id(cls, value: str) -> str:
        return _url_safe_id(value, field_name="command_id")

    @model_validator(mode="after")
    def validate_event_identity(self) -> "WorldMutationReceipt":
        if self.event.command_id != self.command_id:
            raise ValueError("event.command_id must match command_id")
        if self.event.revision != self.revision:
            raise ValueError("event.revision must match revision")
        return self


_COMMAND_ADAPTER = TypeAdapter(WorldMutationCommand)
_EVENT_ADAPTER = TypeAdapter(WorldMutationEvent)


def parse_world_command(value: Any) -> WorldMutationCommand:
    return _COMMAND_ADAPTER.validate_python(value)


def parse_world_command_json(value: str | bytes | bytearray) -> WorldMutationCommand:
    return _COMMAND_ADAPTER.validate_json(value)


def parse_world_event(value: Any) -> WorldMutationEvent:
    return _EVENT_ADAPTER.validate_python(value)


__all__ = [
    "ENGINE_NATIVE_SYSTEM_ID",
    "MAX_ACTIVE_WORLDS",
    "MAX_WORLD_NAME_LENGTH",
    "MAX_WORLD_RECORDS",
    "WORLD_CATALOG_COMMAND_SCHEMA_VERSION",
    "WORLD_CATALOG_EVENT_SCHEMA_VERSION",
    "WORLD_CATALOG_RECEIPT_SCHEMA_VERSION",
    "WORLD_CATALOG_VIEW_SCHEMA_VERSION",
    "WORLD_RECORD_SCHEMA_VERSION",
    "WorldArchiveCommand",
    "WorldArchivedEvent",
    "WorldCatalogEntry",
    "WorldCatalogView",
    "WorldCreateCommand",
    "WorldCreatedEvent",
    "WorldMutationCommand",
    "WorldMutationEvent",
    "WorldMutationReceipt",
    "WorldRecord",
    "WorldRenameCommand",
    "WorldRenamedEvent",
    "parse_world_command",
    "parse_world_command_json",
    "parse_world_event",
    "world_name_key",
]
