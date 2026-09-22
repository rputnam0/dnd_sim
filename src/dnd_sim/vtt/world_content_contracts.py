"""Strict, inert contracts for reusable engine-native VTT world content.

These records describe durable actor and item definitions.  They intentionally do
not contain encounter runtime state, provider credentials, remote locations, HTML,
or executable extension data.  Encounter deployment is a separate authority
boundary.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import html
import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_serializer,
    field_validator,
    model_validator,
)

from dnd_sim.io_models import ActionConfig

WORLD_ACTOR_DOCUMENT_SCHEMA_VERSION = "vtt.world_actor_document.v1"
WORLD_ITEM_DOCUMENT_SCHEMA_VERSION = "vtt.world_item_document.v1"
WORLD_CONTENT_COMMAND_SCHEMA_VERSION = "vtt.world_content_command.v1"
WORLD_CONTENT_EVENT_SCHEMA_VERSION = "vtt.world_content_event.v1"
WORLD_CONTENT_RECEIPT_SCHEMA_VERSION = "vtt.world_content_receipt.v1"
WORLD_CONTENT_VIEW_SCHEMA_VERSION = "vtt.world_content_view.v1"
WORLD_CONTENT_SEARCH_HIT_SCHEMA_VERSION = "vtt.world_content_search_hit.v1"
WORLD_CONTENT_PROJECTION_SCHEMA_VERSION = "vtt.world_content_projection.v1"
WORLD_PROJECTED_ACTOR_DOCUMENT_SCHEMA_VERSION = "vtt.projected_actor_document.v1"
WORLD_PROJECTED_ITEM_DOCUMENT_SCHEMA_VERSION = "vtt.projected_item_document.v1"
DOCUMENT_PERMISSIONS_SCHEMA_VERSION = "vtt.document_permissions.v1"
DOCUMENT_PROVENANCE_SCHEMA_VERSION = "vtt.document_provenance.v1"
DND5E_ACTOR_SHEET_SCHEMA_VERSION = "vtt.dnd5e_actor_sheet.v1"
DND5E_ITEM_DATA_SCHEMA_VERSION = "vtt.dnd5e_item_data.v1"
DND5E_ACTION_INPUT_SCHEMA_VERSION = "vtt.dnd5e_action_input.v1"
DND5E_ABILITY_SCORES_SCHEMA_VERSION = "vtt.dnd5e_ability_scores.v1"
DND5E_MOVEMENT_SPEEDS_SCHEMA_VERSION = "vtt.dnd5e_movement_speeds.v1"
DND5E_SENSES_SCHEMA_VERSION = "vtt.dnd5e_senses.v1"
ACTOR_INVENTORY_ITEM_SCHEMA_VERSION = "vtt.actor_inventory_item.v1"

MAX_ACTIVE_ACTORS = 1_000
MAX_ACTIVE_ITEMS = 10_000
MAX_RETAINED_ACTORS = 2_000
MAX_RETAINED_ITEMS = 20_000
MAX_ACTOR_INVENTORY_ITEMS = 256
MAX_ACTOR_ACTIONS = 128
MAX_DOCUMENT_TAGS = 32
MAX_ASSIGNED_PARTICIPANTS = 16
MAX_SEARCH_RESULTS = 100
MAX_DOCUMENT_NAME_LENGTH = 160
MAX_DESCRIPTION_LENGTH = 8_192
MAX_STATIC_MAPPING_ENTRIES = 128
MAX_DOCUMENT_JSON_BYTES = 256 * 1024

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
DocumentDigest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
DocumentKind: TypeAlias = Literal["actor", "item"]
WorldContentPrincipalRole: TypeAlias = Literal["gm", "player", "spectator"]

_PORTABLE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_ENGINE_KEY_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:[ _-][a-z0-9]+)*")
_TAG_PATTERN = re.compile(r"[a-z0-9][a-z0-9 _-]{0,63}")
_HTML_PATTERN = re.compile(
    r"(?:<!doctype\b|<!--|<\s*/?\s*[A-Za-z][A-Za-z0-9:-]*\b[^>]*>)",
    re.IGNORECASE,
)
_EXECUTABLE_URI_PATTERN = re.compile(
    r"(?:javascript\s*:|vbscript\s*:|data\s*:)",
    re.IGNORECASE,
)
_REMOTE_URL_PATTERN = re.compile(
    r"(?:\b(?:blob|file|filesystem|ftp|https?|ipfs|s3|wss?)\s*:(?://)?|" r"(?<![:/])//[A-Za-z0-9])",
    re.IGNORECASE,
)
_WINDOWS_PATH_PATTERN = re.compile(r"(?:^|[\s('" + '"' + r"])[A-Za-z]:[/\\]")
_PERCENT_RUN_PATTERN = re.compile(r"(?:%[0-9A-Fa-f]{2})+")
_PERCENT_UNICODE_PATTERN = re.compile(r"%u([0-9A-Fa-f]{4})", re.IGNORECASE)
_BEARER_VALUE_PATTERN = re.compile(
    r"(?:^|\s)bearer\s+[A-Za-z0-9._~+/=-]{8,}(?:$|\s)", re.IGNORECASE
)
_JWT_VALUE_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]{2,}\b")
_CREDENTIAL_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:api[_ -]?key|access[_ -]?token|password|private[_ -]?key|secret)"
    r"\s*[:=]\s*[^\s,;]{8,}",
    re.IGNORECASE,
)
_CSS_RULE_PATTERN = re.compile(
    r"(?:[.#]?[A-Za-z][A-Za-z0-9_-]*|\*)\s*\{[^{}]{0,2048}:[^{}]{0,2048}\}",
    re.IGNORECASE,
)
_CSS_COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)
_PEM_PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----", re.IGNORECASE)
_OPENAI_SECRET_PATTERN = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")
_GITHUB_SECRET_PATTERN = re.compile(r"\bghp_[A-Za-z0-9]{20,}\b", re.IGNORECASE)
_AWS_ACCESS_KEY_PATTERN = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_BASIC_AUTH_PATTERN = re.compile(r"\bbasic\s+([A-Za-z0-9+/]{8,}={0,2})\b", re.IGNORECASE)
_DAMAGE_PATTERN = re.compile(r"^(?:(\d+)d(\d+))?([+-]\d+)?$")
_SENSITIVE_KEY_FRAGMENTS = (
    "accesskey",
    "apikey",
    "authorization",
    "clientsecret",
    "cookie",
    "credential",
    "jwt",
    "password",
    "privatekey",
    "secret",
    "sessionid",
    "token",
)
_SENSITIVE_KEYS = {"auth", "authentication", "oauth"}
_SECURITY_SCAN_PASSES = 3
_SECURITY_SCAN_MAX_LENGTH = MAX_DESCRIPTION_LENGTH * 4


class _StrictWorldContentModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
        allow_inf_nan=False,
    )


def _percent_decode(value: str) -> str:
    value = _PERCENT_UNICODE_PATTERN.sub(lambda match: chr(int(match.group(1), 16)), value)

    def decode_run(match: re.Match[str]) -> str:
        encoded = match.group(0)
        raw = bytes(int(encoded[index + 1 : index + 3], 16) for index in range(0, len(encoded), 3))
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1")

    return _PERCENT_RUN_PATTERN.sub(decode_run, value)


def _security_detection_text(value: str, *, field_name: str, allow_newlines: bool) -> str:
    detected = value
    for _ in range(_SECURITY_SCAN_PASSES):
        decoded = unicodedata.normalize("NFKC", html.unescape(_percent_decode(detected)))
        if len(decoded) > _SECURITY_SCAN_MAX_LENGTH:
            raise ValueError(f"{field_name} expands beyond the security scan bound")
        if decoded == detected:
            break
        detected = decoded

    for character in detected:
        category = unicodedata.category(character)
        if category in {"Cs", "Cf"}:
            raise ValueError(f"{field_name} contains an unsupported Unicode scalar")
        if category == "Cc" and not (allow_newlines and character in {"\n", "\r", "\t"}):
            raise ValueError(f"{field_name} contains an unsupported control character")
    return detected


def _contains_basic_auth_secret(value: str) -> bool:
    for match in _BASIC_AUTH_PATTERN.finditer(value):
        token = match.group(1)
        padded = token + "=" * (-len(token) % 4)
        try:
            decoded = base64.b64decode(padded, validate=True)
        except (binascii.Error, ValueError):
            continue
        if b":" in decoded:
            return True
    return False


def _scan_inert_text(value: str, *, field_name: str, allow_newlines: bool) -> None:
    detected = _security_detection_text(
        value,
        field_name=field_name,
        allow_newlines=allow_newlines,
    )
    slash_normalized = detected.translate(
        str.maketrans(
            {
                "\\": "/",
                "⁄": "/",
                "∕": "/",
                "⧸": "/",
            }
        )
    )
    compact = "".join(character for character in slash_normalized if not character.isspace())
    without_css_comments = _CSS_COMMENT_PATTERN.sub("", slash_normalized)
    compact_without_css_comments = _CSS_COMMENT_PATTERN.sub("", compact)

    if _EXECUTABLE_URI_PATTERN.search(compact) is not None:
        raise ValueError(f"{field_name} contains an executable URI")
    if (
        _REMOTE_URL_PATTERN.search(compact) is not None
        or _WINDOWS_PATH_PATTERN.search(slash_normalized) is not None
    ):
        raise ValueError(f"{field_name} contains a remote URL or external path")
    if _HTML_PATTERN.search(compact) is not None:
        raise ValueError(f"{field_name} contains HTML or SVG markup")
    if (
        _CSS_RULE_PATTERN.search(without_css_comments) is not None
        or _CSS_RULE_PATTERN.search(compact_without_css_comments) is not None
    ):
        raise ValueError(f"{field_name} contains CSS")
    if (
        _BEARER_VALUE_PATTERN.search(detected) is not None
        or _JWT_VALUE_PATTERN.search(detected) is not None
        or _CREDENTIAL_ASSIGNMENT_PATTERN.search(detected) is not None
        or _CREDENTIAL_ASSIGNMENT_PATTERN.search(compact) is not None
        or _PEM_PRIVATE_KEY_PATTERN.search(detected) is not None
        or _OPENAI_SECRET_PATTERN.search(detected) is not None
        or _GITHUB_SECRET_PATTERN.search(detected) is not None
        or _AWS_ACCESS_KEY_PATTERN.search(detected) is not None
        or _contains_basic_auth_secret(detected)
    ):
        raise ValueError(f"{field_name} contains credential material")


def _canonical_text(
    value: Any,
    *,
    field_name: str,
    maximum_length: int,
    allow_newlines: bool = False,
) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    if len(value) > maximum_length:
        raise ValueError(f"{field_name} must be at most {maximum_length} characters")
    for character in value:
        category = unicodedata.category(character)
        if category in {"Cs", "Cf"}:
            raise ValueError(f"{field_name} contains an unsupported Unicode scalar")
        if category == "Cc" and not (allow_newlines and character in {"\n", "\r", "\t"}):
            raise ValueError(f"{field_name} contains an unsupported control character")
    _scan_inert_text(value, field_name=field_name, allow_newlines=allow_newlines)
    return value


def _portable_id(value: Any, *, field_name: str) -> str:
    value = _canonical_text(value, field_name=field_name, maximum_length=128)
    if _PORTABLE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a portable opaque identifier")
    return value


def _engine_key(value: Any, *, field_name: str) -> str:
    value = _canonical_text(value, field_name=field_name, maximum_length=64)
    if _ENGINE_KEY_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase engine key")
    collapsed = re.sub(r"[^a-z0-9]", "", value)
    if collapsed in _SENSITIVE_KEYS or any(
        fragment in collapsed for fragment in _SENSITIVE_KEY_FRAGMENTS
    ):
        raise ValueError(f"{field_name} contains a credential-like key")
    return value


def _static_label(value: Any, *, field_name: str) -> str:
    value = _canonical_text(value, field_name=field_name, maximum_length=128)
    if value != value.lower():
        raise ValueError(f"{field_name} must use canonical lowercase text")
    if re.fullmatch(r"[a-z0-9][a-z0-9 '&(),+._/-]{0,127}", value) is None:
        raise ValueError(f"{field_name} contains unsupported label characters")
    return value


def _require_sorted_unique(values: Sequence[str], *, field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must contain unique values")
    if tuple(values) != tuple(sorted(values)):
        raise ValueError(f"{field_name} must use canonical sorted order")


def document_name_key(value: str) -> str:
    """Return the deterministic comparison key for active document names."""

    return unicodedata.normalize("NFKC", value).casefold()


def _canonical_model_json(model: BaseModel) -> str:
    return json.dumps(
        model.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def document_digest(document: "WorldDocument") -> str:
    """Return a deterministic digest over one complete validated document."""

    if not isinstance(document, (WorldActorDocument, WorldItemDocument)):
        raise TypeError("document must be a world actor or item document")
    validated = parse_world_document(_canonical_model_json(document))
    encoded = _canonical_model_json(validated).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_document_size(document: BaseModel) -> None:
    encoded = _canonical_model_json(document).encode("utf-8")
    if len(encoded) > MAX_DOCUMENT_JSON_BYTES:
        raise ValueError(f"document must encode to at most {MAX_DOCUMENT_JSON_BYTES} bytes")


class DocumentPermissions(_StrictWorldContentModel):
    """Declarative visibility/control policy; GMs remain implicitly authoritative."""

    schema_version: Literal[DOCUMENT_PERMISSIONS_SCHEMA_VERSION] = (
        DOCUMENT_PERMISSIONS_SCHEMA_VERSION
    )
    audience: Literal["gm_only", "assigned_participants", "players", "table"] = "gm_only"
    control: Literal["gm_only", "assigned_participants"] = "gm_only"
    assigned_participant_ids: tuple[str, ...] = Field(
        default=(), max_length=MAX_ASSIGNED_PARTICIPANTS
    )

    @field_validator("assigned_participant_ids")
    @classmethod
    def validate_participant_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for participant_id in value:
            _portable_id(participant_id, field_name="assigned_participant_id")
        _require_sorted_unique(value, field_name="assigned_participant_ids")
        return value

    @model_validator(mode="after")
    def validate_control_visibility(self) -> Self:
        if self.control == "assigned_participants" and self.audience == "gm_only":
            raise ValueError("assigned controllers must also be included in the audience")
        return self

    def can_view(
        self,
        *,
        principal_id: str | None,
        principal_role: WorldContentPrincipalRole,
    ) -> bool:
        if principal_role not in {"gm", "player", "spectator"}:
            raise ValueError("principal_role must be gm, player, or spectator")
        if principal_role == "gm":
            return True
        if self.audience == "table":
            return True
        if principal_role == "spectator":
            return False
        if self.audience == "players":
            return True
        if principal_id is None:
            return False
        principal_id = _portable_id(principal_id, field_name="principal_id")
        return (
            self.audience == "assigned_participants"
            and principal_id in self.assigned_participant_ids
        )

    def can_control(
        self,
        *,
        principal_id: str | None,
        principal_role: WorldContentPrincipalRole,
    ) -> bool:
        if principal_role not in {"gm", "player", "spectator"}:
            raise ValueError("principal_role must be gm, player, or spectator")
        if principal_role == "gm":
            return True
        if principal_role != "player" or principal_id is None or self.control == "gm_only":
            return False
        principal_id = _portable_id(principal_id, field_name="principal_id")
        return principal_id in self.assigned_participant_ids


class DocumentProvenance(_StrictWorldContentModel):
    """Provider-neutral source fingerprints without external IDs or locations."""

    schema_version: Literal[DOCUMENT_PROVENANCE_SCHEMA_VERSION] = DOCUMENT_PROVENANCE_SCHEMA_VERSION
    source_digest: DocumentDigest
    source_record_digest: DocumentDigest | None = None
    import_manifest_digest: DocumentDigest | None = None


class Dnd5eAbilityScores(_StrictWorldContentModel):
    schema_version: Literal[DND5E_ABILITY_SCORES_SCHEMA_VERSION] = (
        DND5E_ABILITY_SCORES_SCHEMA_VERSION
    )
    strength: Annotated[int, Field(strict=True, ge=1, le=30)]
    dexterity: Annotated[int, Field(strict=True, ge=1, le=30)]
    constitution: Annotated[int, Field(strict=True, ge=1, le=30)]
    intelligence: Annotated[int, Field(strict=True, ge=1, le=30)]
    wisdom: Annotated[int, Field(strict=True, ge=1, le=30)]
    charisma: Annotated[int, Field(strict=True, ge=1, le=30)]


class Dnd5eMovementSpeeds(_StrictWorldContentModel):
    schema_version: Literal[DND5E_MOVEMENT_SPEEDS_SCHEMA_VERSION] = (
        DND5E_MOVEMENT_SPEEDS_SCHEMA_VERSION
    )
    walk: Annotated[int, Field(strict=True, ge=0, le=10_000)] = 30
    burrow: Annotated[int, Field(strict=True, ge=0, le=10_000)] | None = None
    climb: Annotated[int, Field(strict=True, ge=0, le=10_000)] | None = None
    fly: Annotated[int, Field(strict=True, ge=0, le=10_000)] | None = None
    swim: Annotated[int, Field(strict=True, ge=0, le=10_000)] | None = None


class Dnd5eSenses(_StrictWorldContentModel):
    schema_version: Literal[DND5E_SENSES_SCHEMA_VERSION] = DND5E_SENSES_SCHEMA_VERSION
    blindsight_ft: Annotated[int, Field(strict=True, ge=0, le=10_000)] | None = None
    darkvision_ft: Annotated[int, Field(strict=True, ge=0, le=10_000)] | None = None
    tremorsense_ft: Annotated[int, Field(strict=True, ge=0, le=10_000)] | None = None
    truesight_ft: Annotated[int, Field(strict=True, ge=0, le=10_000)] | None = None
    passive_perception: Annotated[int, Field(strict=True, ge=0, le=100)] | None = None


class Dnd5eActionInput(_StrictWorldContentModel):
    """Bounded declarative action fields already accepted by ``ActionConfig``."""

    schema_version: Literal[DND5E_ACTION_INPUT_SCHEMA_VERSION] = DND5E_ACTION_INPUT_SCHEMA_VERSION
    name: str
    action_type: Literal["attack", "save", "utility"] = "attack"
    to_hit: Annotated[int, Field(strict=True, ge=-30, le=30)] | None = None
    damage: str | None = None
    damage_type: str = "bludgeoning"
    attack_count: Annotated[int, Field(strict=True, ge=1, le=20)] = 1
    save_dc: Annotated[int, Field(strict=True, ge=1, le=40)] | None = None
    save_ability: Literal["str", "dex", "con", "int", "wis", "cha"] | None = None
    half_on_save: bool = False
    action_cost: Literal["action", "bonus", "reaction", "legendary", "lair"] = "action"
    target_mode: Literal[
        "single_enemy",
        "single_ally",
        "single_creature",
        "self",
        "all_enemies",
        "all_allies",
        "all_creatures",
        "n_enemies",
        "n_allies",
        "random_enemy",
        "random_ally",
    ] = "single_enemy"
    reach_ft: Annotated[int, Field(strict=True, ge=0, le=1_000)] | None = None
    range_ft: Annotated[int, Field(strict=True, ge=0, le=10_000)] | None = None
    range_normal_ft: Annotated[int, Field(strict=True, ge=0, le=10_000)] | None = None
    range_long_ft: Annotated[int, Field(strict=True, ge=0, le=10_000)] | None = None
    max_targets: Annotated[int, Field(strict=True, ge=1, le=1_000)] | None = None
    concentration: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _canonical_text(value, field_name="action name", maximum_length=160)

    @field_validator("damage_type")
    @classmethod
    def validate_damage_type(cls, value: str) -> str:
        return _engine_key(value, field_name="damage_type")

    @field_validator("damage")
    @classmethod
    def validate_damage(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = _canonical_text(value, field_name="damage", maximum_length=64)
        normalized = value.replace(" ", "")
        if normalized.isdigit() or (normalized.startswith("-") and normalized[1:].isdigit()):
            dice_count, die_size, flat = 0, 0, int(normalized)
        else:
            match = _DAMAGE_PATTERN.fullmatch(normalized)
            if match is None:
                raise ValueError("damage must be a bounded engine dice expression")
            dice_count = int(match.group(1) or 0)
            die_size = int(match.group(2) or 0)
            flat = int(match.group(3) or 0)
        if "d" in value.lower() and (dice_count < 1 or die_size < 2):
            raise ValueError("damage dice must use at least one die with at least two sides")
        if dice_count > 100 or die_size > 1_000 or abs(flat) > 1_000_000:
            raise ValueError("damage expression exceeds the supported engine bounds")
        return value

    @model_validator(mode="after")
    def validate_engine_action(self) -> Self:
        if (self.save_dc is None) != (self.save_ability is None):
            raise ValueError("save_dc and save_ability must be provided together")
        if (
            self.range_normal_ft is not None
            and self.range_long_ft is not None
            and self.range_long_ft < self.range_normal_ft
        ):
            raise ValueError("range_long_ft must not be less than range_normal_ft")
        payload = self.model_dump(mode="python", exclude={"schema_version"})
        ActionConfig.model_validate(payload)
        return self


def _validate_static_mapping(
    value: Mapping[str, int],
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> Mapping[str, int]:
    if len(value) > MAX_STATIC_MAPPING_ENTRIES:
        raise ValueError(f"{field_name} must contain at most {MAX_STATIC_MAPPING_ENTRIES} entries")
    for key, amount in value.items():
        _engine_key(key, field_name=f"{field_name} key")
        if type(amount) is not int or not minimum <= amount <= maximum:
            raise ValueError(
                f"{field_name}.{key} must be an integer from {minimum} through {maximum}"
            )
    return MappingProxyType(dict(sorted(value.items())))


class Dnd5eActorSheet(_StrictWorldContentModel):
    """Static actor inputs, excluding all encounter-lifecycle values."""

    schema_version: Literal[DND5E_ACTOR_SHEET_SCHEMA_VERSION] = DND5E_ACTOR_SHEET_SCHEMA_VERSION
    actor_kind: Literal["player_character", "non_player_character"]
    size: Literal["tiny", "small", "medium", "large", "huge", "gargantuan"] = "medium"
    level: Annotated[int, Field(strict=True, ge=1, le=20)] | None = None
    challenge_rating: str | None = None
    max_hit_points: Annotated[int, Field(strict=True, ge=1, le=1_000_000)]
    armor_class: Annotated[int, Field(strict=True, ge=0, le=100)]
    speed_ft: Annotated[int, Field(strict=True, ge=0, le=10_000)] = 30
    initiative_modifier: Annotated[int, Field(strict=True, ge=-30, le=30)] = 0
    movement_speeds: Dnd5eMovementSpeeds = Field(default_factory=Dnd5eMovementSpeeds)
    senses: Dnd5eSenses = Field(default_factory=Dnd5eSenses)
    ability_scores: Dnd5eAbilityScores
    class_levels: Mapping[str, Annotated[int, Field(strict=True, ge=1, le=20)]] = Field(
        default_factory=dict, max_length=20
    )
    save_modifiers: Mapping[str, Annotated[int, Field(strict=True, ge=-30, le=30)]] = Field(
        default_factory=dict, max_length=6
    )
    skill_modifiers: Mapping[str, Annotated[int, Field(strict=True, ge=-30, le=30)]] = Field(
        default_factory=dict, max_length=MAX_STATIC_MAPPING_ENTRIES
    )
    resource_maxima: Mapping[str, Annotated[int, Field(strict=True, ge=1, le=1_000_000)]] = Field(
        default_factory=dict, max_length=MAX_STATIC_MAPPING_ENTRIES
    )
    proficiencies: tuple[str, ...] = Field(default=(), max_length=MAX_STATIC_MAPPING_ENTRIES)
    expertise: tuple[str, ...] = Field(default=(), max_length=MAX_STATIC_MAPPING_ENTRIES)
    languages: tuple[str, ...] = Field(default=(), max_length=MAX_STATIC_MAPPING_ENTRIES)
    traits: tuple[str, ...] = Field(default=(), max_length=MAX_STATIC_MAPPING_ENTRIES)
    known_spells: tuple[str, ...] = Field(default=(), max_length=MAX_STATIC_MAPPING_ENTRIES)
    damage_resistances: tuple[str, ...] = Field(default=(), max_length=MAX_STATIC_MAPPING_ENTRIES)
    damage_immunities: tuple[str, ...] = Field(default=(), max_length=MAX_STATIC_MAPPING_ENTRIES)
    damage_vulnerabilities: tuple[str, ...] = Field(
        default=(), max_length=MAX_STATIC_MAPPING_ENTRIES
    )
    condition_immunities: tuple[str, ...] = Field(default=(), max_length=MAX_STATIC_MAPPING_ENTRIES)
    creature_type: str = "humanoid"
    uses_death_saves: bool | None = None
    actions: tuple[Dnd5eActionInput, ...] = Field(default=(), max_length=MAX_ACTOR_ACTIONS)

    @field_validator("class_levels")
    @classmethod
    def validate_class_levels(cls, value: Mapping[str, int]) -> Mapping[str, int]:
        frozen = _validate_static_mapping(
            value,
            field_name="class_levels",
            minimum=1,
            maximum=20,
        )
        if sum(frozen.values()) > 20:
            raise ValueError("class levels must total at most 20")
        return frozen

    @field_validator("save_modifiers")
    @classmethod
    def validate_save_modifiers(cls, value: Mapping[str, int]) -> Mapping[str, int]:
        allowed = {"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"}
        unknown = set(value).difference(allowed)
        if unknown:
            raise ValueError("save_modifiers contains unsupported abilities")
        return _validate_static_mapping(
            value,
            field_name="save_modifiers",
            minimum=-30,
            maximum=30,
        )

    @field_validator("skill_modifiers")
    @classmethod
    def validate_skill_modifiers(cls, value: Mapping[str, int]) -> Mapping[str, int]:
        return _validate_static_mapping(
            value,
            field_name="skill_modifiers",
            minimum=-30,
            maximum=30,
        )

    @field_validator("resource_maxima")
    @classmethod
    def validate_resource_maxima(cls, value: Mapping[str, int]) -> Mapping[str, int]:
        return _validate_static_mapping(
            value,
            field_name="resource_maxima",
            minimum=1,
            maximum=1_000_000,
        )

    @field_serializer(
        "class_levels",
        "save_modifiers",
        "skill_modifiers",
        "resource_maxima",
    )
    def serialize_static_mapping(self, value: Mapping[str, int]) -> dict[str, int]:
        return dict(value)

    @field_validator("proficiencies", "expertise", "languages", "traits", "known_spells")
    @classmethod
    def validate_static_labels(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        for entry in value:
            _static_label(entry, field_name=info.field_name)
        _require_sorted_unique(value, field_name=info.field_name)
        return value

    @field_validator(
        "damage_resistances",
        "damage_immunities",
        "damage_vulnerabilities",
        "condition_immunities",
    )
    @classmethod
    def validate_engine_keys(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        for entry in value:
            _engine_key(entry, field_name=info.field_name)
        _require_sorted_unique(value, field_name=info.field_name)
        return value

    @field_validator("challenge_rating")
    @classmethod
    def validate_challenge_rating(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = _canonical_text(
            value,
            field_name="challenge_rating",
            maximum_length=4,
        )
        if re.fullmatch(r"(?:0|1/8|1/4|1/2|[1-9]|[12][0-9]|30)", value) is None:
            raise ValueError("challenge_rating must be a canonical value from 0 through 30")
        return value

    @field_validator("creature_type")
    @classmethod
    def validate_creature_type(cls, value: str) -> str:
        return _engine_key(value, field_name="creature_type")

    @model_validator(mode="after")
    def validate_actor_kind(self) -> Self:
        if self.actor_kind == "player_character" and not self.class_levels:
            raise ValueError("player_character sheets require class_levels")
        if (
            self.actor_kind == "player_character"
            and self.level is not None
            and self.level != sum(self.class_levels.values())
        ):
            raise ValueError("level must equal total class levels for player characters")
        if self.speed_ft != self.movement_speeds.walk:
            raise ValueError("speed_ft must match movement_speeds.walk")
        return self


class Dnd5eItemData(_StrictWorldContentModel):
    """Reusable static item data; charges spent and other runtime state are excluded."""

    schema_version: Literal[DND5E_ITEM_DATA_SCHEMA_VERSION] = DND5E_ITEM_DATA_SCHEMA_VERSION
    item_type: Literal["armor", "consumable", "feature", "gear", "spell", "weapon"]
    description: str | None = None
    equip_slots: tuple[str, ...] = Field(default=(), max_length=16)
    value_cp: Annotated[int, Field(strict=True, ge=0, le=1_000_000_000)] = 0
    weight_lb: Annotated[float, Field(strict=True, ge=0, le=1_000_000)] = 0.0
    requires_attunement: bool = False
    consumable: bool = False
    max_charges: Annotated[int, Field(strict=True, ge=1, le=1_000_000)] | None = None
    action: Dnd5eActionInput | None = None

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _canonical_text(
            value,
            field_name="description",
            maximum_length=MAX_DESCRIPTION_LENGTH,
            allow_newlines=True,
        )

    @field_validator("equip_slots")
    @classmethod
    def validate_equip_slots(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for slot in value:
            _engine_key(slot, field_name="equip_slot")
        _require_sorted_unique(value, field_name="equip_slots")
        return value

    @field_validator("weight_lb")
    @classmethod
    def validate_weight_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("weight_lb must be finite")
        return value

    @model_validator(mode="after")
    def validate_static_item_semantics(self) -> Self:
        if self.consumable and self.item_type not in {"consumable", "gear"}:
            raise ValueError("consumable items must use item_type consumable or gear")
        return self


class ActorInventoryItem(_StrictWorldContentModel):
    schema_version: Literal[ACTOR_INVENTORY_ITEM_SCHEMA_VERSION] = (
        ACTOR_INVENTORY_ITEM_SCHEMA_VERSION
    )
    item_id: str
    quantity: Annotated[int, Field(strict=True, ge=1, le=1_000_000)] = 1
    equipped: bool = False
    attuned: bool = False

    @field_validator("item_id")
    @classmethod
    def validate_item_id(cls, value: str) -> str:
        return _portable_id(value, field_name="item_id")


def _validate_document_name(value: str) -> str:
    return _canonical_text(
        value,
        field_name="name",
        maximum_length=MAX_DOCUMENT_NAME_LENGTH,
    )


def _validate_folder_id(value: str | None) -> str | None:
    return None if value is None else _portable_id(value, field_name="folder_id")


def _validate_tags(value: tuple[str, ...]) -> tuple[str, ...]:
    for tag in value:
        tag = _canonical_text(tag, field_name="tag", maximum_length=64)
        if _TAG_PATTERN.fullmatch(tag) is None:
            raise ValueError("tags must be lowercase searchable labels")
    _require_sorted_unique(value, field_name="tags")
    return value


class WorldActorDocument(_StrictWorldContentModel):
    schema_version: Literal[WORLD_ACTOR_DOCUMENT_SCHEMA_VERSION] = (
        WORLD_ACTOR_DOCUMENT_SCHEMA_VERSION
    )
    document_kind: Literal["actor"] = "actor"
    actor_id: str
    table_id: str
    document_revision: PositiveInt = 1
    name: str
    folder_id: str | None = None
    tags: tuple[str, ...] = Field(default=(), max_length=MAX_DOCUMENT_TAGS)
    permissions: DocumentPermissions
    provenance: DocumentProvenance | None = None
    sheet: Dnd5eActorSheet
    inventory: tuple[ActorInventoryItem, ...] = Field(
        default=(), max_length=MAX_ACTOR_INVENTORY_ITEMS
    )
    gm_notes: str | None = None

    @field_validator("actor_id", "table_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _portable_id(value, field_name=info.field_name)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_document_name(value)

    @field_validator("folder_id")
    @classmethod
    def validate_folder_id(cls, value: str | None) -> str | None:
        return _validate_folder_id(value)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_tags(value)

    @field_validator("inventory")
    @classmethod
    def validate_inventory(
        cls, value: tuple[ActorInventoryItem, ...]
    ) -> tuple[ActorInventoryItem, ...]:
        item_ids = tuple(entry.item_id for entry in value)
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("inventory must reference unique item IDs")
        if item_ids != tuple(sorted(item_ids)):
            raise ValueError("inventory must use canonical item order")
        return value

    @field_validator("gm_notes")
    @classmethod
    def validate_gm_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _canonical_text(
            value,
            field_name="gm_notes",
            maximum_length=MAX_DESCRIPTION_LENGTH,
            allow_newlines=True,
        )

    @model_validator(mode="after")
    def validate_encoded_size(self) -> Self:
        _validate_document_size(self)
        return self

    @property
    def document_id(self) -> str:
        return self.actor_id


class WorldItemDocument(_StrictWorldContentModel):
    schema_version: Literal[WORLD_ITEM_DOCUMENT_SCHEMA_VERSION] = WORLD_ITEM_DOCUMENT_SCHEMA_VERSION
    document_kind: Literal["item"] = "item"
    item_id: str
    table_id: str
    document_revision: PositiveInt = 1
    name: str
    folder_id: str | None = None
    tags: tuple[str, ...] = Field(default=(), max_length=MAX_DOCUMENT_TAGS)
    permissions: DocumentPermissions
    provenance: DocumentProvenance | None = None
    data: Dnd5eItemData

    @field_validator("item_id", "table_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _portable_id(value, field_name=info.field_name)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_document_name(value)

    @field_validator("folder_id")
    @classmethod
    def validate_folder_id(cls, value: str | None) -> str | None:
        return _validate_folder_id(value)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_tags(value)

    @model_validator(mode="after")
    def validate_encoded_size(self) -> Self:
        _validate_document_size(self)
        return self

    @property
    def document_id(self) -> str:
        return self.item_id


WorldDocument: TypeAlias = Annotated[
    WorldActorDocument | WorldItemDocument,
    Field(discriminator="document_kind"),
]


class WorldProjectedActorDocument(_StrictWorldContentModel):
    """Actor content safe for an authorized client; authority metadata is absent."""

    schema_version: Literal[WORLD_PROJECTED_ACTOR_DOCUMENT_SCHEMA_VERSION] = (
        WORLD_PROJECTED_ACTOR_DOCUMENT_SCHEMA_VERSION
    )
    document_kind: Literal["actor"] = "actor"
    actor_id: str
    table_id: str
    document_revision: PositiveInt
    name: str
    folder_id: str | None = None
    tags: tuple[str, ...] = ()
    sheet: Dnd5eActorSheet
    inventory: tuple[ActorInventoryItem, ...] = ()
    can_control: bool

    @field_validator("actor_id", "table_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _portable_id(value, field_name=info.field_name)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_document_name(value)

    @field_validator("folder_id")
    @classmethod
    def validate_folder_id(cls, value: str | None) -> str | None:
        return _validate_folder_id(value)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_tags(value)

    @field_validator("inventory")
    @classmethod
    def validate_inventory(
        cls, value: tuple[ActorInventoryItem, ...]
    ) -> tuple[ActorInventoryItem, ...]:
        item_ids = tuple(entry.item_id for entry in value)
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("inventory must reference unique item IDs")
        if item_ids != tuple(sorted(item_ids)):
            raise ValueError("inventory must use canonical item order")
        return value

    @property
    def document_id(self) -> str:
        return self.actor_id


class WorldProjectedItemDocument(_StrictWorldContentModel):
    """Item content safe for an authorized client; provenance is absent."""

    schema_version: Literal[WORLD_PROJECTED_ITEM_DOCUMENT_SCHEMA_VERSION] = (
        WORLD_PROJECTED_ITEM_DOCUMENT_SCHEMA_VERSION
    )
    document_kind: Literal["item"] = "item"
    item_id: str
    table_id: str
    document_revision: PositiveInt
    name: str
    folder_id: str | None = None
    tags: tuple[str, ...] = ()
    data: Dnd5eItemData
    can_control: bool

    @field_validator("item_id", "table_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _portable_id(value, field_name=info.field_name)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_document_name(value)

    @field_validator("folder_id")
    @classmethod
    def validate_folder_id(cls, value: str | None) -> str | None:
        return _validate_folder_id(value)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_tags(value)

    @property
    def document_id(self) -> str:
        return self.item_id


WorldProjectedDocument: TypeAlias = Annotated[
    WorldProjectedActorDocument | WorldProjectedItemDocument,
    Field(discriminator="document_kind"),
]


class WorldContentProjectionEntry(_StrictWorldContentModel):
    document: WorldProjectedDocument
    archived: bool = False

    @property
    def document_id(self) -> str:
        return self.document.document_id

    @property
    def document_kind(self) -> DocumentKind:
        return self.document.document_kind


class WorldContentProjection(_StrictWorldContentModel):
    """A role-filtered client projection with hidden records structurally absent."""

    schema_version: Literal[WORLD_CONTENT_PROJECTION_SCHEMA_VERSION] = (
        WORLD_CONTENT_PROJECTION_SCHEMA_VERSION
    )
    table_id: str
    revision: NonNegativeInt
    documents: tuple[WorldContentProjectionEntry, ...] = ()

    @field_validator("table_id")
    @classmethod
    def validate_table_id(cls, value: str) -> str:
        return _portable_id(value, field_name="table_id")

    @model_validator(mode="after")
    def validate_documents(self) -> Self:
        keys = tuple((entry.document_kind, entry.document_id) for entry in self.documents)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("documents must use unique kind/ID keys in sorted order")
        if any(entry.document.table_id != self.table_id for entry in self.documents):
            raise ValueError("documents must all belong to the projected table")
        return self


class WorldContentEntry(_StrictWorldContentModel):
    document: WorldDocument
    archived: bool = False

    @field_validator("archived", mode="before")
    @classmethod
    def validate_archived(cls, value: Any) -> bool:
        if type(value) is not bool:
            raise ValueError("archived must be a boolean")
        return value

    @property
    def document_id(self) -> str:
        return self.document.document_id

    @property
    def document_kind(self) -> DocumentKind:
        return self.document.document_kind


class WorldContentView(_StrictWorldContentModel):
    schema_version: Literal[WORLD_CONTENT_VIEW_SCHEMA_VERSION] = WORLD_CONTENT_VIEW_SCHEMA_VERSION
    table_id: str
    revision: NonNegativeInt
    documents: tuple[WorldContentEntry, ...] = ()

    @field_validator("table_id")
    @classmethod
    def validate_table_id(cls, value: str) -> str:
        return _portable_id(value, field_name="table_id")

    @model_validator(mode="after")
    def validate_document_projection(self) -> Self:
        keys = tuple((entry.document_kind, entry.document_id) for entry in self.documents)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("documents must use unique kind/ID keys in sorted order")
        if any(entry.document.table_id != self.table_id for entry in self.documents):
            raise ValueError("documents must all belong to the projected table")
        actors = tuple(entry for entry in self.documents if entry.document_kind == "actor")
        items = tuple(entry for entry in self.documents if entry.document_kind == "item")
        if len(actors) > MAX_RETAINED_ACTORS or len(items) > MAX_RETAINED_ITEMS:
            raise ValueError("document projection exceeds retained content limits")
        active_actors = tuple(entry for entry in actors if not entry.archived)
        active_items = tuple(entry for entry in items if not entry.archived)
        if len(active_actors) > MAX_ACTIVE_ACTORS:
            raise ValueError("document projection exceeds the active actor limit")
        if len(active_items) > MAX_ACTIVE_ITEMS:
            raise ValueError("document projection exceeds the active item limit")
        names = [
            (entry.document_kind, document_name_key(entry.document.name))
            for entry in self.active_documents
        ]
        if len(names) != len(set(names)):
            raise ValueError("active document names must be unique by kind")
        return self

    @property
    def active_documents(self) -> tuple[WorldContentEntry, ...]:
        return tuple(entry for entry in self.documents if not entry.archived)

    @property
    def archived_documents(self) -> tuple[WorldContentEntry, ...]:
        return tuple(entry for entry in self.documents if entry.archived)

    def entry(self, document_kind: DocumentKind, document_id: str) -> WorldContentEntry | None:
        document_id = _portable_id(document_id, field_name="document_id")
        return next(
            (
                entry
                for entry in self.documents
                if entry.document_kind == document_kind and entry.document_id == document_id
            ),
            None,
        )

    def document(
        self, document_kind: DocumentKind, document_id: str
    ) -> WorldActorDocument | WorldItemDocument | None:
        entry = self.entry(document_kind, document_id)
        return None if entry is None else entry.document


class WorldContentSearchHit(_StrictWorldContentModel):
    """Audience-filtered searchable metadata; sheets and descriptions are absent."""

    schema_version: Literal[WORLD_CONTENT_SEARCH_HIT_SCHEMA_VERSION] = (
        WORLD_CONTENT_SEARCH_HIT_SCHEMA_VERSION
    )
    table_id: str
    document_kind: DocumentKind
    document_id: str
    name: str
    folder_id: str | None = None
    tags: tuple[str, ...] = ()
    can_control: bool

    @field_validator("table_id", "document_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _portable_id(value, field_name=info.field_name)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_document_name(value)

    @field_validator("folder_id")
    @classmethod
    def validate_folder_id(cls, value: str | None) -> str | None:
        return _validate_folder_id(value)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_tags(value)


class _WorldContentCommandBase(_StrictWorldContentModel):
    schema_version: Literal[WORLD_CONTENT_COMMAND_SCHEMA_VERSION] = (
        WORLD_CONTENT_COMMAND_SCHEMA_VERSION
    )
    command_id: str
    expected_revision: NonNegativeInt

    @field_validator("command_id")
    @classmethod
    def validate_command_id(cls, value: str) -> str:
        return _portable_id(value, field_name="command_id")


class WorldContentCreateCommand(_WorldContentCommandBase):
    command_type: Literal["create"] = "create"
    document: WorldDocument

    @model_validator(mode="after")
    def validate_initial_revision(self) -> Self:
        if self.document.document_revision != 1:
            raise ValueError("created documents must start at document_revision 1")
        return self


class WorldContentUpdateCommand(_WorldContentCommandBase):
    command_type: Literal["update"] = "update"
    document: WorldDocument


class WorldContentArchiveCommand(_WorldContentCommandBase):
    command_type: Literal["archive"] = "archive"
    table_id: str
    document_kind: DocumentKind
    document_id: str

    @field_validator("table_id", "document_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _portable_id(value, field_name=info.field_name)


WorldContentMutationCommand: TypeAlias = Annotated[
    WorldContentCreateCommand | WorldContentUpdateCommand | WorldContentArchiveCommand,
    Field(discriminator="command_type"),
]


class _WorldContentEventBase(_StrictWorldContentModel):
    schema_version: Literal[WORLD_CONTENT_EVENT_SCHEMA_VERSION] = WORLD_CONTENT_EVENT_SCHEMA_VERSION
    event_id: str
    sequence: PositiveInt
    revision: PositiveInt
    command_id: str

    @field_validator("event_id", "command_id")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _portable_id(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_sequence_revision(self) -> Self:
        if self.sequence != self.revision:
            raise ValueError("sequence must match revision")
        return self


class WorldContentCreatedEvent(_WorldContentEventBase):
    event_type: Literal["created"] = "created"
    document: WorldDocument


class WorldContentUpdatedEvent(_WorldContentEventBase):
    event_type: Literal["updated"] = "updated"
    previous_document_digest: DocumentDigest
    document: WorldDocument


class WorldContentArchivedEvent(_WorldContentEventBase):
    event_type: Literal["archived"] = "archived"
    table_id: str
    document_kind: DocumentKind
    document_id: str
    prior_document_digest: DocumentDigest

    @field_validator("table_id", "document_id")
    @classmethod
    def validate_document_identity(cls, value: str, info: Any) -> str:
        return _portable_id(value, field_name=info.field_name)


WorldContentMutationEvent: TypeAlias = Annotated[
    WorldContentCreatedEvent | WorldContentUpdatedEvent | WorldContentArchivedEvent,
    Field(discriminator="event_type"),
]


class WorldContentMutationReceipt(_StrictWorldContentModel):
    schema_version: Literal[WORLD_CONTENT_RECEIPT_SCHEMA_VERSION] = (
        WORLD_CONTENT_RECEIPT_SCHEMA_VERSION
    )
    command_id: str
    revision: PositiveInt
    event: WorldContentMutationEvent

    @field_validator("command_id")
    @classmethod
    def validate_command_id(cls, value: str) -> str:
        return _portable_id(value, field_name="command_id")

    @model_validator(mode="after")
    def validate_event_identity(self) -> Self:
        if self.event.command_id != self.command_id:
            raise ValueError("event.command_id must match command_id")
        if self.event.revision != self.revision:
            raise ValueError("event.revision must match revision")
        return self


_COMMAND_ADAPTER = TypeAdapter(WorldContentMutationCommand)
_EVENT_ADAPTER = TypeAdapter(WorldContentMutationEvent)
_DOCUMENT_ADAPTER = TypeAdapter(WorldDocument)


def parse_world_content_command(value: Any) -> WorldContentMutationCommand:
    if isinstance(value, (str, bytes, bytearray)):
        return _COMMAND_ADAPTER.validate_json(value)
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return _COMMAND_ADAPTER.validate_json(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def parse_world_content_event(value: Any) -> WorldContentMutationEvent:
    if isinstance(value, (str, bytes, bytearray)):
        return _EVENT_ADAPTER.validate_json(value)
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return _EVENT_ADAPTER.validate_json(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def parse_world_document(value: Any) -> WorldDocument:
    if isinstance(value, (str, bytes, bytearray)):
        return _DOCUMENT_ADAPTER.validate_json(value)
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return _DOCUMENT_ADAPTER.validate_json(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


__all__ = [
    "ACTOR_INVENTORY_ITEM_SCHEMA_VERSION",
    "DND5E_ABILITY_SCORES_SCHEMA_VERSION",
    "DND5E_ACTION_INPUT_SCHEMA_VERSION",
    "DND5E_ACTOR_SHEET_SCHEMA_VERSION",
    "DND5E_ITEM_DATA_SCHEMA_VERSION",
    "DND5E_MOVEMENT_SPEEDS_SCHEMA_VERSION",
    "DND5E_SENSES_SCHEMA_VERSION",
    "DOCUMENT_PERMISSIONS_SCHEMA_VERSION",
    "DOCUMENT_PROVENANCE_SCHEMA_VERSION",
    "MAX_ACTIVE_ACTORS",
    "MAX_ACTIVE_ITEMS",
    "MAX_ACTOR_ACTIONS",
    "MAX_ACTOR_INVENTORY_ITEMS",
    "MAX_ASSIGNED_PARTICIPANTS",
    "MAX_DOCUMENT_TAGS",
    "MAX_DOCUMENT_JSON_BYTES",
    "MAX_RETAINED_ACTORS",
    "MAX_RETAINED_ITEMS",
    "MAX_SEARCH_RESULTS",
    "WORLD_ACTOR_DOCUMENT_SCHEMA_VERSION",
    "WORLD_CONTENT_COMMAND_SCHEMA_VERSION",
    "WORLD_CONTENT_EVENT_SCHEMA_VERSION",
    "WORLD_CONTENT_RECEIPT_SCHEMA_VERSION",
    "WORLD_CONTENT_PROJECTION_SCHEMA_VERSION",
    "WORLD_CONTENT_SEARCH_HIT_SCHEMA_VERSION",
    "WORLD_CONTENT_VIEW_SCHEMA_VERSION",
    "WORLD_ITEM_DOCUMENT_SCHEMA_VERSION",
    "WORLD_PROJECTED_ACTOR_DOCUMENT_SCHEMA_VERSION",
    "WORLD_PROJECTED_ITEM_DOCUMENT_SCHEMA_VERSION",
    "ActorInventoryItem",
    "Dnd5eAbilityScores",
    "Dnd5eActionInput",
    "Dnd5eActorSheet",
    "Dnd5eItemData",
    "Dnd5eMovementSpeeds",
    "Dnd5eSenses",
    "DocumentKind",
    "DocumentPermissions",
    "DocumentProvenance",
    "WorldActorDocument",
    "WorldContentArchiveCommand",
    "WorldContentArchivedEvent",
    "WorldContentCreateCommand",
    "WorldContentCreatedEvent",
    "WorldContentEntry",
    "WorldContentMutationCommand",
    "WorldContentMutationEvent",
    "WorldContentMutationReceipt",
    "WorldContentPrincipalRole",
    "WorldContentProjection",
    "WorldContentProjectionEntry",
    "WorldContentSearchHit",
    "WorldContentUpdateCommand",
    "WorldContentUpdatedEvent",
    "WorldContentView",
    "WorldDocument",
    "WorldItemDocument",
    "WorldProjectedActorDocument",
    "WorldProjectedDocument",
    "WorldProjectedItemDocument",
    "document_digest",
    "document_name_key",
    "parse_world_content_command",
    "parse_world_content_event",
    "parse_world_document",
]
