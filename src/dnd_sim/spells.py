from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

DuplicatePolicy = Literal["fail_fast", "prefer_richest"]

_SPELL_NORMALIZE_RE = re.compile(r"[\s_-]+")
_SPELL_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
_RANGE_FEET_RE = re.compile(r"(\d+)\s*(?:feet|foot|ft\.?)", flags=re.IGNORECASE)
_RANGE_MILES_RE = re.compile(r"(\d+)\s*miles?", flags=re.IGNORECASE)
_LEVEL_RE = re.compile(r"(\d+)(?:st|nd|rd|th)\s*[- ]+\s*level", flags=re.IGNORECASE)
_CANTRIP_RE = re.compile(r"\bcantrip\b", flags=re.IGNORECASE)
_SCHOOL_CANTRIP_RE = re.compile(r"([A-Za-z]+)\s+cantrip\b", flags=re.IGNORECASE)
_SCHOOL_LEVELED_RE = re.compile(
    r"\d+(?:st|nd|rd|th)\s*[- ]+\s*level\s+([A-Za-z]+)",
    flags=re.IGNORECASE,
)
_DURATION_VALUE_RE = re.compile(
    r"(\d+)\s*(round|rounds|minute|minutes|hour|hours|day|days)\b",
    flags=re.IGNORECASE,
)
_SAVE_ABILITY_RE = re.compile(
    r"make\s+a\s+(strength|dexterity|constitution|intelligence|wisdom|charisma)\s+saving throw",
    flags=re.IGNORECASE,
)
_ABILITY_NAME_TO_SHORT = {
    "strength": "str",
    "dexterity": "dex",
    "constitution": "con",
    "intelligence": "int",
    "wisdom": "wis",
    "charisma": "cha",
}
_ABILITY_SHORT = set(_ABILITY_NAME_TO_SHORT.values())
_SPELL_DB_CACHE: tuple[Path, DuplicatePolicy, dict[str, dict[str, Any]]] | None = None
_META_HYPHEN_TRANSLATION = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u00ad": "-",
        "\u2043": "-",
        "\uFE63": "-",
        "\uFF0D": "-",
    }
)


class SpellDatabaseValidationError(ValueError):
    """Raised when spell records cannot be validated into canonical schema."""


