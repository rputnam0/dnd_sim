from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from dnd_sim import db_schema
from dnd_sim.snapshot_codecs import (
    _campaign_snapshot_hash,
    _canonical_json_text,
    _encounter_snapshot_hash,
    _faction_snapshot_hash,
    _normalize_campaign_like_snapshot,
    _normalize_faction_snapshot,
    _normalize_world_snapshot,
    _parse_json_column,
    _required_text,
    _world_snapshot_hash,
)

_CAMPAIGN_SNAPSHOT_VERSION = "campaign_snapshot.v1"
_ENCOUNTER_SNAPSHOT_VERSION = "encounter_snapshot.v1"
_WORLD_SNAPSHOT_VERSION = "world_snapshot.v1"
_FACTION_SNAPSHOT_VERSION = "faction_snapshot.v1"


def save_campaign_snapshot(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    snapshot: Mapping[str, Any],
) -> None:
    db_schema.create_campaign_state_tables(conn)
    normalized_campaign_id = _required_text(campaign_id, field_name="campaign_id")
    normalized_snapshot = _normalize_campaign_like_snapshot(
        snapshot, snapshot_name="campaign snapshot"
    )
    snapshot_hash = _campaign_snapshot_hash(
        normalized_campaign_id,
        _CAMPAIGN_SNAPSHOT_VERSION,
        normalized_snapshot,
    )
    updated_at = datetime.now(UTC).isoformat()
    conn.execute(
        f"""
        INSERT INTO {db_schema.CAMPAIGN_STATES_TABLE} (
            campaign_id,
            snapshot_version,
            party_state_json,
            resources_json,
            active_effects_json,
            initiative_context_json,
            replay_bundle_id,
            snapshot_hash,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(campaign_id) DO UPDATE SET
            snapshot_version = excluded.snapshot_version,
            party_state_json = excluded.party_state_json,
            resources_json = excluded.resources_json,
            active_effects_json = excluded.active_effects_json,
            initiative_context_json = excluded.initiative_context_json,
            replay_bundle_id = excluded.replay_bundle_id,
            snapshot_hash = excluded.snapshot_hash,
            updated_at = excluded.updated_at
        """,
        (
            normalized_campaign_id,
            _CAMPAIGN_SNAPSHOT_VERSION,
            _canonical_json_text(normalized_snapshot["party_state"]),
            _canonical_json_text(normalized_snapshot["resources"]),
            _canonical_json_text(normalized_snapshot["active_effects"]),
            _canonical_json_text(normalized_snapshot["initiative_context"]),
            normalized_snapshot["replay_bundle_id"],
            snapshot_hash,
            updated_at,
        ),
    )
    conn.commit()


