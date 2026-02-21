import json
import sys
from pathlib import Path

# Add src to python path to import dnd_sim
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dnd_sim.db import get_connection, init_db
from dnd_sim.io import load_character_db

def main():
    base_dir = Path(__file__).resolve().parent.parent
    
    print("Initializing SQLite Database...")
    init_db()

    with get_connection() as conn:
        cursor = conn.cursor()

        # 1. Migrate Traits
        # There isn't a central traits.json, but maybe we have traits in `db/raw/5etools/feats.json`?
        # The user's io.py implies there is a load_traits(path) function.
        # Let's skip traits for a moment if we are only migrating the engine runtime.

        # 2. Migrate Characters
        char_db_path = base_dir / "river_line" / "db" / "characters"
        if char_db_path.exists():
            print(f"Migrating characters from {char_db_path}...")
            characters = load_character_db(char_db_path)
            for char_id, char_data in characters.items():
                name = char_data.get("name", char_id)
                class_level = char_data.get("class_level", "1")
                ac = int(char_data.get("ac", 10))
                max_hp = int(char_data.get("max_hp", 10))
                initiative_mod = char_data.get("initiative_mod")
                
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO characters (character_id, name, class_level, ac, max_hp, initiative_mod, data_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (char_id, name, class_level, ac, max_hp, initiative_mod, json.dumps(char_data))
                )
            print(f"Migrated {len(characters)} characters.")

        # 3. Migrate Enemies
        monsters_dir = base_dir / "db" / "rules" / "2014" / "monsters"
        if monsters_dir.exists():
            print(f"Migrating enemies from {monsters_dir}...")
            count = 0
            for enemy_file in monsters_dir.glob("*.json"):
                with open(enemy_file, "r", encoding="utf-8") as f:
                    enemy_data = json.load(f)
                
                enemy_id = enemy_data.get("identity", {}).get("enemy_id", enemy_file.stem)
                name = enemy_data.get("identity", {}).get("name", enemy_id)
                team = enemy_data.get("identity", {}).get("team", "enemy")
                ac = int(enemy_data.get("stat_block", {}).get("ac", 10))
                max_hp = int(enemy_data.get("stat_block", {}).get("max_hp", 10))
                initiative_mod = enemy_data.get("stat_block", {}).get("initiative_mod")
                cr = enemy_data.get("stat_block", {}).get("cr")

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO enemies (enemy_id, name, team, cr, ac, max_hp, initiative_mod, data_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (enemy_id, name, team, cr, ac, max_hp, initiative_mod, json.dumps(enemy_data))
                )
                count += 1
            print(f"Migrated {count} enemies.")

        # 4. Scenario specific enemies (e.g. from river_line encounters)
        encounters_dir = base_dir / "river_line" / "encounters"
        count = 0
        if encounters_dir.exists():
            print(f"Migrating scenario enemies from {encounters_dir}...")
            for enemy_file in encounters_dir.rglob("enemies/*.json"):
                with open(enemy_file, "r", encoding="utf-8") as f:
                    enemy_data = json.load(f)
                
                enemy_id = enemy_data.get("identity", {}).get("enemy_id", enemy_file.stem)
                name = enemy_data.get("identity", {}).get("name", enemy_id)
                team = enemy_data.get("identity", {}).get("team", "enemy")
                ac = int(enemy_data.get("stat_block", {}).get("ac", 10))
                max_hp = int(enemy_data.get("stat_block", {}).get("max_hp", 10))
                initiative_mod = enemy_data.get("stat_block", {}).get("initiative_mod")
                cr = enemy_data.get("stat_block", {}).get("cr")

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO enemies (enemy_id, name, team, cr, ac, max_hp, initiative_mod, data_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (enemy_id, name, team, cr, ac, max_hp, initiative_mod, json.dumps(enemy_data))
                )
                count += 1
            print(f"Migrated {count} scenario enemies.")

        conn.commit()
        print("Database migration complete.")

if __name__ == "__main__":
    main()
