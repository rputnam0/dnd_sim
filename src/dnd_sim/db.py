import json
import sqlite3
from pathlib import Path
from typing import Any

CONTENT_RECORDS_TABLE = "content_records"
CONTENT_CAPABILITIES_TABLE = "content_capabilities"

CONTENT_RECORDS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS content_records (
    content_id TEXT PRIMARY KEY,
    content_type TEXT NOT NULL,
    source_book TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    CHECK (length(trim(content_id)) > 0),
    CHECK (length(trim(content_type)) > 0),
    CHECK (length(trim(source_book)) > 0),
    CHECK (length(trim(schema_version)) > 0),
    CHECK (length(trim(source_hash)) > 0),
    CHECK (length(trim(payload_json)) > 0)
)
"""

CONTENT_CAPABILITIES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS content_capabilities (
    content_id TEXT PRIMARY KEY,
    content_type TEXT NOT NULL,
    support_state TEXT NOT NULL,
    unsupported_reason TEXT,
    last_verified_commit TEXT NOT NULL,
    FOREIGN KEY (content_id) REFERENCES content_records(content_id) ON DELETE CASCADE,
    CHECK (length(trim(content_id)) > 0),
    CHECK (length(trim(content_type)) > 0),
    CHECK (length(trim(support_state)) > 0),
    CHECK (length(trim(last_verified_commit)) > 0),
    CHECK (
        (support_state = 'blocked' AND unsupported_reason IS NOT NULL AND length(trim(unsupported_reason)) > 0)
        OR
        (support_state <> 'blocked' AND unsupported_reason IS NULL)
    )
)
"""

CONTENT_METADATA_INDEXES_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_content_records_content_type ON content_records(content_type)",
    (
        "CREATE INDEX IF NOT EXISTS idx_content_capabilities_support_state "
        "ON content_capabilities(support_state)"
    ),
)


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


def _canonical_json_text(payload: dict[str, Any] | list[Any] | str) -> str:
    if isinstance(payload, str):
        decoded = json.loads(payload)
        return json.dumps(decoded, sort_keys=True)
    return json.dumps(payload, sort_keys=True)


def _required_text(value: str, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _normalize_unsupported_reason(
    *,
    support_state: str,
    unsupported_reason: str | None,
) -> str | None:
    normalized_state = _required_text(support_state, field_name="support_state")
    normalized_reason = None if unsupported_reason is None else str(unsupported_reason).strip()
    if normalized_state == "blocked":
        if not normalized_reason:
            raise ValueError("unsupported_reason is required when support_state='blocked'")
        return normalized_reason
    if normalized_reason is not None:
        raise ValueError("unsupported_reason must be null when support_state is not 'blocked'")
    return None


def create_content_metadata_tables(conn: sqlite3.Connection) -> None:
    """Create canonical metadata tables for content records and support state."""
    conn.execute(CONTENT_RECORDS_SCHEMA_SQL)
    conn.execute(CONTENT_CAPABILITIES_SCHEMA_SQL)
    for statement in CONTENT_METADATA_INDEXES_SQL:
        conn.execute(statement)


def upsert_content_record(
    conn: sqlite3.Connection,
    *,
    content_id: str,
    content_type: str,
    source_book: str,
    schema_version: str,
    source_hash: str,
    payload_json: dict[str, Any] | list[Any] | str,
) -> None:
    """Insert or update one canonical content record row."""
    conn.execute(
        """
        INSERT INTO content_records (
            content_id, content_type, source_book, schema_version, source_hash, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(content_id) DO UPDATE SET
            content_type=excluded.content_type,
            source_book=excluded.source_book,
            schema_version=excluded.schema_version,
            source_hash=excluded.source_hash,
            payload_json=excluded.payload_json
        """,
        (
            _required_text(content_id, field_name="content_id"),
            _required_text(content_type, field_name="content_type"),
            _required_text(source_book, field_name="source_book"),
            _required_text(schema_version, field_name="schema_version"),
            _required_text(source_hash, field_name="source_hash"),
            _canonical_json_text(payload_json),
        ),
    )


def upsert_content_capability(
    conn: sqlite3.Connection,
    *,
    content_id: str,
    content_type: str,
    support_state: str,
    unsupported_reason: str | None,
    last_verified_commit: str,
) -> None:
    """Insert or update one canonical content capability row."""
    normalized_state = _required_text(support_state, field_name="support_state")
    normalized_reason = _normalize_unsupported_reason(
        support_state=normalized_state,
        unsupported_reason=unsupported_reason,
    )
    conn.execute(
        """
        INSERT INTO content_capabilities (
            content_id, content_type, support_state, unsupported_reason, last_verified_commit
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(content_id) DO UPDATE SET
            content_type=excluded.content_type,
            support_state=excluded.support_state,
            unsupported_reason=excluded.unsupported_reason,
            last_verified_commit=excluded.last_verified_commit
        """,
        (
            _required_text(content_id, field_name="content_id"),
            _required_text(content_type, field_name="content_type"),
            normalized_state,
            normalized_reason,
            _required_text(last_verified_commit, field_name="last_verified_commit"),
        ),
    )


def init_db() -> None:
    """Initializes the SQLite database schemas for the Hybrid JSON architecture."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Traits & Feats
        # Storing name as primary key since JSON keys were lowercase strings
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS traits (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                data_json TEXT NOT NULL
            )
            """)

        # Characters (Party Members)
        # Core metadata pulled into standard columns for searching/filtering
        # Complex nested structures (spells, actions, resources) stay in JSON
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS characters (
                character_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                ac INTEGER NOT NULL,
                max_hp INTEGER NOT NULL,
                initiative_mod INTEGER,
                data_json TEXT NOT NULL
            )
            """)

        # Enemies (Monsters/NPCs)
        # CR and Team pulled out along with combat stats
        cursor.execute("""
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
            """)

        create_content_metadata_tables(conn)
        conn.commit()


def execute_query(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    """Helper to execute a query and fetch all rows."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()
