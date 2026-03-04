import json
import math
import re
from pathlib import Path


def get_proficiency_bonus(cr_str: str) -> int:
    if cr_str in ["0", "1/8", "1/4", "1/2"]:
        return 2
    try:
        cr = int(cr_str)
        return max(2, (cr - 1) // 4 + 2)
    except ValueError:
        return 2

def get_ability_modifier(score: int) -> int:
    return math.floor((score - 10) / 2)


def _ability_modifier_from_payload(monster: dict, ability: str) -> int:
    stat_block = monster.get("stat_block", {}) if isinstance(monster, dict) else {}
    direct_mod = stat_block.get(f"{ability}_mod")
    if isinstance(direct_mod, (int, float)):
        return int(direct_mod)

    ability_scores = monster.get("ability_scores")
    if not isinstance(ability_scores, dict):
        ability_scores = stat_block.get("ability_scores")
    if isinstance(ability_scores, dict) and ability in ability_scores:
        return get_ability_modifier(int(ability_scores[ability]))

    raise KeyError(f"missing ability modifier for {ability}")


def test_monster_saving_throws_math():
    root = Path(__file__).resolve().parents[1]
    monsters_dir = root / "db" / "rules" / "2014" / "monsters"

    if not monsters_dir.exists():
        return  # Skip if not ingested

    for json_file in monsters_dir.glob("*.json"):
        with open(json_file, "r") as f:
            monster = json.load(f)

        stat_block = monster.get("stat_block", {}) if isinstance(monster, dict) else {}
        cr = str(stat_block.get("cr", monster.get("cr", "0")))
        prof_bonus = get_proficiency_bonus(cr)
        save_mods = stat_block.get("save_mods", {})
        if not isinstance(save_mods, dict) or not save_mods:
            continue

        for ability, actual_bonus in save_mods.items():
            attr = str(ability).lower()
            if attr not in {"str", "dex", "con", "int", "wis", "cha"}:
                continue
            try:
                expected_mod = _ability_modifier_from_payload(monster, attr)
            except KeyError:
                continue
            expected_total = expected_mod + prof_bonus
            actual_total = int(actual_bonus)

            assert expected_total == actual_total, (
                f"{monster['identity']['name'] if isinstance(monster.get('identity'), dict) else json_file.stem} "
                f"{attr} save mismatch: Expected {expected_total} "
                f"(Mod {expected_mod} + PB {prof_bonus}), Got {actual_total}"
            )


def test_monster_hp_math():
    root = Path(__file__).resolve().parents[1]
    monsters_dir = root / "db" / "rules" / "2014" / "monsters"

    if not monsters_dir.exists():
        return

    for json_file in monsters_dir.glob("*.json"):
        with open(json_file, "r") as f:
            monster = json.load(f)

        stat_block = monster.get("stat_block", {}) if isinstance(monster, dict) else {}
        hp = stat_block.get("max_hp", monster.get("hp"))
        if hp is None:
            continue
        assert int(hp) > 0

        formula = stat_block.get("hp_formula", monster.get("hp_formula"))
        if not isinstance(formula, str) or not formula.strip():
            continue

        # Replace unicode minus signs with standard hyphens.
        formula = formula.replace(" ", "").replace("−", "-").replace("–", "-")

        # Example: 18d10+36
        match = re.match(r"(\d+)d(\d+)(?:([+-])(\d+))?", formula)
        if not match:
            continue

        count, die, op, flat = match.groups()
        count = int(count)
        die = int(die)
        flat = int(flat) if flat else 0
        if op == "-":
            flat = -flat

        try:
            con_mod = _ability_modifier_from_payload(monster, "con")
        except KeyError:
            continue
        expected_flat = count * con_mod

        # Flat modifier should match count * CON mod.
        assert expected_flat == flat, (
            f"{monster['identity']['name'] if isinstance(monster.get('identity'), dict) else json_file.stem} "
            f"flat HP mismatch: Expected {count}*{con_mod}={expected_flat}, got {flat}"
        )