class CanonicalSpellRecord(BaseModel):
    name: str
    type: Literal["spell"] = "spell"
    level: int = Field(ge=0, le=9)
    school: str | None = None
    casting_time: str
    action_type: Literal["attack", "save", "utility"] | None = None
    target_mode: Literal[
        "single_enemy",
        "single_ally",
        "self",
        "all_enemies",
        "all_allies",
        "all_creatures",
        "n_enemies",
        "n_allies",
        "random_enemy",
        "random_ally",
    ] | None = None
    range_ft: int | None = Field(default=None, ge=0)
    concentration: bool = False
    ritual: bool = False
    duration_rounds: int | None = Field(default=None, ge=0)
    description: str
    save_dc: int | None = Field(default=None, ge=0)
    save_ability: str | None = None
    damage_type: str | None = None
    mechanics: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("name", "casting_time", "description")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("school")
    @classmethod
    def _normalize_school(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text.title() if text else None

    @field_validator("save_ability")
    @classmethod
    def _normalize_save_ability(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip().lower()
        if not text:
            return None
        if text in _ABILITY_SHORT:
            return text
        if text in _ABILITY_NAME_TO_SHORT:
            return _ABILITY_NAME_TO_SHORT[text]
        raise ValueError(f"unsupported save ability '{value}'")


def slugify_spell_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def spell_lookup_key(name: str) -> str:
    text = str(name).strip().lower()
    text = text.replace("’", "'").replace("`", "'")
    text = re.sub(r"\[[^]]*\]", " ", text)
    text = re.sub(
        r"\((?:ritual|concentration|materials?|somatic|verbal|v,s,m)[^)]*\)",
        " ",
        text,
    )
    text = text.replace("'", "")
    text = _SPELL_PUNCT_RE.sub(" ", text)
    return _SPELL_NORMALIZE_RE.sub(" ", text).strip()


def spell_name_variants(name: str) -> list[str]:
    raw = str(name).strip()
    variants = {raw}
    normalized = raw.replace("’", "'")
    variants.add(normalized)
    variants.add(re.sub(r"\[[^]]*\]", "", normalized).strip())
    variants.add(re.sub(r"\([^)]*\)", "", normalized).strip())
    collapsed = re.sub(r"\[[^]]*\]", "", re.sub(r"\([^)]*\)", "", normalized)).strip()
    variants.add(collapsed)
    variants.add(re.sub(r"\s+", " ", collapsed).strip())
    return [value for value in variants if value]


def _normalize_meta_text(meta: str) -> str:
    text = str(meta).translate(_META_HYPHEN_TRANSLATION)
    text = re.sub(r"-{2,}", "-", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_level_from_meta(meta: str) -> int | None:
    normalized_meta = _normalize_meta_text(meta)
    if _CANTRIP_RE.search(normalized_meta):
        return 0
    match = _LEVEL_RE.search(normalized_meta)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _parse_school_from_meta(meta: str) -> str | None:
    normalized_meta = _normalize_meta_text(meta)
    cantrip_match = _SCHOOL_CANTRIP_RE.search(normalized_meta)
    if cantrip_match:
        return cantrip_match.group(1).title()
    leveled_match = _SCHOOL_LEVELED_RE.search(normalized_meta)
    if leveled_match:
        return leveled_match.group(1).title()
    return None


def _parse_range_ft(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text == "self":
        return 0
    feet_match = _RANGE_FEET_RE.search(text)
    if feet_match:
        return int(feet_match.group(1))
    miles_match = _RANGE_MILES_RE.search(text)
    if miles_match:
        return int(miles_match.group(1)) * 5280
    return None


def _duration_to_rounds(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if "instantaneous" in text:
        return 0

    match = _DURATION_VALUE_RE.search(text)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("round"):
        return amount
    if unit.startswith("minute"):
        return amount * 10
    if unit.startswith("hour"):
        return amount * 600
    if unit.startswith("day"):
        return amount * 14400
    return None


def _extract_save_ability(description: str) -> str | None:
    match = _SAVE_ABILITY_RE.search(description)
    if not match:
        return None
    return _ABILITY_NAME_TO_SHORT.get(match.group(1).lower())


def _coerce_mechanics(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SpellDatabaseValidationError("mechanics must be a list")
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(value):
        if isinstance(row, str):
            text = row.strip()
            if text:
                out.append({"effect_type": "note", "text": text})
            continue
        if not isinstance(row, dict):
            raise SpellDatabaseValidationError(f"mechanics[{idx}] must be an object")
        out.append(dict(row))
    return out


def canonicalize_spell_payload(
    payload: dict[str, Any], *, source_path: Path | None = None
) -> dict[str, Any]:
    """Normalize a spell payload to canonical spell schema and validate it."""

    if not isinstance(payload, dict):
        raise SpellDatabaseValidationError("Spell payload must be a JSON object")

    source = str(source_path) if source_path is not None else "<memory>"
    name = str(payload.get("name", "")).strip()
    meta = str(payload.get("meta", "")).strip()
    description = str(payload.get("description") or payload.get("description_raw") or "").strip()
    if not description:
        description = str(payload.get("meta") or name).strip()

    level_raw = payload.get("level")
    if level_raw is None:
        level_raw = _parse_level_from_meta(meta)
    if level_raw is None:
        level_raw = 0

    school_raw = payload.get("school")
    if school_raw is None:
        school_raw = _parse_school_from_meta(meta)

    concentration_raw = payload.get("concentration")
    if concentration_raw is None:
        concentration_raw = "concentration" in str(payload.get("duration", "")).lower()
    ritual_raw = payload.get("ritual")
    if ritual_raw is None:
        ritual_text = " ".join(
            [
                str(payload.get("meta", "")),
                str(payload.get("casting_time", "")),
                str(payload.get("name", "")),
            ]
        ).lower()
        ritual_raw = "ritual" in ritual_text

    save_ability = payload.get("save_ability")
    if save_ability is None and description:
        save_ability = _extract_save_ability(description)

    casting_time = str(payload.get("casting_time", "")).strip() or "action"

    normalized = {
        "name": name,
        "type": str(payload.get("type", "spell") or "spell").strip().lower(),
        "level": int(level_raw),
        "school": school_raw,
        "casting_time": casting_time,
        "action_type": str(payload.get("action_type", "")).strip().lower() or None,
        "target_mode": str(payload.get("target_mode", "")).strip().lower() or None,
        "range_ft": _parse_range_ft(payload.get("range_ft", payload.get("range"))),
        "concentration": bool(concentration_raw),
        "ritual": bool(ritual_raw),
        "duration_rounds": _duration_to_rounds(
            payload.get("duration_rounds", payload.get("duration"))
        ),
        "description": description,
        "save_dc": int(payload["save_dc"]) if payload.get("save_dc") is not None else None,
        "save_ability": save_ability,
        "damage_type": payload.get("damage_type"),
        "mechanics": _coerce_mechanics(payload.get("mechanics")),
    }

    try:
        record = CanonicalSpellRecord.model_validate(normalized)
    except (ValidationError, ValueError) as exc:
        raise SpellDatabaseValidationError(f"Invalid spell schema in {source}: {exc}") from exc
    return record.model_dump()


def _record_richness(record: dict[str, Any]) -> tuple[int, int]:
    score = 0
    for field in ("school", "range_ft", "duration_rounds", "save_ability", "damage_type"):
        value = record.get(field)
        if value not in (None, ""):
            score += 1
    if record.get("mechanics"):
        score += 3
    if record.get("concentration"):
        score += 1
    if record.get("ritual"):
        score += 1
    if record.get("description"):
        score += 1
    return score, len(record.get("description", ""))


def _select_duplicate_record(
    *,
    key: str,
    existing_record: dict[str, Any],
    existing_path: Path,
    candidate_record: dict[str, Any],
    candidate_path: Path,
    policy: DuplicatePolicy,
) -> tuple[dict[str, Any], Path]:
    if policy == "fail_fast":
        raise SpellDatabaseValidationError(
            "Duplicate spell lookup key " f"'{key}' found in {existing_path} and {candidate_path}."
        )

    existing_rank = (_record_richness(existing_record), str(existing_path))
    candidate_rank = (_record_richness(candidate_record), str(candidate_path))
    if candidate_rank > existing_rank:
        return candidate_record, candidate_path
    return existing_record, existing_path


def clear_spell_database_cache() -> None:
    global _SPELL_DB_CACHE
    _SPELL_DB_CACHE = None


def load_spell_database(
    spells_dir: Path, *, duplicate_policy: DuplicatePolicy = "fail_fast"
) -> dict[str, dict[str, Any]]:
    """Load and validate all spell records keyed by normalized lookup key."""

    root = Path(spells_dir)
    if not root.exists():
        raise SpellDatabaseValidationError(f"Spell directory does not exist: {root}")

    by_key: dict[str, dict[str, Any]] = {}
    key_sources: dict[str, Path] = {}

    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SpellDatabaseValidationError(f"Invalid spell JSON at {path}: {exc}") from exc
        canonical = canonicalize_spell_payload(payload, source_path=path)
        key = spell_lookup_key(canonical["name"])
        if not key:
            raise SpellDatabaseValidationError(f"Invalid spell name in {path}")
        if key not in by_key:
            by_key[key] = canonical
            key_sources[key] = path
            continue

        selected_record, selected_path = _select_duplicate_record(
            key=key,
            existing_record=by_key[key],
            existing_path=key_sources[key],
            candidate_record=canonical,
            candidate_path=path,
            policy=duplicate_policy,
        )
        by_key[key] = selected_record
        key_sources[key] = selected_path

    return by_key


def get_spell_database(
    spells_dir: Path, *, duplicate_policy: DuplicatePolicy = "fail_fast"
) -> dict[str, dict[str, Any]]:
    global _SPELL_DB_CACHE
    root = Path(spells_dir).resolve()
    if _SPELL_DB_CACHE is not None:
        cached_root, cached_policy, cached_records = _SPELL_DB_CACHE
        if cached_root == root and cached_policy == duplicate_policy:
            return cached_records

    records = load_spell_database(root, duplicate_policy=duplicate_policy)
    _SPELL_DB_CACHE = (root, duplicate_policy, records)
    return records


def lookup_spell_definition(
    name: str,
    *,
    spells_dir: Path,
    duplicate_policy: DuplicatePolicy = "fail_fast",
) -> dict[str, Any] | None:
    records = get_spell_database(spells_dir, duplicate_policy=duplicate_policy)
    for variant in spell_name_variants(name):
        key = spell_lookup_key(variant)
        if key and key in records:
            return dict(records[key])
    return None
