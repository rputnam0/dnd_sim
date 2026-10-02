"""Bounded durable invitations and guest identities for prepared VTT worlds.

Only random bearer digests are stored. Guest sessions deliberately belong to
the service's in-memory authority, not this database. This is a separately
versioned extension and never mutates installation or world-catalog history.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator
from pydantic import model_validator

from .participants import PARTICIPANT_SCHEMA_VERSION, TableParticipant

WORLD_INVITATION_STORE_SCHEMA_VERSION = "vtt.world_invitation_store.v1"
INVITATION_TTL_SECONDS = 24 * 60 * 60
MAX_ACTIVE_WORLD_GUESTS = 10
MAX_WORLD_INVITATIONS = 1_024
_MAX_EPOCH = (1 << 63) - 1
_METADATA_TABLE = "_vtt_world_invitation_metadata"
_INVITATIONS_TABLE = "_vtt_world_invitations"
_TABLES = {_METADATA_TABLE, _INVITATIONS_TABLE}
_COLUMNS = (
    "invitation_id",
    "world_id",
    "table_id",
    "command_id",
    "role",
    "created_at",
    "expires_at",
    "token_hash",
    "status",
    "participant_id",
    "display_name",
    "redeemed_at",
    "revoked_at",
)

InvitationRole = Literal["player", "spectator"]
Epoch = Annotated[int, Field(strict=True, ge=0, le=_MAX_EPOCH)]


class WorldInvitationStoreError(RuntimeError):
    """Base failure of the durable world access boundary."""


class WorldInvitationSchemaError(WorldInvitationStoreError):
    pass


class WorldInvitationCorruptionError(WorldInvitationStoreError):
    pass


class InvitationAuthenticationError(WorldInvitationStoreError):
    def __init__(self) -> None:
        super().__init__("authentication failed")


class InvitationCommandConflictError(WorldInvitationStoreError):
    pass


class InvitationLimitError(WorldInvitationStoreError):
    pass


class InvitationNotFoundError(WorldInvitationStoreError):
    pass


def _identity(value: Any) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value) is None
    ):
        raise ValueError("identity must be a URL-safe string of 1 to 128 characters")
    return value


def _display_name(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 80
        or value != value.strip()
        or unicodedata.normalize("NFKC", value) != value
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ValueError("display_name must be bounded canonical display text")
    return value


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class InvitationIssueCommand(_StrictModel):
    command_id: str
    role: InvitationRole

    @field_validator("command_id")
    @classmethod
    def validate_command_id(cls, value: str) -> str:
        return _identity(value)


class InvitationJoinCommand(_StrictModel):
    display_name: str

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        return _display_name(value)


class InvitationPublic(_StrictModel):
    """The complete public invitation shape; no secret or digest is present."""

    invitation_id: str
    role: InvitationRole
    created_at: Epoch
    expires_at: Epoch
    status: Literal["pending", "redeemed", "revoked", "expired"]
    participant: TableParticipant | None = None

    @field_validator("invitation_id")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _identity(value)

    @model_validator(mode="after")
    def validate_record(self) -> "InvitationPublic":
        if self.expires_at - self.created_at != INVITATION_TTL_SECONDS:
            raise ValueError("invitation lifetime must be exactly 24 hours")
        if (self.status == "redeemed" and self.participant is None) or (
            self.status in {"pending", "expired"} and self.participant is not None
        ):
            raise ValueError("participant must match invitation status")
        if self.participant is not None:
            _identity(self.participant.participant_id)
            _display_name(self.participant.display_name)
            if self.participant.role != self.role or self.participant.owned_actor_ids:
                raise ValueError("guest participant must match invitation authority")
        return self


@dataclass(frozen=True, slots=True)
class InvitationIssuance:
    invitation: InvitationPublic
    invitation_token: SecretStr | None
    replayed: bool


@dataclass(frozen=True, slots=True)
class InvitationBinding:
    world_id: str
    table_id: str
    invitation: InvitationPublic

    @property
    def participant(self) -> TableParticipant | None:
        return self.invitation.participant


class _StoredInvitation(_StrictModel):
    invitation_id: str
    world_id: str
    table_id: str
    command_id: str
    role: InvitationRole
    created_at: Epoch
    expires_at: Epoch
    token_hash: str = Field(repr=False)
    status: Literal["pending", "redeemed", "revoked"]
    participant_id: str | None
    display_name: str | None
    redeemed_at: Epoch | None
    revoked_at: Epoch | None

    @field_validator("invitation_id", "world_id", "table_id", "command_id")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _identity(value)

    @field_validator("token_hash")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("token digest is invalid")
        return value

    @model_validator(mode="after")
    def validate_state(self) -> "_StoredInvitation":
        if self.expires_at - self.created_at != INVITATION_TTL_SECONDS:
            raise ValueError("invalid invitation lifetime")
        if self.redeemed_at is None:
            if (
                self.participant_id is not None
                or self.display_name is not None
                or self.status == "redeemed"
            ):
                raise ValueError("invalid unredeemed invitation")
        else:
            _identity(self.participant_id)
            _display_name(self.display_name)
            if (
                self.status == "pending"
                or not self.created_at <= self.redeemed_at < self.expires_at
            ):
                raise ValueError("invalid redeemed invitation")
        if self.status == "revoked":
            if self.revoked_at is None or self.revoked_at < (self.redeemed_at or self.created_at):
                raise ValueError("invalid revocation time")
        elif self.revoked_at is not None:
            raise ValueError("invalid revocation state")
        return self

    def public(self, now: int) -> InvitationPublic:
        participant = None
        if self.participant_id is not None:
            participant = TableParticipant(
                schema_version=PARTICIPANT_SCHEMA_VERSION,
                participant_id=self.participant_id,
                display_name=self.display_name,
                role=self.role,
            )
        status = self.status
        if status == "pending" and now >= self.expires_at:
            status = "expired"
        return InvitationPublic(
            invitation_id=self.invitation_id,
            role=self.role,
            created_at=self.created_at,
            expires_at=self.expires_at,
            status=status,
            participant=participant,
        )

    def binding(self, now: int) -> InvitationBinding:
        return InvitationBinding(self.world_id, self.table_id, self.public(now))


def _token_digest(token: Any) -> str:
    if isinstance(token, SecretStr):
        token = token.get_secret_value()
    if not isinstance(token, str) or re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is None:
        raise InvitationAuthenticationError()
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class SQLiteWorldInvitationStore:
    """Atomic invitations; callers serialize a shared connection with their lock."""

    def __init__(
        self, connection: sqlite3.Connection, *, clock: Callable[[], int] | None = None
    ) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        if connection.in_transaction:
            raise WorldInvitationStoreError("cannot initialize inside an active transaction")
        self._connection = connection
        self._clock = clock or (lambda: int(time.time()))
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            existing = {
                row[0]
                for row in self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE name IN (?, ?)", tuple(sorted(_TABLES))
                )
            }
            if existing and existing != _TABLES:
                raise WorldInvitationSchemaError("invitation store schema is incomplete")
            if not existing:
                self._connection.execute(f"""
                    CREATE TABLE {_METADATA_TABLE} (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        schema_version TEXT NOT NULL,
                        record_count INTEGER NOT NULL
                    )
                """)
                self._connection.execute(
                    f"INSERT INTO {_METADATA_TABLE} VALUES (1, ?, 0)",
                    (WORLD_INVITATION_STORE_SCHEMA_VERSION,),
                )
                self._connection.execute(f"""
                    CREATE TABLE {_INVITATIONS_TABLE} (
                        invitation_id TEXT PRIMARY KEY,
                        world_id TEXT NOT NULL,
                        table_id TEXT NOT NULL,
                        command_id TEXT NOT NULL UNIQUE,
                        role TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        expires_at INTEGER NOT NULL,
                        token_hash TEXT NOT NULL UNIQUE,
                        status TEXT NOT NULL,
                        participant_id TEXT UNIQUE,
                        display_name TEXT,
                        redeemed_at INTEGER,
                        revoked_at INTEGER
                    )
                """)
            self._read_records_locked()
            self._connection.commit()
        except BaseException as exc:
            if self._connection.in_transaction:
                self._connection.rollback()
            if isinstance(exc, sqlite3.DatabaseError):
                raise WorldInvitationSchemaError("invitation store schema is invalid") from exc
            raise

    def _read_records_locked(self) -> tuple[_StoredInvitation, ...]:
        for name, columns in (
            (_METADATA_TABLE, ("singleton", "schema_version", "record_count")),
            (_INVITATIONS_TABLE, _COLUMNS),
        ):
            actual = tuple(row[1] for row in self._connection.execute(f"PRAGMA table_info({name})"))
            if actual != columns:
                raise WorldInvitationSchemaError("invitation store schema is incomplete or invalid")
        metadata = self._connection.execute(f"SELECT * FROM {_METADATA_TABLE}").fetchall()
        if len(metadata) != 1 or metadata[0][0] != 1:
            raise WorldInvitationCorruptionError("invitation store metadata is missing or invalid")
        if metadata[0][1] != WORLD_INVITATION_STORE_SCHEMA_VERSION:
            raise WorldInvitationSchemaError("unsupported invitation store schema")
        expected_count = metadata[0][2]
        if type(expected_count) is not int or expected_count < 0:
            raise WorldInvitationCorruptionError("invitation record count is invalid")
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM {_INVITATIONS_TABLE} ORDER BY created_at, invitation_id"
        ).fetchall()
        if len(rows) != expected_count:
            raise WorldInvitationCorruptionError("invitation records disagree with metadata")
        try:
            records = tuple(
                _StoredInvitation.model_validate(dict(zip(_COLUMNS, row))) for row in rows
            )
        except (ValidationError, ValueError, TypeError) as exc:
            raise WorldInvitationCorruptionError("invitation record violates its contract") from exc
        for field in ("invitation_id", "command_id", "token_hash", "participant_id"):
            values = [
                getattr(record, field) for record in records if getattr(record, field) is not None
            ]
            if len(set(values)) != len(values):
                raise WorldInvitationCorruptionError("invitation identity was reused")
        if any(
            count > MAX_WORLD_INVITATIONS
            for count in Counter(row.world_id for row in records).values()
        ):
            raise WorldInvitationCorruptionError("invitation history exceeds its world limit")
        world_tables: dict[str, str] = {}
        table_worlds: dict[str, str] = {}
        for record in records:
            if (
                world_tables.setdefault(record.world_id, record.table_id) != record.table_id
                or table_worlds.setdefault(record.table_id, record.world_id) != record.world_id
            ):
                raise WorldInvitationCorruptionError(
                    "invitation world/table binding is inconsistent"
                )
        return records

    def _now(self) -> int:
        now = self._clock()
        if type(now) is not int or not 0 <= now <= _MAX_EPOCH - INVITATION_TTL_SECONDS:
            raise TypeError("clock must return a bounded non-negative integer epoch")
        return now

    @contextmanager
    def _transaction(
        self, *, write: bool = False
    ) -> Iterator[tuple[tuple[_StoredInvitation, ...], int]]:
        if self._connection.in_transaction:
            raise WorldInvitationStoreError(
                "cannot access invitation store inside an active transaction"
            )
        try:
            self._connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield self._read_records_locked(), self._now()
            if write:
                self._read_records_locked()
            self._connection.commit()
        except BaseException as exc:
            if self._connection.in_transaction:
                self._connection.rollback()
            if isinstance(exc, sqlite3.DatabaseError):
                raise WorldInvitationCorruptionError(
                    "invitation store database operation failed"
                ) from exc
            raise

    def issue(
        self, world_id: str, table_id: str, command_id: str, role: InvitationRole
    ) -> InvitationIssuance:
        """Issue once; exact retries return current public state without the bearer."""

        world_id, table_id = _identity(world_id), _identity(table_id)
        command = InvitationIssueCommand(command_id=command_id, role=role)
        with self._transaction(write=True) as (records, now):
            previous = next((row for row in records if row.command_id == command.command_id), None)
            if previous is not None:
                if (previous.world_id, previous.table_id, previous.role) != (
                    world_id,
                    table_id,
                    command.role,
                ):
                    raise InvitationCommandConflictError("invitation command has different content")
                return InvitationIssuance(previous.public(now), None, True)
            if any(
                (row.world_id == world_id and row.table_id != table_id)
                or (row.table_id == table_id and row.world_id != world_id)
                for row in records
            ):
                raise InvitationCommandConflictError("invitation world/table binding conflicts")
            world_records = tuple(row for row in records if row.world_id == world_id)
            if len(world_records) >= MAX_WORLD_INVITATIONS:
                raise InvitationLimitError("world invitation history limit reached")
            if (
                sum(
                    row.status == "redeemed" or (row.status == "pending" and now < row.expires_at)
                    for row in world_records
                )
                >= MAX_ACTIVE_WORLD_GUESTS
            ):
                raise InvitationLimitError("world active guest limit reached")
            for _ in range(16):
                plaintext = secrets.token_urlsafe(32)
                digest = _token_digest(plaintext)
                invitation_id = f"invite-{secrets.token_hex(16)}"
                if not any(
                    row.token_hash == digest or row.invitation_id == invitation_id
                    for row in records
                ):
                    break
            else:
                raise WorldInvitationStoreError("invitation entropy source failed")
            record = _StoredInvitation(
                invitation_id=invitation_id,
                world_id=world_id,
                table_id=table_id,
                command_id=command.command_id,
                role=command.role,
                created_at=now,
                expires_at=now + INVITATION_TTL_SECONDS,
                token_hash=digest,
                status="pending",
                participant_id=None,
                display_name=None,
                redeemed_at=None,
                revoked_at=None,
            )
            self._connection.execute(
                f"INSERT INTO {_INVITATIONS_TABLE} ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' for _ in _COLUMNS)})",
                tuple(getattr(record, name) for name in _COLUMNS),
            )
            self._connection.execute(
                f"UPDATE {_METADATA_TABLE} SET record_count = record_count + 1 WHERE singleton = 1"
            )
            return InvitationIssuance(record.public(now), SecretStr(plaintext), False)

    @staticmethod
    def _authenticate(
        records: tuple[_StoredInvitation, ...], token: Any, now: int
    ) -> _StoredInvitation:
        digest = _token_digest(token)
        record = next(
            (row for row in records if secrets.compare_digest(row.token_hash, digest)), None
        )
        if (
            record is None
            or record.status != "pending"
            or not record.created_at <= now < record.expires_at
        ):
            raise InvitationAuthenticationError()
        return record

    def authenticate_invitation(self, token: str | SecretStr) -> InvitationBinding:
        """Authenticate the code without consuming it or exposing its digest."""

        with self._transaction() as (records, now):
            return self._authenticate(records, token, now).binding(now)

    def redeem(self, token: str | SecretStr, display_name: str) -> InvitationBinding:
        """Atomically consume one valid code and create its durable guest identity."""

        with self._transaction(write=True) as (records, now):
            record = self._authenticate(records, token, now)
            command = InvitationJoinCommand(display_name=display_name)
            for _ in range(16):
                participant_id = f"guest-{secrets.token_hex(16)}"
                if not any(row.participant_id == participant_id for row in records):
                    break
            else:
                raise WorldInvitationStoreError("participant entropy source failed")
            self._connection.execute(
                f"UPDATE {_INVITATIONS_TABLE} SET status = 'redeemed', participant_id = ?, display_name = ?, redeemed_at = ? WHERE invitation_id = ? AND status = 'pending'",
                (participant_id, command.display_name, now, record.invitation_id),
            )
            updated = _StoredInvitation.model_validate(
                {
                    **record.model_dump(),
                    "status": "redeemed",
                    "participant_id": participant_id,
                    "display_name": command.display_name,
                    "redeemed_at": now,
                }
            )
            return updated.binding(now)

    def list(self, world_id: str, table_id: str) -> tuple[InvitationPublic, ...]:
        world_id, table_id = _identity(world_id), _identity(table_id)
        with self._transaction() as (records, now):
            return tuple(
                row.public(now)
                for row in records
                if row.world_id == world_id and row.table_id == table_id
            )

    def revoke(self, world_id: str, table_id: str, invitation_id: str) -> None:
        """End pending-code and participant authority, retaining the GM's record."""

        world_id, table_id, invitation_id = (
            _identity(world_id),
            _identity(table_id),
            _identity(invitation_id),
        )
        with self._transaction(write=True) as (records, now):
            record = next(
                (
                    row
                    for row in records
                    if (row.world_id, row.table_id, row.invitation_id)
                    == (world_id, table_id, invitation_id)
                ),
                None,
            )
            if record is None:
                raise InvitationNotFoundError("invitation not found")
            if record.status != "revoked":
                self._connection.execute(
                    f"UPDATE {_INVITATIONS_TABLE} SET status = 'revoked', revoked_at = ? WHERE invitation_id = ?",
                    (max(now, record.redeemed_at or record.created_at), invitation_id),
                )

    def authenticate_participant(
        self, world_id: str, table_id: str, participant_id: str
    ) -> TableParticipant:
        world_id, table_id, participant_id = (
            _identity(world_id),
            _identity(table_id),
            _identity(participant_id),
        )
        with self._transaction() as (records, now):
            record = next(
                (
                    row
                    for row in records
                    if (row.world_id, row.table_id, row.participant_id)
                    == (world_id, table_id, participant_id)
                    and row.status == "redeemed"
                ),
                None,
            )
            if record is None:
                raise InvitationAuthenticationError()
            participant = record.public(now).participant
            assert participant is not None
            return participant


__all__ = [
    "INVITATION_TTL_SECONDS",
    "MAX_ACTIVE_WORLD_GUESTS",
    "MAX_WORLD_INVITATIONS",
    "WORLD_INVITATION_STORE_SCHEMA_VERSION",
    "InvitationAuthenticationError",
    "InvitationBinding",
    "InvitationCommandConflictError",
    "InvitationIssuance",
    "InvitationIssueCommand",
    "InvitationJoinCommand",
    "InvitationLimitError",
    "InvitationNotFoundError",
    "InvitationPublic",
    "InvitationRole",
    "SQLiteWorldInvitationStore",
    "WorldInvitationCorruptionError",
    "WorldInvitationSchemaError",
    "WorldInvitationStoreError",
]
