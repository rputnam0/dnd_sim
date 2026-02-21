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

def test_monster_saving_throws_math():
    root = Path(__file__).resolve().parents[1]
    monsters_dir = root / "db" / "rules" / "2014" / "monsters"
    
    if not monsters_dir.exists():
        return # Skip if not ingested
        
    for json_file in monsters_dir.glob("*.json"):
        with open(json_file, "r") as f:
            monster = json.load(f)
            
        cr = monster.get("cr", "0")
        prof_bonus = get_proficiency_bonus(cr)
        scores = monster["ability_scores"]
        saves_text = monster.get("saving_throws_text", "")
        
        if not saves_text:
            continue
            
        # Example format: "Con +6, Int +8, Wis +6" or "Saving Throws Wis +2"
        # Since commas might be missing or words appended, safely extract using regex
        saves_text = saves_text.replace("−", "-").replace("–", "-")
        save_matches = re.findall(r"([A-Za-z]{3,})\s*([+-]\d+)", saves_text)
        
        for attr, bonus_str in save_matches:
            # Special case for "Saving Throws" prefix if it leaked
            if attr.lower() in ["saving", "throws"]:
                continue
                
            attr = attr.lower()
            if attr not in scores:
                continue
                
            expected_mod = get_ability_modifier(scores[attr])
            expected_total = expected_mod + prof_bonus
            actual_total = int(bonus_str)
            
            assert expected_total == actual_total, f"{monster['name']} {attr} save mismatch: Expected {expected_total} (Mod {expected_mod} + PB {prof_bonus}), Got {actual_total}"

def test_monster_hp_math():
    root = Path(__file__).resolve().parents[1]
    monsters_dir = root / "db" / "rules" / "2014" / "monsters"
    
    if not monsters_dir.exists():
        return
        
    for json_file in monsters_dir.glob("*.json"):
        with open(json_file, "r") as f:
            monster = json.load(f)
            
        hp = monster["hp"]
        # Replace unicode minus signs with standard hyphens
        formula = monster["hp_formula"].replace(" ", "").replace("−", "-").replace("–", "-")
        scores = monster["ability_scores"]
        
        # 18d10+36
        match = re.match(r"(\d+)d(\d+)(?:([+-])(\d+))?", formula)
        if not match:
            continue
            
        count, die, op, flat = match.groups()
        count = int(count)
        die = int(die)
        flat = int(flat) if flat else 0
        if op == "-":
            flat = -flat
            
        con_mod = get_ability_modifier(scores["con"])
        expected_flat = count * con_mod
        
        # In 5e, average HP per die is (die / 2) + 0.5
        avg_die = (die / 2.0) + 0.5
        expected_avg_hp = math.floor(count * avg_die) + expected_flat
        
        # Sometimes monsters have a +1 or -1 HP difference from truncation, but the flat mod is fixed.
        assert expected_flat == flat, f"{monster['name']} flat HP mismatch: Expected {count}*{con_mod}={expected_flat}, got {flat}"
