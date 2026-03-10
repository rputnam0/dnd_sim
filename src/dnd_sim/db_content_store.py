import json
import re
import sqlite3
from typing import Any

from dnd_sim.db_schema import (
    CONTENT_CAPABILITIES_TABLE,
    CONTENT_RECORDS_TABLE,
    LEGACY_BLOB_LAST_VERIFIED_COMMIT,
    LEGACY_BLOB_SCHEMA_VERSION,
    LEGACY_BLOB_SOURCE_PREFIX,
    LEGACY_BLOB_SUPPORT_STATE,
    LEGACY_BLOB_TABLE_SPECS,
    LEGACY_IMPORTED_AT,
    _canonical_json_text,
    _required_text,
    _stable_payload_hash,
    _table_exists,
)

_CONTENT_ID_RE = re.compile(r"^(?P<kind>[a-z_]+):(?P<slug>[a-z0-9_]+)\|(?P<source>[A-Z0-9_]+)$")
_CONTENT_SLUG_RE = re.compile(r"[^a-z0-9]+")
_GLOBAL_CONTENT_SCHEMA_VERSION = "wld11.v1"
_DEFAULT_RULES_SOURCE_BOOK = "2014"


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


def _canonical_legacy_content_id(*, content_type: str, legacy_id: str) -> str:
    normalized_type = _required_text(content_type, field_name="content_type").lower()
    normalized_id = _required_text(legacy_id, field_name="legacy_id")
    if normalized_id.startswith(f"{normalized_type}:"):
        return normalized_id
    return f"{normalized_type}:{normalized_id}"


