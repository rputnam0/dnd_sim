import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

CONTENT_RECORDS_TABLE = "content_records"
CONTENT_CAPABILITIES_TABLE = "content_capabilities"
CAMPAIGN_STATES_TABLE = "campaign_states"
ENCOUNTER_STATES_TABLE = "encounter_states"
LEGACY_IMPORTED_AT = "1970-01-01T00:00:00+00:00"

CONTENT_RECORDS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS content_records (
    content_id TEXT PRIMARY KEY,
    content_type TEXT NOT NULL,
    source_book TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    canonicalization_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    CHECK (length(trim(content_id)) > 0),
    CHECK (length(trim(content_type)) > 0),
    CHECK (length(trim(source_book)) > 0),
    CHECK (length(trim(schema_version)) > 0),
    CHECK (length(trim(source_path)) > 0),
    CHECK (length(trim(source_hash)) > 0),
    CHECK (length(trim(canonicalization_hash)) > 0),
    CHECK (length(trim(payload_json)) > 0),
    CHECK (length(trim(imported_at)) > 0)
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
    "CREATE INDEX IF NOT EXISTS idx_content_records_source_hash ON content_records(source_hash)",
    (
        "CREATE INDEX IF NOT EXISTS idx_content_records_canonicalization_hash "
        "ON content_records(canonicalization_hash)"
    ),
    "CREATE INDEX IF NOT EXISTS idx_content_records_imported_at ON content_records(imported_at)",
    (
        "CREATE INDEX IF NOT EXISTS idx_content_capabilities_support_state "
        "ON content_capabilities(support_state)"
    ),
)

CAMPAIGN_STATES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS campaign_states (
    campaign_id TEXT PRIMARY KEY,
    snapshot_version TEXT NOT NULL,
    party_state_json TEXT NOT NULL,
    resources_json TEXT NOT NULL,
    active_effects_json TEXT NOT NULL,
    initiative_context_json TEXT NOT NULL,
    replay_bundle_id TEXT,
    snapshot_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (length(trim(campaign_id)) > 0),
    CHECK (length(trim(snapshot_version)) > 0),
    CHECK (length(trim(party_state_json)) > 0),
    CHECK (length(trim(resources_json)) > 0),
    CHECK (length(trim(active_effects_json)) > 0),
    CHECK (length(trim(initiative_context_json)) > 0),
    CHECK (length(trim(snapshot_hash)) > 0),
    CHECK (length(trim(updated_at)) > 0)
)
"""

ENCOUNTER_STATES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS encounter_states (
    campaign_id TEXT NOT NULL,
    encounter_id TEXT NOT NULL,
    snapshot_version TEXT NOT NULL,
    party_state_json TEXT NOT NULL,
    resources_json TEXT NOT NULL,
    active_effects_json TEXT NOT NULL,
    initiative_context_json TEXT NOT NULL,
    replay_bundle_id TEXT,
    snapshot_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (campaign_id, encounter_id),
    FOREIGN KEY (campaign_id) REFERENCES campaign_states(campaign_id) ON DELETE CASCADE,
    CHECK (length(trim(campaign_id)) > 0),
    CHECK (length(trim(encounter_id)) > 0),
    CHECK (length(trim(snapshot_version)) > 0),
    CHECK (length(trim(party_state_json)) > 0),
    CHECK (length(trim(resources_json)) > 0),
    CHECK (length(trim(active_effects_json)) > 0),
    CHECK (length(trim(initiative_context_json)) > 0),
    CHECK (length(trim(snapshot_hash)) > 0),
    CHECK (length(trim(updated_at)) > 0)
)
"""

