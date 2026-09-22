"""Tamper-evident first-run administration and session storage for the VTT.

This module deliberately has no HTTP, browser, world, or table dependencies.  Its
only secret-bearing return object is :class:`SessionIssuance`, which releases an
opaque bearer once and redacts it from representations.  Durable storage contains
salted scrypt verifiers for human-entered secrets and hashes for random bearers.

The event log and a separately chained, AUTOINCREMENT-backed anchor log detect
partial edits, tail deletion, and mutable-head rewinds.  No integrity structure
stored in the database itself can detect a coordinated rollback of the entire
database file (including ``sqlite_sequence``) to an older valid snapshot; that
threat requires an external signed anchor or trusted backup generation counter.
Likewise, an actor with arbitrary database write access can recompute these
unkeyed records; operating-system access controls or an external keyed signature
are required against that stronger attacker.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import sqlite3
import time
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from .installation_contracts import (
    AdminPublic,
    AuthenticationAttemptBudget,
    InstallationView,
    ScryptParameters,
    SessionPublic,
)

INSTALLATION_STORE_SCHEMA_VERSION = "vtt.installation_store.v1"
INSTALLATION_EVENT_SCHEMA_VERSION = "vtt.installation_event.v1"
logger = logging.getLogger(__name__)

_METADATA_TABLE = "_vtt_installation_metadata"
_HEAD_TABLE = "_vtt_installation_head"
_EVENTS_TABLE = "_vtt_installation_events"
_ANCHORS_TABLE = "_vtt_installation_anchors"
_EXPECTED_TABLES = {_METADATA_TABLE, _HEAD_TABLE, _EVENTS_TABLE, _ANCHORS_TABLE}

_SALT_BYTES = 16
_ADMIN_ID_BYTES = 16
_SESSION_ID_BYTES = 16
_BEARER_BYTES = 32
_MAX_ENTROPY_ATTEMPTS = 16
_DEFAULT_SESSION_TTL_SECONDS = 3_600
_MIN_SESSION_TTL_SECONDS = 60
_MAX_SESSION_TTL_SECONDS = 86_400
_GENERIC_AUTHENTICATION_FAILURE = "authentication failed"
_SAFE_MODE_FAILURE = "installation is in read-only safe mode"


class InstallationStoreError(RuntimeError):
    """Base error for the installation identity boundary."""


class BootstrapClaimError(InstallationStoreError):
    pass


class InstallationAlreadyInitializedError(InstallationStoreError):
    pass


class InstallationSafeModeError(InstallationStoreError):
    pass


class InstallationIntegrityError(InstallationStoreError):
    pass


class AuthenticationError(InstallationStoreError):
    pass


class SessionBearerConsumedError(InstallationStoreError):
    pass


class EntropySourceError(InstallationStoreError):
    pass


class _StrictStoredModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _validate_human_text(
    value: Any,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    if value != value.strip() or not minimum <= len(value) <= maximum:
        raise ValueError(
            f"{field_name} must contain {minimum} to {maximum} characters "
            "without surrounding whitespace"
        )
    if unicodedata.normalize("NFKC", value) != value:
        raise ValueError(f"{field_name} must use canonical NFKC Unicode")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError(f"{field_name} contains an unsupported character")
    return value


def _validated_password(value: Any) -> str:
    value = _validate_human_text(
        value,
        field_name="password",
        minimum=12,
        maximum=256,
    )
    if len(value.encode("utf-8")) > 1_024:
        raise ValueError("password UTF-8 representation is too large")
    return value


def _redacted_secret_input(value: Any) -> SecretStr:
    if isinstance(value, SecretStr):
        return value
    return SecretStr(value if isinstance(value, str) else "")


def _redacted_admin_payload(payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return payload
    copied = dict(payload)
    if "password" in copied:
        copied["password"] = _redacted_secret_input(copied["password"])
    return copied


class _AdminSetupPayload(_StrictStoredModel):
    username: str
    display_name: str
    password: SecretStr

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return _validate_human_text(
            value,
            field_name="username",
            minimum=3,
            maximum=64,
        )

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        return _validate_human_text(
            value,
            field_name="display_name",
            minimum=1,
            maximum=80,
        )

    @field_validator("password", mode="before")
    @classmethod
    def validate_password(cls, value: Any) -> SecretStr:
        secret = _redacted_secret_input(value)
        return SecretStr(_validated_password(secret.get_secret_value()))


class _PasswordPayload(_StrictStoredModel):
    password: SecretStr

    @field_validator("password", mode="before")
    @classmethod
    def validate_password(cls, value: Any) -> SecretStr:
        secret = _redacted_secret_input(value)
        return SecretStr(_validated_password(secret.get_secret_value()))


class _StoredEventBase(_StrictStoredModel):
    schema_version: Literal[INSTALLATION_EVENT_SCHEMA_VERSION] = INSTALLATION_EVENT_SCHEMA_VERSION
    revision: Annotated[int, Field(strict=True, ge=1)]
    occurred_at: Annotated[int, Field(strict=True, ge=0)]


class _InitializedEvent(_StoredEventBase):
    event_type: Literal["initialized"] = "initialized"
    admin: AdminPublic
    password_salt_hex: str
    password_verifier_hex: str
    password_scrypt: ScryptParameters

    @field_validator("password_salt_hex")
    @classmethod
    def validate_salt(cls, value: str) -> str:
        return _validate_hex(value, field_name="password_salt_hex", byte_count=_SALT_BYTES)

    @field_validator("password_verifier_hex")
    @classmethod
    def validate_verifier(cls, value: str, info: Any) -> str:
        del info
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64,128}", value) is None:
            raise ValueError("password_verifier_hex is invalid")
        return value

    @model_validator(mode="after")
    def validate_verifier_length(self) -> "_InitializedEvent":
        if len(self.password_verifier_hex) != self.password_scrypt.dklen * 2:
            raise ValueError("password verifier length does not match scrypt parameters")
        if self.admin.created_at != self.occurred_at:
            raise ValueError("administrator creation time must match initialization time")
        return self


class _SessionIssuedEvent(_StoredEventBase):
    event_type: Literal["session_issued"] = "session_issued"
    session: SessionPublic
    token_hash: str

    @field_validator("token_hash")
    @classmethod
    def validate_token_hash(cls, value: str) -> str:
        return _validate_hex(value, field_name="token_hash", byte_count=32)

    @model_validator(mode="after")
    def validate_issue_time(self) -> "_SessionIssuedEvent":
        if self.session.issued_at != self.occurred_at or self.session.revoked:
            raise ValueError("issued session metadata is inconsistent")
        return self


class _SessionRevokedEvent(_StoredEventBase):
    event_type: Literal["session_revoked"] = "session_revoked"
    session_id: str
    admin_id: str

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        if not isinstance(value, str) or re.fullmatch(r"ses_[A-Za-z0-9_-]+", value) is None:
            raise ValueError("session_id is invalid")
        return value

    @field_validator("admin_id")
    @classmethod
    def validate_admin_id(cls, value: str) -> str:
        if not isinstance(value, str) or re.fullmatch(r"adm_[A-Za-z0-9_-]+", value) is None:
            raise ValueError("admin_id is invalid")
        return value


class _PasswordChangedEvent(_StoredEventBase):
    event_type: Literal["password_changed"] = "password_changed"
    admin_id: str
    password_salt_hex: str
    password_verifier_hex: str
    password_scrypt: ScryptParameters

    @field_validator("admin_id")
    @classmethod
    def validate_admin_id(cls, value: str) -> str:
        if not isinstance(value, str) or re.fullmatch(r"adm_[A-Za-z0-9_-]+", value) is None:
            raise ValueError("admin_id is invalid")
        return value

    @field_validator("password_salt_hex")
    @classmethod
    def validate_salt(cls, value: str) -> str:
        return _validate_hex(value, field_name="password_salt_hex", byte_count=_SALT_BYTES)

    @field_validator("password_verifier_hex")
    @classmethod
    def validate_verifier(cls, value: str) -> str:
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64,128}", value) is None:
            raise ValueError("password_verifier_hex is invalid")
        return value

    @model_validator(mode="after")
    def validate_verifier_length(self) -> "_PasswordChangedEvent":
        if len(self.password_verifier_hex) != self.password_scrypt.dklen * 2:
            raise ValueError("password verifier length does not match scrypt parameters")
        return self


_StoredEvent: TypeAlias = Annotated[
    _InitializedEvent | _SessionIssuedEvent | _SessionRevokedEvent | _PasswordChangedEvent,
    Field(discriminator="event_type"),
]
_STORED_EVENT_ADAPTER = TypeAdapter(_StoredEvent)


@dataclass(frozen=True, slots=True)
class _Metadata:
    bootstrap_salt_hex: str
    bootstrap_verifier_hex: str
    bootstrap_scrypt: ScryptParameters


@dataclass(frozen=True, slots=True)
class _Credential:
    salt_hex: str
    verifier_hex: str
    parameters: ScryptParameters


@dataclass(frozen=True, slots=True)
class _SessionState:
    session: SessionPublic
    token_hash: str
    revoked: bool

    def public(self) -> SessionPublic:
        return self.session.model_copy(update={"revoked": self.revoked})


@dataclass(frozen=True, slots=True)
class _InstallationState:
    revision: int
    admin: AdminPublic | None
    credential: _Credential | None
    sessions: dict[str, _SessionState]
    password_changed_at: int | None


@dataclass(slots=True)
class _AttemptWindow:
    started_at: int
    failures: int


class SessionIssuance:
    """Ephemeral one-shot bearer delivery paired with secret-free metadata."""

    __slots__ = ("_bearer", "session")

    def __init__(self, *, session: SessionPublic, bearer: str) -> None:
        self.session = session
        self._bearer: str | None = bearer

    def consume_bearer(self) -> str:
        bearer = self._bearer
        if bearer is None:
            raise SessionBearerConsumedError("session bearer was already consumed")
        self._bearer = None
        return bearer

    def __repr__(self) -> str:
        return f"SessionIssuance(session={self.session!r}, bearer=<redacted>)"


def _validate_hex(value: Any, *, field_name: str, byte_count: int) -> str:
    if not isinstance(value, str) or re.fullmatch(rf"[0-9a-f]{{{byte_count * 2}}}", value) is None:
        raise ValueError(f"{field_name} is invalid")
    return value


def _canonical_json(model: BaseModel) -> str:
    return json.dumps(
        model.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _parse_json(encoded: Any, *, field_name: str) -> Any:
    if not isinstance(encoded, str):
        raise InstallationIntegrityError(f"stored {field_name} is invalid")
    try:
        return json.loads(
            encoded,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InstallationIntegrityError(f"stored {field_name} is invalid") from exc


def _derive_secret(
    secret: bytes,
    *,
    salt: bytes,
    parameters: ScryptParameters,
) -> bytes:
    max_memory = max(64 * 1024 * 1024, 256 * parameters.n * parameters.r)
    return hashlib.scrypt(
        secret,
        salt=salt,
        n=parameters.n,
        r=parameters.r,
        p=parameters.p,
        maxmem=max_memory,
        dklen=parameters.dklen,
    )


def _token_hash(bearer: Any) -> str:
    if not isinstance(bearer, str) or not 1 <= len(bearer) <= 256:
        bearer = "invalid-session-bearer"
    try:
        encoded = bearer.encode("utf-8")
    except UnicodeError:
        encoded = b"invalid-session-bearer"
    return hashlib.sha256(b"dnd-sim-vtt-session-v1\0" + encoded).hexdigest()


def _event_hash(*, revision: int, event_json: str, previous_hash: str) -> str:
    payload = json.dumps(
        {
            "event_json": event_json,
            "previous_hash": previous_hash,
            "revision": revision,
            "store_schema_version": INSTALLATION_STORE_SCHEMA_VERSION,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _anchor_hash(*, revision: int, event_entry_hash: str, previous_anchor_hash: str) -> str:
    payload = json.dumps(
        {
            "event_entry_hash": event_entry_hash,
            "previous_anchor_hash": previous_anchor_hash,
            "revision": revision,
            "store_schema_version": INSTALLATION_STORE_SCHEMA_VERSION,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(b"dnd-sim-vtt-installation-anchor-v1\0" + payload).hexdigest()


def _genesis_hash(metadata: _Metadata) -> str:
    payload = json.dumps(
        {
            "bootstrap_salt_hex": metadata.bootstrap_salt_hex,
            "bootstrap_scrypt": metadata.bootstrap_scrypt.model_dump(mode="json"),
            "bootstrap_verifier_hex": metadata.bootstrap_verifier_hex,
            "store_schema_version": INSTALLATION_STORE_SCHEMA_VERSION,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(b"dnd-sim-vtt-installation-genesis-v1\0" + payload).hexdigest()


class SQLiteInstallationStore:
    """Single-installation administration and bearer-session authority."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        bootstrap_claim: str | None = None,
        clock: Callable[[], int] | None = None,
        random_bytes: Callable[[int], bytes] | None = None,
        scrypt_parameters: ScryptParameters | None = None,
        attempt_budget: AuthenticationAttemptBudget | None = None,
        session_ttl_seconds: int = _DEFAULT_SESSION_TTL_SECONDS,
    ) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        if connection.in_transaction:
            raise InstallationStoreError(
                "cannot initialize installation storage inside an active transaction"
            )
        if type(session_ttl_seconds) is not int or not (
            _MIN_SESSION_TTL_SECONDS <= session_ttl_seconds <= _MAX_SESSION_TTL_SECONDS
        ):
            raise ValueError(
                f"session_ttl_seconds must be {_MIN_SESSION_TTL_SECONDS} to "
                f"{_MAX_SESSION_TTL_SECONDS}"
            )

        self._connection = connection
        self._clock = clock or (lambda: int(time.time()))
        self._random_bytes = random_bytes or secrets.token_bytes
        self._scrypt_parameters = scrypt_parameters or ScryptParameters()
        self._attempt_budget = attempt_budget or AuthenticationAttemptBudget()
        self._session_ttl_seconds = session_ttl_seconds
        self._attempts: dict[str, _AttemptWindow] = {}
        self._global_attempt: _AttemptWindow | None = None
        self._safe_mode = False
        self._now()
        self._open_or_provision(bootstrap_claim)

    def __repr__(self) -> str:
        state = "safe_mode" if self._safe_mode else "available"
        return f"SQLiteInstallationStore(state={state!r})"

    def view(self) -> InstallationView:
        if self._safe_mode:
            return self._safe_mode_view()
        try:
            state = self._read_public_state()
        except (InstallationIntegrityError, sqlite3.DatabaseError):
            self._safe_mode = True
            return self._safe_mode_view()
        if state.admin is None:
            return InstallationView(
                state="uninitialized",
                revision=state.revision,
                setup_claimed=False,
                active_admin_count=0,
                integrity_status="verified",
            )
        return InstallationView(
            state="ready",
            revision=state.revision,
            setup_claimed=True,
            active_admin_count=1,
            integrity_status="verified",
        )

    def admins(self) -> tuple[AdminPublic, ...]:
        state = self._require_readable_state()
        return () if state.admin is None else (state.admin,)

    def initialize(
        self,
        *,
        bootstrap_claim: str,
        admin_payload: Mapping[str, Any] | Any,
    ) -> AdminPublic:
        """Claim setup once, authenticating the claim before parsing admin input."""

        self._require_writable()
        now = self._now()
        if self._global_attempt_blocked(now):
            raise BootstrapClaimError("setup claim rejected")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            state, metadata = self._read_state_locked()
            if state.admin is not None:
                raise InstallationAlreadyInitializedError("installation is already initialized")
            if not self._bootstrap_matches(bootstrap_claim, metadata):
                self._record_global_attempt_failure(now)
                raise BootstrapClaimError("setup claim rejected")

            self._global_attempt = None
            # HTTP adapters may pass bounded raw bytes so even malformed JSON is
            # rejected only after authenticating the local operator's claim.
            if isinstance(admin_payload, (bytes, bytearray)):
                try:
                    admin_payload = json.loads(admin_payload)
                except (ValueError, UnicodeError, RecursionError):
                    raise ValueError("invalid administrator payload") from None
            payload = _AdminSetupPayload.model_validate(_redacted_admin_payload(admin_payload))
            occurred_at = now
            existing_random_values = self._stored_random_values(state, metadata)
            admin_id = "adm_" + self._new_unique_encoded(
                _ADMIN_ID_BYTES,
                existing=existing_random_values,
            )
            salt = self._new_unique_bytes(
                _SALT_BYTES,
                existing_hex=existing_random_values,
            )
            password = payload.password.get_secret_value().encode("utf-8")
            verifier = _derive_secret(
                password,
                salt=salt,
                parameters=self._scrypt_parameters,
            )
            admin = AdminPublic(
                admin_id=admin_id,
                username=payload.username,
                display_name=payload.display_name,
                created_at=occurred_at,
            )
            event = _InitializedEvent(
                revision=state.revision + 1,
                occurred_at=occurred_at,
                admin=admin,
                password_salt_hex=salt.hex(),
                password_verifier_hex=verifier.hex(),
                password_scrypt=self._scrypt_parameters,
            )
            self._append_event_locked(event)
            self._read_state_locked()
            self._connection.commit()
            return admin
        except (InstallationIntegrityError, sqlite3.DatabaseError) as exc:
            self._rollback()
            self._safe_mode = True
            raise InstallationSafeModeError(_SAFE_MODE_FAILURE) from exc
        except BaseException:
            self._rollback()
            raise

    def login(self, *, username: Any, password: Any) -> SessionIssuance:
        self._require_writable()
        now = self._now()
        principal_key = self._principal_attempt_key(username)
        if self._global_attempt_blocked(now) or self._attempt_blocked(principal_key, now):
            raise AuthenticationError(_GENERIC_AUTHENTICATION_FAILURE)

        rejected = False
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            state, metadata = self._read_state_locked()
            selected_admin = self._select_admin(state, username)
            credential = state.credential if selected_admin is not None else None
            if credential is None:
                candidate_salt = bytes.fromhex(metadata.bootstrap_salt_hex)
                candidate_parameters = metadata.bootstrap_scrypt
                expected_verifier = bytes.fromhex(metadata.bootstrap_verifier_hex)
            else:
                candidate_salt = bytes.fromhex(credential.salt_hex)
                candidate_parameters = credential.parameters
                expected_verifier = bytes.fromhex(credential.verifier_hex)

            password_bytes = self._login_password_bytes(password)
            actual_verifier = _derive_secret(
                password_bytes,
                salt=candidate_salt,
                parameters=candidate_parameters,
            )
            credential_matches = secrets.compare_digest(actual_verifier, expected_verifier)
            if selected_admin is None or not credential_matches:
                rejected = True
                raise AuthenticationError(_GENERIC_AUTHENTICATION_FAILURE)

            existing_random_values = self._stored_random_values(state, metadata)
            session_id = "ses_" + self._new_unique_encoded(
                _SESSION_ID_BYTES,
                existing=existing_random_values,
            )
            bearer = "vtt1_" + self._new_unique_encoded(
                _BEARER_BYTES,
                existing=existing_random_values,
            )
            token_hash = _token_hash(bearer)
            if token_hash in {session.token_hash for session in state.sessions.values()}:
                raise EntropySourceError("entropy source could not produce a unique value")
            session = SessionPublic(
                session_id=session_id,
                admin_id=selected_admin.admin_id,
                issued_at=now,
                expires_at=now + self._session_ttl_seconds,
                revoked=False,
            )
            event = _SessionIssuedEvent(
                revision=state.revision + 1,
                occurred_at=now,
                session=session,
                token_hash=token_hash,
            )
            self._append_event_locked(event)
            self._read_state_locked()
            self._connection.commit()
            self._attempts.pop(principal_key, None)
            self._global_attempt = None
            return SessionIssuance(session=session, bearer=bearer)
        except AuthenticationError:
            self._rollback()
            if rejected:
                self._record_attempt_failure(principal_key, now)
                self._record_global_attempt_failure(now)
            raise AuthenticationError(_GENERIC_AUTHENTICATION_FAILURE) from None
        except (InstallationIntegrityError, sqlite3.DatabaseError) as exc:
            self._rollback()
            self._safe_mode = True
            raise InstallationSafeModeError(_SAFE_MODE_FAILURE) from exc
        except BaseException:
            self._rollback()
            raise

    def authenticate_session(self, bearer: Any) -> SessionPublic:
        state = self._require_readable_state()
        return self._authenticate_in_state(state, bearer, now=self._now())

    def sessions(self, *, admin_bearer: Any) -> tuple[SessionPublic, ...]:
        state = self._require_readable_state()
        caller = self._authenticate_in_state(state, admin_bearer, now=self._now())
        return tuple(
            session.public()
            for _, session in sorted(state.sessions.items())
            if session.session.admin_id == caller.admin_id
        )

    def revoke_session(
        self,
        admin_bearer: Any,
        *,
        session_id: Any | None = None,
    ) -> SessionPublic:
        """Revoke the caller's session or another session owned by that administrator."""

        self._require_writable()
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            state, _ = self._read_state_locked()
            now = self._now()
            authenticated = self._authenticate_in_state(state, admin_bearer, now=now)
            target_id = authenticated.session_id if session_id is None else session_id
            target = state.sessions.get(target_id) if isinstance(target_id, str) else None
            if (
                target is None
                or target.revoked
                or target.session.admin_id != authenticated.admin_id
            ):
                raise AuthenticationError(_GENERIC_AUTHENTICATION_FAILURE)
            event = _SessionRevokedEvent(
                revision=state.revision + 1,
                occurred_at=now,
                session_id=target.session.session_id,
                admin_id=authenticated.admin_id,
            )
            self._append_event_locked(event)
            resulting_state, _ = self._read_state_locked()
            self._connection.commit()
            return resulting_state.sessions[target.session.session_id].public()
        except AuthenticationError:
            self._rollback()
            raise AuthenticationError(_GENERIC_AUTHENTICATION_FAILURE) from None
        except (InstallationIntegrityError, sqlite3.DatabaseError) as exc:
            self._rollback()
            self._safe_mode = True
            raise InstallationSafeModeError(_SAFE_MODE_FAILURE) from exc
        except BaseException:
            self._rollback()
            raise

    def change_password(self, admin_bearer: Any, *, new_password: Any) -> AdminPublic:
        """Change the sole admin password and invalidate all existing sessions."""

        self._require_writable()
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            state, metadata = self._read_state_locked()
            now = self._now()
            authenticated = self._authenticate_in_state(state, admin_bearer, now=now)
            payload = _PasswordPayload.model_validate(
                {"password": _redacted_secret_input(new_password)}
            )
            existing_random_values = self._stored_random_values(state, metadata)
            salt = self._new_unique_bytes(
                _SALT_BYTES,
                existing_hex=existing_random_values,
            )
            verifier = _derive_secret(
                payload.password.get_secret_value().encode("utf-8"),
                salt=salt,
                parameters=self._scrypt_parameters,
            )
            event = _PasswordChangedEvent(
                revision=state.revision + 1,
                occurred_at=now,
                admin_id=authenticated.admin_id,
                password_salt_hex=salt.hex(),
                password_verifier_hex=verifier.hex(),
                password_scrypt=self._scrypt_parameters,
            )
            self._append_event_locked(event)
            self._read_state_locked()
            self._connection.commit()
            if state.admin is None:  # pragma: no cover - protected by authentication
                raise InstallationIntegrityError("authenticated administrator is missing")
            return state.admin
        except AuthenticationError:
            self._rollback()
            raise AuthenticationError(_GENERIC_AUTHENTICATION_FAILURE) from None
        except (InstallationIntegrityError, sqlite3.DatabaseError) as exc:
            self._rollback()
            self._safe_mode = True
            raise InstallationSafeModeError(_SAFE_MODE_FAILURE) from exc
        except BaseException:
            self._rollback()
            raise

    def _open_or_provision(self, bootstrap_claim: str | None) -> None:
        existing_tables = {
            str(row[0])
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            if str(row[0]) in _EXPECTED_TABLES
        }
        if existing_tables and existing_tables != _EXPECTED_TABLES:
            self._safe_mode = True
            return
        if existing_tables == _EXPECTED_TABLES:
            try:
                self._read_public_state()
            except (InstallationIntegrityError, sqlite3.DatabaseError):
                self._safe_mode = True
            return

        claim_bytes = self._provisioning_claim_bytes(bootstrap_claim)
        salt = self._entropy(_SALT_BYTES)
        verifier = _derive_secret(
            claim_bytes,
            salt=salt,
            parameters=self._scrypt_parameters,
        )
        metadata = _Metadata(
            bootstrap_salt_hex=salt.hex(),
            bootstrap_verifier_hex=verifier.hex(),
            bootstrap_scrypt=self._scrypt_parameters,
        )
        parameters_json = json.dumps(
            self._scrypt_parameters.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(f"""
                CREATE TABLE {_METADATA_TABLE} (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    schema_version TEXT NOT NULL,
                    bootstrap_salt_hex TEXT NOT NULL,
                    bootstrap_verifier_hex TEXT NOT NULL,
                    bootstrap_scrypt_json TEXT NOT NULL
                )
                """)
            self._connection.execute(f"""
                CREATE TABLE {_HEAD_TABLE} (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    revision INTEGER NOT NULL CHECK (revision >= 0),
                    head_hash TEXT NOT NULL CHECK (length(head_hash) = 64)
                )
                """)
            self._connection.execute(f"""
                CREATE TABLE {_EVENTS_TABLE} (
                    store_schema_version TEXT NOT NULL,
                    revision INTEGER PRIMARY KEY CHECK (revision >= 1),
                    event_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL CHECK (length(previous_hash) = 64),
                    entry_hash TEXT NOT NULL CHECK (length(entry_hash) = 64),
                    CHECK (length(trim(event_json)) > 0)
                )
                """)
            self._connection.execute(f"""
                CREATE TABLE {_ANCHORS_TABLE} (
                    store_schema_version TEXT NOT NULL,
                    revision INTEGER PRIMARY KEY AUTOINCREMENT CHECK (revision >= 1),
                    event_entry_hash TEXT NOT NULL CHECK (length(event_entry_hash) = 64),
                    previous_anchor_hash TEXT NOT NULL CHECK (length(previous_anchor_hash) = 64),
                    anchor_hash TEXT NOT NULL CHECK (length(anchor_hash) = 64)
                )
                """)
            self._connection.execute(
                f"""
                INSERT INTO {_METADATA_TABLE} (
                    singleton,
                    schema_version,
                    bootstrap_salt_hex,
                    bootstrap_verifier_hex,
                    bootstrap_scrypt_json
                ) VALUES (1, ?, ?, ?, ?)
                """,
                (
                    INSTALLATION_STORE_SCHEMA_VERSION,
                    metadata.bootstrap_salt_hex,
                    metadata.bootstrap_verifier_hex,
                    parameters_json,
                ),
            )
            self._connection.execute(
                f"INSERT INTO {_HEAD_TABLE} (singleton, revision, head_hash) VALUES (1, 0, ?)",
                (_genesis_hash(metadata),),
            )
            self._read_state_locked()
            self._connection.commit()
        except BaseException:
            self._rollback()
            raise

    def _read_public_state(self) -> _InstallationState:
        if self._connection.in_transaction:
            raise InstallationStoreError("cannot read installation state inside a transaction")
        try:
            self._connection.execute("BEGIN")
            state, _ = self._read_state_locked()
            self._connection.commit()
            return state
        except BaseException:
            self._rollback()
            raise

    def _read_state_locked(self) -> tuple[_InstallationState, _Metadata]:
        metadata = self._read_metadata_locked()
        head = self._connection.execute(
            f"SELECT revision, head_hash FROM {_HEAD_TABLE} WHERE singleton = 1"
        ).fetchone()
        if head is None or len(head) != 2:
            raise InstallationIntegrityError("installation head is missing")
        revision = self._stored_non_negative_int(head[0], field_name="head revision")
        head_hash = self._stored_hash(head[1], field_name="head hash")
        rows = self._connection.execute(f"""
            SELECT store_schema_version, revision, event_json, previous_hash, entry_hash
            FROM {_EVENTS_TABLE}
            ORDER BY revision ASC
            """).fetchall()
        if len(rows) != revision:
            raise InstallationIntegrityError("installation event count does not match head")

        admin: AdminPublic | None = None
        credential: _Credential | None = None
        sessions: dict[str, _SessionState] = {}
        password_changed_at: int | None = None
        previous_hash = _genesis_hash(metadata)
        event_entry_hashes: list[str] = []
        previous_time = 0
        for expected_revision, row in enumerate(rows, start=1):
            if len(row) != 5 or row[0] != INSTALLATION_STORE_SCHEMA_VERSION:
                raise InstallationIntegrityError("stored installation event schema is invalid")
            stored_revision = self._stored_positive_int(
                row[1],
                field_name="event revision",
            )
            if stored_revision != expected_revision:
                raise InstallationIntegrityError("installation event revisions are not contiguous")
            event_json = row[2]
            stored_previous_hash = self._stored_hash(row[3], field_name="previous hash")
            stored_entry_hash = self._stored_hash(row[4], field_name="entry hash")
            if stored_previous_hash != previous_hash:
                raise InstallationIntegrityError("installation event chain is discontinuous")
            expected_hash = _event_hash(
                revision=stored_revision,
                event_json=event_json,
                previous_hash=stored_previous_hash,
            )
            if not secrets.compare_digest(stored_entry_hash, expected_hash):
                raise InstallationIntegrityError("installation event integrity check failed")
            try:
                event = _STORED_EVENT_ADAPTER.validate_python(
                    _parse_json(event_json, field_name="event JSON")
                )
            except ValidationError as exc:
                raise InstallationIntegrityError("stored installation event is invalid") from exc
            if event.revision != stored_revision or _canonical_json(event) != event_json:
                raise InstallationIntegrityError("stored installation event is not canonical")
            if event.occurred_at < previous_time:
                raise InstallationIntegrityError("installation event time moved backwards")
            previous_time = event.occurred_at
            admin, credential, sessions, password_changed_at = self._apply_event(
                event,
                admin=admin,
                credential=credential,
                sessions=sessions,
                password_changed_at=password_changed_at,
            )
            previous_hash = stored_entry_hash
            event_entry_hashes.append(stored_entry_hash)

        if not secrets.compare_digest(previous_hash, head_hash):
            raise InstallationIntegrityError("installation head integrity check failed")
        self._verify_anchors_locked(
            revision=revision,
            genesis_hash=_genesis_hash(metadata),
            event_entry_hashes=event_entry_hashes,
        )
        if admin is None and revision != 0:
            raise InstallationIntegrityError("installation history lacks initialization")
        if admin is not None and credential is None:
            raise InstallationIntegrityError("administrator credential is missing")
        return (
            _InstallationState(
                revision=revision,
                admin=admin,
                credential=credential,
                sessions=sessions,
                password_changed_at=password_changed_at,
            ),
            metadata,
        )

    def _read_metadata_locked(self) -> _Metadata:
        rows = self._connection.execute(f"""
            SELECT schema_version, bootstrap_salt_hex, bootstrap_verifier_hex,
                   bootstrap_scrypt_json
            FROM {_METADATA_TABLE}
            """).fetchall()
        if len(rows) != 1 or len(rows[0]) != 4:
            raise InstallationIntegrityError("installation metadata is missing")
        schema_version, salt_hex, verifier_hex, parameters_json = rows[0]
        if schema_version != INSTALLATION_STORE_SCHEMA_VERSION:
            raise InstallationIntegrityError("installation metadata schema is unsupported")
        try:
            salt_hex = _validate_hex(
                salt_hex,
                field_name="bootstrap_salt_hex",
                byte_count=_SALT_BYTES,
            )
            parameters = ScryptParameters.model_validate(
                _parse_json(parameters_json, field_name="bootstrap scrypt parameters")
            )
            verifier_hex = _validate_hex(
                verifier_hex,
                field_name="bootstrap_verifier_hex",
                byte_count=parameters.dklen,
            )
        except (ValueError, ValidationError) as exc:
            raise InstallationIntegrityError("installation metadata is invalid") from exc
        canonical_parameters = json.dumps(
            parameters.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if canonical_parameters != parameters_json:
            raise InstallationIntegrityError("installation metadata is not canonical")
        return _Metadata(
            bootstrap_salt_hex=salt_hex,
            bootstrap_verifier_hex=verifier_hex,
            bootstrap_scrypt=parameters,
        )

    def _apply_event(
        self,
        event: _StoredEvent,
        *,
        admin: AdminPublic | None,
        credential: _Credential | None,
        sessions: dict[str, _SessionState],
        password_changed_at: int | None,
    ) -> tuple[
        AdminPublic | None,
        _Credential | None,
        dict[str, _SessionState],
        int | None,
    ]:
        next_sessions = dict(sessions)
        if isinstance(event, _InitializedEvent):
            if event.revision != 1 or admin is not None or credential is not None or sessions:
                raise InstallationIntegrityError("installation was initialized more than once")
            return (
                event.admin,
                _Credential(
                    salt_hex=event.password_salt_hex,
                    verifier_hex=event.password_verifier_hex,
                    parameters=event.password_scrypt,
                ),
                next_sessions,
                None,
            )
        if admin is None or credential is None:
            raise InstallationIntegrityError("installation event precedes initialization")
        if isinstance(event, _SessionIssuedEvent):
            if event.session.admin_id != admin.admin_id:
                raise InstallationIntegrityError("session references an unknown administrator")
            if event.session.session_id in next_sessions:
                raise InstallationIntegrityError("session identity was reused")
            if event.token_hash in {session.token_hash for session in next_sessions.values()}:
                raise InstallationIntegrityError("session token hash was reused")
            if password_changed_at is not None and event.occurred_at < password_changed_at:
                raise InstallationIntegrityError("session predates the current credential epoch")
            next_sessions[event.session.session_id] = _SessionState(
                session=event.session,
                token_hash=event.token_hash,
                revoked=False,
            )
            return admin, credential, next_sessions, password_changed_at
        if isinstance(event, _SessionRevokedEvent):
            current = next_sessions.get(event.session_id)
            if (
                current is None
                or current.session.admin_id != event.admin_id
                or current.revoked
                or event.occurred_at < current.session.issued_at
            ):
                raise InstallationIntegrityError("session revocation is inconsistent")
            next_sessions[event.session_id] = _SessionState(
                session=current.session,
                token_hash=current.token_hash,
                revoked=True,
            )
            return admin, credential, next_sessions, password_changed_at
        if event.admin_id != admin.admin_id:
            raise InstallationIntegrityError("password change references an unknown administrator")
        next_sessions = {
            session_id: _SessionState(
                session=session.session,
                token_hash=session.token_hash,
                revoked=True,
            )
            for session_id, session in next_sessions.items()
        }
        return (
            admin,
            _Credential(
                salt_hex=event.password_salt_hex,
                verifier_hex=event.password_verifier_hex,
                parameters=event.password_scrypt,
            ),
            next_sessions,
            event.occurred_at,
        )

    def _append_event_locked(self, event: _StoredEvent) -> None:
        event_json = _canonical_json(event)
        head = self._connection.execute(
            f"SELECT revision, head_hash FROM {_HEAD_TABLE} WHERE singleton = 1"
        ).fetchone()
        if head is None or len(head) != 2:
            raise InstallationIntegrityError("installation head is missing")
        current_revision = self._stored_non_negative_int(head[0], field_name="head revision")
        previous_hash = self._stored_hash(head[1], field_name="head hash")
        if event.revision != current_revision + 1:
            raise InstallationIntegrityError("installation append revision is not contiguous")
        entry_hash = _event_hash(
            revision=event.revision,
            event_json=event_json,
            previous_hash=previous_hash,
        )
        anchor = self._connection.execute(f"""
            SELECT revision, anchor_hash
            FROM {_ANCHORS_TABLE}
            ORDER BY revision DESC
            LIMIT 1
            """).fetchone()
        if current_revision == 0:
            if anchor is not None:
                raise InstallationIntegrityError("installation anchor high-water is inconsistent")
            previous_anchor_hash = previous_hash
        else:
            if anchor is None or len(anchor) != 2 or anchor[0] != current_revision:
                raise InstallationIntegrityError("installation anchor high-water is inconsistent")
            previous_anchor_hash = self._stored_hash(
                anchor[1],
                field_name="anchor hash",
            )
        anchor_hash = _anchor_hash(
            revision=event.revision,
            event_entry_hash=entry_hash,
            previous_anchor_hash=previous_anchor_hash,
        )
        self._connection.execute(
            f"""
            INSERT INTO {_EVENTS_TABLE} (
                store_schema_version, revision, event_json, previous_hash, entry_hash
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                INSTALLATION_STORE_SCHEMA_VERSION,
                event.revision,
                event_json,
                previous_hash,
                entry_hash,
            ),
        )
        self._connection.execute(
            f"""
            INSERT INTO {_ANCHORS_TABLE} (
                store_schema_version,
                revision,
                event_entry_hash,
                previous_anchor_hash,
                anchor_hash
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                INSTALLATION_STORE_SCHEMA_VERSION,
                event.revision,
                entry_hash,
                previous_anchor_hash,
                anchor_hash,
            ),
        )
        cursor = self._connection.execute(
            f"""
            UPDATE {_HEAD_TABLE}
            SET revision = ?, head_hash = ?
            WHERE singleton = 1 AND revision = ? AND head_hash = ?
            """,
            (event.revision, entry_hash, current_revision, previous_hash),
        )
        if cursor.rowcount != 1:
            raise InstallationIntegrityError("installation head update conflicted")

    def _verify_anchors_locked(
        self,
        *,
        revision: int,
        genesis_hash: str,
        event_entry_hashes: list[str],
    ) -> None:
        rows = self._connection.execute(f"""
            SELECT store_schema_version, revision, event_entry_hash,
                   previous_anchor_hash, anchor_hash
            FROM {_ANCHORS_TABLE}
            ORDER BY revision ASC
            """).fetchall()
        if len(rows) != revision or len(event_entry_hashes) != revision:
            raise InstallationIntegrityError("installation anchor count is inconsistent")

        sequence = self._connection.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = ?",
            (_ANCHORS_TABLE,),
        ).fetchone()
        high_water = (
            0
            if sequence is None
            else self._stored_non_negative_int(
                sequence[0],
                field_name="anchor high-water",
            )
        )
        if high_water != revision:
            raise InstallationIntegrityError("installation anchor high-water is inconsistent")

        previous_anchor_hash = genesis_hash
        for expected_revision, (row, event_entry_hash) in enumerate(
            zip(rows, event_entry_hashes, strict=True),
            start=1,
        ):
            if len(row) != 5 or row[0] != INSTALLATION_STORE_SCHEMA_VERSION:
                raise InstallationIntegrityError("stored installation anchor schema is invalid")
            stored_revision = self._stored_positive_int(
                row[1],
                field_name="anchor revision",
            )
            stored_event_entry_hash = self._stored_hash(
                row[2],
                field_name="anchored event hash",
            )
            stored_previous_anchor_hash = self._stored_hash(
                row[3],
                field_name="previous anchor hash",
            )
            stored_anchor_hash = self._stored_hash(row[4], field_name="anchor hash")
            if stored_revision != expected_revision:
                raise InstallationIntegrityError("installation anchor revisions are not contiguous")
            if not secrets.compare_digest(stored_event_entry_hash, event_entry_hash):
                raise InstallationIntegrityError("installation anchor references another event")
            if not secrets.compare_digest(
                stored_previous_anchor_hash,
                previous_anchor_hash,
            ):
                raise InstallationIntegrityError("installation anchor chain is discontinuous")
            expected_anchor_hash = _anchor_hash(
                revision=stored_revision,
                event_entry_hash=stored_event_entry_hash,
                previous_anchor_hash=stored_previous_anchor_hash,
            )
            if not secrets.compare_digest(stored_anchor_hash, expected_anchor_hash):
                raise InstallationIntegrityError("installation anchor integrity check failed")
            previous_anchor_hash = stored_anchor_hash

    def _authenticate_in_state(
        self,
        state: _InstallationState,
        bearer: Any,
        *,
        now: int,
    ) -> SessionPublic:
        candidate_hash = _token_hash(bearer)
        selected: _SessionState | None = None
        for session in state.sessions.values():
            if secrets.compare_digest(candidate_hash, session.token_hash):
                selected = session
        if (
            selected is None
            or selected.revoked
            or now >= selected.session.expires_at
            or state.admin is None
            or selected.session.admin_id != state.admin.admin_id
        ):
            raise AuthenticationError(_GENERIC_AUTHENTICATION_FAILURE)
        return selected.public()

    @staticmethod
    def _select_admin(state: _InstallationState, username: Any) -> AdminPublic | None:
        if state.admin is None or not isinstance(username, str) or len(username) > 256:
            return None
        try:
            candidate_key = unicodedata.normalize("NFKC", username).casefold().encode("utf-8")
            actual_key = (
                unicodedata.normalize("NFKC", state.admin.username).casefold().encode("utf-8")
            )
        except UnicodeError:
            return None
        return state.admin if secrets.compare_digest(candidate_key, actual_key) else None

    @staticmethod
    def _login_password_bytes(password: Any) -> bytes:
        try:
            return _validated_password(password).encode("utf-8")
        except (UnicodeError, ValueError):
            return b"invalid-password-candidate"

    @staticmethod
    def _provisioning_claim_bytes(claim: Any) -> bytes:
        try:
            claim = _validate_human_text(
                claim,
                field_name="bootstrap claim",
                minimum=24,
                maximum=512,
            )
            encoded = claim.encode("utf-8")
        except (UnicodeError, ValueError) as exc:
            raise BootstrapClaimError("a valid bootstrap claim is required") from exc
        if len(encoded) > 1_024:
            raise BootstrapClaimError("a valid bootstrap claim is required")
        return encoded

    @staticmethod
    def _bootstrap_candidate_bytes(claim: Any) -> bytes:
        try:
            claim = _validate_human_text(
                claim,
                field_name="bootstrap claim",
                minimum=24,
                maximum=512,
            )
            encoded = claim.encode("utf-8")
            return encoded if len(encoded) <= 1_024 else b"invalid-bootstrap-claim"
        except (UnicodeError, ValueError):
            return b"invalid-bootstrap-claim"

    def _bootstrap_matches(self, claim: Any, metadata: _Metadata) -> bool:
        actual = _derive_secret(
            self._bootstrap_candidate_bytes(claim),
            salt=bytes.fromhex(metadata.bootstrap_salt_hex),
            parameters=metadata.bootstrap_scrypt,
        )
        return secrets.compare_digest(actual, bytes.fromhex(metadata.bootstrap_verifier_hex))

    def _stored_random_values(
        self,
        state: _InstallationState,
        metadata: _Metadata,
    ) -> set[str]:
        values = {metadata.bootstrap_salt_hex}
        if state.admin is not None:
            values.add(state.admin.admin_id.removeprefix("adm_"))
        if state.credential is not None:
            values.add(state.credential.salt_hex)
        for session in state.sessions.values():
            values.add(session.session.session_id.removeprefix("ses_"))
            values.add(session.token_hash)
        return values

    def _new_unique_bytes(self, size: int, *, existing_hex: set[str]) -> bytes:
        for _ in range(_MAX_ENTROPY_ATTEMPTS):
            value = self._entropy(size)
            if value.hex() not in existing_hex:
                return value
        raise EntropySourceError("entropy source could not produce a unique value")

    def _new_unique_encoded(self, size: int, *, existing: set[str]) -> str:
        for _ in range(_MAX_ENTROPY_ATTEMPTS):
            value = base64.urlsafe_b64encode(self._entropy(size)).rstrip(b"=").decode("ascii")
            if value not in existing:
                return value
        raise EntropySourceError("entropy source could not produce a unique value")

    def _entropy(self, size: int) -> bytes:
        try:
            value = self._random_bytes(size)
        except BaseException:
            raise
        if not isinstance(value, bytes) or len(value) != size:
            raise EntropySourceError("entropy source returned an invalid value")
        return value

    def _now(self) -> int:
        value = self._clock()
        if type(value) is not int or value < 0:
            raise TypeError("clock must return a non-negative integer epoch")
        return value

    def _principal_attempt_key(self, username: Any) -> str:
        if isinstance(username, str) and len(username) <= 256:
            try:
                value = unicodedata.normalize("NFKC", username).casefold().encode("utf-8")
            except UnicodeError:
                value = b"invalid-principal"
        else:
            value = b"invalid-principal"
        return hashlib.sha256(b"dnd-sim-vtt-login-budget-v1\0" + value).hexdigest()

    def _attempt_blocked(self, principal_key: str, now: int) -> bool:
        attempt = self._attempts.get(principal_key)
        if attempt is None:
            return False
        if now - attempt.started_at >= self._attempt_budget.window_seconds:
            self._attempts.pop(principal_key, None)
            return False
        return attempt.failures >= self._attempt_budget.maximum_failures

    def _global_attempt_blocked(self, now: int) -> bool:
        attempt = self._global_attempt
        if attempt is None:
            return False
        if now - attempt.started_at >= self._attempt_budget.global_window_seconds:
            self._global_attempt = None
            return False
        return attempt.failures >= self._attempt_budget.global_maximum_failures

    def _record_attempt_failure(self, principal_key: str, now: int) -> None:
        attempt = self._attempts.get(principal_key)
        if attempt is None or now - attempt.started_at >= self._attempt_budget.window_seconds:
            if attempt is None and len(self._attempts) >= self._attempt_budget.maximum_principals:
                oldest_key = min(
                    self._attempts,
                    key=lambda key: (self._attempts[key].started_at, key),
                )
                self._attempts.pop(oldest_key, None)
            self._attempts[principal_key] = _AttemptWindow(started_at=now, failures=1)
            return
        attempt.failures = min(attempt.failures + 1, self._attempt_budget.maximum_failures)

    def _record_global_attempt_failure(self, now: int) -> None:
        attempt = self._global_attempt
        if (
            attempt is None
            or now - attempt.started_at >= self._attempt_budget.global_window_seconds
        ):
            self._global_attempt = _AttemptWindow(started_at=now, failures=1)
            return
        attempt.failures = min(
            attempt.failures + 1,
            self._attempt_budget.global_maximum_failures,
        )

    def _require_readable_state(self) -> _InstallationState:
        self._require_writable()
        try:
            return self._read_public_state()
        except (InstallationIntegrityError, sqlite3.DatabaseError) as exc:
            self._safe_mode = True
            raise InstallationSafeModeError(_SAFE_MODE_FAILURE) from exc

    def _require_writable(self) -> None:
        if self._safe_mode:
            raise InstallationSafeModeError(_SAFE_MODE_FAILURE)

    @staticmethod
    def _stored_non_negative_int(value: Any, *, field_name: str) -> int:
        if type(value) is not int or value < 0:
            raise InstallationIntegrityError(f"stored {field_name} is invalid")
        return value

    @staticmethod
    def _stored_positive_int(value: Any, *, field_name: str) -> int:
        if type(value) is not int or value < 1:
            raise InstallationIntegrityError(f"stored {field_name} is invalid")
        return value

    @staticmethod
    def _stored_hash(value: Any, *, field_name: str) -> str:
        try:
            return _validate_hex(value, field_name=field_name, byte_count=32)
        except ValueError as exc:
            raise InstallationIntegrityError(f"stored {field_name} is invalid") from exc

    def _rollback(self) -> None:
        if self._connection.in_transaction:
            self._connection.rollback()

    @staticmethod
    def _safe_mode_view() -> InstallationView:
        return InstallationView(
            state="safe_mode",
            revision=0,
            setup_claimed=None,
            active_admin_count=None,
            integrity_status="failed",
        )
