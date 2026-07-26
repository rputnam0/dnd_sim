"""Versioned supported-rules profiles for authoritative simulation behavior."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator

RULES_PROFILE_SCHEMA_VERSION = "1.0"
DEFAULT_RULES_PROFILE_ID = "5e_2014_combat_foundation"
DEFAULT_RULES_PROFILE_VERSION = "1.0.0"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULES_PROFILES_DIR = REPO_ROOT / "db" / "rules" / "2014" / "profiles"

ActorKind: TypeAlias = Literal["player_character", "monster", "summon", "construct"]
ZeroHitPointMode: TypeAlias = Literal["death_saves", "dead"]

_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class _StrictProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ZeroHitPointPolicy(_StrictProfileModel):
    """Default zero-HP disposition by runtime actor kind."""

    player_character: ZeroHitPointMode
    monster: ZeroHitPointMode
    summon: ZeroHitPointMode
    construct_actor: ZeroHitPointMode = Field(alias="construct")
    allow_explicit_actor_override: bool

    def resolve_uses_death_saves(
        self,
        *,
        actor_kind: ActorKind,
        explicit: bool | None = None,
    ) -> bool:
        if explicit is not None:
            if not self.allow_explicit_actor_override:
                raise ValueError("rules profile does not allow explicit actor overrides")
            return explicit
        mode_by_kind: dict[ActorKind, ZeroHitPointMode] = {
            "player_character": self.player_character,
            "monster": self.monster,
            "summon": self.summon,
            "construct": self.construct_actor,
        }
        return mode_by_kind[actor_kind] == "death_saves"


class SupportedRulesProfile(_StrictProfileModel):
    """Pinned, validated rules policy selected by a scenario."""

    schema_version: Literal["1.0"]
    profile_id: str
    profile_version: str
    ruleset: Literal["5e-2014"]
    zero_hit_point_policy: ZeroHitPointPolicy

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        if _PROFILE_ID_RE.fullmatch(value) is None:
            raise ValueError("profile_id must use safe lowercase snake_case")
        return value

    @field_validator("profile_version")
    @classmethod
    def validate_profile_version(cls, value: str) -> str:
        if _SEMVER_RE.fullmatch(value) is None:
            raise ValueError("profile_version must be semantic version X.Y.Z")
        return value

    def resolve_uses_death_saves(
        self,
        *,
        actor_kind: ActorKind,
        explicit: bool | None = None,
    ) -> bool:
        return self.zero_hit_point_policy.resolve_uses_death_saves(
            actor_kind=actor_kind,
            explicit=explicit,
        )

    def reference(self) -> dict[str, str]:
        return {
            "ruleset": self.ruleset,
            "rules_profile_id": self.profile_id,
            "rules_profile_version": self.profile_version,
        }


@lru_cache(maxsize=32)
def load_supported_rules_profile(
    *,
    profile_id: str = DEFAULT_RULES_PROFILE_ID,
    profile_version: str = DEFAULT_RULES_PROFILE_VERSION,
    profiles_dir: Path = DEFAULT_RULES_PROFILES_DIR,
) -> SupportedRulesProfile:
    """Load an exact rules profile reference and reject implicit version drift."""

    if _PROFILE_ID_RE.fullmatch(profile_id) is None:
        raise ValueError("profile_id must use safe lowercase snake_case")
    if _SEMVER_RE.fullmatch(profile_version) is None:
        raise ValueError("profile_version must be semantic version X.Y.Z")

    source = profiles_dir.resolve() / f"{profile_id}.json"
    if not source.is_file():
        raise ValueError(f"rules profile not found: {profile_id}@{profile_version}")

    profile = SupportedRulesProfile.model_validate_json(source.read_text(encoding="utf-8"))
    if profile.profile_id != profile_id:
        raise ValueError(
            f"rules profile ID mismatch: requested {profile_id}, found {profile.profile_id}"
        )
    if profile.profile_version != profile_version:
        raise ValueError(
            "rules profile version mismatch: "
            f"requested {profile_version}, found {profile.profile_version}"
        )
    return profile


__all__ = [
    "ActorKind",
    "DEFAULT_RULES_PROFILE_ID",
    "DEFAULT_RULES_PROFILE_VERSION",
    "DEFAULT_RULES_PROFILES_DIR",
    "RULES_PROFILE_SCHEMA_VERSION",
    "SupportedRulesProfile",
    "ZeroHitPointMode",
    "ZeroHitPointPolicy",
    "load_supported_rules_profile",
]
