from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

_CLASS_LEVEL_SEGMENT_RE = re.compile(r"^\s*([A-Za-z][A-Za-z' -]*?)\s+(\d+)\s*$")
_CLASS_LEVEL_FALLBACK_RE = re.compile(r"([A-Za-z][A-Za-z' -]+?)\s*(\d+)")
_ABILITY_DISPLAY_NAMES = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}
_MULTICLASS_PREREQUISITES: dict[str, tuple[dict[str, int], ...]] = {
    "artificer": ({"int": 13},),
    "barbarian": ({"str": 13},),
    "bard": ({"cha": 13},),
    "cleric": ({"wis": 13},),
    "druid": ({"wis": 13},),
    "fighter": ({"str": 13}, {"dex": 13}),
    "monk": ({"dex": 13, "wis": 13},),
    "paladin": ({"str": 13, "cha": 13},),
    "ranger": ({"dex": 13, "wis": 13},),
    "rogue": ({"dex": 13},),
    "sorcerer": ({"cha": 13},),
    "warlock": ({"cha": 13},),
    "wizard": ({"int": 13},),
}
_FULL_CASTER_CLASSES = {"bard", "cleric", "druid", "sorcerer", "wizard"}
_HALF_CASTER_CLASSES = {"paladin", "ranger"}
_HALF_UP_CASTER_CLASSES = {"artificer"}
_THIRD_CASTER_CLASSES = {"arcane trickster", "eldritch knight"}
_MULTICLASS_SPELL_SLOT_TABLE: dict[int, dict[int, int]] = {
    1: {1: 2},
    2: {1: 3},
    3: {1: 4, 2: 2},
    4: {1: 4, 2: 3},
    5: {1: 4, 2: 3, 3: 2},
    6: {1: 4, 2: 3, 3: 3},
    7: {1: 4, 2: 3, 3: 3, 4: 1},
    8: {1: 4, 2: 3, 3: 3, 4: 2},
    9: {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},
    10: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2},
    11: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1},
    12: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1},
    13: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1},
    14: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1},
    15: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1},
    16: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1},
    17: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1, 9: 1},
    18: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 1, 7: 1, 8: 1, 9: 1},
    19: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 1, 8: 1, 9: 1},
    20: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 2, 8: 1, 9: 1},
}


@dataclass(frozen=True, slots=True)
class ClassLevelValidation:
    class_level_text: str
    class_levels: dict[str, int]
    total_level: int


def normalize_class_name(class_name: str) -> str:
    return re.sub(r"\s+", " ", str(class_name).strip().lower()).strip()


def normalize_class_levels(class_levels: Mapping[str, int] | None) -> dict[str, int]:
    normalized: dict[str, int] = {}
    if not isinstance(class_levels, Mapping):
        return normalized
    for raw_name, raw_level in class_levels.items():
        key = normalize_class_name(str(raw_name))
        if not key:
            continue
        level = int(raw_level)
        if level <= 0:
            raise ValueError(f"invalid class_level: class_levels.{key} must be >= 1")
        normalized[key] = normalized.get(key, 0) + level
    return normalized


def parse_class_levels(class_level_text: str) -> dict[str, int]:
    text = str(class_level_text or "").strip()
    if not text:
        return {}
    try:
        return parse_class_levels_strict(text)
    except ValueError:
        pass

    fallback: dict[str, int] = {}
    for class_name, raw_level in _CLASS_LEVEL_FALLBACK_RE.findall(text):
        key = normalize_class_name(class_name)
        if not key:
            continue
        fallback[key] = fallback.get(key, 0) + int(raw_level)
    return fallback


def parse_class_levels_strict(class_level_text: str) -> dict[str, int]:
    text = str(class_level_text or "").strip()
    if not text:
        return {}

    levels: dict[str, int] = {}
    segments = [segment.strip() for segment in text.split("/")]
    if any(not segment for segment in segments):
        raise ValueError(f"invalid class_level: '{class_level_text}'")
    for segment in segments:
        match = _CLASS_LEVEL_SEGMENT_RE.fullmatch(segment)
        if match is None:
            raise ValueError(f"invalid class_level: '{class_level_text}'")
        key = normalize_class_name(match.group(1))
        level = int(match.group(2))
        if not key or level <= 0:
            raise ValueError(f"invalid class_level: '{class_level_text}'")
        levels[key] = levels.get(key, 0) + level
    return levels


