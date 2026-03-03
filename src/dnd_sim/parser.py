from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from dnd_sim.characters import validate_class_level_representation
from dnd_sim.models import AttackProfile, CharacterRecord, RawField

_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$")

_SKILL_FIELDS = {
    "acrobatics",
    "animal",
    "arcana",
    "athletics",
    "deception",
    "history",
    "insight",
    "intimidation",
    "investigation",
    "medicine",
    "nature",
    "perception",
    "performance",
    "persuasion",
    "religion",
    "sleightofhand",
    "stealth",
    "survival",
}

_ABILITY_FIELDS = {
    "STR": "str",
    "DEX": "dex",
    "CON": "con",
    "INT": "int",
    "WIS": "wis",
    "CHA": "cha",
}

_SAVE_FIELDS = {
    "ST Strength": "str",
    "ST Dexterity": "dex",
    "ST Constitution": "con",
    "ST Intelligence": "int",
    "ST Wisdom": "wis",
    "ST Charisma": "cha",
}


def slugify(value: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return base or "unnamed_character"


def _extract_int(value: str, default: int = 0) -> int:
    found = re.search(r"-?\d+", value)
    return int(found.group(0)) if found else default


def _extract_mod(value: str, default: int = 0) -> int:
    found = re.search(r"[+-]?\d+", value)
    return int(found.group(0)) if found else default


def _normalize_field(field: str) -> str:
    return re.sub(r"\s+", "", field).lower()


def _parse_damage_value(value: str) -> tuple[str, str]:
    if not value or value == "--":
        return "1", "bludgeoning"
    first = value.split()[0]
    damage_type = "bludgeoning"
    parts = value.split()
    if len(parts) > 1:
        damage_type = parts[-1].lower()
    return first, damage_type


def _extract_traits(raw_fields: list[RawField]) -> list[str]:
    traits: set[str] = set()
    for raw in raw_fields:
        if not raw.field.startswith("FeaturesTraits"):
            continue
        text = raw.value.replace("<br>", "\n")
        for match in re.finditer(r"\*\s*([^•\n]+?)\s*•", text):
            trait = match.group(1).strip()
            if trait:
                traits.add(trait)
    return sorted(traits)


def _extract_spell_slots(raw_fields: list[RawField]) -> dict[str, int]:
    slots: dict[str, int] = {}
    for raw in raw_fields:
        if not raw.field.startswith("spellSlotHeader"):
            continue
        idx = raw.field.replace("spellSlotHeader", "")
        if idx == "0":
            continue
        found = re.search(r"(\d+)\s+Slots", raw.value)
        if found:
            slots[idx] = int(found.group(1))
    return slots


def _extract_resources(raw_fields: list[RawField]) -> dict[str, Any]:
    resources: dict[str, Any] = {}
    merged = "\n".join(field.value for field in raw_fields)

    ki_match = re.search(r"Ki Points:\s*(\d+)", merged, flags=re.IGNORECASE)
    if ki_match:
        resources["ki"] = {"max": int(ki_match.group(1))}

    wild_shape_match = re.search(
        r"Wild Shape\s*•\s*(\d+)\s*/\s*Long Rest", merged, flags=re.IGNORECASE
    )
    if wild_shape_match:
        resources["wild_shape"] = {"max": int(wild_shape_match.group(1))}

    spell_slots = _extract_spell_slots(raw_fields)
    if spell_slots:
        resources["spell_slots"] = spell_slots

    generic_rest_uses: dict[str, int] = {}
    for match in re.finditer(r"\|\s*([^:\n]+):\s*(\d+)\s*/\s*(Short|Long) Rest", merged):
        key = slugify(match.group(1))
        generic_rest_uses[key] = int(match.group(2))
    if generic_rest_uses:
        resources["feature_uses"] = generic_rest_uses

    return resources


def _extract_attacks(raw_fields: list[RawField]) -> list[AttackProfile]:
    names: dict[str, str] = {}
    to_hit: dict[str, int] = {}
    damages: dict[str, tuple[str, str]] = {}

    for raw in raw_fields:
        name_match = re.fullmatch(r"Wpn Name(?:\s+(\d+))?", raw.field)
        if name_match:
            idx = name_match.group(1) or "1"
            names[idx] = raw.value
            continue

        atk_match = re.fullmatch(r"Wpn(\d+) AtkBonus", raw.field)
        if atk_match:
            idx = atk_match.group(1)
            to_hit[idx] = _extract_mod(raw.value)
            continue

        dmg_match = re.fullmatch(r"Wpn(\d+) Damage", raw.field)
        if dmg_match:
            idx = dmg_match.group(1)
            damages[idx] = _parse_damage_value(raw.value)

    attacks: list[AttackProfile] = []
    for idx in sorted(names, key=lambda value: int(value)):
        damage, damage_type = damages.get(idx, ("1", "bludgeoning"))
        attacks.append(
            AttackProfile(
                name=names[idx],
                to_hit=to_hit.get(idx, 0),
                damage=damage,
                damage_type=damage_type,
            )
        )
    return attacks


def _parse_section_rows(section_text: str) -> list[RawField]:
    raw_fields: list[RawField] = []
    seen: set[tuple[int, str, str]] = set()
    for line in section_text.splitlines():
        match = _ROW_RE.match(line.strip())
        if not match:
            continue
        page = int(match.group(1))
        field = match.group(2).strip()
        value = match.group(3).strip().replace("<br>", "\n")
        entry = (page, field, value)
        if entry in seen:
            continue
        seen.add(entry)
        raw_fields.append(RawField(page=page, field=field, value=value))
    return raw_fields


def _build_character_record(pdf_name: str, raw_fields: list[RawField]) -> CharacterRecord:
    by_field: dict[str, str] = {}
    for raw in raw_fields:
        if raw.field not in by_field:
            by_field[raw.field] = raw.value

    name = by_field.get("CharacterName") or by_field.get("CharacterName2") or pdf_name
    class_level = by_field.get("CLASS  LEVEL") or by_field.get("CLASS  LEVEL2") or "Unknown"
    class_progression = validate_class_level_representation(class_level_text=class_level)

    ability_scores = {
        key: _extract_int(by_field.get(field, "0")) for field, key in _ABILITY_FIELDS.items()
    }

    save_mods = {key: _extract_mod(by_field.get(field, "0")) for field, key in _SAVE_FIELDS.items()}

    skill_mods: dict[str, int] = {}
    for field, value in by_field.items():
        normalized = _normalize_field(field)
        if normalized in _SKILL_FIELDS:
            skill_mods[normalized] = _extract_mod(value)

    speed_ft = _extract_int(by_field.get("Speed", "30"), default=30)

    attacks = _extract_attacks(raw_fields)
    resources = _extract_resources(raw_fields)
    traits = _extract_traits(raw_fields)

    return CharacterRecord(
        character_id=slugify(name),
        name=name,
        class_level=class_progression.class_level_text,
        max_hp=_extract_int(by_field.get("MaxHP", "1"), default=1),
        ac=_extract_int(by_field.get("AC", "10"), default=10),
        speed_ft=speed_ft,
        ability_scores=ability_scores,
        save_mods=save_mods,
        skill_mods=skill_mods,
        attacks=attacks,
        resources=resources,
        traits=traits,
        raw_fields=raw_fields,
        source={"pdf_name": pdf_name},
        class_levels=class_progression.class_levels,
    )


def parse_characters_from_markdown(markdown_text: str) -> list[CharacterRecord]:
    matches = list(_SECTION_RE.finditer(markdown_text))
    records: list[CharacterRecord] = []

    for idx, match in enumerate(matches):
        section_name = match.group(1).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown_text)
        section_text = markdown_text[start:end]
        raw_fields = _parse_section_rows(section_text)
        if raw_fields:
            records.append(_build_character_record(section_name, raw_fields))

    return sorted(records, key=lambda rec: rec.character_id)


def parse_characters_from_markdown_file(markdown_path: Path) -> list[CharacterRecord]:
    return parse_characters_from_markdown(markdown_path.read_text(encoding="utf-8"))


def write_character_db(records: list[CharacterRecord], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    index = {
        "characters": [
            {
                "character_id": record.character_id,
                "name": record.name,
                "class_level": record.class_level,
                "class_levels": record.class_levels,
                "source_pdf": record.source["pdf_name"],
            }
            for record in sorted(records, key=lambda item: item.character_id)
        ]
    }

    for record in records:
        path = out_dir / f"{record.character_id}.json"
        path.write_text(json.dumps(record.to_dict(), indent=2, sort_keys=True), encoding="utf-8")

    (out_dir / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True), encoding="utf-8"
    )


def parse_markdown_to_character_db(markdown_path: Path, out_dir: Path) -> list[CharacterRecord]:
    records = parse_characters_from_markdown_file(markdown_path)
    write_character_db(records, out_dir)
    return records
