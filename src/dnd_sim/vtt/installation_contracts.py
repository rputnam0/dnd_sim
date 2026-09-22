"""Secret-free public contracts for standalone VTT installation identity."""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

INSTALLATION_VIEW_SCHEMA_VERSION = "vtt.installation_view.v1"
ADMIN_PUBLIC_SCHEMA_VERSION = "vtt.admin_public.v1"
SESSION_PUBLIC_SCHEMA_VERSION = "vtt.admin_session_public.v1"
SCRYPT_PARAMETERS_SCHEMA_VERSION = "vtt.scrypt_parameters.v1"
ATTEMPT_BUDGET_SCHEMA_VERSION = "vtt.authentication_attempt_budget.v1"

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _canonical_text(value: Any, *, field_name: str, minimum: int, maximum: int) -> str:
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


def _opaque_id(value: Any, *, field_name: str, prefix: str) -> str:
    value = _canonical_text(value, field_name=field_name, minimum=len(prefix) + 1, maximum=128)
    if re.fullmatch(rf"{re.escape(prefix)}[A-Za-z0-9_-]+", value) is None:
        raise ValueError(f"{field_name} must be an opaque {prefix} identifier")
    return value


class ScryptParameters(_StrictFrozenModel):
    """Explicitly bounded password derivation parameters persisted per verifier."""

    schema_version: Literal[SCRYPT_PARAMETERS_SCHEMA_VERSION] = SCRYPT_PARAMETERS_SCHEMA_VERSION
    n: Annotated[int, Field(strict=True, ge=2**14, le=2**17)] = 2**14
    r: Annotated[int, Field(strict=True, ge=8, le=16)] = 8
    p: Annotated[int, Field(strict=True, ge=1, le=4)] = 1
    dklen: Annotated[int, Field(strict=True, ge=32, le=64)] = 32

    @field_validator("n")
    @classmethod
    def validate_power_of_two(cls, value: int) -> int:
        if value & (value - 1):
            raise ValueError("n must be a power of two")
        return value


class AuthenticationAttemptBudget(_StrictFrozenModel):
    """Pure, bounded login throttling policy for a single process."""

    schema_version: Literal[ATTEMPT_BUDGET_SCHEMA_VERSION] = ATTEMPT_BUDGET_SCHEMA_VERSION
    maximum_failures: Annotated[int, Field(strict=True, ge=1, le=20)] = 5
    window_seconds: Annotated[int, Field(strict=True, ge=10, le=3_600)] = 60
    maximum_principals: Annotated[int, Field(strict=True, ge=16, le=10_000)] = 1_024
    global_maximum_failures: Annotated[int, Field(strict=True, ge=1, le=100)] = 20
    global_window_seconds: Annotated[int, Field(strict=True, ge=10, le=3_600)] = 60


class AdminPublic(_StrictFrozenModel):
    """Public administrator metadata. Credential material is deliberately absent."""

    schema_version: Literal[ADMIN_PUBLIC_SCHEMA_VERSION] = ADMIN_PUBLIC_SCHEMA_VERSION
    admin_id: str
    username: str
    display_name: str
    created_at: NonNegativeInt

    @field_validator("admin_id")
    @classmethod
    def validate_admin_id(cls, value: str) -> str:
        return _opaque_id(value, field_name="admin_id", prefix="adm_")

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return _canonical_text(value, field_name="username", minimum=3, maximum=64)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        return _canonical_text(value, field_name="display_name", minimum=1, maximum=80)


class SessionPublic(_StrictFrozenModel):
    """A secret-free description of an administrator session."""

    schema_version: Literal[SESSION_PUBLIC_SCHEMA_VERSION] = SESSION_PUBLIC_SCHEMA_VERSION
    session_id: str
    admin_id: str
    issued_at: NonNegativeInt
    expires_at: PositiveInt
    revoked: bool = False

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        return _opaque_id(value, field_name="session_id", prefix="ses_")

    @field_validator("admin_id")
    @classmethod
    def validate_admin_id(cls, value: str) -> str:
        return _opaque_id(value, field_name="admin_id", prefix="adm_")

    @field_validator("revoked", mode="before")
    @classmethod
    def validate_revoked(cls, value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError("revoked must be a boolean")
        return value

    @model_validator(mode="after")
    def validate_lifetime(self) -> "SessionPublic":
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        return self


class InstallationView(_StrictFrozenModel):
    """Fail-closed, secret-free public installation state."""

    schema_version: Literal[INSTALLATION_VIEW_SCHEMA_VERSION] = INSTALLATION_VIEW_SCHEMA_VERSION
    state: Literal["uninitialized", "ready", "safe_mode"]
    revision: NonNegativeInt
    setup_claimed: bool | None
    active_admin_count: NonNegativeInt | None
    integrity_status: Literal["verified", "failed"]

    @field_validator("setup_claimed", mode="before")
    @classmethod
    def validate_setup_claimed(cls, value: Any) -> bool | None:
        if value is not None and not isinstance(value, bool):
            raise ValueError("setup_claimed must be a boolean or null")
        return value

    @model_validator(mode="after")
    def validate_state_claims(self) -> "InstallationView":
        if self.state == "uninitialized":
            expected = (False, 0, "verified")
        elif self.state == "ready":
            if self.active_admin_count is None or self.active_admin_count < 1:
                raise ValueError("ready installation must have an active administrator")
            expected = (True, self.active_admin_count, "verified")
        else:
            expected = (None, None, "failed")
        actual = (self.setup_claimed, self.active_admin_count, self.integrity_status)
        if actual != expected:
            raise ValueError(f"{self.state} installation has inconsistent public state")
        return self
