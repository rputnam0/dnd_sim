from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Mapping
from typing import Any

from dnd_sim import db as db_module

logger = logging.getLogger(__name__)

SNAPSHOT_SCHEMA_VERSION = "1"
DEFAULT_UPDATED_AT = "1970-01-01T00:00:00+00:00"


def _required_text(value: Any, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _canonical_json_text(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _mapping_or_default(value: Any, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    return dict(value)


def _list_or_default(value: Any, *, field_name: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return list(value)


def _extract_replay_bundle_id(snapshot: dict[str, Any]) -> str | None:
    direct = _optional_text(snapshot.get("replay_bundle_id") or snapshot.get("replay_id"))
    if direct is not None:
        return direct
    replay = snapshot.get("replay")
    if not isinstance(replay, Mapping):
        return None
    return _optional_text(replay.get("bundle_id") or replay.get("replay_bundle_id"))


def _normalize_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        raise ValueError("snapshot must be a mapping")

    party_state = _mapping_or_default(
        snapshot.get("party_state", snapshot.get("party")),
        field_name="party_state",
    )
    resources = _mapping_or_default(
        snapshot.get("resources", snapshot.get("resource_state")),
        field_name="resources",
    )
    active_effects = _list_or_default(
        snapshot.get("active_effects", snapshot.get("effects")),
        field_name="active_effects",
    )
    initiative_context = _mapping_or_default(
        snapshot.get("initiative_context", snapshot.get("initiative")),
        field_name="initiative_context",
    )
    snapshot_version = _required_text(
        snapshot.get("snapshot_version", snapshot.get("version", SNAPSHOT_SCHEMA_VERSION)),
        field_name="snapshot_version",
    )
    replay_bundle_id = _extract_replay_bundle_id(dict(snapshot))
    updated_at = _required_text(
        snapshot.get("updated_at", DEFAULT_UPDATED_AT),
        field_name="updated_at",
    )

    return {
        "snapshot_version": snapshot_version,
        "party_state": party_state,
        "resources": resources,
        "active_effects": active_effects,
        "initiative_context": initiative_context,
        "replay_bundle_id": replay_bundle_id,
        "updated_at": updated_at,
    }


def _normalize_world_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        raise ValueError("snapshot must be a mapping")

    world_flags = _mapping_or_default(
        snapshot.get("world_flags", snapshot.get("flags")),
        field_name="world_flags",
    )
    objectives = _mapping_or_default(
        snapshot.get("objectives", snapshot.get("objective_state")),
        field_name="objectives",
    )
    map_state = _mapping_or_default(
        snapshot.get("map_state", snapshot.get("map")),
        field_name="map_state",
    )
    encounter_state = _mapping_or_default(
        snapshot.get("encounter_state", snapshot.get("encounter")),
        field_name="encounter_state",
    )
    snapshot_version = _required_text(
        snapshot.get("snapshot_version", snapshot.get("version", SNAPSHOT_SCHEMA_VERSION)),
        field_name="snapshot_version",
    )
    replay_bundle_id = _extract_replay_bundle_id(dict(snapshot))
    updated_at = _required_text(
        snapshot.get("updated_at", DEFAULT_UPDATED_AT),
        field_name="updated_at",
    )

    return {
        "snapshot_version": snapshot_version,
        "world_flags": world_flags,
        "objectives": objectives,
        "map_state": map_state,
        "encounter_state": encounter_state,
        "replay_bundle_id": replay_bundle_id,
        "updated_at": updated_at,
    }


def _normalize_faction_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        raise ValueError("snapshot must be a mapping")

    reputation = _mapping_or_default(
        snapshot.get("reputation", snapshot.get("reputations")),
        field_name="reputation",
    )
    faction_state = _mapping_or_default(
        snapshot.get("faction_state", snapshot.get("state")),
        field_name="faction_state",
    )
    snapshot_version = _required_text(
        snapshot.get("snapshot_version", snapshot.get("version", SNAPSHOT_SCHEMA_VERSION)),
        field_name="snapshot_version",
    )
    updated_at = _required_text(
        snapshot.get("updated_at", DEFAULT_UPDATED_AT),
        field_name="updated_at",
    )

    return {
        "snapshot_version": snapshot_version,
        "reputation": reputation,
        "faction_state": faction_state,
        "updated_at": updated_at,
    }


def _snapshot_hash(
    *,
    snapshot_version: str,
    party_state_json: str,
    resources_json: str,
    active_effects_json: str,
    initiative_context_json: str,
    replay_bundle_id: str | None,
) -> str:
    replay_part = replay_bundle_id or ""
    digest = hashlib.sha256(
        "|".join(
            [
                snapshot_version,
                party_state_json,
                resources_json,
                active_effects_json,
                initiative_context_json,
                replay_part,
            ]
        ).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def _world_snapshot_hash(
    *,
    snapshot_version: str,
    world_flags_json: str,
    objectives_json: str,
    map_state_json: str,
    encounter_state_json: str,
    replay_bundle_id: str | None,
) -> str:
    replay_part = replay_bundle_id or ""
    digest = hashlib.sha256(
        "|".join(
            [
                snapshot_version,
                world_flags_json,
                objectives_json,
                map_state_json,
                encounter_state_json,
                replay_part,
            ]
        ).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def _faction_snapshot_hash(
    *,
    snapshot_version: str,
    reputation_json: str,
    faction_state_json: str,
) -> str:
    digest = hashlib.sha256(
        "|".join(
            [
                snapshot_version,
                reputation_json,
                faction_state_json,
            ]
        ).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def _decode_json_field(row: sqlite3.Row, field_name: str) -> Any:
    raw = str(row[field_name])
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Corrupt snapshot payload in field '{field_name}'") from exc


def _row_to_snapshot(row: sqlite3.Row) -> dict[str, Any]:
    snapshot_version = _required_text(row["snapshot_version"], field_name="snapshot_version")
    party_state = _decode_json_field(row, "party_state_json")
    resources = _decode_json_field(row, "resources_json")
    active_effects = _decode_json_field(row, "active_effects_json")
    initiative_context = _decode_json_field(row, "initiative_context_json")
    replay_bundle_id = _optional_text(row["replay_bundle_id"])
    updated_at = _required_text(row["updated_at"], field_name="updated_at")
    persisted_hash = _required_text(row["snapshot_hash"], field_name="snapshot_hash")

    recalculated_hash = _snapshot_hash(
        snapshot_version=snapshot_version,
        party_state_json=_canonical_json_text(party_state),
        resources_json=_canonical_json_text(resources),
        active_effects_json=_canonical_json_text(active_effects),
        initiative_context_json=_canonical_json_text(initiative_context),
        replay_bundle_id=replay_bundle_id,
    )
    if persisted_hash != recalculated_hash:
        raise ValueError("Corrupt snapshot: snapshot hash mismatch")

    return {
        "snapshot_version": snapshot_version,
        "party_state": party_state,
        "resources": resources,
        "active_effects": active_effects,
        "initiative_context": initiative_context,
        "replay_bundle_id": replay_bundle_id,
        "snapshot_hash": persisted_hash,
        "updated_at": updated_at,
    }


def _row_to_world_snapshot(row: sqlite3.Row) -> dict[str, Any]:
    snapshot_version = _required_text(row["snapshot_version"], field_name="snapshot_version")
    world_flags = _decode_json_field(row, "world_flags_json")
    objectives = _decode_json_field(row, "objectives_json")
    map_state = _decode_json_field(row, "map_state_json")
    encounter_state = _decode_json_field(row, "encounter_state_json")
    replay_bundle_id = _optional_text(row["replay_bundle_id"])
    updated_at = _required_text(row["updated_at"], field_name="updated_at")
    persisted_hash = _required_text(row["snapshot_hash"], field_name="snapshot_hash")

    recalculated_hash = _world_snapshot_hash(
        snapshot_version=snapshot_version,
        world_flags_json=_canonical_json_text(world_flags),
        objectives_json=_canonical_json_text(objectives),
        map_state_json=_canonical_json_text(map_state),
        encounter_state_json=_canonical_json_text(encounter_state),
        replay_bundle_id=replay_bundle_id,
    )
    if persisted_hash != recalculated_hash:
        raise ValueError("Corrupt snapshot: snapshot hash mismatch")

    return {
        "snapshot_version": snapshot_version,
        "world_flags": world_flags,
        "objectives": objectives,
        "map_state": map_state,
        "encounter_state": encounter_state,
        "replay_bundle_id": replay_bundle_id,
        "snapshot_hash": persisted_hash,
        "updated_at": updated_at,
    }


def _row_to_faction_snapshot(row: sqlite3.Row) -> dict[str, Any]:
    snapshot_version = _required_text(row["snapshot_version"], field_name="snapshot_version")
    reputation = _decode_json_field(row, "reputation_json")
    faction_state = _decode_json_field(row, "faction_state_json")
    updated_at = _required_text(row["updated_at"], field_name="updated_at")
    persisted_hash = _required_text(row["snapshot_hash"], field_name="snapshot_hash")

    recalculated_hash = _faction_snapshot_hash(
        snapshot_version=snapshot_version,
        reputation_json=_canonical_json_text(reputation),
        faction_state_json=_canonical_json_text(faction_state),
    )
    if persisted_hash != recalculated_hash:
        raise ValueError("Corrupt snapshot: snapshot hash mismatch")

    return {
        "snapshot_version": snapshot_version,
        "reputation": reputation,
        "faction_state": faction_state,
        "snapshot_hash": persisted_hash,
        "updated_at": updated_at,
    }


def save_campaign_snapshot(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    snapshot: dict[str, Any],
) -> None:
    normalized = _normalize_snapshot(snapshot)
    db_module.create_campaign_state_tables(conn)

    party_state_json = _canonical_json_text(normalized["party_state"])
    resources_json = _canonical_json_text(normalized["resources"])
    active_effects_json = _canonical_json_text(normalized["active_effects"])
    initiative_context_json = _canonical_json_text(normalized["initiative_context"])
    snapshot_hash = _snapshot_hash(
        snapshot_version=normalized["snapshot_version"],
        party_state_json=party_state_json,
        resources_json=resources_json,
        active_effects_json=active_effects_json,
        initiative_context_json=initiative_context_json,
        replay_bundle_id=normalized["replay_bundle_id"],
    )

    conn.execute(
        """
        INSERT INTO campaign_states (
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
            snapshot_version=excluded.snapshot_version,
            party_state_json=excluded.party_state_json,
            resources_json=excluded.resources_json,
            active_effects_json=excluded.active_effects_json,
            initiative_context_json=excluded.initiative_context_json,
            replay_bundle_id=excluded.replay_bundle_id,
            snapshot_hash=excluded.snapshot_hash,
            updated_at=excluded.updated_at
        """,
        (
            _required_text(campaign_id, field_name="campaign_id"),
            normalized["snapshot_version"],
            party_state_json,
            resources_json,
            active_effects_json,
            initiative_context_json,
            normalized["replay_bundle_id"],
            snapshot_hash,
            normalized["updated_at"],
        ),
    )


def load_campaign_snapshot(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM campaign_states WHERE campaign_id = ?",
        (_required_text(campaign_id, field_name="campaign_id"),),
    ).fetchone()
    if row is None:
        raise KeyError(f"Unknown campaign_id={campaign_id}")

    snapshot = _row_to_snapshot(row)
    snapshot["campaign_id"] = str(row["campaign_id"])
    return snapshot


def save_encounter_snapshot(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    encounter_id: str,
    snapshot: dict[str, Any],
) -> None:
    normalized = _normalize_snapshot(snapshot)
    db_module.create_campaign_state_tables(conn)

    party_state_json = _canonical_json_text(normalized["party_state"])
    resources_json = _canonical_json_text(normalized["resources"])
    active_effects_json = _canonical_json_text(normalized["active_effects"])
    initiative_context_json = _canonical_json_text(normalized["initiative_context"])
    snapshot_hash = _snapshot_hash(
        snapshot_version=normalized["snapshot_version"],
        party_state_json=party_state_json,
        resources_json=resources_json,
        active_effects_json=active_effects_json,
        initiative_context_json=initiative_context_json,
        replay_bundle_id=normalized["replay_bundle_id"],
    )

    conn.execute(
        """
        INSERT INTO encounter_states (
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
            snapshot_version=excluded.snapshot_version,
            party_state_json=excluded.party_state_json,
            resources_json=excluded.resources_json,
            active_effects_json=excluded.active_effects_json,
            initiative_context_json=excluded.initiative_context_json,
            replay_bundle_id=excluded.replay_bundle_id,
            snapshot_hash=excluded.snapshot_hash,
            updated_at=excluded.updated_at
        """,
        (
            _required_text(campaign_id, field_name="campaign_id"),
            _required_text(encounter_id, field_name="encounter_id"),
            normalized["snapshot_version"],
            party_state_json,
            resources_json,
            active_effects_json,
            initiative_context_json,
            normalized["replay_bundle_id"],
            snapshot_hash,
            normalized["updated_at"],
        ),
    )


def load_encounter_snapshot(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    encounter_id: str,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT * FROM encounter_states
        WHERE campaign_id = ? AND encounter_id = ?
        """,
        (
            _required_text(campaign_id, field_name="campaign_id"),
            _required_text(encounter_id, field_name="encounter_id"),
        ),
    ).fetchone()
    if row is None:
        raise KeyError(
            f"Unknown encounter state campaign_id={campaign_id} encounter_id={encounter_id}"
        )

    snapshot = _row_to_snapshot(row)
    snapshot["campaign_id"] = str(row["campaign_id"])
    snapshot["encounter_id"] = str(row["encounter_id"])
    return snapshot


def save_world_snapshot(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    snapshot: dict[str, Any],
) -> None:
    normalized = _normalize_world_snapshot(snapshot)
    db_module.create_campaign_state_tables(conn)

    world_flags_json = _canonical_json_text(normalized["world_flags"])
    objectives_json = _canonical_json_text(normalized["objectives"])
    map_state_json = _canonical_json_text(normalized["map_state"])
    encounter_state_json = _canonical_json_text(normalized["encounter_state"])
    snapshot_hash = _world_snapshot_hash(
        snapshot_version=normalized["snapshot_version"],
        world_flags_json=world_flags_json,
        objectives_json=objectives_json,
        map_state_json=map_state_json,
        encounter_state_json=encounter_state_json,
        replay_bundle_id=normalized["replay_bundle_id"],
    )

    conn.execute(
        """
        INSERT INTO world_states (
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
            snapshot_version=excluded.snapshot_version,
            world_flags_json=excluded.world_flags_json,
            objectives_json=excluded.objectives_json,
            map_state_json=excluded.map_state_json,
            encounter_state_json=excluded.encounter_state_json,
            replay_bundle_id=excluded.replay_bundle_id,
            snapshot_hash=excluded.snapshot_hash,
            updated_at=excluded.updated_at
        """,
        (
            _required_text(campaign_id, field_name="campaign_id"),
            normalized["snapshot_version"],
            world_flags_json,
            objectives_json,
            map_state_json,
            encounter_state_json,
            normalized["replay_bundle_id"],
            snapshot_hash,
            normalized["updated_at"],
        ),
    )


def load_world_snapshot(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM world_states WHERE campaign_id = ?",
        (_required_text(campaign_id, field_name="campaign_id"),),
    ).fetchone()
    if row is None:
        raise KeyError(f"Unknown world state campaign_id={campaign_id}")

    snapshot = _row_to_world_snapshot(row)
    snapshot["campaign_id"] = str(row["campaign_id"])
    return snapshot


def save_faction_snapshot(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    faction_id: str,
    snapshot: dict[str, Any],
) -> None:
    normalized = _normalize_faction_snapshot(snapshot)
    db_module.create_campaign_state_tables(conn)

    reputation_json = _canonical_json_text(normalized["reputation"])
    faction_state_json = _canonical_json_text(normalized["faction_state"])
    snapshot_hash = _faction_snapshot_hash(
        snapshot_version=normalized["snapshot_version"],
        reputation_json=reputation_json,
        faction_state_json=faction_state_json,
    )

    conn.execute(
        """
        INSERT INTO faction_states (
            campaign_id,
            faction_id,
            snapshot_version,
            reputation_json,
            faction_state_json,
            snapshot_hash,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(campaign_id, faction_id) DO UPDATE SET
            snapshot_version=excluded.snapshot_version,
            reputation_json=excluded.reputation_json,
            faction_state_json=excluded.faction_state_json,
            snapshot_hash=excluded.snapshot_hash,
            updated_at=excluded.updated_at
        """,
        (
            _required_text(campaign_id, field_name="campaign_id"),
            _required_text(faction_id, field_name="faction_id"),
            normalized["snapshot_version"],
            reputation_json,
            faction_state_json,
            snapshot_hash,
            normalized["updated_at"],
        ),
    )


def load_faction_snapshot(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    faction_id: str,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT * FROM faction_states
        WHERE campaign_id = ? AND faction_id = ?
        """,
        (
            _required_text(campaign_id, field_name="campaign_id"),
            _required_text(faction_id, field_name="faction_id"),
        ),
    ).fetchone()
    if row is None:
        raise KeyError(f"Unknown faction state campaign_id={campaign_id} faction_id={faction_id}")

    snapshot = _row_to_faction_snapshot(row)
    snapshot["campaign_id"] = str(row["campaign_id"])
    snapshot["faction_id"] = str(row["faction_id"])
    return snapshot


def persist_campaign_snapshot(
    *,
    campaign_id: str,
    snapshot: dict[str, Any],
) -> None:
    with db_module.get_connection() as conn:
        save_campaign_snapshot(conn, campaign_id=campaign_id, snapshot=snapshot)
        conn.commit()


def persist_encounter_snapshot(
    *,
    campaign_id: str,
    encounter_id: str,
    snapshot: dict[str, Any],
) -> None:
    with db_module.get_connection() as conn:
        save_encounter_snapshot(
            conn,
            campaign_id=campaign_id,
            encounter_id=encounter_id,
            snapshot=snapshot,
        )
        conn.commit()


def persist_world_snapshot(
    *,
    campaign_id: str,
    snapshot: dict[str, Any],
) -> None:
    with db_module.get_connection() as conn:
        save_world_snapshot(
            conn,
            campaign_id=campaign_id,
            snapshot=snapshot,
        )
        conn.commit()


def persist_faction_snapshot(
    *,
    campaign_id: str,
    faction_id: str,
    snapshot: dict[str, Any],
) -> None:
    with db_module.get_connection() as conn:
        save_faction_snapshot(
            conn,
            campaign_id=campaign_id,
            faction_id=faction_id,
            snapshot=snapshot,
        )
        conn.commit()