def load_campaign_snapshot(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
) -> dict[str, Any]:
    normalized_campaign_id = _required_text(campaign_id, field_name="campaign_id")
    row = conn.execute(
        f"""
        SELECT
            campaign_id,
            party_state_json,
            resources_json,
            active_effects_json,
            initiative_context_json,
            replay_bundle_id,
            snapshot_hash
        FROM {db_schema.CAMPAIGN_STATES_TABLE}
        WHERE campaign_id = ?
        """,
        (normalized_campaign_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"campaign snapshot not found: {normalized_campaign_id}")

    snapshot = {
        "party_state": _parse_json_column(
            row["party_state_json"], column_name="party_state_json", expected=dict
        ),
        "resources": _parse_json_column(
            row["resources_json"], column_name="resources_json", expected=dict
        ),
        "active_effects": _parse_json_column(
            row["active_effects_json"],
            column_name="active_effects_json",
            expected=list,
        ),
        "initiative_context": _parse_json_column(
            row["initiative_context_json"],
            column_name="initiative_context_json",
            expected=dict,
        ),
        "replay_bundle_id": row["replay_bundle_id"],
    }
    normalized_snapshot = _normalize_campaign_like_snapshot(
        snapshot, snapshot_name="campaign snapshot"
    )
    expected_hash = _campaign_snapshot_hash(
        normalized_campaign_id,
        _CAMPAIGN_SNAPSHOT_VERSION,
        normalized_snapshot,
    )
    if str(row["snapshot_hash"]) != expected_hash:
        raise ValueError("snapshot hash mismatch")

    return {
        "campaign_id": normalized_campaign_id,
        **normalized_snapshot,
    }


def save_encounter_snapshot(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    encounter_id: str,
    snapshot: Mapping[str, Any],
) -> None:
    db_schema.create_campaign_state_tables(conn)
    normalized_campaign_id = _required_text(campaign_id, field_name="campaign_id")
    normalized_encounter_id = _required_text(encounter_id, field_name="encounter_id")
    normalized_snapshot = _normalize_campaign_like_snapshot(
        snapshot, snapshot_name="encounter snapshot"
    )
    snapshot_hash = _encounter_snapshot_hash(
        normalized_campaign_id,
        normalized_encounter_id,
        _ENCOUNTER_SNAPSHOT_VERSION,
        normalized_snapshot,
    )
    updated_at = datetime.now(UTC).isoformat()
    conn.execute(
        f"""
        INSERT INTO {db_schema.ENCOUNTER_STATES_TABLE} (
            campaign_id,
            encounter_id,
            snapshot_version,
            party_state_json,
            resources_json,
            active_effects_json,
            initiative_context_json,
            replay_bundle_id,
            snapshot_hash,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(campaign_id, encounter_id) DO UPDATE SET
            snapshot_version = excluded.snapshot_version,
            party_state_json = excluded.party_state_json,
            resources_json = excluded.resources_json,
            active_effects_json = excluded.active_effects_json,
            initiative_context_json = excluded.initiative_context_json,
            replay_bundle_id = excluded.replay_bundle_id,
            snapshot_hash = excluded.snapshot_hash,
            updated_at = excluded.updated_at
        """,
        (
            normalized_campaign_id,
            normalized_encounter_id,
            _ENCOUNTER_SNAPSHOT_VERSION,
            _canonical_json_text(normalized_snapshot["party_state"]),
            _canonical_json_text(normalized_snapshot["resources"]),
            _canonical_json_text(normalized_snapshot["active_effects"]),
            _canonical_json_text(normalized_snapshot["initiative_context"]),
            normalized_snapshot["replay_bundle_id"],
            snapshot_hash,
            updated_at,
        ),
    )
    conn.commit()


def load_encounter_snapshot(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    encounter_id: str,
) -> dict[str, Any]:
    normalized_campaign_id = _required_text(campaign_id, field_name="campaign_id")
    normalized_encounter_id = _required_text(encounter_id, field_name="encounter_id")
    row = conn.execute(
        f"""
        SELECT
            campaign_id,
            encounter_id,
            party_state_json,
            resources_json,
            active_effects_json,
            initiative_context_json,
            replay_bundle_id,
            snapshot_hash
        FROM {db_schema.ENCOUNTER_STATES_TABLE}
        WHERE campaign_id = ? AND encounter_id = ?
        """,
        (normalized_campaign_id, normalized_encounter_id),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"encounter snapshot not found: {normalized_campaign_id}/{normalized_encounter_id}"
        )

    snapshot = {
        "party_state": _parse_json_column(
            row["party_state_json"], column_name="party_state_json", expected=dict
        ),
        "resources": _parse_json_column(
            row["resources_json"], column_name="resources_json", expected=dict
        ),
        "active_effects": _parse_json_column(
            row["active_effects_json"],
            column_name="active_effects_json",
            expected=list,
        ),
        "initiative_context": _parse_json_column(
            row["initiative_context_json"],
            column_name="initiative_context_json",
            expected=dict,
        ),
        "replay_bundle_id": row["replay_bundle_id"],
    }
    normalized_snapshot = _normalize_campaign_like_snapshot(
        snapshot, snapshot_name="encounter snapshot"
    )
    expected_hash = _encounter_snapshot_hash(
        normalized_campaign_id,
        normalized_encounter_id,
        _ENCOUNTER_SNAPSHOT_VERSION,
        normalized_snapshot,
    )
    if str(row["snapshot_hash"]) != expected_hash:
        raise ValueError("snapshot hash mismatch")

    return {
        "campaign_id": normalized_campaign_id,
        "encounter_id": normalized_encounter_id,
        **normalized_snapshot,
    }


def save_world_snapshot(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    snapshot: Mapping[str, Any],
) -> None:
    db_schema.create_campaign_state_tables(conn)
    normalized_campaign_id = _required_text(campaign_id, field_name="campaign_id")
    normalized_snapshot = _normalize_world_snapshot(snapshot)
    snapshot_hash = _world_snapshot_hash(
        normalized_campaign_id,
        _WORLD_SNAPSHOT_VERSION,
        normalized_snapshot,
    )
    updated_at = datetime.now(UTC).isoformat()
    conn.execute(
        f"""
        INSERT INTO {db_schema.WORLD_STATES_TABLE} (
            campaign_id,
            snapshot_version,
            world_flags_json,
            objectives_json,
            map_state_json,
            encounter_state_json,
            replay_bundle_id,
            snapshot_hash,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(campaign_id) DO UPDATE SET
            snapshot_version = excluded.snapshot_version,
            world_flags_json = excluded.world_flags_json,
            objectives_json = excluded.objectives_json,
            map_state_json = excluded.map_state_json,
            encounter_state_json = excluded.encounter_state_json,
            replay_bundle_id = excluded.replay_bundle_id,
            snapshot_hash = excluded.snapshot_hash,
            updated_at = excluded.updated_at
        """,
        (
            normalized_campaign_id,
            _WORLD_SNAPSHOT_VERSION,
            _canonical_json_text(normalized_snapshot["world_flags"]),
            _canonical_json_text(normalized_snapshot["objectives"]),
            _canonical_json_text(normalized_snapshot["map_state"]),
            _canonical_json_text(normalized_snapshot["encounter_state"]),
            normalized_snapshot["replay_bundle_id"],
            snapshot_hash,
            updated_at,
        ),
    )
    conn.commit()


def load_world_snapshot(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
) -> dict[str, Any]:
    normalized_campaign_id = _required_text(campaign_id, field_name="campaign_id")
    row = conn.execute(
        f"""
        SELECT
            campaign_id,
            world_flags_json,
            objectives_json,
            map_state_json,
            encounter_state_json,
            replay_bundle_id,
            snapshot_hash
        FROM {db_schema.WORLD_STATES_TABLE}
        WHERE campaign_id = ?
        """,
        (normalized_campaign_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"world snapshot not found: {normalized_campaign_id}")

    snapshot = {
        "world_flags": _parse_json_column(
            row["world_flags_json"], column_name="world_flags_json", expected=dict
        ),
        "objectives": _parse_json_column(
            row["objectives_json"], column_name="objectives_json", expected=dict
        ),
        "map_state": _parse_json_column(
            row["map_state_json"], column_name="map_state_json", expected=dict
        ),
        "encounter_state": _parse_json_column(
            row["encounter_state_json"],
            column_name="encounter_state_json",
            expected=dict,
        ),
        "replay_bundle_id": row["replay_bundle_id"],
    }
    normalized_snapshot = _normalize_world_snapshot(snapshot)
    expected_hash = _world_snapshot_hash(
        normalized_campaign_id,
        _WORLD_SNAPSHOT_VERSION,
        normalized_snapshot,
    )
    if str(row["snapshot_hash"]) != expected_hash:
        raise ValueError("snapshot hash mismatch")

    return {
        "campaign_id": normalized_campaign_id,
        **normalized_snapshot,
    }


def save_faction_snapshot(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    faction_id: str,
    snapshot: Mapping[str, Any],
) -> None:
    db_schema.create_campaign_state_tables(conn)
    normalized_campaign_id = _required_text(campaign_id, field_name="campaign_id")
    normalized_faction_id = _required_text(faction_id, field_name="faction_id")
    normalized_snapshot = _normalize_faction_snapshot(snapshot)
    snapshot_hash = _faction_snapshot_hash(
        normalized_campaign_id,
        normalized_faction_id,
        _FACTION_SNAPSHOT_VERSION,
        normalized_snapshot,
    )
    updated_at = datetime.now(UTC).isoformat()
    conn.execute(
        f"""
        INSERT INTO {db_schema.FACTION_STATES_TABLE} (
            campaign_id,
            faction_id,
            snapshot_version,
            reputation_json,
            faction_state_json,
            snapshot_hash,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(campaign_id, faction_id) DO UPDATE SET
            snapshot_version = excluded.snapshot_version,
            reputation_json = excluded.reputation_json,
            faction_state_json = excluded.faction_state_json,
            snapshot_hash = excluded.snapshot_hash,
            updated_at = excluded.updated_at
        """,
        (
            normalized_campaign_id,
            normalized_faction_id,
            _FACTION_SNAPSHOT_VERSION,
            _canonical_json_text(normalized_snapshot["reputation"]),
            _canonical_json_text(normalized_snapshot["faction_state"]),
            snapshot_hash,
            updated_at,
        ),
    )
    conn.commit()


def load_faction_snapshot(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    faction_id: str,
) -> dict[str, Any]:
    normalized_campaign_id = _required_text(campaign_id, field_name="campaign_id")
    normalized_faction_id = _required_text(faction_id, field_name="faction_id")
    row = conn.execute(
        f"""
        SELECT
            campaign_id,
            faction_id,
            reputation_json,
            faction_state_json,
            snapshot_hash
        FROM {db_schema.FACTION_STATES_TABLE}
        WHERE campaign_id = ? AND faction_id = ?
        """,
        (normalized_campaign_id, normalized_faction_id),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"faction snapshot not found: {normalized_campaign_id}/{normalized_faction_id}"
        )

    snapshot = {
        "reputation": _parse_json_column(
            row["reputation_json"], column_name="reputation_json", expected=dict
        ),
        "faction_state": _parse_json_column(
            row["faction_state_json"],
            column_name="faction_state_json",
            expected=dict,
        ),
    }
    normalized_snapshot = _normalize_faction_snapshot(snapshot)
    expected_hash = _faction_snapshot_hash(
        normalized_campaign_id,
        normalized_faction_id,
        _FACTION_SNAPSHOT_VERSION,
        normalized_snapshot,
    )
    if str(row["snapshot_hash"]) != expected_hash:
        raise ValueError("snapshot hash mismatch")

    return {
        "campaign_id": normalized_campaign_id,
        "faction_id": normalized_faction_id,
        **normalized_snapshot,
    }
