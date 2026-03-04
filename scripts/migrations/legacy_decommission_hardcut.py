from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from dnd_sim.characters import canonical_class_level_text, normalize_class_levels, parse_class_levels
from dnd_sim.monster_backfill import backfill_monster_payload
from dnd_sim.spells import canonicalize_spell_payload, spell_lookup_key

CANONICAL_EFFECT_ALIASES = {
    "shapechange": "transform",
    "summon_creature": "summon",
    "command_construct_companion": "command_allied",
    "antimagic": "antimagic_field",
    "antimagic_zone": "antimagic_field",
}

EXECUTABLE_EFFECT_TYPES = {
    "damage",
    "heal",
    "temp_hp",
    "apply_condition",
    "remove_condition",
    "resource_change",
    "next_attack_advantage",
    "next_attack_disadvantage",
    "forced_movement",
    "hazard",
    "max_hp_increase",
    "speed_increase",
    "sense",
    "ignore_resistance",
    "reduce_damage_taken",
    "damage_roll_floor",
    "reaction_attack",
    "summon",
    "conjure",
    "transform",
    "command_allied",
    "mount",
    "dismount",
}

SOURCE_TYPE_MAP = {
    "feat": "feat",
    "racial_trait": "species",
    "species_trait": "species",
    "background_feature": "background",
    "subclass_feature": "subclass",
    "class_feature": "class",
    "metamagic": "class",
}

ENEMY_SCHEMA_KEYS = {
    "identity",
    "stat_block",
    "actions",
    "bonus_actions",
    "reactions",
    "legendary_actions",
    "lair_actions",
    "innate_spellcasting",
    "resources",
    "damage_resistances",
    "damage_immunities",
    "damage_vulnerabilities",
    "condition_immunities",
    "script_hooks",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _canonical_effect_type(raw_effect_type: Any) -> str:
    text = str(raw_effect_type or "").strip().lower()
    return CANONICAL_EFFECT_ALIASES.get(text, text)


def _normalize_trigger(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text if text else None


def _normalize_source_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"feat", "species", "background", "subclass", "class", "other"}:
        return text
    return SOURCE_TYPE_MAP.get(text, "other")


def _normalize_mechanics_rows(rows: Any) -> list[Any]:
    if not isinstance(rows, list):
        return []

    normalized: list[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            normalized.append(row)
            continue
        payload = dict(row)

        trigger = _normalize_trigger(payload.get("trigger"))
        legacy_trigger = _normalize_trigger(payload.get("event_trigger"))
        if trigger:
            payload["trigger"] = trigger
        elif legacy_trigger:
            payload["trigger"] = legacy_trigger
        payload.pop("event_trigger", None)

        if "effect_type" in payload and str(payload.get("effect_type", "")).strip():
            payload["effect_type"] = _canonical_effect_type(payload["effect_type"])
            payload.pop("meta_type", None)
        else:
            legacy_type = str(payload.get("type", "")).strip().lower()
            canonical_legacy = _canonical_effect_type(legacy_type)
            if canonical_legacy in EXECUTABLE_EFFECT_TYPES:
                payload["effect_type"] = canonical_legacy
                payload.pop("meta_type", None)
            elif legacy_type:
                payload["meta_type"] = legacy_type
                payload.pop("effect_type", None)
            else:
                payload.pop("effect_type", None)
        payload.pop("type", None)

        if isinstance(payload.get("meta_type"), str):
            payload["meta_type"] = str(payload["meta_type"]).strip().lower()
        normalized.append(payload)
    return normalized


def migrate_traits(traits_dir: Path) -> int:
    migrated = 0
    for path in sorted(traits_dir.glob("*.json")):
        payload = _load_json(path)
        source_type = payload.get("source_type", payload.get("type"))
        payload["source_type"] = _normalize_source_type(source_type)
        payload.pop("type", None)
        payload["mechanics"] = _normalize_mechanics_rows(payload.get("mechanics"))
        _dump_json(path, payload)
        migrated += 1
    return migrated


def _spell_richness(payload: dict[str, Any]) -> tuple[int, int]:
    score = 0
    for field in ("school", "range_ft", "duration_rounds", "save_ability", "damage_type"):
        if payload.get(field) not in (None, ""):
            score += 1
    if payload.get("mechanics"):
        score += 3
    if payload.get("concentration"):
        score += 1
    if payload.get("ritual"):
        score += 1
    if payload.get("description"):
        score += 1
    return score, len(str(payload.get("description", "")))


def _choose_spell_winner(candidates: list[tuple[Path, dict[str, Any]]]) -> tuple[Path, dict[str, Any]]:
    ranked = sorted(
        candidates,
        key=lambda row: (
            -_spell_richness(row[1])[0],
            -_spell_richness(row[1])[1],
            row[0].name,
        ),
    )
    return ranked[0]


def migrate_spells(spells_dir: Path) -> tuple[int, int]:
    grouped: dict[str, list[tuple[Path, dict[str, Any]]]] = defaultdict(list)
    for path in sorted(spells_dir.glob("*.json")):
        raw = _load_json(path)
        canonical = canonicalize_spell_payload(raw, source_path=path)
        canonical["mechanics"] = _normalize_mechanics_rows(canonical.get("mechanics"))
        key = spell_lookup_key(canonical["name"])
        grouped[key].append((path, canonical))

    rewritten = 0
    deleted = 0
    for _key, candidates in grouped.items():
        winner_path, winner_payload = _choose_spell_winner(candidates)
        _dump_json(winner_path, winner_payload)
        rewritten += 1
        for path, _payload in candidates:
            if path == winner_path:
                continue
            path.unlink()
            deleted += 1
    return rewritten, deleted


def _normalize_action_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, Any]] = []
    for action in rows:
        if not isinstance(action, dict):
            continue
        payload = dict(action)
        payload["effects"] = _normalize_mechanics_rows(payload.get("effects"))
        payload["mechanics"] = _normalize_mechanics_rows(payload.get("mechanics"))
        normalized.append(payload)
    return normalized


