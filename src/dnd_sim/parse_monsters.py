from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from dnd_sim.monster_backfill import (
    backfill_monster_payload,
    extract_innate_spellcasting_entries,
    extract_legendary_resistance_uses,
    slugify_name,
)
from dnd_sim.telemetry import emit_event

logger = logging.getLogger(__name__)

_MONSTER_BLOCK_RE = re.compile(
    r"^(?P<name>.*?)\n"
    r"(?P<meta>.*?)\n"
    r"Armor Class (?P<ac>\d+)(?P<ac_text>.*?)\n"
    r"Hit Points (?P<hp>\d+) \((?P<hp_formula>.*?)\)\n"
    r"Speed (?P<speed>.*?)\n"
    r"STR DEX CON INT WIS CHA\n"
    r"(?P<str>\d+) \([^)]+\) (?P<dex>\d+) \([^)]+\) (?P<con>\d+) \([^)]+\) "
    r"(?P<int>\d+) \([^)]+\) (?P<wis>\d+) \([^)]+\) (?P<cha>\d+) \([^)]+\)",
    re.MULTILINE,
)
_SECTION_RE = re.compile(r"^(Actions|Reactions|Legendary Actions|Lair Actions)\s*$", re.MULTILINE)
_ENTRY_RE = re.compile(r"^(?P<name>[A-Z][A-Za-z0-9'’(),\-/ ]{0,100})\.\s*(?P<description>.*)$")
_TO_HIT_RE = re.compile(r"([+-]\d+)\s+to hit", re.IGNORECASE)
_SAVE_RE = re.compile(
    r"DC\s*(\d+)\s*(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)\s+saving throw",
    re.IGNORECASE,
)
_DAMAGE_RE = re.compile(r"\((\d+d\d+(?:\s*[+-]\s*\d+)?)\)\s+([A-Za-z]+)\s+damage", re.IGNORECASE)
_RANGE_REACH_RE = re.compile(r"reach\s*(\d+)\s*(?:ft\.?|feet)", re.IGNORECASE)
_RANGE_WITHIN_RE = re.compile(r"within\s*(\d+)\s*(?:ft\.?|feet)", re.IGNORECASE)
_RECHARGE_RE = re.compile(r"\((Recharge\s+[^)]+)\)", re.IGNORECASE)
_USES_RE = re.compile(r"\((\d+)\s*/\s*Day\)", re.IGNORECASE)
_LEGENDARY_COST_RE = re.compile(r"\((?:Costs?|Cost)\s+(\d+)\s+Actions?\)", re.IGNORECASE)
_LEGENDARY_POOL_RE = re.compile(r"can take\s+(\d+)\s+legendary actions", re.IGNORECASE)

_ABILITY_MAP = {
    "strength": "str",
    "dexterity": "dex",
    "constitution": "con",
    "intelligence": "int",
    "wisdom": "wis",
    "charisma": "cha",
}

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
}


def _clean_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("---PAGE"):
            continue
        if line.startswith("System Reference Document"):
            continue
        lines.append(line)
    return lines


def _is_entry_start(line: str) -> bool:
    if line.startswith(("The ", "On ", "Only ", "If ", "At ", "When ", "Each ", "A ", "An ")):
        return False
    return _ENTRY_RE.match(line) is not None