def _infer_source_book(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("source_book", "source", "book"):
            candidate = payload.get(key)
            if isinstance(candidate, str):
                normalized = candidate.strip()
                if normalized:
                    return normalized
        source_payload = payload.get("source")
        if isinstance(source_payload, dict):
            for key in ("book", "source_book", "id", "abbr", "code"):
                candidate = source_payload.get(key)
                if isinstance(candidate, str):
                    normalized = candidate.strip()
                    if normalized:
                        return normalized
    return "legacy_blob"


def _safe_json_loads(raw_payload: str) -> Any | None:
    try:
        return json.loads(raw_payload)
    except json.JSONDecodeError:
        return None


def _legacy_spec_for_content_type(content_type: str) -> tuple[str, str, str] | None:
    normalized_type = _required_text(content_type, field_name="content_type").lower()
    for table_name, id_column, legacy_type in LEGACY_BLOB_TABLE_SPECS:
        if normalized_type == legacy_type:
            return table_name, id_column, legacy_type
    return None


def _canonical_record_payload(
    row: sqlite3.Row | tuple[Any, ...],
) -> dict[str, Any]:
    payload_raw = str(row[7])
    payload_json = _safe_json_loads(payload_raw)
    return {
        "content_id": str(row[0]),
        "content_type": str(row[1]),
        "source_book": str(row[2]),
        "schema_version": str(row[3]),
        "source_path": str(row[4]),
        "source_hash": str(row[5]),
        "canonicalization_hash": str(row[6]),
        "payload_json": payload_json if payload_json is not None else payload_raw,
        "imported_at": str(row[8]),
    }


def _canonical_capability_payload(
    row: sqlite3.Row | tuple[Any, ...] | None,
) -> dict[str, Any]:
    if row is None:
        return {
            "support_state": None,
            "unsupported_reason": None,
            "last_verified_commit": None,
        }
    return {
        "support_state": str(row[0]),
        "unsupported_reason": None if row[1] is None else str(row[1]),
        "last_verified_commit": str(row[2]),
    }


def _legacy_blob_rows(
    conn: sqlite3.Connection,
    *,
    content_type: str | None = None,
) -> list[dict[str, Any]]:
    normalized_filter = None if content_type is None else content_type.strip().lower()
    rows: list[dict[str, Any]] = []
    for table_name, id_column, legacy_type in LEGACY_BLOB_TABLE_SPECS:
        if normalized_filter is not None and legacy_type != normalized_filter:
            continue
        if not _table_exists(conn, table_name):
            continue
        for legacy_id, raw_payload in conn.execute(f"""
            SELECT {id_column}, data_json
            FROM {table_name}
            ORDER BY {id_column}
            """).fetchall():
            normalized_legacy_id = _required_text(
                str(legacy_id),
                field_name=f"{table_name}.{id_column}",
            )
            payload_raw = str(raw_payload)
            payload_json = _safe_json_loads(payload_raw)
            if payload_json is None:
                rows.append(
                    {
                        "content_id": _canonical_legacy_content_id(
                            content_type=legacy_type,
                            legacy_id=normalized_legacy_id,
                        ),
                        "content_type": legacy_type,
                        "source_book": "legacy_blob",
                        "schema_version": LEGACY_BLOB_SCHEMA_VERSION,
                        "source_path": (
                            f"{LEGACY_BLOB_SOURCE_PREFIX}/{table_name}/{normalized_legacy_id}"
                        ),
                        "source_hash": _stable_payload_hash(payload_raw),
                        "canonicalization_hash": _stable_payload_hash(payload_raw),
                        "payload_json": payload_raw,
                        "imported_at": LEGACY_IMPORTED_AT,
                        "support_state": LEGACY_BLOB_SUPPORT_STATE,
                        "unsupported_reason": None,
                        "last_verified_commit": LEGACY_BLOB_LAST_VERIFIED_COMMIT,
                        "storage_origin": "legacy_blob",
                        "invalid_payload": True,
                    }
                )
                continue

            rows.append(
                {
                    "content_id": _canonical_legacy_content_id(
                        content_type=legacy_type,
                        legacy_id=normalized_legacy_id,
                    ),
                    "content_type": legacy_type,
                    "source_book": _infer_source_book(payload_json),
                    "schema_version": LEGACY_BLOB_SCHEMA_VERSION,
                    "source_path": (
                        f"{LEGACY_BLOB_SOURCE_PREFIX}/{table_name}/{normalized_legacy_id}"
                    ),
                    "source_hash": _stable_payload_hash(payload_raw),
                    "canonicalization_hash": _stable_payload_hash(payload_json),
                    "payload_json": payload_json,
                    "imported_at": LEGACY_IMPORTED_AT,
                    "support_state": LEGACY_BLOB_SUPPORT_STATE,
                    "unsupported_reason": None,
                    "last_verified_commit": LEGACY_BLOB_LAST_VERIFIED_COMMIT,
                    "storage_origin": "legacy_blob",
                    "invalid_payload": False,
                }
            )
    return rows


def fetch_content_record_compatible(
    conn: sqlite3.Connection,
    *,
    content_id: str,
) -> dict[str, Any] | None:
    """Fetch a content record with canonical-first and legacy-blob fallback reads."""
    normalized_content_id = _required_text(content_id, field_name="content_id")

    if _table_exists(conn, CONTENT_RECORDS_TABLE):
        row = conn.execute(
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
            FROM {CONTENT_RECORDS_TABLE}
            WHERE content_id = ?
            """,
            (normalized_content_id,),
        ).fetchone()
        if row is not None:
            capability_row = None
            if _table_exists(conn, CONTENT_CAPABILITIES_TABLE):
                capability_row = conn.execute(
                    f"""
                    SELECT support_state, unsupported_reason, last_verified_commit
                    FROM {CONTENT_CAPABILITIES_TABLE}
                    WHERE content_id = ?
                    """,
                    (normalized_content_id,),
                ).fetchone()
            payload = _canonical_record_payload(row)
            payload.update(_canonical_capability_payload(capability_row))
            payload["storage_origin"] = "canonical"
            return payload

    if ":" not in normalized_content_id:
        return None
    content_type, legacy_id = normalized_content_id.split(":", maxsplit=1)
    spec = _legacy_spec_for_content_type(content_type)
    if spec is None:
        return None

    table_name, id_column, legacy_type = spec
    if not _table_exists(conn, table_name):
        return None

    row = conn.execute(
        f"""
        SELECT {id_column}, data_json
        FROM {table_name}
        WHERE {id_column} = ?
        """,
        (legacy_id,),
    ).fetchone()
    if row is None:
        return None

    payload_raw = str(row[1])
    payload_json = _safe_json_loads(payload_raw)
    if payload_json is None:
        return None

    source_path = f"{LEGACY_BLOB_SOURCE_PREFIX}/{table_name}/{legacy_id}"
    return {
        "content_id": normalized_content_id,
        "content_type": legacy_type,
        "source_book": _infer_source_book(payload_json),
        "schema_version": LEGACY_BLOB_SCHEMA_VERSION,
        "source_path": source_path,
        "source_hash": _stable_payload_hash(payload_raw),
        "canonicalization_hash": _stable_payload_hash(payload_json),
        "payload_json": payload_json,
        "imported_at": LEGACY_IMPORTED_AT,
        "support_state": LEGACY_BLOB_SUPPORT_STATE,
        "unsupported_reason": None,
        "last_verified_commit": LEGACY_BLOB_LAST_VERIFIED_COMMIT,
        "storage_origin": "legacy_blob",
    }


def fetch_content_records_compatible(
    conn: sqlite3.Connection,
    *,
    content_type: str | None = None,
) -> list[dict[str, Any]]:
    """List canonical content rows plus unmigrated legacy blob rows deterministically."""
    normalized_filter = None if content_type is None else content_type.strip().lower()
    records_by_id: dict[str, dict[str, Any]] = {}

    if _table_exists(conn, CONTENT_RECORDS_TABLE):
        params: tuple[Any, ...] = ()
        where_clause = ""
        if normalized_filter is not None:
            where_clause = "WHERE content_type = ?"
            params = (normalized_filter,)
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
            FROM {CONTENT_RECORDS_TABLE}
            {where_clause}
            """,
            params,
        ).fetchall()
        for row in rows:
            content_id_value = str(row[0])
            capability_row = None
            if _table_exists(conn, CONTENT_CAPABILITIES_TABLE):
                capability_row = conn.execute(
                    f"""
                    SELECT support_state, unsupported_reason, last_verified_commit
                    FROM {CONTENT_CAPABILITIES_TABLE}
                    WHERE content_id = ?
                    """,
                    (content_id_value,),
                ).fetchone()
            payload = _canonical_record_payload(row)
            payload.update(_canonical_capability_payload(capability_row))
            payload["storage_origin"] = "canonical"
            records_by_id[content_id_value] = payload

    for row in _legacy_blob_rows(conn, content_type=normalized_filter):
        content_id_value = str(row["content_id"])
        if content_id_value in records_by_id:
            continue
        if bool(row.get("invalid_payload")):
            continue
        payload = dict(row)
        payload.pop("invalid_payload", None)
        records_by_id[content_id_value] = payload

    return sorted(
        records_by_id.values(),
        key=lambda row: (
            str(row.get("content_type", "")).casefold(),
            str(row.get("content_id", "")).casefold(),
        ),
    )
