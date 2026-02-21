import json
import sqlite3
from pathlib import Path
from typing import Any


def get_db_path() -> Path:
    """Returns the absolute path to the dnd_sim SQLite database."""
    base_dir = Path(__file__).resolve().parent.parent.parent
    return base_dir / "data" / "dnd_sim.db"


def get_connection() -> sqlite3.Connection:
    """Returns a configured SQLite connection with foreign keys enabled."""
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    """Initializes the SQLite database schemas for the Hybrid JSON architecture."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Traits & Feats
        # Storing name as primary key since JSON keys were lowercase strings
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS traits (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                data_json TEXT NOT NULL
            )
            """
        )

        # Characters (Party Members)
        # Core metadata pulled into standard columns for searching/filtering
        # Complex nested structures (spells, actions, resources) stay in JSON
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS characters (
                character_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                class_level TEXT NOT NULL,
                ac INTEGER NOT NULL,
                max_hp INTEGER NOT NULL,
                initiative_mod INTEGER,
                data_json TEXT NOT NULL
            )
            """
        )

        # Enemies (Monsters/NPCs)
        # CR and Team pulled out along with combat stats
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS enemies (
                enemy_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                team TEXT NOT NULL,
                cr REAL,
                ac INTEGER NOT NULL,
                max_hp INTEGER NOT NULL,
                initiative_mod INTEGER,
                data_json TEXT NOT NULL
            )
            """
        )

        conn.commit()


def execute_query(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    """Helper to execute a query and fetch all rows."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()
