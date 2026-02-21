import json
from pathlib import Path

def main():
    root = Path(__file__).resolve().parents[2]
    out_dir = root / "db" / "rules" / "2014" / "traits"
    out_dir.mkdir(parents=True, exist_ok=True)

    traits = [
        {
            "name": "Shield Master",
            "type": "feat",
            "description": "If you are subjected to an effect that allows you to make a Dexterity saving throw to take only half damage, you can use your reaction to take no damage if you succeed on the saving throw, interposing your shield between yourself and the source of the effect.",
            "mechanics": [
                {
                    "effect_type": "evade_damage",
                    "trigger": "dex_save_success",
                    "requires_reaction": True,
                    "condition": "equipped_shield"
                }
            ]
        },
        {
            "name": "War Caster",
            "type": "feat",
            "description": "You have advantage on Constitution saving throws that you make to maintain your concentration on a spell when you take damage.",
            "mechanics": [
                {
                    "effect_type": "advantage",
                    "trigger": "concentration_save"
                }
            ]
        },
        {
            "name": "Careful Spell",
            "type": "metamagic",
            "description": "When you cast a spell that forces other creatures to make a saving throw, you can protect some of those creatures from the spell's full force. To do so, you spend 1 sorcery point and choose a number of those creatures up to your Charisma modifier (minimum of one creature). A chosen creature automatically succeeds on its saving throw against the spell.",
            "mechanics": [
                {
                    "effect_type": "auto_save_allies",
                    "trigger": "spell_cast",
                    "target_mode": "all_creatures",
                    "resource_cost": {"sorcery_points": 1},
                    "max_targets": "cha_mod"
                }
            ]
        },
        {
            "name": "Empowered Spell",
            "type": "metamagic",
            "description": "When you roll damage for a spell, you can spend 1 sorcery point to reroll a number of the damage dice up to your Charisma modifier (minimum of one). You must use the new rolls.",
            "mechanics": [
                {
                    "effect_type": "reroll_damage_dice",
                    "trigger": "spell_damage_roll",
                    "resource_cost": {"sorcery_points": 1},
                    "max_dice": "cha_mod"
                }
            ]
        },
        {
            "name": "Evasion",
            "type": "class_feature",
            "description": "When you are subjected to an effect that allows you to make a Dexterity saving throw to take only half damage, you instead take no damage if you succeed on the saving throw, and only half damage if you fail.",
            "mechanics": [
                {
                    "effect_type": "evasion",
                    "trigger": "dex_save"
                }
            ]
        },
        {
            "name": "Savage Attacker",
            "type": "feat",
            "description": "Once per turn when you roll damage for a melee weapon attack, you can reroll the weapon's damage dice and use either total.",
            "mechanics": [
                {
                    "effect_type": "advantage_damage_roll",
                    "trigger": "melee_weapon_damage_roll",
                    "frequency": "once_per_turn"
                }
            ]
        }
    ]

    for trait in traits:
        safe_name = trait["name"].lower().replace(" ", "_")
        path = out_dir / f"{safe_name}.json"
        path.write_text(json.dumps(trait, indent=2), encoding="utf-8")
        print(f"Wrote {path.name}")

if __name__ == "__main__":
    main()
