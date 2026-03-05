from __future__ import annotations

import json
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class SupportsRandInt(Protocol):
    def randint(self, a: int, b: int) -> int:
        ...


REPO_ROOT = Path(__file__).resolve().parents[2]
NONCOMBAT_CATALOG_PATH = REPO_ROOT / "db" / "rules" / "2014" / "noncombat_catalog.json"
ABILITY_ALIASES = {
    "str": "str",
    "strength": "str",
    "dex": "dex",
    "dexterity": "dex",
    "con": "con",
    "constitution": "con",
    "int": "int",
    "intelligence": "int",
    "wis": "wis",
    "wisdom": "wis",
    "cha": "cha",
    "charisma": "cha",
}


@dataclass(frozen=True, slots=True)
class AbilityCheckResult:
    natural_roll: int
    total: int
    modifier: int
    dc: int
    success: bool
    margin: int


@dataclass(frozen=True, slots=True)
class ContestCheckResult:
    attacker_roll: int
    attacker_total: int
    attacker_modifier: int
    defender_roll: int
    defender_total: int
    defender_modifier: int
    success: bool
    margin: int


@dataclass(frozen=True, slots=True)
class PassiveCheckResult:
    score: int
    dc: int
    success: bool
    margin: int


@dataclass(frozen=True, slots=True)
class NoncombatCatalog:
    skill_abilities: dict[str, str]
    tool_abilities: dict[str, str]


def _validate_int(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")


def _validate_dc(dc: int) -> None:
    _validate_int("dc", dc)
    if dc < 0:
        raise ValueError("dc must be >= 0")


def _normalize_key(value: str) -> str:
    key = str(value).strip().lower()
    key = key.replace("'", "")
    key = key.replace("’", "")
    key = key.replace("-", "_")
    key = key.replace(" ", "_")
    while "__" in key:
        key = key.replace("__", "_")
    return key


def _normalize_ability(value: str) -> str:
    key = _normalize_key(value)
    if key not in ABILITY_ALIASES:
        raise ValueError(f"Unknown ability key: {value}")
    return ABILITY_ALIASES[key]


def _normalize_name_set(values: set[str] | None) -> set[str]:
    if not values:
        return set()
    return {_normalize_key(value) for value in values}


def _build_ability_mapping(raw: object, *, label: str) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} mapping must be an object")
    mapping: dict[str, str] = {}
    for raw_name, raw_ability in raw.items():
        key = _normalize_key(str(raw_name))
        if not key:
            raise ValueError(f"{label} contains an empty name entry")
        mapping[key] = _normalize_ability(str(raw_ability))
    return mapping


@lru_cache(maxsize=1)
def _load_default_catalog() -> NoncombatCatalog:
    return load_noncombat_catalog()


def load_noncombat_catalog(path: Path | None = None) -> NoncombatCatalog:
    source_path = path or NONCOMBAT_CATALOG_PATH
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    skill_abilities = _build_ability_mapping(payload.get("skills", {}), label="skills")
    tool_abilities = _build_ability_mapping(payload.get("tools", {}), label="tools")
    if not skill_abilities:
        raise ValueError("skills mapping cannot be empty")
    if not tool_abilities:
        raise ValueError("tools mapping cannot be empty")
    return NoncombatCatalog(
        skill_abilities=skill_abilities,
        tool_abilities=tool_abilities,
    )


def _resolve_ability_modifier(
    *,
    ability: str,
    ability_modifiers: dict[str, int],
) -> int:
    normalized_mods = {_normalize_ability(key): value for key, value in ability_modifiers.items()}
    if ability not in normalized_mods:
        raise ValueError(f"Missing ability modifier for '{ability}'")
    modifier = normalized_mods[ability]
    _validate_int(f"{ability} modifier", modifier)
    return modifier


def _proficiency_delta(
    *,
    name: str,
    proficiency_bonus: int,
    proficiencies: set[str],
    expertise: set[str],
) -> int:
    if name not in proficiencies:
        return 0
    if name in expertise:
        return proficiency_bonus * 2
    return proficiency_bonus


def _specialist_delta(*, name: str, specialist_bonuses: dict[str, int] | None) -> int:
    if not specialist_bonuses:
        return 0
    normalized = {_normalize_key(key): value for key, value in specialist_bonuses.items()}
    if name not in normalized:
        return 0
    value = normalized[name]
    _validate_int(f"specialist bonus for {name}", value)
    return value


def roll_d20(
    rng: SupportsRandInt,
    *,
    advantage: bool = False,
    disadvantage: bool = False,
) -> int:
    if advantage and disadvantage:
        advantage = False
        disadvantage = False

    if advantage:
        return max(rng.randint(1, 20), rng.randint(1, 20))
    if disadvantage:
        return min(rng.randint(1, 20), rng.randint(1, 20))
    return rng.randint(1, 20)


def evaluate_dc(total: int, dc: int) -> bool:
    _validate_int("total", total)
    _validate_dc(dc)
    return total >= dc


def resolve_skill_modifier(
    *,
    skill: str,
    ability_modifiers: dict[str, int],
    proficiency_bonus: int,
    proficient_skills: set[str] | None = None,
    expertise_skills: set[str] | None = None,
    specialist_bonuses: dict[str, int] | None = None,
    catalog: NoncombatCatalog | None = None,
) -> int:
    _validate_int("proficiency bonus", proficiency_bonus)
    if proficiency_bonus < 0:
        raise ValueError("proficiency bonus must be >= 0")

    source = catalog or _load_default_catalog()
    normalized_skill = _normalize_key(skill)
    if normalized_skill not in source.skill_abilities:
        raise ValueError(f"Unknown skill: {skill}")

    ability = source.skill_abilities[normalized_skill]
    base_modifier = _resolve_ability_modifier(ability=ability, ability_modifiers=ability_modifiers)
    proficiency_delta = _proficiency_delta(
        name=normalized_skill,
        proficiency_bonus=proficiency_bonus,
        proficiencies=_normalize_name_set(proficient_skills),
        expertise=_normalize_name_set(expertise_skills),
    )
    specialist_delta = _specialist_delta(
        name=normalized_skill,
        specialist_bonuses=specialist_bonuses,
    )
    return base_modifier + proficiency_delta + specialist_delta