def _parse_named_entries(text: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    current_name: str | None = None
    current_parts: list[str] = []

    for line in _clean_lines(text):
        if _is_entry_start(line):
            if current_name is not None:
                entries.append((current_name, " ".join(current_parts).strip()))
            match = _ENTRY_RE.match(line)
            if match is None:
                continue
            current_name = match.group("name").strip()
            current_parts = [match.group("description").strip()]
            continue

        if current_name is not None:
            current_parts.append(line)

    if current_name is not None:
        entries.append((current_name, " ".join(current_parts).strip()))
    return entries


def _extract_sections(block_text: str) -> tuple[dict[str, str], int | None]:
    matches = list(_SECTION_RE.finditer(block_text))
    if not matches:
        return {}, None

    sections: dict[str, str] = {}
    for idx, match in enumerate(matches):
        heading = match.group(1)
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(block_text)
        sections[heading] = block_text[start:end]

    return sections, matches[0].start()


def _parse_multiattack_count(description: str) -> int:
    match = re.search(r"makes\s+(\w+)\s+.*attacks?", description, flags=re.IGNORECASE)
    if not match:
        return 1

    value = match.group(1).lower()
    if value.isdigit():
        return int(value)
    return _NUMBER_WORDS.get(value, 1)


def _ability_short_name(full_name: str) -> str:
    return _ABILITY_MAP.get(full_name.strip().lower(), full_name.strip().lower()[:3])


def _extract_effects(description: str, *, action_type: str) -> list[dict[str, Any]]:
    desc_lower = description.lower()
    effects: list[dict[str, Any]] = []

    if "knocked prone" in desc_lower:
        effects.append(
            {
                "effect_type": "apply_condition",
                "apply_on": "save_fail" if action_type == "save" else "hit",
                "target": "target",
                "condition": "prone",
                "duration_rounds": 1,
            }
        )

    if "become frightened" in desc_lower or "becomes frightened" in desc_lower:
        effects.append(
            {
                "effect_type": "apply_condition",
                "apply_on": "save_fail" if action_type == "save" else "hit",
                "target": "target",
                "condition": "frightened",
            }
        )

    if "heavily obscured" in desc_lower:
        effects.append(
            {
                "effect_type": "note",
                "apply_on": "always",
                "target": "source",
                "text": "Heavily obscured zone not yet executable.",
            }
        )

    return effects


def _normalize_action_name(raw_name: str) -> tuple[str, dict[str, Any]]:
    work_name = raw_name.strip()
    tags: list[str] = []

    action: dict[str, Any] = {
        "name": slugify_name(work_name),
        "tags": tags,
    }

    recharge_match = _RECHARGE_RE.search(work_name)
    if recharge_match:
        action["recharge"] = recharge_match.group(1).replace("–", "-")
        work_name = _RECHARGE_RE.sub("", work_name).strip()

    uses_match = _USES_RE.search(work_name)
    if uses_match:
        action["max_uses"] = int(uses_match.group(1))
        work_name = _USES_RE.sub("", work_name).strip()

    legendary_cost_match = _LEGENDARY_COST_RE.search(work_name)
    if legendary_cost_match:
        cost = int(legendary_cost_match.group(1))
        tags.append(f"legendary_cost:{cost}")
        work_name = _LEGENDARY_COST_RE.sub("", work_name).strip()

    action["name"] = slugify_name(work_name)
    return work_name, action


def _parse_action_entry(name: str, description: str, *, section: str) -> dict[str, Any]:
    clean_name, action = _normalize_action_name(name)

    action_cost = {
        "Actions": "action",
        "Reactions": "reaction",
        "Legendary Actions": "legendary",
        "Lair Actions": "lair",
    }.get(section, "action")

    desc_lower = description.lower()
    if "weapon attack" in desc_lower or "spell attack" in desc_lower or "to hit" in desc_lower:
        action_type = "attack"
    elif (
        "saving throw" in desc_lower
        or "must make a dc" in desc_lower
        or "must succeed on a dc" in desc_lower
    ):
        action_type = "save"
    else:
        action_type = "utility"

    target_mode = "single_enemy"
    if "each creature" in desc_lower or "creatures of" in desc_lower:
        target_mode = "all_enemies"
    elif "itself" in desc_lower or "on itself" in desc_lower:
        target_mode = "self"

    to_hit_match = _TO_HIT_RE.search(description.replace("−", "-"))
    if to_hit_match:
        action["to_hit"] = int(to_hit_match.group(1))

    damage_match = _DAMAGE_RE.search(description)
    if damage_match:
        action["damage"] = re.sub(r"\s+", "", damage_match.group(1).replace("−", "-"))
        action["damage_type"] = damage_match.group(2).lower()

    save_match = _SAVE_RE.search(description)
    if save_match:
        action["save_dc"] = int(save_match.group(1))
        action["save_ability"] = _ability_short_name(save_match.group(2))
        if "half as much damage" in desc_lower:
            action["half_on_save"] = True

    range_match = _RANGE_REACH_RE.search(description)
    if range_match:
        action["range_ft"] = int(range_match.group(1))
    else:
        within_match = _RANGE_WITHIN_RE.search(description)
        if within_match:
            action["range_ft"] = int(within_match.group(1))

    action["action_cost"] = action_cost
    action["action_type"] = action_type
    action["target_mode"] = target_mode

    if clean_name.lower() == "multiattack":
        action["attack_count"] = _parse_multiattack_count(description)

    effects = _extract_effects(description, action_type=action_type)
    if effects:
        action["effects"] = effects

    return action


def parse_monsters(raw_text: str) -> list[dict[str, Any]]:
    start_idx = raw_text.find("Monsters (A)")
    if start_idx == -1:
        start_idx = raw_text.find("Monsters (")

    end_match = re.search(r"Appendix PH-A:\s*", raw_text)
    if start_idx == -1 or end_match is None:
        return []

    text = raw_text[start_idx : end_match.start()]
    monsters: list[dict[str, Any]] = []

    matches = list(_MONSTER_BLOCK_RE.finditer(text))
    for idx, match in enumerate(matches):
        name = match.group("name").strip()
        if (
            name in {"Actions", "Legendary Actions", "Reactions", "Lair Actions"}
            or "---PAGE" in name
        ):
            continue

        meta = match.group("meta").strip()
        ac = int(match.group("ac"))
        hp = int(match.group("hp"))
        hp_formula = match.group("hp_formula").strip()

        ability_scores = {
            "str": int(match.group("str")),
            "dex": int(match.group("dex")),
            "con": int(match.group("con")),
            "int": int(match.group("int")),
            "wis": int(match.group("wis")),
            "cha": int(match.group("cha")),
        }

        block_start = match.end()
        block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block_text = text[block_start:block_end]

        cr_match = re.search(r"Challenge\s+([\d/]+)", block_text)
        saving_match = re.search(r"Saving Throws\s+([^\n]+)", block_text)
        speed_match = re.search(r"Speed\s+([^\n]+)", match.group(0))
        speed_text = speed_match.group(1).strip() if speed_match else ""

        sections, first_section_idx = _extract_sections(block_text)

        traits_text = ""
        if cr_match:
            traits_start = cr_match.end()
            traits_end = first_section_idx if first_section_idx is not None else len(block_text)
            traits_text = block_text[traits_start:traits_end]

        parsed_trait_entries = _parse_named_entries(traits_text)
        traits = [entry_name for entry_name, _entry_desc in parsed_trait_entries]
        trait_entries = [
            {"name": entry_name, "description": entry_desc}
            for entry_name, entry_desc in parsed_trait_entries
        ]
        innate_spellcasting = extract_innate_spellcasting_entries(trait_entries=trait_entries)
        legendary_resistance_uses = extract_legendary_resistance_uses(trait_entries=trait_entries)

        parsed_actions = [
            _parse_action_entry(entry_name, entry_desc, section="Actions")
            for entry_name, entry_desc in _parse_named_entries(sections.get("Actions", ""))
        ]
        parsed_reactions = [
            _parse_action_entry(entry_name, entry_desc, section="Reactions")
            for entry_name, entry_desc in _parse_named_entries(sections.get("Reactions", ""))
        ]
        parsed_legendary = [
            _parse_action_entry(entry_name, entry_desc, section="Legendary Actions")
            for entry_name, entry_desc in _parse_named_entries(
                sections.get("Legendary Actions", "")
            )
        ]
        parsed_lair = [
            _parse_action_entry(entry_name, entry_desc, section="Lair Actions")
            for entry_name, entry_desc in _parse_named_entries(sections.get("Lair Actions", ""))
        ]

        legendary_pool = 0
        legendary_text = sections.get("Legendary Actions", "")
        legendary_pool_match = _LEGENDARY_POOL_RE.search(legendary_text)
        if legendary_pool_match:
            legendary_pool = int(legendary_pool_match.group(1))
        elif parsed_legendary:
            legendary_pool = 3

        resources: dict[str, int] = (
            {"legendary_actions": legendary_pool} if legendary_pool > 0 else {}
        )
        if legendary_resistance_uses is not None and legendary_resistance_uses > 0:
            resources["legendary_resistance"] = legendary_resistance_uses

        payload: dict[str, Any] = {
            "name": name,
            "meta": meta,
            "ac": ac,
            "hp": hp,
            "hp_formula": hp_formula,
            "speed": speed_text,
            "ability_scores": ability_scores,
            "cr": cr_match.group(1) if cr_match else "0",
            "saving_throws_text": saving_match.group(1).strip() if saving_match else "",
            "traits": traits,
            "trait_entries": trait_entries,
            "actions": parsed_actions,
            "bonus_actions": [],
            "reactions": parsed_reactions,
            "legendary_actions": parsed_legendary,
            "lair_actions": parsed_lair,
            "innate_spellcasting": innate_spellcasting,
            "resources": resources,
        }

        modern_payload = backfill_monster_payload(payload)
        merged = dict(payload)
        merged.update(modern_payload)
        monsters.append(merged)

    return monsters


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    root = Path(__file__).resolve().parents[2]
    raw_path = root / "db" / "rules" / "2014" / "srd_raw.txt"
    out_dir = root / "db" / "rules" / "2014" / "monsters"

    if not raw_path.exists():
        emit_event(
            logger,
            event_type="monsters_parse_input_missing",
            source=__name__,
            payload={"input_path": str(raw_path)},
            level=logging.ERROR,
        )
        return

    raw_text = raw_path.read_text(encoding="utf-8")
    monsters = parse_monsters(raw_text)

    emit_event(
        logger,
        event_type="monsters_parsed",
        source=__name__,
        payload={"count": len(monsters), "input_path": str(raw_path)},
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    for monster in monsters:
        safe_name = slugify_name(monster["name"])[:50]
        if not safe_name:
            continue
        (out_dir / f"{safe_name}.json").write_text(json.dumps(monster, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
