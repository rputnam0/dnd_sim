from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from dnd_sim import db as db_module

logger = logging.getLogger(__name__)


def _normalize_filter(
    value: str | None,
    *,
    field_name: str,
    lowercase: bool = False,
) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty when provided")
    return normalized.lower() if lowercase else normalized


def _normalize_limit(limit: int | None) -> int | None:
    if limit is None:
        return None
    normalized = int(limit)
    if normalized <= 0:
        raise ValueError("limit must be >= 1 when provided")
    return normalized


def _record_matches_filter(record_value: Any, filter_value: str | None, *, lowercase: bool) -> bool:
    if filter_value is None:
        return True
    if record_value is None:
        return False
    left = str(record_value).strip()
    right = str(filter_value).strip()
    if lowercase:
        return left.lower() == right.lower()
    return left == right


def query_content_records(
    conn: sqlite3.Connection,
    *,
    content_id: str | None = None,
    content_type: str | None = None,
    support_state: str | None = None,
    unsupported_reason: str | None = None,
    source_book: str | None = None,
    schema_version: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Query canonical lineage/capability records with deterministic ordering."""
    normalized_content_id = _normalize_filter(content_id, field_name="content_id")
    normalized_content_type = _normalize_filter(
        content_type,
        field_name="content_type",
        lowercase=True,
    )
    normalized_support_state = _normalize_filter(
        support_state,
        field_name="support_state",
        lowercase=True,
    )
    normalized_unsupported_reason = _normalize_filter(
        unsupported_reason,
        field_name="unsupported_reason",
        lowercase=True,
    )
    normalized_source_book = _normalize_filter(
        source_book,
        field_name="source_book",
        lowercase=True,
    )
    normalized_schema_version = _normalize_filter(
        schema_version,
        field_name="schema_version",
        lowercase=True,
    )
    normalized_limit = _normalize_limit(limit)

    if normalized_unsupported_reason is not None and (
        normalized_support_state is not None and normalized_support_state != "blocked"
    ):
        raise ValueError(
            "unsupported_reason filter requires support_state='blocked' or omitted support_state"
        )

    records = db_module.fetch_content_records_compatible(conn, content_type=normalized_content_type)
    filtered: list[dict[str, Any]] = []
    for record in records:
        if not _record_matches_filter(
            record.get("content_id"), normalized_content_id, lowercase=False
        ):
            continue
        if not _record_matches_filter(
            record.get("support_state"),
            normalized_support_state,
            lowercase=True,
        ):
            continue
        if not _record_matches_filter(
            record.get("unsupported_reason"),
            normalized_unsupported_reason,
            lowercase=True,
        ):
            continue
        if not _record_matches_filter(
            record.get("source_book"),
            normalized_source_book,
            lowercase=True,
        ):
            continue
        if not _record_matches_filter(
            record.get("schema_version"),
            normalized_schema_version,
            lowercase=True,
        ):
            continue
        filtered.append(record)
        if normalized_limit is not None and len(filtered) >= normalized_limit:
            break
    return filtered


def summarize_content_coverage(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize support-state and schema-version coverage for query results."""
    support_counts: dict[str, int] = {}
    schema_counts: dict[str, int] = {}

    for record in records:
        support_state = str(record.get("support_state") or "unknown").strip().lower()
        schema_version = str(record.get("schema_version") or "unknown").strip().lower()
        support_counts[support_state] = support_counts.get(support_state, 0) + 1
        schema_counts[schema_version] = schema_counts.get(schema_version, 0) + 1

    return {
        "records_total": len(records),
        "support_state_counts": [
            {"support_state": support_state, "count": support_counts[support_state]}
            for support_state in sorted(support_counts)
        ],
        "schema_version_counts": [
            {"schema_version": schema_version, "count": schema_counts[schema_version]}
            for schema_version in sorted(schema_counts)
        ],
    }


def query_content_records_from_db(
    *,
    db_path: Path | str | None = None,
    content_id: str | None = None,
    content_type: str | None = None,
    support_state: str | None = None,
    unsupported_reason: str | None = None,
    source_book: str | None = None,
    schema_version: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    target_path = Path(db_path) if db_path is not None else db_module.get_db_path()
    if not target_path.exists():
        raise FileNotFoundError(f"Database file not found: {target_path}")

    with sqlite3.connect(target_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return query_content_records(
            conn,
            content_id=content_id,
            content_type=content_type,
            support_state=support_state,
            unsupported_reason=unsupported_reason,
            source_book=source_book,
            schema_version=schema_version,
            limit=limit,
        )