def migrate_monsters(monsters_dir: Path) -> int:
    migrated = 0
    for path in sorted(monsters_dir.glob("*.json")):
        raw = _load_json(path)
        modern = backfill_monster_payload(raw)
        canonical = {key: modern.get(key) for key in ENEMY_SCHEMA_KEYS}
        canonical["actions"] = _normalize_action_rows(canonical.get("actions"))
        canonical["bonus_actions"] = _normalize_action_rows(canonical.get("bonus_actions"))
        canonical["reactions"] = _normalize_action_rows(canonical.get("reactions"))
        canonical["legendary_actions"] = _normalize_action_rows(canonical.get("legendary_actions"))
        canonical["lair_actions"] = _normalize_action_rows(canonical.get("lair_actions"))
        _dump_json(path, canonical)
        migrated += 1
    return migrated


def migrate_characters(characters_dir: Path) -> int:
    migrated = 0
    for path in sorted(characters_dir.glob("*.json")):
        if path.name == "index.json":
            continue
        payload = _load_json(path)
        class_levels_raw = payload.get("class_levels")
        if isinstance(class_levels_raw, dict) and class_levels_raw:
            class_levels = normalize_class_levels(class_levels_raw)
        else:
            class_levels = parse_class_levels(str(payload.get("class_level", "")))
            class_levels = normalize_class_levels(class_levels)
        if not class_levels:
            raise ValueError(f"{path} is missing canonical class_levels mapping")
        payload["class_levels"] = class_levels
        payload["class_level"] = canonical_class_level_text(class_levels)
        _dump_json(path, payload)
        migrated += 1
    return migrated


def main() -> None:
    parser = argparse.ArgumentParser(description="Run legacy decommission canonical data migration.")
    parser.add_argument("--repo-root", default=".", help="Repository root path.")
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    traits_dir = root / "db/rules/2014/traits"
    spells_dir = root / "db/rules/2014/spells"
    monsters_dir = root / "db/rules/2014/monsters"
    characters_dir = root / "river_line/db/characters"

    traits_count = migrate_traits(traits_dir)
    rewritten_spells, deleted_spells = migrate_spells(spells_dir)
    monsters_count = migrate_monsters(monsters_dir)
    characters_count = migrate_characters(characters_dir)

    print(f"migrated traits: {traits_count}")
    print(f"rewrote spells: {rewritten_spells}")
    print(f"deleted duplicate spells: {deleted_spells}")
    print(f"migrated monsters: {monsters_count}")
    print(f"migrated characters: {characters_count}")


if __name__ == "__main__":
    main()
