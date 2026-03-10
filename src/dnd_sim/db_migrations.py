import sqlite3
from typing import Any

from dnd_sim.db_content_store import (
    _DEFAULT_RULES_SOURCE_BOOK,
    _GLOBAL_CONTENT_SCHEMA_VERSION,
    _canonical_content_id,
    _coerce_existing_content_id,
    _legacy_blob_rows,
    _normalize_source_book,
    _parse_payload,
    upsert_content_capability,
    upsert_content_record,
)
from dnd_sim.db_schema import (
    CONTENT_CAPABILITIES_TABLE,
    CONTENT_RECORDS_TABLE,
    LEGACY_BLOB_LAST_VERIFIED_COMMIT,
    LEGACY_BLOB_SCHEMA_VERSION,
    LEGACY_BLOB_SOURCE_PREFIX,
    LEGACY_BLOB_SUPPORT_STATE,
    LEGACY_IMPORTED_AT,
    create_campaign_state_tables,
    create_content_metadata_tables,
    get_connection,
    _required_text,
    _stable_payload_hash,
    _table_exists,
)


def _content_record_from_trait_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = _parse_payload(row["data_json"])
    source_book = _normalize_source_book(
        payload.get("source_book"), default=_DEFAULT_RULES_SOURCE_BOOK
    )
    content_id = _coerce_existing_content_id(payload.get("content_id"))
    if content_id is None:
        content_id = _canonical_content_id("trait", row["id"], source_book)
    canonical_payload = payload if payload else {"name": row["name"]}
    source_path = str(payload.get("source_path") or f"sqlite:traits/{row['id']}")
    imported_at = str(payload.get("imported_at") or LEGACY_IMPORTED_AT)
    return {
        "content_id": content_id,
        "content_type": "trait",
        "source_book": source_book,
        "schema_version": str(payload.get("schema_version") or _GLOBAL_CONTENT_SCHEMA_VERSION),
        "source_path": source_path,
        "source_hash": _stable_payload_hash(canonical_payload),
        "canonicalization_hash": _stable_payload_hash(canonical_payload),
        "payload_json": canonical_payload,
        "imported_at": imported_at,
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
    canonical_payload = (
        payload if payload else {"character_id": row["character_id"], "name": row["name"]}
    )
    source_path = str(payload.get("source_path") or f"sqlite:characters/{row['character_id']}")
    imported_at = str(payload.get("imported_at") or LEGACY_IMPORTED_AT)
    return {
        "content_id": content_id,
        "content_type": "character",
        "source_book": source_book,
        "schema_version": str(payload.get("schema_version") or _GLOBAL_CONTENT_SCHEMA_VERSION),
        "source_path": source_path,
        "source_hash": _stable_payload_hash(canonical_payload),
        "canonicalization_hash": _stable_payload_hash(canonical_payload),
        "payload_json": canonical_payload,
        "imported_at": imported_at,
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
    canonical_payload = (
        payload if payload else {"identity": {"enemy_id": row["enemy_id"], "name": row["name"]}}
    )
    source_path = str(payload.get("source_path") or f"sqlite:enemies/{row['enemy_id']}")
    imported_at = str(payload.get("imported_at") or LEGACY_IMPORTED_AT)
    return {
        "content_id": content_id,
        "content_type": "monster",
        "source_book": source_book,
        "schema_version": str(payload.get("schema_version") or _GLOBAL_CONTENT_SCHEMA_VERSION),
        "source_path": source_path,
        "source_hash": _stable_payload_hash(canonical_payload),
        "canonicalization_hash": _stable_payload_hash(canonical_payload),
        "payload_json": canonical_payload,
        "imported_at": imported_at,
    }


def _collect_content_records(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    if _table_exists(cursor.connection, "traits"):
        for row in cursor.execute("SELECT id, name, data_json FROM traits").fetchall():
            records.append(_content_record_from_trait_row(row))

    if _table_exists(cursor.connection, "characters"):
        for row in cursor.execute(
            "SELECT character_id, name, ac, max_hp, initiative_mod, data_json FROM characters"
        ).fetchall():
            records.append(_content_record_from_character_row(row))

    if _table_exists(cursor.connection, "enemies"):
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
        upsert_content_record(
            cursor.connection,
            content_id=str(record["content_id"]),
            content_type=str(record["content_type"]),
            source_book=str(record["source_book"]),
            schema_version=str(record["schema_version"]),
            source_path=str(record["source_path"]),
            source_hash=str(record["source_hash"]),
            canonicalization_hash=str(record["canonicalization_hash"]),
            payload_json=record["payload_json"],
            imported_at=str(record["imported_at"]),
        )
    return len(records)


def backfill_content_records() -> int:
    """Backfill canonical content_records entries from traits, characters, and enemies."""
    with get_connection() as conn:
        cursor = conn.cursor()
        create_content_metadata_tables(conn)
        count = _upsert_content_records(cursor, _collect_content_records(cursor))
        conn.commit()
        return count


def backfill_legacy_blob_content(conn: sqlite3.Connection) -> dict[str, int]:
    """Backfill legacy JSON/blob rows into canonical metadata + state tables."""
    create_content_metadata_tables(conn)
    create_campaign_state_tables(conn)

    existing_ids: set[str] = set()
    if _table_exists(conn, CONTENT_RECORDS_TABLE):
        existing_ids = {
            str(row[0])
            for row in conn.execute(f"SELECT content_id FROM {CONTENT_RECORDS_TABLE}").fetchall()
        }

    stats = {
        "migrated_records": 0,
        "skipped_existing": 0,
        "invalid_payloads": 0,
    }
    for row in _legacy_blob_rows(conn):
        content_id = str(row["content_id"])
        if content_id in existing_ids:
            stats["skipped_existing"] += 1
            continue
        if bool(row.get("invalid_payload")):
            stats["invalid_payloads"] += 1
            continue

        upsert_content_record(
            conn,
            content_id=content_id,
            content_type=str(row["content_type"]),
            source_book=str(row["source_book"]),
            schema_version=str(row["schema_version"]),
            source_path=str(row["source_path"]),
            source_hash=str(row["source_hash"]),
            canonicalization_hash=str(row["canonicalization_hash"]),
            payload_json=row["payload_json"],
            imported_at=str(row["imported_at"]),
        )
        upsert_content_capability(
            conn,
            content_id=content_id,
            content_type=str(row["content_type"]),
            support_state=str(row["support_state"]),
            unsupported_reason=None,
            last_verified_commit=str(row["last_verified_commit"]),
        )
        existing_ids.add(content_id)
        stats["migrated_records"] += 1
    return stats


def rollback_legacy_blob_backfill(conn: sqlite3.Connection) -> int:
    """Delete DBS-06 backfilled canonical rows from legacy blob source paths."""
    if not _table_exists(conn, CONTENT_RECORDS_TABLE):
        return 0

    to_delete = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM {CONTENT_RECORDS_TABLE}
            WHERE source_path LIKE ?
            """,
            (f"{LEGACY_BLOB_SOURCE_PREFIX}/%",),
        ).fetchone()[0]
    )
    if to_delete == 0:
        return 0

    conn.execute(
        f"DELETE FROM {CONTENT_RECORDS_TABLE} WHERE source_path LIKE ?",
        (f"{LEGACY_BLOB_SOURCE_PREFIX}/%",),
    )
    if _table_exists(conn, CONTENT_CAPABILITIES_TABLE):
        conn.execute(f"""
            DELETE FROM {CONTENT_CAPABILITIES_TABLE}
            WHERE content_id NOT IN (
                SELECT content_id FROM {CONTENT_RECORDS_TABLE}
            )
            """)
    return to_delete