CAMPAIGN_STATE_INDEXES_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_campaign_states_updated_at ON campaign_states(updated_at)",
    (
        "CREATE INDEX IF NOT EXISTS idx_campaign_states_replay_bundle_id "
        "ON campaign_states(replay_bundle_id)"
    ),
    "CREATE INDEX IF NOT EXISTS idx_encounter_states_campaign_id ON encounter_states(campaign_id)",
    "CREATE INDEX IF NOT EXISTS idx_encounter_states_updated_at ON encounter_states(updated_at)",
    (
        "CREATE INDEX IF NOT EXISTS idx_encounter_states_replay_bundle_id "
        "ON encounter_states(replay_bundle_id)"
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


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [str(row[1]) for row in rows]


def _canonical_json_text(payload: dict[str, Any] | list[Any] | str) -> str:
    if isinstance(payload, str):
        decoded = json.loads(payload)
        return json.dumps(decoded, sort_keys=True, separators=(",", ":"))
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _stable_payload_hash(payload: dict[str, Any] | list[Any] | str) -> str:
    if isinstance(payload, str):
        try:
            canonical = _canonical_json_text(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            canonical = payload.strip()
    else:
        canonical = _canonical_json_text(payload)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


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


def _add_lineage_column_if_missing(
    conn: sqlite3.Connection,
    *,
    column_name: str,
    definition: str,
) -> None:
    columns = set(_table_columns(conn, CONTENT_RECORDS_TABLE))
    if column_name in columns:
        return
    conn.execute(f"ALTER TABLE {CONTENT_RECORDS_TABLE} ADD COLUMN {column_name} {definition}")


def _migrate_content_record_lineage_columns(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, CONTENT_RECORDS_TABLE):
        return

    _add_lineage_column_if_missing(
        conn,
        column_name="source_path",
        definition="TEXT NOT NULL DEFAULT ''",
    )
    _add_lineage_column_if_missing(
        conn,
        column_name="canonicalization_hash",
        definition="TEXT NOT NULL DEFAULT ''",
    )
    _add_lineage_column_if_missing(
        conn,
        column_name="imported_at",
        definition="TEXT NOT NULL DEFAULT ''",
    )

    rows = conn.execute("""
        SELECT content_id, source_path, source_hash, canonicalization_hash, payload_json, imported_at
        FROM content_records
        """).fetchall()
    for row in rows:
        content_id = _required_text(str(row[0]), field_name="content_id")
        payload_json = str(row[4])
        payload_hash = _stable_payload_hash(payload_json)

        source_path = str(row[1] or "").strip() or f"legacy:{content_id}"
        source_hash = str(row[2] or "").strip() or payload_hash
        canonicalization_hash = str(row[3] or "").strip() or payload_hash
        imported_at = str(row[5] or "").strip() or LEGACY_IMPORTED_AT

        conn.execute(
            """
            UPDATE content_records
            SET source_path = ?, source_hash = ?, canonicalization_hash = ?, imported_at = ?
            WHERE content_id = ?
            """,
            (source_path, source_hash, canonicalization_hash, imported_at, content_id),
        )


def create_content_metadata_tables(conn: sqlite3.Connection) -> None:
    """Create canonical metadata tables for content records and support state."""
    conn.execute(CONTENT_RECORDS_SCHEMA_SQL)
    _migrate_content_record_lineage_columns(conn)
    conn.execute(CONTENT_CAPABILITIES_SCHEMA_SQL)
    for statement in CONTENT_METADATA_INDEXES_SQL:
        conn.execute(statement)


def create_campaign_state_tables(conn: sqlite3.Connection) -> None:
    """Create campaign and encounter state persistence tables."""
    conn.execute(CAMPAIGN_STATES_SCHEMA_SQL)
    conn.execute(ENCOUNTER_STATES_SCHEMA_SQL)
    for statement in CAMPAIGN_STATE_INDEXES_SQL:
        conn.execute(statement)


def upsert_content_record(
    conn: sqlite3.Connection,
    *,
    content_id: str,
    content_type: str,
    source_book: str,
    schema_version: str,
    source_path: str,
    source_hash: str,
    canonicalization_hash: str,
    payload_json: dict[str, Any] | list[Any] | str,
    imported_at: str,
) -> None:
    """Insert or update one canonical content record row."""
    conn.execute(
        """
        INSERT INTO content_records (
            content_id,
            content_type,
            source_book,
            schema_version,
            source_path,
            source_hash,
            canonicalization_hash,
            payload_json,
            imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(content_id) DO UPDATE SET
            content_type=excluded.content_type,
            source_book=excluded.source_book,
            schema_version=excluded.schema_version,
            source_path=excluded.source_path,
            source_hash=excluded.source_hash,
            canonicalization_hash=excluded.canonicalization_hash,
            payload_json=excluded.payload_json,
            imported_at=excluded.imported_at
        """,
        (
            _required_text(content_id, field_name="content_id"),
            _required_text(content_type, field_name="content_type"),
            _required_text(source_book, field_name="source_book"),
            _required_text(schema_version, field_name="schema_version"),
            _required_text(source_path, field_name="source_path"),
            _required_text(source_hash, field_name="source_hash"),
            _required_text(canonicalization_hash, field_name="canonicalization_hash"),
            _canonical_json_text(payload_json),
            _required_text(imported_at, field_name="imported_at"),
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


def fetch_content_lineage(
    conn: sqlite3.Connection,
    *,
    content_type: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch content lineage rows in deterministic imported-at order."""
    params: tuple[Any, ...] = ()
    where_clause = ""
    if content_type is not None:
        where_clause = "WHERE content_type = ?"
        params = (_required_text(content_type, field_name="content_type"),)

    rows = conn.execute(
        f"""
        SELECT
            content_id,
            content_type,
            source_book,
            schema_version,
            source_path,
            source_hash,
            canonicalization_hash,
            payload_json,
            imported_at
        FROM content_records
        {where_clause}
        ORDER BY imported_at ASC, content_id ASC
        """,
        params,
    ).fetchall()

    lineage: list[dict[str, Any]] = []
    for row in rows:
        payload_raw = str(row[7])
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            payload = payload_raw

        lineage.append(
            {
                "content_id": str(row[0]),
                "content_type": str(row[1]),
                "source_book": str(row[2]),
                "schema_version": str(row[3]),
                "source_path": str(row[4]),
                "source_hash": str(row[5]),
                "canonicalization_hash": str(row[6]),
                "payload_json": payload,
                "imported_at": str(row[8]),
            }
        )
    return lineage


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
        create_campaign_state_tables(conn)
        conn.commit()


def execute_query(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    """Helper to execute a query and fetch all rows."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()
