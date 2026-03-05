import json
import re
import sqlite3
from pathlib import Path
from typing import Any

_CONTENT_ID_RE = re.compile(r"^(?P<kind>[a-z_]+):(?P<slug>[a-z0-9_]+)\|(?P<source>[A-Z0-9_]+)$")
_CONTENT_SLUG_RE = re.compile(r"[^a-z0-9]+")
_GLOBAL_CONTENT_SCHEMA_VERSION = "wld11.v1"
_DEFAULT_RULES_SOURCE_BOOK = "2014"


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


def _slugify(value: Any) -> str:
    return _CONTENT_SLUG_RE.sub("_", str(value).strip().lower()).strip("_")


def _normalize_source_book(value: Any, *, default: str) -> str:
    if not isinstance(value, str):
        return default
    normalized = _slugify(value).upper()
    return normalized or default


def _canonical_content_id(kind: str, identifier: Any, source_book: str) -> str:
    slug = _slugify(identifier)
    if not slug:
        raise ValueError(f"cannot derive canonical ID for kind '{kind}' from blank identifier")
    source = _normalize_source_book(source_book, default=source_book)
    if not source:
        raise ValueError(f"cannot derive canonical ID for kind '{kind}' without source book")
    return f"{kind}:{slug}|{source}"


def _parse_payload(raw_json: Any) -> dict[str, Any]:
    try:
        payload = json.loads(str(raw_json))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _coerce_existing_content_id(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise ValueError("content_id must be a string when provided")
    normalized = raw_value.strip()
    if not normalized:
        raise ValueError("content_id must be non-empty when provided")
    if _CONTENT_ID_RE.fullmatch(normalized) is None:
        raise ValueError(f"invalid content_id '{normalized}'")
    return normalized


def _content_record_from_trait_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = _parse_payload(row["data_json"])
    source_book = _normalize_source_book(
        payload.get("source_book"), default=_DEFAULT_RULES_SOURCE_BOOK
    )
    content_id = _coerce_existing_content_id(payload.get("content_id"))
    if content_id is None:
        content_id = _canonical_content_id(
            "trait",
            row["id"],
            source_book,
        )
    return {
        "content_id": content_id,
        "content_type": "trait",
        "source_book": source_book,
        "schema_version": str(payload.get("schema_version") or _GLOBAL_CONTENT_SCHEMA_VERSION),
        "source_path": str(payload.get("source_path") or f"sqlite:traits/{row['id']}"),
        "payload_json": json.dumps(payload if payload else {"name": row["name"]}, sort_keys=True),
    }


def _content_record_from_character_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = _parse_payload(row["data_json"])
    source_book = _normalize_source_book(payload.get("source_book"), default="CUSTOM")
    content_id = _coerce_existing_content_id(payload.get("content_id"))
    if content_id is None:
        content_id = _canonical_content_id(
            "character",
            payload.get("character_id") or row["character_id"],
            source_book,
        )
    return {
        "content_id": content_id,
        "content_type": "character",
        "source_book": source_book,
        "schema_version": str(payload.get("schema_version") or _GLOBAL_CONTENT_SCHEMA_VERSION),
        "source_path": str(
            payload.get("source_path") or f"sqlite:characters/{row['character_id']}"
        ),
        "payload_json": json.dumps(
            payload if payload else {"character_id": row["character_id"], "name": row["name"]},
            sort_keys=True,
        ),
    }


def _content_record_from_enemy_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = _parse_payload(row["data_json"])
    identity = payload.get("identity")
    identity_enemy_id = identity.get("enemy_id") if isinstance(identity, dict) else None
    source_book = _normalize_source_book(
        payload.get("source_book"), default=_DEFAULT_RULES_SOURCE_BOOK
    )
    content_id = _coerce_existing_content_id(payload.get("content_id"))
    if content_id is None:
        content_id = _canonical_content_id(
            "monster",
            identity_enemy_id or row["enemy_id"],
            source_book,
        )
    return {
        "content_id": content_id,
        "content_type": "monster",
        "source_book": source_book,
        "schema_version": str(payload.get("schema_version") or _GLOBAL_CONTENT_SCHEMA_VERSION),
        "source_path": str(payload.get("source_path") or f"sqlite:enemies/{row['enemy_id']}"),
        "payload_json": json.dumps(
            (
                payload
                if payload
                else {"identity": {"enemy_id": row["enemy_id"], "name": row["name"]}}
            ),
            sort_keys=True,
        ),
    }


def _ensure_content_records_schema(cursor: sqlite3.Cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS content_records (
            content_id TEXT PRIMARY KEY,
            content_type TEXT NOT NULL,
            source_book TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            source_path TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_content_records_type
        ON content_records(content_type)
        """)


def _collect_content_records(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for row in cursor.execute("SELECT id, name, data_json FROM traits").fetchall():
        records.append(_content_record_from_trait_row(row))

    for row in cursor.execute(
        "SELECT character_id, name, ac, max_hp, initiative_mod, data_json FROM characters"
    ).fetchall():
        records.append(_content_record_from_character_row(row))

    for row in cursor.execute(
        "SELECT enemy_id, name, team, cr, ac, max_hp, initiative_mod, data_json FROM enemies"
    ).fetchall():
        records.append(_content_record_from_enemy_row(row))

    return records


def _upsert_content_records(cursor: sqlite3.Cursor, records: list[dict[str, Any]]) -> int:
    seen: dict[str, str] = {}
    for record in records:
        content_id = str(record["content_id"])
        source_path = str(record["source_path"])
        if content_id in seen:
            raise ValueError(
                f"duplicate content_id '{content_id}' across {seen[content_id]} and {source_path}"
            )
        seen[content_id] = source_path

    for record in records:
        cursor.execute(
            """
            INSERT INTO content_records (
                content_id,
                content_type,
                source_book,
                schema_version,
                source_path,
                payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(content_id) DO UPDATE SET
                content_type = excluded.content_type,
                source_book = excluded.source_book,
                schema_version = excluded.schema_version,
                source_path = excluded.source_path,
                payload_json = excluded.payload_json,
                imported_at = CURRENT_TIMESTAMP
            """,
            (
                record["content_id"],
                record["content_type"],
                record["source_book"],
                record["schema_version"],
                record["source_path"],
                record["payload_json"],
            ),
        )
    return len(records)


def backfill_content_records() -> int:
    """Backfill canonical content_records entries from traits, characters, and enemies."""
    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_content_records_schema(cursor)
        count = _upsert_content_records(cursor, _collect_content_records(cursor))
        conn.commit()
        return count


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

        _ensure_content_records_schema(cursor)
        _upsert_content_records(cursor, _collect_content_records(cursor))
        conn.commit()


def execute_query(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    """Helper to execute a query and fetch all rows."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()
