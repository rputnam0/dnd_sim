"""Inert, provider-neutral contracts for importing external VTT content.

This module is intentionally limited to validation, canonical hashing, and a pure
normalization protocol.  Capture, authentication, network access, persistence, and
engine mutation belong to separately reviewed boundaries.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Annotated, Any, Literal, Protocol, Self, TypeAlias, runtime_checkable

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

INTEGRATION_MANIFEST_SCHEMA_VERSION = "vtt.integration_manifest.v1"
logger = logging.getLogger(__name__)
INTEGRATION_GRANT_SCHEMA_VERSION = "vtt.integration_grant.v1"
CONTENT_PROVENANCE_SCHEMA_VERSION = "vtt.content_provenance.v1"
EXTERNAL_CONTENT_RECORD_SCHEMA_VERSION = "vtt.external_content_record.v1"
BLOB_MANIFEST_SCHEMA_VERSION = "vtt.blob_manifest.v1"
EXTERNAL_CONTENT_ENVELOPE_SCHEMA_VERSION = "vtt.external_content_envelope.v1"
IMPORT_PREVIEW_CHANGE_SCHEMA_VERSION = "vtt.import_preview_change.v1"
IMPORT_PREVIEW_SCHEMA_VERSION = "vtt.import_preview.v1"
IMPORT_COMMIT_SCHEMA_VERSION = "vtt.import_commit.v1"

MAX_EXTENSION_API_VERSION = 1_000_000
MAX_MANIFEST_PERMISSIONS = 16
MAX_MANIFEST_PROVIDERS = 32
MAX_MANIFEST_CONTRIBUTION_TYPES = 16
MAX_EXTERNAL_RECORDS = 500
MAX_EXTERNAL_BLOBS = 128
MAX_EXTERNAL_BLOB_BYTES = 32 * 1024 * 1024
MAX_EXTERNAL_TOTAL_BLOB_BYTES = 256 * 1024 * 1024
MAX_EXTERNAL_JSON_DEPTH = 8
MAX_EXTERNAL_JSON_NODES = 4_096
MAX_EXTERNAL_OBJECT_KEYS = 128
MAX_EXTERNAL_ARRAY_ITEMS = 256
MAX_EXTERNAL_STRING_LENGTH = 16_384
MAX_EXTERNAL_RECORD_JSON_BYTES = 256 * 1024
MAX_IMPORT_CHANGES = MAX_EXTERNAL_RECORDS
MAX_IMPORT_WARNINGS = 128
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_GRANT_LIFETIME = timedelta(days=30)

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
APIVersion = Annotated[int, Field(strict=True, ge=1, le=MAX_EXTENSION_API_VERSION)]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
BlobDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

IntegrationPermission: TypeAlias = Literal[
    "actors:import",
    "items:import",
    "journals:import",
    "playlists:import",
    "rollable-tables:import",
    "scenes:import",
]
ContributionType: TypeAlias = Literal[
    "actor",
    "item",
    "journal",
    "playlist",
    "rollable_table",
    "scene",
]
ImportConflictPolicy: TypeAlias = Literal[
    "keep_existing",
    "reject",
    "replace_existing",
]
ImportOperation: TypeAlias = Literal["create", "skip", "update"]
BlobMediaType: TypeAlias = Literal[
    "audio/flac",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "video/mp4",
    "video/webm",
]

_CONTRIBUTION_PERMISSION: dict[ContributionType, IntegrationPermission] = {
    "actor": "actors:import",
    "item": "items:import",
    "journal": "journals:import",
    "playlist": "playlists:import",
    "rollable_table": "rollable-tables:import",
    "scene": "scenes:import",
}


class _StrictIntegrationModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )


_IDENTIFIER_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*")
_VERSION_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
_PROVIDER_SCHEMA_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_DATA_KEY_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}")
_FILE_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,159}")
_HTML_PATTERN = re.compile(
    r"(?:<!doctype\b|<!--|<\s*/?\s*[A-Za-z][A-Za-z0-9:-]*\b[^>]*>)",
    re.IGNORECASE,
)
_EXECUTABLE_URI_PATTERN = re.compile(
    r"(?:javascript\s*:|vbscript\s*:|data\s*:\s*"
    r"(?:text/html|image/svg\+xml|application/javascript|text/javascript))",
    re.IGNORECASE,
)
_DATA_URI_PATTERN = re.compile(r"(?<![A-Za-z0-9+.-])data\s*:", re.IGNORECASE)
_REMOTE_URL_PATTERN = re.compile(
    r"(?:\b(?:file|ftp|https?|ipfs|s3|wss?)\s*:(?:/+)?|(?<![:/])//[A-Za-z0-9])",
    re.IGNORECASE,
)
_SENSITIVE_DATA_KEY_EXACT = frozenset(
    {
        "auth",
        "authentication",
        "authorization",
        "bearer",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "jwt",
        "password",
        "secret",
    }
)
_PROTOTYPE_KEYS = frozenset({"__proto__", "constructor", "prototype"})
_SENSITIVE_DATA_KEY_SUFFIXES = (
    "accesstoken",
    "apikey",
    "apikeyhash",
    "authheader",
    "authorizationheader",
    "authtoken",
    "bearertoken",
    "clientsecret",
    "credential",
    "credentials",
    "idtoken",
    "password",
    "privatekey",
    "refreshtoken",
    "secret",
    "sessioncookie",
    "sessionid",
    "sessionkey",
    "signingkey",
    "tokenvalue",
)
_BEARER_VALUE_PATTERN = re.compile(
    r"(?:^|\s)bearer\s+[A-Za-z0-9._~+/=-]{8,}(?:$|\s)", re.IGNORECASE
)
_BASIC_VALUE_PATTERN = re.compile(r"(?:^|\s)basic\s+[A-Za-z0-9+/]+={0,2}(?:$|\s)", re.IGNORECASE)
_JWT_VALUE_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]{2,}\b")
_PEM_VALUE_PATTERN = re.compile(
    r"-----\s*begin\s+(?:[A-Z0-9 ]+\s+)?(?:private|secret)\s+key\s*-----",
    re.IGNORECASE,
)
_COMPACT_CREDENTIAL_PATTERN = re.compile(
    r"(?:^|[:=;,])(?:basic|bearer)[A-Za-z0-9._~+/=-]{8,}(?:$|[,;])",
    re.IGNORECASE,
)
_COMPACT_PEM_PATTERN = re.compile(
    r"-----BEGIN(?:[A-Z0-9]+)?(?:PRIVATE|SECRET)KEY-----",
    re.IGNORECASE,
)
_PERCENT_ESCAPE_PATTERN = re.compile(r"(?:%[0-9A-Fa-f]{2})+")
_MAX_SECURITY_NORMALIZATION_PASSES = 4
_MAX_SECURITY_NORMALIZED_TEXT_LENGTH = MAX_EXTERNAL_STRING_LENGTH * 4


def _require_unicode_scalars(value: str, *, field_name: str) -> str:
    if any(unicodedata.category(character) == "Cs" for character in value):
        raise ValueError(f"{field_name} must contain only Unicode scalar values")
    return value


def _security_normalized_text(value: str) -> str:
    """Build a bounded detection view without changing accepted text or digests.

    Require convergence within four passes, so nested escapes cannot hide behind
    the work limit. Percent decoding is local UTF-8 processing, not URL handling.
    """

    for _ in range(_MAX_SECURITY_NORMALIZATION_PASSES):
        decoded = _PERCENT_ESCAPE_PATTERN.sub(
            lambda match: bytes.fromhex(match.group().replace("%", "")).decode(
                "utf-8", errors="replace"
            ),
            value,
        )
        decoded = unicodedata.normalize("NFKC", html.unescape(decoded))
        if len(decoded) > _MAX_SECURITY_NORMALIZED_TEXT_LENGTH:
            raise ValueError("external text exceeds the security normalization length limit")
        compact = "".join(
            character
            for character in decoded
            if ord(character) > 32
            and ord(character) != 127
            and not character.isspace()
            and unicodedata.category(character) != "Cf"
        )
        normalized = (
            compact.replace("\\", "/")
            .replace("\u2215", "/")
            .replace("\u2044", "/")
            .replace("\uff0f", "/")
        )
        if normalized == value:
            return normalized
        value = normalized
    raise ValueError("external text exceeds the security decoding depth limit")


def _is_sensitive_data_key(value: str) -> bool:
    """Classify bounded credential key families without matching domain substrings."""

    collapsed_key = re.sub(r"[^a-z0-9]", "", value.lower())
    if collapsed_key in _SENSITIVE_DATA_KEY_EXACT:
        return True
    return any(collapsed_key.endswith(suffix) for suffix in _SENSITIVE_DATA_KEY_SUFFIXES)


def _canonical_text(value: str, *, field_name: str, maximum_length: int = 128) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    _require_unicode_scalars(value, field_name=field_name)
    if len(value) > maximum_length:
        raise ValueError(f"{field_name} must be at most {maximum_length} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field_name} must not contain control characters")
    security_value = _security_normalized_text(value)
    if (
        _BEARER_VALUE_PATTERN.search(value) is not None
        or _BASIC_VALUE_PATTERN.search(value) is not None
        or _JWT_VALUE_PATTERN.search(value) is not None
        or _PEM_VALUE_PATTERN.search(value) is not None
        or _COMPACT_CREDENTIAL_PATTERN.search(security_value) is not None
        or _COMPACT_PEM_PATTERN.search(security_value) is not None
    ):
        raise ValueError(f"{field_name} contains credential material")
    return value


def _canonical_identifier(value: str, *, field_name: str) -> str:
    value = _canonical_text(value, field_name=field_name)
    if _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"{field_name} must be a lowercase identifier with dot, dash, or underscore separators"
        )
    return value


def _canonical_id(value: str, *, field_name: str, maximum_length: int = 128) -> str:
    value = _canonical_text(value, field_name=field_name, maximum_length=maximum_length)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value) is None:
        raise ValueError(f"{field_name} must be a portable identifier")
    return value


def _require_sorted_unique(values: Sequence[str], *, field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must contain unique values")
    if tuple(values) != tuple(sorted(values)):
        raise ValueError(f"{field_name} must use canonical sorted order")


def _normalize_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _require_inert_external_text(value: str, *, field_name: str) -> str:
    _require_unicode_scalars(value, field_name=field_name)
    security_value = _security_normalized_text(value)
    if (
        _DATA_URI_PATTERN.search(value) is not None
        or _DATA_URI_PATTERN.search(security_value) is not None
    ):
        raise ValueError(f"{field_name} contains an executable URI")
    if (
        _EXECUTABLE_URI_PATTERN.search(value) is not None
        or _EXECUTABLE_URI_PATTERN.search(security_value) is not None
    ):
        raise ValueError(f"{field_name} contains an executable URI")
    if (
        _REMOTE_URL_PATTERN.search(value) is not None
        or _REMOTE_URL_PATTERN.search(security_value) is not None
    ):
        raise ValueError(f"{field_name} contains remote URLs")
    if _HTML_PATTERN.search(value) is not None or _HTML_PATTERN.search(security_value) is not None:
        raise ValueError(f"{field_name} contains HTML or SVG markup")
    if (
        _BEARER_VALUE_PATTERN.search(value) is not None
        or _BASIC_VALUE_PATTERN.search(value) is not None
        or _JWT_VALUE_PATTERN.search(value) is not None
        or _PEM_VALUE_PATTERN.search(value) is not None
        or _COMPACT_CREDENTIAL_PATTERN.search(security_value) is not None
        or _COMPACT_PEM_PATTERN.search(security_value) is not None
    ):
        raise ValueError(f"{field_name} contains credential material")
    return value


def _canonical_digest_value(value: Any) -> JsonValue:
    if isinstance(value, BaseModel):
        return _canonical_digest_value(value.model_dump(mode="python", round_trip=True))
    if isinstance(value, Mapping):
        canonical_items: list[JsonValue] = []
        for key in sorted(value):
            if not isinstance(key, str):
                raise TypeError("canonical digest mapping keys must be strings")
            _require_unicode_scalars(key, field_name="canonical digest mapping key")
            canonical_items.append([key, _canonical_digest_value(value[key])])
        return ["object", canonical_items]
    if isinstance(value, (list, tuple)):
        return ["array", [_canonical_digest_value(nested) for nested in value]]
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canonical digest datetimes must include a timezone")
        return ["datetime", value.astimezone(UTC).isoformat().replace("+00:00", "Z")]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical digest numbers must be finite")
        return ["float", value]
    if value is None:
        return ["null"]
    if type(value) is bool:
        return ["boolean", value]
    if type(value) is int:
        return ["integer", value]
    if isinstance(value, str):
        _require_unicode_scalars(value, field_name="canonical digest text")
        return ["string", value]
    raise TypeError(f"canonical digest does not support {type(value).__name__}")


def canonical_digest(value: BaseModel | Mapping[str, Any] | Sequence[Any]) -> str:
    """Return a deterministic, type-tagged SHA-256 digest for inert JSON data."""

    canonical = _canonical_digest_value(value)
    encoded = json.dumps(
        canonical,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_external_json(value: Any) -> dict[str, JsonValue]:
    node_count = 0

    def visit(nested: Any, *, depth: int) -> JsonValue:
        nonlocal node_count
        node_count += 1
        if node_count > MAX_EXTERNAL_JSON_NODES:
            raise ValueError("external data exceeds the maximum node count")
        if depth > MAX_EXTERNAL_JSON_DEPTH:
            raise ValueError("external data exceeds the maximum depth")

        if isinstance(nested, Mapping):
            if len(nested) > MAX_EXTERNAL_OBJECT_KEYS:
                raise ValueError("external object exceeds the maximum key count")
            result: dict[str, JsonValue] = {}
            for key, child in nested.items():
                if not isinstance(key, str):
                    raise ValueError("external data keys must be portable identifiers")
                _require_unicode_scalars(key, field_name="external data key")
                if _DATA_KEY_PATTERN.fullmatch(key) is None:
                    raise ValueError("external data keys must be portable identifiers")
                if _is_sensitive_data_key(key) or key.lower() in _PROTOTYPE_KEYS:
                    raise ValueError(f"external data contains sensitive key '{key}'")
                result[key] = visit(child, depth=depth + 1)
            return result

        if isinstance(nested, (list, tuple)):
            if len(nested) > MAX_EXTERNAL_ARRAY_ITEMS:
                raise ValueError("external array exceeds the maximum item count")
            return [visit(child, depth=depth + 1) for child in nested]

        if isinstance(nested, str):
            if len(nested) > MAX_EXTERNAL_STRING_LENGTH:
                raise ValueError("external string exceeds the maximum length")
            if "\x00" in nested:
                raise ValueError("external strings must not contain null characters")
            return _require_inert_external_text(nested, field_name="external data")

        if type(nested) is bool or nested is None:
            return nested
        if type(nested) is int:
            if abs(nested) > MAX_SAFE_INTEGER:
                raise ValueError("external integers must fit the portable safe-integer range")
            return nested
        if type(nested) is float:
            if not math.isfinite(nested):
                raise ValueError("external numbers must be finite")
            if abs(nested) > MAX_SAFE_INTEGER:
                raise ValueError("external numbers exceed the portable numeric range")
            return nested
        raise ValueError("external data must contain only inert JSON values")

    if not isinstance(value, Mapping):
        raise ValueError("data must be a JSON object")
    validated = visit(value, depth=0)
    if not isinstance(validated, dict):
        raise ValueError("data must be a JSON object")
    encoded = json.dumps(
        validated,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > MAX_EXTERNAL_RECORD_JSON_BYTES:
        raise ValueError("external record data exceeds the encoded byte limit")
    return validated


class IntegrationManifest(_StrictIntegrationModel):
    """Static extension declaration; it confers no authority by itself."""

    schema_version: Literal[INTEGRATION_MANIFEST_SCHEMA_VERSION] = (
        INTEGRATION_MANIFEST_SCHEMA_VERSION
    )
    extension_id: str
    publisher_id: str
    extension_version: str
    api_version_min: APIVersion
    api_version_max: APIVersion
    permissions: tuple[IntegrationPermission, ...] = Field(
        default=(), max_length=MAX_MANIFEST_PERMISSIONS
    )
    provider_ids: tuple[str, ...] = Field(default=(), max_length=MAX_MANIFEST_PROVIDERS)
    contribution_types: tuple[ContributionType, ...] = Field(
        default=(), max_length=MAX_MANIFEST_CONTRIBUTION_TYPES
    )

    @field_validator("extension_id", "publisher_id")
    @classmethod
    def validate_manifest_identity(cls, value: str, info: Any) -> str:
        return _canonical_identifier(value, field_name=info.field_name)

    @field_validator("extension_version")
    @classmethod
    def validate_extension_version(cls, value: str) -> str:
        value = _canonical_text(value, field_name="extension_version", maximum_length=128)
        if _VERSION_PATTERN.fullmatch(value) is None:
            raise ValueError("extension_version must be a canonical semantic version")
        return value

    @field_validator("permissions")
    @classmethod
    def validate_permissions(
        cls, value: tuple[IntegrationPermission, ...]
    ) -> tuple[IntegrationPermission, ...]:
        _require_sorted_unique(value, field_name="permissions")
        return value

    @field_validator("provider_ids")
    @classmethod
    def validate_provider_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for provider_id in value:
            _canonical_identifier(provider_id, field_name="provider_id")
        _require_sorted_unique(value, field_name="provider_ids")
        return value

    @field_validator("contribution_types")
    @classmethod
    def validate_contribution_types(
        cls, value: tuple[ContributionType, ...]
    ) -> tuple[ContributionType, ...]:
        _require_sorted_unique(value, field_name="contribution_types")
        return value

    @model_validator(mode="after")
    def validate_api_version_range(self) -> Self:
        if self.api_version_min > self.api_version_max:
            raise ValueError("api_version_min must not exceed api_version_max")
        missing_permissions = {
            _CONTRIBUTION_PERMISSION[contribution_type]
            for contribution_type in self.contribution_types
        }.difference(self.permissions)
        if missing_permissions:
            raise ValueError(
                "contribution_types require matching permissions: "
                + ", ".join(sorted(missing_permissions))
            )
        return self

    def require_api_version(self, api_version: int) -> None:
        if type(api_version) is not int:
            raise ValueError("api_version must be an integer")
        if not self.api_version_min <= api_version <= self.api_version_max:
            raise ValueError("api_version is outside the manifest compatibility range")


class IntegrationGrant(_StrictIntegrationModel):
    """Public grant metadata containing a verifier hash, never bearer material."""

    schema_version: Literal[INTEGRATION_GRANT_SCHEMA_VERSION] = INTEGRATION_GRANT_SCHEMA_VERSION
    grant_id: str
    extension_id: str
    manifest_digest: Digest
    participant_id: str
    table_id: str
    permissions: tuple[IntegrationPermission, ...] = Field(
        default=(), max_length=MAX_MANIFEST_PERMISSIONS
    )
    provider_ids: tuple[str, ...] = Field(default=(), max_length=MAX_MANIFEST_PROVIDERS)
    contribution_types: tuple[ContributionType, ...] = Field(
        default=(), max_length=MAX_MANIFEST_CONTRIBUTION_TYPES
    )
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    revoked_at: AwareDatetime | None = None
    token_hash: Digest

    @field_validator("grant_id", "participant_id", "table_id")
    @classmethod
    def validate_binding_id(cls, value: str, info: Any) -> str:
        return _canonical_id(value, field_name=info.field_name)

    @field_validator("extension_id")
    @classmethod
    def validate_extension_id(cls, value: str) -> str:
        return _canonical_identifier(value, field_name="extension_id")

    @field_validator("permissions")
    @classmethod
    def validate_permissions(
        cls, value: tuple[IntegrationPermission, ...]
    ) -> tuple[IntegrationPermission, ...]:
        _require_sorted_unique(value, field_name="permissions")
        return value

    @field_validator("provider_ids")
    @classmethod
    def validate_provider_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for provider_id in value:
            _canonical_identifier(provider_id, field_name="provider_id")
        _require_sorted_unique(value, field_name="provider_ids")
        return value

    @field_validator("contribution_types")
    @classmethod
    def validate_contribution_types(
        cls, value: tuple[ContributionType, ...]
    ) -> tuple[ContributionType, ...]:
        _require_sorted_unique(value, field_name="contribution_types")
        return value

    @field_validator("issued_at", "expires_at", "revoked_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _normalize_utc(value)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be later than issued_at")
        if self.expires_at - self.issued_at > MAX_GRANT_LIFETIME:
            raise ValueError("grant exceeds the maximum lifetime")
        if self.revoked_at is not None and self.revoked_at < self.issued_at:
            raise ValueError("revoked_at must not be earlier than issued_at")
        if self.revoked_at is not None and self.revoked_at > self.expires_at:
            raise ValueError("revoked_at must not be later than expires_at")
        missing_permissions = {
            _CONTRIBUTION_PERMISSION[contribution_type]
            for contribution_type in self.contribution_types
        }.difference(self.permissions)
        if missing_permissions:
            raise ValueError(
                "contribution_types require matching permissions: "
                + ", ".join(sorted(missing_permissions))
            )
        return self

    def require_manifest_scope(self, manifest: IntegrationManifest) -> None:
        if self.extension_id != manifest.extension_id:
            raise ValueError("grant extension_id does not match the manifest")
        if self.manifest_digest != canonical_digest(manifest):
            raise ValueError("grant manifest_digest does not match the exact manifest")
        if not set(self.permissions).issubset(manifest.permissions):
            raise ValueError("grant permissions fall outside the manifest declaration")
        if not set(self.provider_ids).issubset(manifest.provider_ids):
            raise ValueError("grant provider_ids fall outside the manifest declaration")
        if not set(self.contribution_types).issubset(manifest.contribution_types):
            raise ValueError("grant contribution_types fall outside the manifest declaration")

    def is_active(self, *, at: datetime) -> bool:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("at must include a timezone")
        checked_at = _normalize_utc(at)
        return self.revoked_at is None and self.issued_at <= checked_at < self.expires_at


class ContentProvenance(_StrictIntegrationModel):
    schema_version: Literal[CONTENT_PROVENANCE_SCHEMA_VERSION] = CONTENT_PROVENANCE_SCHEMA_VERSION
    provider_record_id: str
    captured_at: AwareDatetime
    source_revision: str | None = None
    source_digest: Digest
    attribution: str | None = None

    @field_validator("provider_record_id")
    @classmethod
    def validate_provider_record_id(cls, value: str) -> str:
        return _canonical_id(value, field_name="provider_record_id", maximum_length=256)

    @field_validator("captured_at")
    @classmethod
    def normalize_captured_at(cls, value: datetime) -> datetime:
        return _normalize_utc(value)

    @field_validator("source_revision")
    @classmethod
    def validate_source_revision(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = _canonical_text(value, field_name="source_revision", maximum_length=256)
        return _require_inert_external_text(value, field_name="source_revision")

    @field_validator("attribution")
    @classmethod
    def validate_attribution(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = _canonical_text(value, field_name="attribution", maximum_length=500)
        return _require_inert_external_text(value, field_name="attribution")


class ExternalContentRecord(_StrictIntegrationModel):
    schema_version: Literal[EXTERNAL_CONTENT_RECORD_SCHEMA_VERSION] = (
        EXTERNAL_CONTENT_RECORD_SCHEMA_VERSION
    )
    record_id: str
    contribution_type: ContributionType
    title: str
    data: dict[str, JsonValue]
    blob_ids: tuple[str, ...] = Field(default=(), max_length=MAX_EXTERNAL_BLOBS)
    provenance: ContentProvenance

    @field_validator("record_id")
    @classmethod
    def validate_record_id(cls, value: str) -> str:
        return _canonical_id(value, field_name="record_id", maximum_length=256)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = _canonical_text(value, field_name="title", maximum_length=240)
        return _require_inert_external_text(value, field_name="title")

    @field_validator("data", mode="before")
    @classmethod
    def validate_data(cls, value: Any) -> dict[str, JsonValue]:
        return _validate_external_json(value)

    @field_validator("blob_ids")
    @classmethod
    def validate_blob_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for blob_id in value:
            _canonical_id(blob_id, field_name="blob_id")
        _require_sorted_unique(value, field_name="blob_ids")
        return value


_MEDIA_EXTENSIONS: dict[BlobMediaType, tuple[str, ...]] = {
    "audio/flac": (".flac",),
    "audio/mpeg": (".mp3",),
    "audio/ogg": (".oga", ".ogg"),
    "audio/wav": (".wav",),
    "image/gif": (".gif",),
    "image/jpeg": (".jpeg", ".jpg"),
    "image/png": (".png",),
    "image/webp": (".webp",),
    "video/mp4": (".mp4",),
    "video/webm": (".webm",),
}


class BlobManifest(_StrictIntegrationModel):
    """Metadata for separately transferred bytes; locations and bytes are excluded."""

    schema_version: Literal[BLOB_MANIFEST_SCHEMA_VERSION] = BLOB_MANIFEST_SCHEMA_VERSION
    blob_id: str
    file_name: str
    media_type: BlobMediaType
    byte_size: Annotated[int, Field(strict=True, ge=1, le=MAX_EXTERNAL_BLOB_BYTES)]
    sha256: BlobDigest
    provenance: ContentProvenance

    @field_validator("blob_id")
    @classmethod
    def validate_blob_id(cls, value: str) -> str:
        return _canonical_id(value, field_name="blob_id")

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: str) -> str:
        value = _canonical_text(value, field_name="file_name", maximum_length=160)
        if (
            value in {".", ".."}
            or "/" in value
            or "\\" in value
            or _FILE_NAME_PATTERN.fullmatch(value) is None
        ):
            raise ValueError("file_name must be a safe base name without a path")
        return value

    @model_validator(mode="after")
    def validate_media_extension(self) -> Self:
        if not self.file_name.lower().endswith(_MEDIA_EXTENSIONS[self.media_type]):
            raise ValueError("file_name extension must match the allowlisted media_type")
        return self

    def require_bytes(self, content: bytes) -> None:
        """Verify separately transferred bytes before they enter durable storage."""

        if type(content) is not bytes:
            raise ValueError("blob content must be bytes")
        if len(content) != self.byte_size:
            raise ValueError("blob content size does not match the manifest")
        if hashlib.sha256(content).hexdigest() != self.sha256:
            raise ValueError("blob content digest does not match the manifest")


class ExternalContentEnvelope(_StrictIntegrationModel):
    """A bounded, inert capture passed into a provider adapter for normalization."""

    schema_version: Literal[EXTERNAL_CONTENT_ENVELOPE_SCHEMA_VERSION] = (
        EXTERNAL_CONTENT_ENVELOPE_SCHEMA_VERSION
    )
    provider_id: str
    provider_schema_version: str
    capture_id: str
    captured_at: AwareDatetime
    records: tuple[ExternalContentRecord, ...] = Field(default=(), max_length=MAX_EXTERNAL_RECORDS)
    blobs: tuple[BlobManifest, ...] = Field(default=(), max_length=MAX_EXTERNAL_BLOBS)

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        return _canonical_identifier(value, field_name="provider_id")

    @field_validator("provider_schema_version")
    @classmethod
    def validate_provider_schema_version(cls, value: str) -> str:
        value = _canonical_text(
            value,
            field_name="provider_schema_version",
            maximum_length=128,
        )
        if _PROVIDER_SCHEMA_PATTERN.fullmatch(value) is None:
            raise ValueError("provider_schema_version must be a portable version identifier")
        return value

    @field_validator("capture_id")
    @classmethod
    def validate_capture_id(cls, value: str) -> str:
        return _canonical_id(value, field_name="capture_id")

    @field_validator("captured_at")
    @classmethod
    def normalize_captured_at(cls, value: datetime) -> datetime:
        return _normalize_utc(value)

    @model_validator(mode="after")
    def validate_canonical_contents(self) -> Self:
        record_ids = tuple(record.record_id for record in self.records)
        _require_sorted_unique(record_ids, field_name="records")
        blob_ids = tuple(blob.blob_id for blob in self.blobs)
        _require_sorted_unique(blob_ids, field_name="blobs")

        known_blob_ids = set(blob_ids)
        referenced_blob_ids: set[str] = set()
        for record in self.records:
            unknown_blob_ids = set(record.blob_ids).difference(known_blob_ids)
            if unknown_blob_ids:
                raise ValueError(
                    "record references unknown blob IDs: " + ", ".join(sorted(unknown_blob_ids))
                )
            referenced_blob_ids.update(record.blob_ids)
            if record.provenance.captured_at > self.captured_at:
                raise ValueError("record provenance cannot be newer than the envelope capture")
        if referenced_blob_ids != known_blob_ids:
            raise ValueError("envelope contains unreferenced blob manifests")
        if any(blob.provenance.captured_at > self.captured_at for blob in self.blobs):
            raise ValueError("blob provenance cannot be newer than the envelope capture")
        if sum(blob.byte_size for blob in self.blobs) > MAX_EXTERNAL_TOTAL_BLOB_BYTES:
            raise ValueError("blob manifests exceed the envelope byte limit")
        return self


class ImportPreviewChange(_StrictIntegrationModel):
    schema_version: Literal[IMPORT_PREVIEW_CHANGE_SCHEMA_VERSION] = (
        IMPORT_PREVIEW_CHANGE_SCHEMA_VERSION
    )
    operation: ImportOperation
    contribution_type: ContributionType
    external_record_id: str
    source_record_digest: Digest
    target_id: str | None = None
    proposed_data: dict[str, JsonValue] | None = None
    summary: str

    @field_validator("external_record_id")
    @classmethod
    def validate_external_record_id(cls, value: str) -> str:
        return _canonical_id(value, field_name="external_record_id", maximum_length=256)

    @field_validator("target_id")
    @classmethod
    def validate_target_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _canonical_id(value, field_name="target_id", maximum_length=256)

    @field_validator("proposed_data", mode="before")
    @classmethod
    def validate_proposed_data(cls, value: Any) -> dict[str, JsonValue] | None:
        if value is None:
            return None
        return _validate_external_json(value)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        value = _canonical_text(value, field_name="summary", maximum_length=240)
        return _require_inert_external_text(value, field_name="summary")

    @model_validator(mode="after")
    def validate_target_binding(self) -> Self:
        if self.operation == "create" and self.target_id is not None:
            raise ValueError("create changes must not declare target_id")
        if self.operation in {"skip", "update"} and self.target_id is None:
            raise ValueError(f"{self.operation} changes must declare target_id")
        if self.operation in {"create", "update"} and self.proposed_data is None:
            raise ValueError(f"{self.operation} changes must declare proposed_data")
        if self.operation == "skip" and self.proposed_data is not None:
            raise ValueError("skip changes must not declare proposed_data")
        return self


class ImportPreview(_StrictIntegrationModel):
    schema_version: Literal[IMPORT_PREVIEW_SCHEMA_VERSION] = IMPORT_PREVIEW_SCHEMA_VERSION
    preview_id: str
    grant_id: str
    extension_id: str
    participant_id: str
    table_id: str
    capture_id: str
    envelope_digest: Digest
    expected_revision: NonNegativeInt
    conflict_policy: ImportConflictPolicy
    changes: tuple[ImportPreviewChange, ...] = Field(default=(), max_length=MAX_IMPORT_CHANGES)
    warnings: tuple[str, ...] = Field(default=(), max_length=MAX_IMPORT_WARNINGS)

    @field_validator("preview_id", "grant_id", "participant_id", "table_id", "capture_id")
    @classmethod
    def validate_binding_id(cls, value: str, info: Any) -> str:
        return _canonical_id(value, field_name=info.field_name)

    @field_validator("extension_id")
    @classmethod
    def validate_extension_id(cls, value: str) -> str:
        return _canonical_identifier(value, field_name="extension_id")

    @field_validator("warnings")
    @classmethod
    def validate_warnings(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for warning in value:
            warning = _canonical_text(warning, field_name="warning", maximum_length=500)
            _require_inert_external_text(warning, field_name="warning")
        _require_sorted_unique(value, field_name="warnings")
        return value

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        record_ids = tuple(change.external_record_id for change in self.changes)
        _require_sorted_unique(record_ids, field_name="changes")
        target_ids = tuple(
            change.target_id for change in self.changes if change.target_id is not None
        )
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("changes must not repeat a target_id")
        return self

    def require_envelope(self, envelope: ExternalContentEnvelope) -> None:
        if self.capture_id != envelope.capture_id:
            raise ValueError("preview capture_id does not match the envelope")
        if self.envelope_digest != canonical_digest(envelope):
            raise ValueError("preview envelope_digest does not match the exact envelope")
        records_by_id = {record.record_id: record for record in envelope.records}
        for change in self.changes:
            record = records_by_id.get(change.external_record_id)
            if record is None:
                raise ValueError("preview change references an unknown external record")
            if change.contribution_type != record.contribution_type:
                raise ValueError(
                    "preview change contribution_type does not match the external record"
                )
            if change.source_record_digest != canonical_digest(record):
                raise ValueError(
                    "preview change source_record_digest does not match the external record"
                )
        if set(records_by_id) != {change.external_record_id for change in self.changes}:
            raise ValueError("preview must contain exactly one change per envelope record")

    def require_authorized(
        self,
        *,
        manifest: IntegrationManifest,
        grant: IntegrationGrant,
        envelope: ExternalContentEnvelope,
        at: datetime,
        api_version: int,
    ) -> None:
        """Validate the complete static authorization and preview relationship."""

        manifest.require_api_version(api_version)
        grant.require_manifest_scope(manifest)
        if not grant.is_active(at=at):
            raise ValueError("integration grant is not active")
        for field_name in ("grant_id", "extension_id", "participant_id", "table_id"):
            expected = getattr(grant, field_name)
            if getattr(self, field_name) != expected:
                raise ValueError(f"preview {field_name} does not match the grant")
        if envelope.provider_id not in manifest.provider_ids:
            raise ValueError("envelope provider is outside the manifest declaration")
        if envelope.provider_id not in grant.provider_ids:
            raise ValueError("envelope provider is outside the grant scope")

        contribution_types = {record.contribution_type for record in envelope.records}.union(
            change.contribution_type for change in self.changes
        )
        for contribution_type in contribution_types:
            if contribution_type not in manifest.contribution_types:
                raise ValueError("content contribution_type is outside the manifest declaration")
            if contribution_type not in grant.contribution_types:
                raise ValueError("content contribution_type is outside the grant scope")
            required_permission = _CONTRIBUTION_PERMISSION[contribution_type]
            if required_permission not in grant.permissions:
                raise ValueError("content requires a permission outside the grant scope")
        self.require_envelope(envelope)


def _deep_freeze_json(value: Any) -> Any:
    """Return a detached, recursively immutable copy of validated JSON data."""

    if isinstance(value, BaseModel):
        return _deep_freeze_json(value.model_dump(mode="python", round_trip=True))
    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze_json(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze_json(child) for child in value)
    if isinstance(value, (str, int, float, bool, datetime)) or value is None:
        return value
    raise TypeError(f"verified write data does not support {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class VerifiedImportWriteSet:
    """Detached execution input produced only after exact commit verification."""

    command_id: str
    preview_id: str
    preview_digest: Digest
    write_set_digest: Digest
    grant_id: str
    extension_id: str
    participant_id: str
    table_id: str
    manifest_digest: Digest
    envelope_digest: Digest
    api_version: int
    authorized_at: datetime
    expected_revision: int
    conflict_policy: ImportConflictPolicy
    changes: tuple[Mapping[str, Any], ...]


class ImportCommit(_StrictIntegrationModel):
    schema_version: Literal[IMPORT_COMMIT_SCHEMA_VERSION] = IMPORT_COMMIT_SCHEMA_VERSION
    command_id: str
    preview_id: str
    preview_digest: Digest
    write_set_digest: Digest
    grant_id: str
    extension_id: str
    participant_id: str
    table_id: str
    expected_revision: NonNegativeInt
    conflict_policy: ImportConflictPolicy

    @field_validator("command_id", "preview_id", "grant_id", "participant_id", "table_id")
    @classmethod
    def validate_binding_id(cls, value: str, info: Any) -> str:
        return _canonical_id(value, field_name=info.field_name)

    @field_validator("extension_id")
    @classmethod
    def validate_extension_id(cls, value: str) -> str:
        return _canonical_identifier(value, field_name="extension_id")

    @classmethod
    def for_preview(cls, preview: ImportPreview, *, command_id: str) -> Self:
        return cls(
            command_id=command_id,
            preview_id=preview.preview_id,
            preview_digest=canonical_digest(preview),
            write_set_digest=canonical_digest(preview.changes),
            grant_id=preview.grant_id,
            extension_id=preview.extension_id,
            participant_id=preview.participant_id,
            table_id=preview.table_id,
            expected_revision=preview.expected_revision,
            conflict_policy=preview.conflict_policy,
        )

    def require_matches(self, preview: ImportPreview) -> None:
        bindings = (
            "preview_id",
            "grant_id",
            "extension_id",
            "participant_id",
            "table_id",
            "expected_revision",
            "conflict_policy",
        )
        for binding in bindings:
            if getattr(self, binding) != getattr(preview, binding):
                raise ValueError(f"commit {binding} does not match the preview")
        if self.preview_digest != canonical_digest(preview):
            raise ValueError("commit preview_digest does not match the exact preview")
        self.require_write_set(preview.changes)

    def require_write_set(self, changes: Sequence[ImportPreviewChange]) -> None:
        """Require execution to use the exact normalized writes shown in preview."""

        if self.write_set_digest != canonical_digest(changes):
            raise ValueError("commit write_set_digest does not match the reviewed writes")

    def verify_for_execution(
        self,
        preview: ImportPreview,
        *,
        manifest: IntegrationManifest,
        grant: IntegrationGrant,
        envelope: ExternalContentEnvelope,
        at: datetime,
        api_version: int,
        current_revision: int,
    ) -> VerifiedImportWriteSet:
        """Verify a commit and return its detached, immutable execution payload."""

        validated_commit = ImportCommit.model_validate(
            self.model_dump(mode="python", round_trip=True),
            strict=True,
        )
        validated_preview = ImportPreview.model_validate(
            preview.model_dump(mode="python", round_trip=True),
            strict=True,
        )
        validated_manifest = IntegrationManifest.model_validate(
            manifest.model_dump(mode="python", round_trip=True),
            strict=True,
        )
        validated_grant = IntegrationGrant.model_validate(
            grant.model_dump(mode="python", round_trip=True),
            strict=True,
        )
        validated_envelope = ExternalContentEnvelope.model_validate(
            envelope.model_dump(mode="python", round_trip=True),
            strict=True,
        )

        validated_preview.require_authorized(
            manifest=validated_manifest,
            grant=validated_grant,
            envelope=validated_envelope,
            at=at,
            api_version=api_version,
        )
        validated_commit.require_matches(validated_preview)
        if type(current_revision) is not int or current_revision < 0:
            raise ValueError("current_revision must be a non-negative integer")
        if current_revision != validated_commit.expected_revision:
            raise ValueError("current_revision does not match the reviewed revision")
        frozen_changes = _deep_freeze_json(validated_preview.changes)
        if not isinstance(frozen_changes, tuple) or not all(
            isinstance(change, Mapping) for change in frozen_changes
        ):
            raise TypeError("verified changes must be an immutable sequence of mappings")
        verified = VerifiedImportWriteSet(
            command_id=validated_commit.command_id,
            preview_id=validated_commit.preview_id,
            preview_digest=validated_commit.preview_digest,
            write_set_digest=validated_commit.write_set_digest,
            grant_id=validated_commit.grant_id,
            extension_id=validated_commit.extension_id,
            participant_id=validated_commit.participant_id,
            table_id=validated_commit.table_id,
            manifest_digest=validated_grant.manifest_digest,
            envelope_digest=validated_preview.envelope_digest,
            api_version=api_version,
            authorized_at=_normalize_utc(at),
            expected_revision=validated_commit.expected_revision,
            conflict_policy=validated_commit.conflict_policy,
            changes=frozen_changes,
        )
        if canonical_digest(verified.changes) != verified.write_set_digest:
            raise ValueError("verified write set changed while creating the execution payload")
        return verified


@runtime_checkable
class ContentProviderAdapter(Protocol):
    """Pure normalization seam; implementations receive and return only data."""

    @property
    def manifest(self) -> IntegrationManifest: ...

    def normalize(
        self,
        envelope: ExternalContentEnvelope,
        *,
        grant_id: str,
        participant_id: str,
        table_id: str,
        expected_revision: int,
        conflict_policy: ImportConflictPolicy,
    ) -> ImportPreview: ...