def _title_class_name(class_name: str) -> str:
    words: list[str] = []
    for token in normalize_class_name(class_name).split(" "):
        parts = [part.capitalize() for part in token.split("'")]
        words.append("'".join(parts))
    return " ".join(words)


def canonical_class_level_text(class_levels: Mapping[str, int] | None) -> str:
    normalized = normalize_class_levels(class_levels)
    if not normalized:
        return ""
    return " / ".join(
        f"{_title_class_name(class_name)} {normalized[class_name]}"
        for class_name in sorted(normalized.keys())
    )


def total_character_level(class_levels: Mapping[str, int] | None) -> int:
    return sum(normalize_class_levels(class_levels).values())


def class_level_for(class_levels: Mapping[str, int] | None, class_name: str) -> int:
    normalized_levels = normalize_class_levels(class_levels)
    key = normalize_class_name(class_name)
    return int(normalized_levels.get(key, 0))


def _format_requirement_set(requirements: Mapping[str, int]) -> str:
    return " and ".join(
        f"{_ABILITY_DISPLAY_NAMES[ability]} {threshold}"
        for ability, threshold in requirements.items()
    )


def _format_requirement_text(requirements: tuple[dict[str, int], ...]) -> str:
    if len(requirements) == 1:
        return _format_requirement_set(requirements[0])
    return " or ".join(_format_requirement_set(requirement) for requirement in requirements)


def validate_multiclass_prerequisites(
    *,
    class_levels: Mapping[str, int] | None,
    ability_scores: Mapping[str, int] | None,
    adding_class: str | None = None,
) -> list[str]:
    normalized_levels = normalize_class_levels(class_levels)
    tracked_classes = set(normalized_levels.keys())
    if adding_class:
        tracked_classes.add(normalize_class_name(adding_class))
    if len(tracked_classes) < 2:
        return []

    scores: dict[str, int] = {
        key: int(value)
        for key, value in (ability_scores or {}).items()
        if key in _ABILITY_DISPLAY_NAMES
    }

    errors: list[str] = []
    for class_name in sorted(tracked_classes):
        requirements = _MULTICLASS_PREREQUISITES.get(class_name)
        if requirements is None:
            continue
        meets_requirement = any(
            all(scores.get(ability, 0) >= threshold for ability, threshold in option.items())
            for option in requirements
        )
        if not meets_requirement:
            req_text = _format_requirement_text(requirements)
            errors.append(f"{class_name} requires {req_text} for multiclassing.")
    return errors


def spellcaster_level_for_multiclass(class_levels: Mapping[str, int] | None) -> int:
    normalized_levels = normalize_class_levels(class_levels)
    effective_level = 0
    for class_name, level in normalized_levels.items():
        if class_name in _FULL_CASTER_CLASSES:
            effective_level += level
        elif class_name in _HALF_UP_CASTER_CLASSES:
            effective_level += (level + 1) // 2
        elif class_name in _HALF_CASTER_CLASSES:
            effective_level += level // 2
        elif class_name in _THIRD_CASTER_CLASSES:
            effective_level += level // 3
    return effective_level


def spell_slots_for_multiclass(class_levels: Mapping[str, int] | None) -> dict[int, int]:
    effective_level = spellcaster_level_for_multiclass(class_levels)
    if effective_level <= 0:
        return {}
    capped_level = min(effective_level, max(_MULTICLASS_SPELL_SLOT_TABLE))
    return dict(_MULTICLASS_SPELL_SLOT_TABLE.get(capped_level, {}))


def validate_class_level_representation(
    *,
    class_level_text: str,
    class_levels: Mapping[str, int] | None = None,
) -> ClassLevelValidation:
    text = str(class_level_text or "").strip()
    normalized_levels = normalize_class_levels(class_levels)
    parsed_from_text: dict[str, int] = {}

    if text and (re.search(r"\d", text) or "/" in text):
        parsed_from_text = parse_class_levels_strict(text)
    elif text:
        parsed_from_text = parse_class_levels(text)

    if normalized_levels and parsed_from_text and normalized_levels != parsed_from_text:
        raise ValueError(
            "invalid class_level: class_level text and class_levels mapping do not match"
        )

    resolved_levels = normalized_levels or parsed_from_text
    canonical_text = canonical_class_level_text(resolved_levels) or text
    return ClassLevelValidation(
        class_level_text=canonical_text,
        class_levels=resolved_levels,
        total_level=total_character_level(resolved_levels),
    )