def resolve_tool_modifier(
    *,
    tool: str,
    ability_modifiers: dict[str, int],
    proficiency_bonus: int,
    proficient_tools: set[str] | None = None,
    expertise_tools: set[str] | None = None,
    specialist_bonuses: dict[str, int] | None = None,
    catalog: NoncombatCatalog | None = None,
) -> int:
    _validate_int("proficiency bonus", proficiency_bonus)
    if proficiency_bonus < 0:
        raise ValueError("proficiency bonus must be >= 0")

    source = catalog or _load_default_catalog()
    normalized_tool = _normalize_key(tool)
    if normalized_tool not in source.tool_abilities:
        raise ValueError(f"Unknown tool: {tool}")

    ability = source.tool_abilities[normalized_tool]
    base_modifier = _resolve_ability_modifier(ability=ability, ability_modifiers=ability_modifiers)
    proficiency_delta = _proficiency_delta(
        name=normalized_tool,
        proficiency_bonus=proficiency_bonus,
        proficiencies=_normalize_name_set(proficient_tools),
        expertise=_normalize_name_set(expertise_tools),
    )
    specialist_delta = _specialist_delta(
        name=normalized_tool,
        specialist_bonuses=specialist_bonuses,
    )
    return base_modifier + proficiency_delta + specialist_delta


def resolve_ability_check(
    rng: SupportsRandInt,
    *,
    modifier: int,
    dc: int,
    advantage: bool = False,
    disadvantage: bool = False,
) -> AbilityCheckResult:
    _validate_int("modifier", modifier)
    _validate_dc(dc)

    natural_roll = roll_d20(
        rng,
        advantage=advantage,
        disadvantage=disadvantage,
    )
    total = natural_roll + modifier
    success = evaluate_dc(total, dc)
    return AbilityCheckResult(
        natural_roll=natural_roll,
        total=total,
        modifier=modifier,
        dc=dc,
        success=success,
        margin=total - dc,
    )


def resolve_contest(
    rng: SupportsRandInt,
    *,
    attacker_modifier: int,
    defender_modifiers: list[int],
    attacker_advantage: bool = False,
    attacker_disadvantage: bool = False,
    defender_advantage: bool = False,
    defender_disadvantage: bool = False,
) -> ContestCheckResult:
    _validate_int("attacker modifier", attacker_modifier)
    for modifier in defender_modifiers:
        if not isinstance(modifier, int) or isinstance(modifier, bool):
            raise ValueError("defender modifiers must be integers")

    defender_modifier = max(defender_modifiers) if defender_modifiers else 0

    attacker_roll = roll_d20(
        rng,
        advantage=attacker_advantage,
        disadvantage=attacker_disadvantage,
    )
    defender_roll = roll_d20(
        rng,
        advantage=defender_advantage,
        disadvantage=defender_disadvantage,
    )
    attacker_total = attacker_roll + attacker_modifier
    defender_total = defender_roll + defender_modifier
    success = attacker_total > defender_total  # Ties go to defender per 2014 rules.

    return ContestCheckResult(
        attacker_roll=attacker_roll,
        attacker_total=attacker_total,
        attacker_modifier=attacker_modifier,
        defender_roll=defender_roll,
        defender_total=defender_total,
        defender_modifier=defender_modifier,
        success=success,
        margin=attacker_total - defender_total,
    )


def passive_score(*, modifier: int, base: int = 10) -> int:
    _validate_int("modifier", modifier)
    _validate_int("base", base)
    if base < 0:
        raise ValueError("base must be >= 0")
    return base + modifier


def resolve_passive_check(*, modifier: int, dc: int, base: int = 10) -> PassiveCheckResult:
    score = passive_score(modifier=modifier, base=base)
    _validate_dc(dc)
    success = evaluate_dc(score, dc)
    return PassiveCheckResult(
        score=score,
        dc=dc,
        success=success,
        margin=score - dc,
    )


def resolve_passive_skill_score(
    *,
    skill: str,
    ability_modifiers: dict[str, int],
    proficiency_bonus: int,
    proficient_skills: set[str] | None = None,
    expertise_skills: set[str] | None = None,
    specialist_bonuses: dict[str, int] | None = None,
    passive_bonus: int = 0,
    base: int = 10,
    catalog: NoncombatCatalog | None = None,
) -> int:
    _validate_int("passive bonus", passive_bonus)
    modifier = resolve_skill_modifier(
        skill=skill,
        ability_modifiers=ability_modifiers,
        proficiency_bonus=proficiency_bonus,
        proficient_skills=proficient_skills,
        expertise_skills=expertise_skills,
        specialist_bonuses=specialist_bonuses,
        catalog=catalog,
    )
    return passive_score(modifier=modifier + passive_bonus, base=base)


__all__ = [
    "AbilityCheckResult",
    "ContestCheckResult",
    "NoncombatCatalog",
    "PassiveCheckResult",
    "evaluate_dc",
    "load_noncombat_catalog",
    "passive_score",
    "resolve_ability_check",
    "resolve_contest",
    "resolve_passive_check",
    "resolve_passive_skill_score",
    "resolve_skill_modifier",
    "resolve_tool_modifier",
    "roll_d20",
]
