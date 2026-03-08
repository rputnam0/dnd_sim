from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CLASSES_DIR = REPO_ROOT / "db" / "rules" / "2014" / "classes"
DEFAULT_SUBCLASSES_DIR = REPO_ROOT / "db" / "rules" / "2014" / "subclasses"

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
_CLASS_ID_ALIASES = {"arcane trickster": "rogue", "eldritch knight": "fighter"}


def _slugify(value: Any) -> str:
    text = str(value).strip().lower()
    chars = [char if char.isalnum() else "_" for char in text]
    token = "".join(chars)
    while "__" in token:
        token = token.replace("__", "_")
    return token.strip("_")


def _required_text(value: Any, *, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty")
    return text


def _normalize_progression_key(value: Any) -> str:
    text = _slugify(value)
    return _CLASS_ID_ALIASES.get(text, text)


@dataclass(frozen=True, slots=True)
class FeatureGrant:
    name: str
    level: int
    subclass_unlock: bool = False


@dataclass(frozen=True, slots=True)
class SpellcastingProfile:
    progression: str
    pact_slots_by_level: dict[int, tuple[int, int]]


@dataclass(frozen=True, slots=True)
class ClassRecord:
    content_id: str
    class_id: str
    name: str
    source_book: str
    features: tuple[FeatureGrant, ...]
    spellcasting: SpellcastingProfile


@dataclass(frozen=True, slots=True)
class SubclassRecord:
    content_id: str
    subclass_id: str
    class_id: str
    name: str
    source_book: str
    features: tuple[FeatureGrant, ...]


@dataclass(frozen=True, slots=True)
class ClassCatalog:
    classes: dict[str, ClassRecord]
    subclasses: dict[tuple[str, str], SubclassRecord]


@dataclass(frozen=True, slots=True)
class CharacterProgression:
    total_level: int
    feature_names: tuple[str, ...]
    spell_slots: dict[int, int]
    pact_slots: dict[int, int]
    subclass_unlock_levels: dict[str, int]
    errors: tuple[str, ...]


def _feature_grant_from_payload(payload: dict[str, Any]) -> FeatureGrant:
    name = _required_text(payload.get("name"), field_name="feature.name")
    level = int(payload.get("level", 0))
    if level <= 0:
        raise ValueError("feature.level must be >= 1")
    return FeatureGrant(
        name=name,
        level=level,
        subclass_unlock=bool(payload.get("subclass_unlock", False)),
    )


def _spellcasting_profile_from_payload(payload: dict[str, Any]) -> SpellcastingProfile:
    progression = _slugify(payload.get("progression") or "none")
    if progression not in {"none", "full", "half", "half_up", "third", "pact"}:
        progression = "none"

    pact_slots_by_level: dict[int, tuple[int, int]] = {}
    raw_pact = payload.get("pact_slots_by_level")
    if isinstance(raw_pact, dict):
        for level_text, row in raw_pact.items():
            if not isinstance(row, dict):
                continue
            try:
                class_level = int(level_text)
                slot_level = int(row.get("slot_level", 0))
                slot_count = int(row.get("slots", 0))
            except (TypeError, ValueError):
                continue
            if class_level <= 0 or slot_level <= 0 or slot_count <= 0:
                continue
            pact_slots_by_level[class_level] = (slot_level, slot_count)
    return SpellcastingProfile(
        progression=progression,
        pact_slots_by_level=dict(sorted(pact_slots_by_level.items())),
    )


def _class_record_from_payload(payload: dict[str, Any]) -> ClassRecord:
    class_id = _normalize_progression_key(payload.get("class_id") or payload.get("name"))
    if not class_id:
        raise ValueError("class_id must be non-empty")
    source_book = _required_text(
        payload.get("source_book") or payload.get("source"), field_name="source_book"
    )
    name = _required_text(payload.get("name"), field_name="name")
    features_raw = payload.get("features", [])
    if not isinstance(features_raw, list):
        raise ValueError("features must be a list")
    features = tuple(
        sorted(
            (_feature_grant_from_payload(row) for row in features_raw if isinstance(row, dict)),
            key=lambda row: (row.level, row.name.casefold()),
        )
    )
    content_id = str(payload.get("content_id") or f"class:{class_id}|{source_book}").strip()
    spellcasting = _spellcasting_profile_from_payload(
        payload.get("spellcasting", {}) if isinstance(payload.get("spellcasting"), dict) else {}
    )
    return ClassRecord(
        content_id=content_id,
        class_id=class_id,
        name=name,
        source_book=source_book,
        features=features,
        spellcasting=spellcasting,
    )


def _subclass_record_from_payload(payload: dict[str, Any]) -> SubclassRecord:
    subclass_id = _slugify(
        payload.get("subclass_id") or payload.get("short_name") or payload.get("name")
    )
    class_id = _normalize_progression_key(payload.get("class_id") or payload.get("class_name"))
    if not subclass_id:
        raise ValueError("subclass_id must be non-empty")
    if not class_id:
        raise ValueError("class_id must be non-empty for subclass")
    source_book = _required_text(
        payload.get("source_book") or payload.get("source"), field_name="source_book"
    )
    name = _required_text(payload.get("name"), field_name="name")
    features_raw = payload.get("features", [])
    if not isinstance(features_raw, list):
        raise ValueError("features must be a list")
    features = tuple(
        sorted(
            (_feature_grant_from_payload(row) for row in features_raw if isinstance(row, dict)),
            key=lambda row: (row.level, row.name.casefold()),
        )
    )
    content_id = str(
        payload.get("content_id") or f"subclass:{subclass_id}_{class_id}|{source_book}"
    ).strip()
    return SubclassRecord(
        content_id=content_id,
        subclass_id=subclass_id,
        class_id=class_id,
        name=name,
        source_book=source_book,
        features=features,
    )


def load_class_catalog(
    *,
    classes_dir: Path = DEFAULT_CLASSES_DIR,
    subclasses_dir: Path = DEFAULT_SUBCLASSES_DIR,
) -> ClassCatalog:
    classes: dict[str, ClassRecord] = {}
    subclasses: dict[tuple[str, str], SubclassRecord] = {}

    for path in sorted(classes_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        record = _class_record_from_payload(payload)
        if record.class_id in classes:
            raise ValueError(f"duplicate class_id '{record.class_id}'")
        classes[record.class_id] = record

    for path in sorted(subclasses_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        record = _subclass_record_from_payload(payload)
        key = (record.class_id, record.subclass_id)
        if key in subclasses:
            raise ValueError(
                f"duplicate subclass '{record.subclass_id}' for class '{record.class_id}'"
            )
        subclasses[key] = record

    return ClassCatalog(
        classes=dict(sorted(classes.items())), subclasses=dict(sorted(subclasses.items()))
    )


@lru_cache(maxsize=1)
def load_default_class_catalog() -> ClassCatalog:
    return load_class_catalog(
        classes_dir=DEFAULT_CLASSES_DIR, subclasses_dir=DEFAULT_SUBCLASSES_DIR
    )


def _normalize_class_levels(class_levels: dict[str, int] | None) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for raw_name, raw_level in (class_levels or {}).items():
        key = _normalize_progression_key(raw_name)
        try:
            level = int(raw_level)
        except (TypeError, ValueError):
            continue
        if not key or level <= 0:
            continue
        normalized[key] = normalized.get(key, 0) + level
    return dict(sorted(normalized.items()))


def _normalize_subclass_choices(subclass_choices: dict[str, str] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for class_name, subclass_name in (subclass_choices or {}).items():
        class_id = _normalize_progression_key(class_name)
        subclass_id = _slugify(subclass_name)
        if class_id and subclass_id:
            normalized[class_id] = subclass_id
    return normalized


def _effective_spellcaster_level(class_levels: dict[str, int], catalog: ClassCatalog) -> int:
    total = 0
    for class_id, level in class_levels.items():
        record = catalog.classes.get(class_id)
        if record is None:
            continue
        progression = record.spellcasting.progression
        if progression == "full":
            total += level
        elif progression == "half":
            total += level // 2
        elif progression == "half_up":
            total += (level + 1) // 2
        elif progression == "third":
            total += level // 3
    return total


def _pact_slot_profile(class_id: str, level: int, catalog: ClassCatalog) -> tuple[int, int] | None:
    record = catalog.classes.get(class_id)
    if record is None:
        return None
    if record.spellcasting.progression != "pact":
        return None
    if record.spellcasting.pact_slots_by_level:
        best_level = max(
            (
                row_level
                for row_level in record.spellcasting.pact_slots_by_level
                if row_level <= level
            ),
            default=None,
        )
        if best_level is not None:
            return record.spellcasting.pact_slots_by_level[best_level]

    if level <= 0:
        return None
    if level == 1:
        return (1, 1)
    if level <= 2:
        return (1, 2)
    if level <= 4:
        return (2, 2)
    if level <= 6:
        return (3, 2)
    if level <= 8:
        return (4, 2)
    if level <= 10:
        return (5, 2)
    if level <= 16:
        return (5, 3)
    return (5, 4)


def build_character_progression(
    *,
    class_levels: dict[str, int] | None,
    subclass_choices: dict[str, str] | None = None,
    catalog: ClassCatalog | None = None,
) -> CharacterProgression:
    active_catalog = catalog or load_default_class_catalog()
    levels = _normalize_class_levels(class_levels)
    subclasses = _normalize_subclass_choices(subclass_choices)

    feature_names: set[str] = set()
    subclass_unlock_levels: dict[str, int] = {}
    pact_slots: dict[int, int] = {}
    errors: list[str] = []

    for class_id, level in levels.items():
        class_record = active_catalog.classes.get(class_id)
        if class_record is None:
            errors.append(f"unknown class reference '{class_id}'")
            continue
        for feature in class_record.features:
            if level >= feature.level:
                feature_names.add(_slugify(feature.name).replace("_", " "))
            if feature.subclass_unlock:
                current = subclass_unlock_levels.get(class_id)
                if current is None or feature.level < current:
                    subclass_unlock_levels[class_id] = feature.level

        pact_profile = _pact_slot_profile(class_id, level, active_catalog)
        if pact_profile is not None:
            slot_level, slot_count = pact_profile
            pact_slots[slot_level] = max(int(pact_slots.get(slot_level, 0)), int(slot_count))

    for class_id, subclass_id in subclasses.items():
        key = (class_id, subclass_id)
        subclass_record = active_catalog.subclasses.get(key)
        class_level = int(levels.get(class_id, 0))
        unlock_level = subclass_unlock_levels.get(class_id)
        if subclass_record is None:
            errors.append(f"invalid subclass reference '{subclass_id}' for class '{class_id}'")
            continue
        if unlock_level is not None and class_level < unlock_level:
            errors.append(
                f"subclass reference '{subclass_id}' for class '{class_id}' "
                f"requires class level {unlock_level}"
            )
            continue
        for feature in subclass_record.features:
            if class_level >= feature.level:
                feature_names.add(_slugify(feature.name).replace("_", " "))

    effective_level = _effective_spellcaster_level(levels, active_catalog)
    spell_slots = (
        dict(_MULTICLASS_SPELL_SLOT_TABLE[min(effective_level, 20)]) if effective_level > 0 else {}
    )

    return CharacterProgression(
        total_level=sum(levels.values()),
        feature_names=tuple(sorted(feature_names)),
        spell_slots=spell_slots,
        pact_slots=dict(sorted(pact_slots.items())),
        subclass_unlock_levels=dict(sorted(subclass_unlock_levels.items())),
        errors=tuple(sorted(set(errors))),
    )
