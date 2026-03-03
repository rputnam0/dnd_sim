from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

_ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_SAVE_BONUS_RE = re.compile(r"([A-Za-z]{3,})\s*([+-]\d+)")
_LEGENDARY_RESISTANCE_RE = re.compile(
    r"legendary resistance(?:\s*\((\d+)\s*/\s*day\))?",
    flags=re.IGNORECASE,
)
_INNATE_TRAIT_RE = re.compile(r"^innate spellcasting\b", flags=re.IGNORECASE)
_INNATE_SPELL_BLOCK_RE = re.compile(
    r"(at will|\d+\s*/\s*day(?:\s*each)?)\s*:\s*(.+?)(?=(?:at will|\d+\s*/\s*day(?:\s*each)?)\s*:|$)",
    flags=re.IGNORECASE,
)
_INNATE_SAVE_DC_RE = re.compile(r"spell save dc\s*(\d+)", flags=re.IGNORECASE)
_INNATE_TO_HIT_RE = re.compile(r"([+-]?\d+)\s*to hit with spell attacks?", flags=re.IGNORECASE)


def slugify_name(value: str) -> str:
    normalized = _NON_ALNUM_RE.sub("_", str(value).strip().lower())
    return normalized.strip("_") or "monster"


def _ability_mod(score: int) -> int:
    return (int(score) - 10) // 2


def _parse_save_mods(text: str) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for ability, bonus in _SAVE_BONUS_RE.findall(str(text).replace("−", "-")):
        key = ability.strip().lower()[:3]
        if key in _ABILITY_KEYS:
            parsed[key] = int(bonus)
    return parsed


