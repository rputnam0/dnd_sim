from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_character(
    character_id: str,
    name: str,
    max_hp: int,
    ac: int,
    to_hit: int,
    damage: str,
    damage_type: str = "bludgeoning",
    ki: int = 0,
) -> dict[str, Any]:
    resources: dict[str, Any] = {}
    if ki:
        resources["ki"] = {"max": ki}

    return {
        "character_id": character_id,
        "name": name,
        "class_level": "Fighter 8",
        "max_hp": max_hp,
        "ac": ac,
        "speed_ft": 30,
        "ability_scores": {
            "str": 16,
            "dex": 14,
            "con": 14,
            "int": 10,
            "wis": 10,
            "cha": 10,
        },
        "save_mods": {
            "str": 3,
            "dex": 2,
            "con": 2,
            "int": 0,
            "wis": 0,
            "cha": 0,
        },
        "skill_mods": {},
        "attacks": [
            {
                "name": "Weapon",
                "to_hit": to_hit,
                "damage": damage,
                "damage_type": damage_type,
            }
        ],
        "resources": resources,
        "traits": ["Extra Attack"],
        "raw_fields": [],
        "source": {"pdf_name": "fixture.pdf"},
    }


def build_enemy(
    enemy_id: str,
    name: str,
    hp: int,
    ac: int,
    to_hit: int,
    damage: str,
    damage_type: str = "slashing",
    legendary_to_hit: int | None = None,
    legendary_damage: str | None = None,
    legendary_pool: int = 0,
) -> dict[str, Any]:
    legendary_actions: list[dict[str, Any]] = []
    resources: dict[str, int] = {}
    if legendary_to_hit is not None and legendary_damage is not None:
        legendary_actions.append(
            {
                "name": "legendary_strike",
                "action_type": "attack",
                "to_hit": legendary_to_hit,
                "damage": legendary_damage,
                "damage_type": damage_type,
                "attack_count": 1,
                "resource_cost": {},
            }
        )
        resources["legendary_actions"] = legendary_pool if legendary_pool > 0 else 1

    return {
        "identity": {
            "enemy_id": enemy_id,
            "name": name,
            "team": "enemy",
        },
        "stat_block": {
            "max_hp": hp,
            "ac": ac,
            "initiative_mod": 1,
            "dex_mod": 1,
            "con_mod": 1,
            "save_mods": {
                "str": 1,
                "dex": 1,
                "con": 1,
                "int": 0,
                "wis": 0,
                "cha": 0,
            },
        },
        "actions": [
            {
                "name": "basic",
                "action_type": "attack",
                "to_hit": to_hit,
                "damage": damage,
                "damage_type": damage_type,
                "attack_count": 1,
                "resource_cost": {},
            }
        ],
        "bonus_actions": [],
        "reactions": [],
        "legendary_actions": legendary_actions,
        "lair_actions": [],
        "resources": resources,
        "damage_resistances": [],
        "damage_immunities": [],
        "damage_vulnerabilities": [],
        "condition_immunities": [],
        "script_hooks": {},
    }