def _normalize_actions(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    raw = payload.get(key, [])
    if not isinstance(raw, list):
        return []

    actions: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        action = deepcopy(row)
        action.setdefault("action_type", "utility")
        action.setdefault("target_mode", "single_enemy")
        action.setdefault("tags", [])
        action.setdefault("effects", [])
        action.setdefault("mechanics", [])
        action.setdefault("action_cost", "action")
        actions.append(action)
    return actions


def _coerce_trait_entries(
    trait_entries: Any = None,
    traits: Any = None,
) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []

    if isinstance(trait_entries, list):
        for row in trait_entries:
            if isinstance(row, dict):
                name = str(row.get("name", "")).strip()
                description = str(row.get("description", "")).strip()
                if name:
                    entries.append((name, description))
                continue
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                name = str(row[0]).strip()
                description = str(row[1]).strip()
                if name:
                    entries.append((name, description))
                continue
            if isinstance(row, str) and row.strip():
                entries.append((row.strip(), ""))

    if entries:
        return entries

    if isinstance(traits, list):
        for row in traits:
            name = str(row).strip()
            if name:
                entries.append((name, ""))
    return entries


def extract_legendary_resistance_uses(
    *,
    trait_entries: Any = None,
    traits: Any = None,
) -> int | None:
    entries = _coerce_trait_entries(trait_entries=trait_entries, traits=traits)
    best: int | None = None
    for name, description in entries:
        match = _LEGENDARY_RESISTANCE_RE.search(f"{name} {description}".strip())
        if match is None:
            continue
        raw_uses = match.group(1)
        uses = int(raw_uses) if raw_uses is not None else 3
        best = uses if best is None else max(best, uses)
    return best


def _normalize_spell_name(raw: str) -> str:
    name = str(raw).strip()
    if not name:
        return ""
    name = name.replace("*", "").replace("’", "'")
    name = re.sub(r"\([^)]*\)", "", name)
    name = re.sub(r"\s+", " ", name).strip(" .;:,")
    if not name:
        return ""
    return name.title()


def extract_innate_spellcasting_entries(
    *,
    trait_entries: Any = None,
    traits: Any = None,
) -> list[dict[str, Any]]:
    entries = _coerce_trait_entries(trait_entries=trait_entries, traits=traits)
    innate_entries: list[dict[str, Any]] = []
    seen: set[tuple[str, int | None]] = set()

    for name, description in entries:
        if _INNATE_TRAIT_RE.search(name) is None:
            continue
        desc = str(description or "")
        save_dc_match = _INNATE_SAVE_DC_RE.search(desc)
        to_hit_match = _INNATE_TO_HIT_RE.search(desc.replace("−", "-"))
        save_dc = int(save_dc_match.group(1)) if save_dc_match else None
        to_hit = int(to_hit_match.group(1)) if to_hit_match else None

        for block in _INNATE_SPELL_BLOCK_RE.finditer(desc):
            frequency = block.group(1).strip().lower()
            spell_blob = block.group(2).strip()
            max_uses: int | None = None
            if frequency != "at will":
                uses_match = re.match(r"(\d+)\s*/\s*day", frequency)
                if uses_match:
                    max_uses = int(uses_match.group(1))

            normalized_blob = spell_blob.replace(" and ", ", ")
            for token in normalized_blob.split(","):
                spell_name = _normalize_spell_name(token)
                if not spell_name:
                    continue
                key = (spell_name.lower(), max_uses)
                if key in seen:
                    continue
                seen.add(key)
                payload: dict[str, Any] = {"spell": spell_name}
                if max_uses is not None:
                    payload["max_uses"] = max_uses
                if save_dc is not None:
                    payload["save_dc"] = save_dc
                if to_hit is not None:
                    payload["to_hit"] = to_hit
                innate_entries.append(payload)

    return innate_entries


def _modern_defaults(payload: dict[str, Any]) -> dict[str, Any]:
    updated = deepcopy(payload)
    updated.setdefault("identity", {})
    updated.setdefault("stat_block", {})

    identity = updated["identity"]
    if not isinstance(identity, dict):
        identity = {}
        updated["identity"] = identity
    identity.setdefault("enemy_id", slugify_name(str(identity.get("name", "monster"))))
    identity.setdefault("name", str(identity.get("enemy_id", "monster")).replace("_", " ").title())
    identity.setdefault("team", "enemy")

    stat_block = updated["stat_block"]
    if not isinstance(stat_block, dict):
        stat_block = {}
        updated["stat_block"] = stat_block
    stat_block.setdefault("max_hp", int(stat_block.get("max_hp", 1) or 1))
    stat_block.setdefault("ac", int(stat_block.get("ac", 10) or 10))
    stat_block.setdefault("speed_ft", 30)
    stat_block.setdefault("initiative_mod", int(stat_block.get("dex_mod", 0) or 0))
    stat_block.setdefault("save_mods", {})

    for key in (
        "actions",
        "bonus_actions",
        "reactions",
        "legendary_actions",
        "lair_actions",
    ):
        updated[key] = _normalize_actions(updated, key)

    # Enforce action cost for special sections.
    for action in updated["reactions"]:
        action["action_cost"] = "reaction"
    for action in updated["legendary_actions"]:
        action["action_cost"] = "legendary"
    for action in updated["lair_actions"]:
        action["action_cost"] = "lair"

    updated.setdefault("resources", {})
    resources = updated["resources"]
    if not isinstance(resources, dict):
        resources = {}
        updated["resources"] = resources
    legendary_resistance_uses = extract_legendary_resistance_uses(
        trait_entries=updated.get("trait_entries"),
        traits=updated.get("traits"),
    )
    if (
        legendary_resistance_uses is not None
        and "legendary_resistance" not in resources
        and legendary_resistance_uses > 0
    ):
        resources["legendary_resistance"] = legendary_resistance_uses

    updated.setdefault("innate_spellcasting", [])
    innate = updated["innate_spellcasting"]
    if not isinstance(innate, list):
        innate = []
    if not innate:
        innate = extract_innate_spellcasting_entries(
            trait_entries=updated.get("trait_entries"),
            traits=updated.get("traits"),
        )
    updated["innate_spellcasting"] = innate

    updated.setdefault("trait_entries", [])
    updated.setdefault("damage_resistances", [])
    updated.setdefault("damage_immunities", [])
    updated.setdefault("damage_vulnerabilities", [])
    updated.setdefault("condition_immunities", [])
    updated.setdefault("script_hooks", {})
    updated.setdefault("traits", [])

    return updated


def is_modern_monster_payload(payload: dict[str, Any]) -> bool:
    return isinstance(payload.get("identity"), dict) and isinstance(payload.get("stat_block"), dict)


def backfill_monster_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Backfill legacy monster payloads into EnemyConfig-compatible schema."""

    if is_modern_monster_payload(payload):
        return _modern_defaults(payload)

    name = str(payload.get("name", "Monster")).strip() or "Monster"
    ability_scores = payload.get("ability_scores", {})
    if not isinstance(ability_scores, dict):
        ability_scores = {}

    scores = {key: int(ability_scores.get(key, 10) or 10) for key in _ABILITY_KEYS}
    save_mods = _parse_save_mods(str(payload.get("saving_throws_text", "")))

    speed_text = str(payload.get("speed", ""))
    speed_match = re.search(r"(\d+)\s*(?:ft\.?|feet)", speed_text)
    speed_ft = int(speed_match.group(1)) if speed_match else 30

    legacy_actions = _normalize_actions(payload, "actions")
    legacy_bonus_actions = _normalize_actions(payload, "bonus_actions")
    legacy_reactions = _normalize_actions(payload, "reactions")
    legacy_legendary_actions = _normalize_actions(payload, "legendary_actions")
    legacy_lair_actions = _normalize_actions(payload, "lair_actions")

    for action in legacy_reactions:
        action["action_cost"] = "reaction"
    for action in legacy_legendary_actions:
        action["action_cost"] = "legendary"
    for action in legacy_lair_actions:
        action["action_cost"] = "lair"

    resources = payload.get("resources", {})
    if not isinstance(resources, dict):
        resources = {}
    legendary_resistance_uses = extract_legendary_resistance_uses(
        trait_entries=payload.get("trait_entries"),
        traits=payload.get("traits"),
    )
    if (
        legendary_resistance_uses is not None
        and "legendary_resistance" not in resources
        and legendary_resistance_uses > 0
    ):
        resources["legendary_resistance"] = legendary_resistance_uses
    if legacy_legendary_actions and "legendary_actions" not in resources:
        resources["legendary_actions"] = 3

    innate_spellcasting = payload.get("innate_spellcasting")
    if not isinstance(innate_spellcasting, list):
        innate_spellcasting = []
    if not innate_spellcasting:
        innate_spellcasting = extract_innate_spellcasting_entries(
            trait_entries=payload.get("trait_entries"),
            traits=payload.get("traits"),
        )

    modern = {
        "identity": {
            "enemy_id": slugify_name(name),
            "name": name,
            "team": "enemy",
        },
        "stat_block": {
            "max_hp": int(payload.get("hp", payload.get("max_hp", 1)) or 1),
            "ac": int(payload.get("ac", 10) or 10),
            "speed_ft": speed_ft,
            "initiative_mod": _ability_mod(scores["dex"]),
            "str_mod": _ability_mod(scores["str"]),
            "dex_mod": _ability_mod(scores["dex"]),
            "con_mod": _ability_mod(scores["con"]),
            "int_mod": _ability_mod(scores["int"]),
            "wis_mod": _ability_mod(scores["wis"]),
            "cha_mod": _ability_mod(scores["cha"]),
            "save_mods": save_mods,
            "cr": payload.get("cr"),
        },
        "actions": legacy_actions,
        "bonus_actions": legacy_bonus_actions,
        "reactions": legacy_reactions,
        "legendary_actions": legacy_legendary_actions,
        "lair_actions": legacy_lair_actions,
        "innate_spellcasting": innate_spellcasting,
        "resources": resources,
        "damage_resistances": payload.get("damage_resistances", []),
        "damage_immunities": payload.get("damage_immunities", []),
        "damage_vulnerabilities": payload.get("damage_vulnerabilities", []),
        "condition_immunities": payload.get("condition_immunities", []),
        "script_hooks": payload.get("script_hooks", {}),
        "traits": payload.get("traits", []),
        "trait_entries": payload.get("trait_entries", []),
    }

    return _modern_defaults(modern)
