from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from dnd_sim import db as db_module
from dnd_sim.campaign_runtime import (
    AdventuringActorState,
    AdventuringDayState,
    EncounterCheckpoint,
)
from dnd_sim.economy import (
    EconomyState,
    MarketItem,
    VendorInventory,
    VendorStock,
    create_economy_state,
)
from dnd_sim.world_runtime import (
    ExplorationState,
    LightSourceState,
    WorldClock,
)
from dnd_sim.world_state import (
    FactionState,
    QuestState,
    WorldState,
)

_CAMPAIGN_SNAPSHOT_VERSION = "campaign_snapshot.v1"
_ENCOUNTER_SNAPSHOT_VERSION = "encounter_snapshot.v1"
_WORLD_SNAPSHOT_VERSION = "world_snapshot.v1"
_FACTION_SNAPSHOT_VERSION = "faction_snapshot.v1"

_CAMPAIGN_REQUIRED_KEYS = frozenset(
    {"party_state", "resources", "active_effects", "initiative_context"}
)
_CAMPAIGN_OPTIONAL_KEYS = frozenset({"replay_bundle_id"})
_WORLD_REQUIRED_KEYS = frozenset({"world_flags", "objectives", "map_state", "encounter_state"})
_WORLD_OPTIONAL_KEYS = frozenset({"replay_bundle_id"})
_FACTION_REQUIRED_KEYS = frozenset({"reputation", "faction_state"})
_FACTION_OPTIONAL_KEYS = frozenset()


def _required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _required_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _required_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    return value


def _required_list(value: Any, *, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return list(value)


def _canonical_json_text(payload: Any) -> str:
    try:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))
    except TypeError as exc:
        raise ValueError("snapshot payload must be JSON-serializable") from exc


def _stable_payload_hash(payload: Any) -> str:
    digest = hashlib.sha256(_canonical_json_text(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _parse_json_column(raw: Any, *, column_name: str, expected: type[dict] | type[list]) -> Any:
    if not isinstance(raw, str):
        raise ValueError(f"{column_name} must be a JSON string")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{column_name} contains invalid JSON") from exc
    if expected is dict and not isinstance(parsed, dict):
        raise ValueError(f"{column_name} must decode to a mapping")
    if expected is list and not isinstance(parsed, list):
        raise ValueError(f"{column_name} must decode to a list")
    return parsed


def _validate_snapshot_keys(
    snapshot: Mapping[str, Any],
    *,
    required_keys: frozenset[str],
    optional_keys: frozenset[str],
    snapshot_name: str,
) -> dict[str, Any]:
    provided_keys = set(snapshot.keys())
    missing = sorted(required_keys - provided_keys)
    if missing:
        raise ValueError(f"{snapshot_name} missing required keys: {', '.join(missing)}")
    unexpected = sorted(provided_keys - (required_keys | optional_keys))
    if unexpected:
        raise ValueError(f"{snapshot_name} has unexpected keys: {', '.join(unexpected)}")
    return dict(snapshot)


def _normalize_campaign_like_snapshot(
    snapshot: Mapping[str, Any],
    *,
    snapshot_name: str,
) -> dict[str, Any]:
    normalized = _validate_snapshot_keys(
        snapshot,
        required_keys=_CAMPAIGN_REQUIRED_KEYS,
        optional_keys=_CAMPAIGN_OPTIONAL_KEYS,
        snapshot_name=snapshot_name,
    )
    normalized["party_state"] = dict(
        _required_mapping(normalized["party_state"], field_name="party_state")
    )
    normalized["resources"] = dict(
        _required_mapping(normalized["resources"], field_name="resources")
    )
    normalized["active_effects"] = _required_list(
        normalized["active_effects"],
        field_name="active_effects",
    )
    normalized["initiative_context"] = dict(
        _required_mapping(normalized["initiative_context"], field_name="initiative_context")
    )
    replay_bundle_id = normalized.get("replay_bundle_id")
    if replay_bundle_id is not None:
        normalized["replay_bundle_id"] = _required_text(
            replay_bundle_id,
            field_name="replay_bundle_id",
        )
    else:
        normalized["replay_bundle_id"] = None
    return normalized


def _normalize_world_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _validate_snapshot_keys(
        snapshot,
        required_keys=_WORLD_REQUIRED_KEYS,
        optional_keys=_WORLD_OPTIONAL_KEYS,
        snapshot_name="world snapshot",
    )
    normalized["world_flags"] = dict(
        _required_mapping(normalized["world_flags"], field_name="world_flags")
    )
    normalized["objectives"] = dict(
        _required_mapping(normalized["objectives"], field_name="objectives")
    )
    normalized["map_state"] = dict(
        _required_mapping(normalized["map_state"], field_name="map_state")
    )
    normalized["encounter_state"] = dict(
        _required_mapping(normalized["encounter_state"], field_name="encounter_state")
    )
    replay_bundle_id = normalized.get("replay_bundle_id")
    if replay_bundle_id is not None:
        normalized["replay_bundle_id"] = _required_text(
            replay_bundle_id,
            field_name="replay_bundle_id",
        )
    else:
        normalized["replay_bundle_id"] = None
    return normalized


def _normalize_faction_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _validate_snapshot_keys(
        snapshot,
        required_keys=_FACTION_REQUIRED_KEYS,
        optional_keys=_FACTION_OPTIONAL_KEYS,
        snapshot_name="faction snapshot",
    )
    normalized["reputation"] = dict(
        _required_mapping(normalized["reputation"], field_name="reputation")
    )
    normalized["faction_state"] = dict(
        _required_mapping(normalized["faction_state"], field_name="faction_state")
    )
    return normalized


def _campaign_snapshot_hash(campaign_id: str, snapshot: Mapping[str, Any]) -> str:
    return _stable_payload_hash(
        {
            "campaign_id": campaign_id,
            "snapshot_version": _CAMPAIGN_SNAPSHOT_VERSION,
            "snapshot": snapshot,
        }
    )


def _encounter_snapshot_hash(
    campaign_id: str, encounter_id: str, snapshot: Mapping[str, Any]
) -> str:
    return _stable_payload_hash(
        {
            "campaign_id": campaign_id,
            "encounter_id": encounter_id,
            "snapshot_version": _ENCOUNTER_SNAPSHOT_VERSION,
            "snapshot": snapshot,
        }
    )


def _world_snapshot_hash(campaign_id: str, snapshot: Mapping[str, Any]) -> str:
    return _stable_payload_hash(
        {
            "campaign_id": campaign_id,
            "snapshot_version": _WORLD_SNAPSHOT_VERSION,
            "snapshot": snapshot,
        }
    )


def _faction_snapshot_hash(campaign_id: str, faction_id: str, snapshot: Mapping[str, Any]) -> str:
    return _stable_payload_hash(
        {
            "campaign_id": campaign_id,
            "faction_id": faction_id,
            "snapshot_version": _FACTION_SNAPSHOT_VERSION,
            "snapshot": snapshot,
        }
    )


def save_campaign_snapshot(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    snapshot: Mapping[str, Any],
) -> None:
    db_module.create_campaign_state_tables(conn)
    normalized_campaign_id = _required_text(campaign_id, field_name="campaign_id")
    normalized_snapshot = _normalize_campaign_like_snapshot(
        snapshot, snapshot_name="campaign snapshot"
    )
    snapshot_hash = _campaign_snapshot_hash(normalized_campaign_id, normalized_snapshot)
    updated_at = datetime.now(UTC).isoformat()
    conn.execute(
        f"""
        INSERT INTO {db_module.CAMPAIGN_STATES_TABLE} (
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
        FROM {db_module.CAMPAIGN_STATES_TABLE}
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
    expected_hash = _campaign_snapshot_hash(normalized_campaign_id, normalized_snapshot)
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
    db_module.create_campaign_state_tables(conn)
    normalized_campaign_id = _required_text(campaign_id, field_name="campaign_id")
    normalized_encounter_id = _required_text(encounter_id, field_name="encounter_id")
    normalized_snapshot = _normalize_campaign_like_snapshot(
        snapshot, snapshot_name="encounter snapshot"
    )
    snapshot_hash = _encounter_snapshot_hash(
        normalized_campaign_id,
        normalized_encounter_id,
        normalized_snapshot,
    )
    updated_at = datetime.now(UTC).isoformat()
    conn.execute(
        f"""
        INSERT INTO {db_module.ENCOUNTER_STATES_TABLE} (
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
        FROM {db_module.ENCOUNTER_STATES_TABLE}
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
    db_module.create_campaign_state_tables(conn)
    normalized_campaign_id = _required_text(campaign_id, field_name="campaign_id")
    normalized_snapshot = _normalize_world_snapshot(snapshot)
    snapshot_hash = _world_snapshot_hash(normalized_campaign_id, normalized_snapshot)
    updated_at = datetime.now(UTC).isoformat()
    conn.execute(
        f"""
        INSERT INTO {db_module.WORLD_STATES_TABLE} (
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
        FROM {db_module.WORLD_STATES_TABLE}
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
    expected_hash = _world_snapshot_hash(normalized_campaign_id, normalized_snapshot)
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
    db_module.create_campaign_state_tables(conn)
    normalized_campaign_id = _required_text(campaign_id, field_name="campaign_id")
    normalized_faction_id = _required_text(faction_id, field_name="faction_id")
    normalized_snapshot = _normalize_faction_snapshot(snapshot)
    snapshot_hash = _faction_snapshot_hash(
        normalized_campaign_id,
        normalized_faction_id,
        normalized_snapshot,
    )
    updated_at = datetime.now(UTC).isoformat()
    conn.execute(
        f"""
        INSERT INTO {db_module.FACTION_STATES_TABLE} (
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
        FROM {db_module.FACTION_STATES_TABLE}
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
        normalized_snapshot,
    )
    if str(row["snapshot_hash"]) != expected_hash:
        raise ValueError("snapshot hash mismatch")

    return {
        "campaign_id": normalized_campaign_id,
        "faction_id": normalized_faction_id,
        **normalized_snapshot,
    }


def _deserialize_light_sources(raw: Any) -> dict[str, LightSourceState]:
    if raw is None:
        return {}

    if isinstance(raw, list):
        normalized: dict[str, LightSourceState] = {}
        for item in raw:
            if not isinstance(item, Mapping):
                raise ValueError("light_sources list entries must be mappings")
            source_id = _required_text(item.get("source_id"), field_name="source_id")
            remaining_minutes = _required_int(
                item.get("remaining_minutes"),
                field_name="remaining_minutes",
            )
            is_lit_raw = item.get("is_lit", remaining_minutes > 0)
            if not isinstance(is_lit_raw, bool):
                raise ValueError("is_lit must be a bool")
            normalized[source_id] = LightSourceState(
                source_id=source_id,
                remaining_minutes=remaining_minutes,
                is_lit=is_lit_raw,
            )
        return normalized

    if isinstance(raw, Mapping):
        normalized = {}
        for source_id, source_payload in raw.items():
            normalized_source_id = _required_text(source_id, field_name="source_id")
            if isinstance(source_payload, Mapping):
                remaining_minutes = _required_int(
                    source_payload.get("remaining_minutes"),
                    field_name="remaining_minutes",
                )
                is_lit_raw = source_payload.get("is_lit", remaining_minutes > 0)
                if not isinstance(is_lit_raw, bool):
                    raise ValueError("is_lit must be a bool")
                normalized[normalized_source_id] = LightSourceState(
                    source_id=normalized_source_id,
                    remaining_minutes=remaining_minutes,
                    is_lit=is_lit_raw,
                )
            elif isinstance(source_payload, int) and not isinstance(source_payload, bool):
                normalized[normalized_source_id] = LightSourceState(
                    source_id=normalized_source_id,
                    remaining_minutes=source_payload,
                    is_lit=source_payload > 0,
                )
            else:
                raise ValueError("light_sources mapping values must be mappings or integer minutes")
        return normalized

    raise ValueError("light_sources must be a list or mapping")


def serialize_world_exploration_state(state: ExplorationState) -> dict[str, Any]:
    if not isinstance(state, ExplorationState):
        raise ValueError("state must be an ExplorationState")

    return {
        "turn_index": state.turn_index,
        "clock": {
            "day": state.clock.day,
            "minute_of_day": state.clock.minute_of_day,
        },
        "location_id": state.location_id,
        "light_sources": [
            {
                "source_id": light.source_id,
                "remaining_minutes": light.remaining_minutes,
                "is_lit": light.is_lit,
            }
            for _, light in sorted(state.light_sources.items())
        ],
    }


def deserialize_world_exploration_state(payload: Mapping[str, Any]) -> ExplorationState:
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a mapping")

    clock_payload = payload.get("clock")
    if not isinstance(clock_payload, Mapping):
        raise ValueError("clock must be a mapping")

    day = _required_int(clock_payload.get("day"), field_name="day")
    minute_of_day = _required_int(
        clock_payload.get("minute_of_day"),
        field_name="minute_of_day",
    )

    location_id: str | None = None
    if payload.get("location_id") is not None:
        location_id = _required_text(payload.get("location_id"), field_name="location_id")

    light_sources = _deserialize_light_sources(payload.get("light_sources"))
    turn_index = _required_int(payload.get("turn_index", 0), field_name="turn_index")

    return ExplorationState(
        turn_index=turn_index,
        clock=WorldClock(day=day, minute_of_day=minute_of_day),
        light_sources=light_sources,
        location_id=location_id,
    )


def serialize_economy_state(state: EconomyState) -> dict[str, Any]:
    if not isinstance(state, EconomyState):
        raise ValueError("state must be an EconomyState")

    return {
        "day_index": state.day_index,
        "market_price_index_bp": state.market_price_index_bp,
        "catalog": [
            {
                "item_id": item.item_id,
                "name": item.name,
                "base_price_cp": item.base_price_cp,
                "rarity": item.rarity,
                "category": item.category,
                "vendor_weight": item.vendor_weight,
                "loot_weight": item.loot_weight,
                "min_vendor_quantity": item.min_vendor_quantity,
                "max_vendor_quantity": item.max_vendor_quantity,
            }
            for _, item in sorted(state.catalog.items())
        ],
        "vendors": [
            {
                "vendor_id": vendor.vendor_id,
                "markup_bp": vendor.markup_bp,
                "stock": [
                    {
                        "item_id": stock.item_id,
                        "quantity": stock.quantity,
                        "unit_price_cp": stock.unit_price_cp,
                    }
                    for _, stock in sorted(vendor.stock.items())
                ],
            }
            for _, vendor in sorted(state.vendors.items())
        ],
    }


def _deserialize_economy_catalog(raw: Any) -> dict[str, MarketItem | Mapping[str, Any]]:
    if raw is None:
        return {}
    if isinstance(raw, list):
        catalog: dict[str, MarketItem | Mapping[str, Any]] = {}
        for row in raw:
            if not isinstance(row, Mapping):
                raise ValueError("catalog rows must be mappings")
            item_id = _required_text(row.get("item_id"), field_name="item_id")
            catalog[item_id] = row
        return catalog
    if isinstance(raw, Mapping):
        catalog = {}
        for item_id, payload in raw.items():
            normalized_item_id = _required_text(item_id, field_name="item_id")
            if isinstance(payload, MarketItem):
                catalog[normalized_item_id] = payload
                continue
            if not isinstance(payload, Mapping):
                raise ValueError("catalog mapping values must be mappings or MarketItem entries")
            merged_payload = dict(payload)
            merged_payload.setdefault("item_id", normalized_item_id)
            catalog[normalized_item_id] = merged_payload
        return catalog
    raise ValueError("catalog must be a list or mapping")


def _deserialize_vendor_stock_rows(raw: Any) -> dict[str, VendorStock | Mapping[str, Any] | int]:
    if raw is None:
        return {}
    if isinstance(raw, list):
        stock: dict[str, VendorStock | Mapping[str, Any] | int] = {}
        for row in raw:
            if not isinstance(row, Mapping):
                raise ValueError("vendor stock rows must be mappings")
            item_id = _required_text(row.get("item_id"), field_name="item_id")
            stock[item_id] = row
        return stock
    if isinstance(raw, Mapping):
        stock = {}
        for item_id, payload in raw.items():
            normalized_item_id = _required_text(item_id, field_name="item_id")
            stock[normalized_item_id] = payload
        return stock
    raise ValueError("vendor stock must be a list or mapping")


def _deserialize_economy_vendors(
    raw: Any,
) -> dict[str, VendorInventory | Mapping[str, Any]]:
    if raw is None:
        return {}
    if isinstance(raw, list):
        vendors: dict[str, VendorInventory | Mapping[str, Any]] = {}
        for row in raw:
            if not isinstance(row, Mapping):
                raise ValueError("vendor rows must be mappings")
            vendor_id = _required_text(row.get("vendor_id"), field_name="vendor_id")
            vendor_payload = dict(row)
            vendor_payload["stock"] = _deserialize_vendor_stock_rows(vendor_payload.get("stock"))
            vendors[vendor_id] = vendor_payload
        return vendors
    if isinstance(raw, Mapping):
        vendors = {}
        for vendor_id, payload in raw.items():
            normalized_vendor_id = _required_text(vendor_id, field_name="vendor_id")
            if isinstance(payload, VendorInventory):
                vendors[normalized_vendor_id] = payload
                continue
            if not isinstance(payload, Mapping):
                raise ValueError(
                    "vendor mapping values must be mappings or VendorInventory entries"
                )
            merged_payload = dict(payload)
            merged_payload.setdefault("vendor_id", normalized_vendor_id)
            merged_payload["stock"] = _deserialize_vendor_stock_rows(merged_payload.get("stock"))
            vendors[normalized_vendor_id] = merged_payload
        return vendors
    raise ValueError("vendors must be a list or mapping")


def deserialize_economy_state(payload: Mapping[str, Any]) -> EconomyState:
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a mapping")

    return create_economy_state(
        day_index=_required_int(payload.get("day_index", 1), field_name="day_index"),
        market_price_index_bp=_required_int(
            payload.get("market_price_index_bp", 10_000),
            field_name="market_price_index_bp",
        ),
        catalog=_deserialize_economy_catalog(payload.get("catalog")),
        vendors=_deserialize_economy_vendors(payload.get("vendors")),
    )


def serialize_world_state(state: WorldState) -> dict[str, Any]:
    if not isinstance(state, WorldState):
        raise ValueError("state must be a WorldState")

    return {
        "turn_index": state.turn_index,
        "world_flags": dict(sorted(state.world_flags.items())),
        "quests": [
            {
                "quest_id": quest.quest_id,
                "status": quest.status,
                "stage_id": quest.stage_id,
                "objective_flags": dict(sorted((quest.objective_flags or {}).items())),
            }
            for _, quest in sorted(state.quests.items())
        ],
        "factions": [
            {
                "faction_id": faction.faction_id,
                "reputation": faction.reputation,
            }
            for _, faction in sorted(state.factions.items())
        ],
    }


def _deserialize_quests(raw: Any) -> dict[str, QuestState]:
    if raw is None:
        return {}

    if isinstance(raw, list):
        quests: dict[str, QuestState] = {}
        for item in raw:
            if not isinstance(item, Mapping):
                raise ValueError("quests list entries must be mappings")
            quest = QuestState(
                quest_id=item.get("quest_id"),
                status=item.get("status", "not_started"),
                stage_id=item.get("stage_id"),
                objective_flags=item.get("objective_flags") or {},
            )
            quests[quest.quest_id] = quest
        return quests

    if isinstance(raw, Mapping):
        quests = {}
        for quest_id, payload in raw.items():
            if isinstance(payload, Mapping):
                quest = QuestState(
                    quest_id=quest_id,
                    status=payload.get("status", "not_started"),
                    stage_id=payload.get("stage_id"),
                    objective_flags=payload.get("objective_flags") or {},
                )
            elif isinstance(payload, str):
                quest = QuestState(quest_id=quest_id, status=payload)
            else:
                raise ValueError("quests mapping values must be mappings or status strings")
            quests[quest.quest_id] = quest
        return quests

    raise ValueError("quests must be a list or mapping")


def _deserialize_factions(raw: Any) -> dict[str, FactionState]:
    if raw is None:
        return {}

    if isinstance(raw, list):
        factions: dict[str, FactionState] = {}
        for item in raw:
            if not isinstance(item, Mapping):
                raise ValueError("factions list entries must be mappings")
            faction = FactionState(
                faction_id=item.get("faction_id"),
                reputation=item.get("reputation", 0),
            )
            factions[faction.faction_id] = faction
        return factions

    if isinstance(raw, Mapping):
        factions = {}
        for faction_id, payload in raw.items():
            if isinstance(payload, Mapping):
                faction = FactionState(
                    faction_id=faction_id,
                    reputation=payload.get("reputation", 0),
                )
            elif isinstance(payload, int) and not isinstance(payload, bool):
                faction = FactionState(faction_id=faction_id, reputation=payload)
            else:
                raise ValueError("factions mapping values must be mappings or integer reputations")
            factions[faction.faction_id] = faction
        return factions

    raise ValueError("factions must be a list or mapping")


def deserialize_world_state(payload: Mapping[str, Any]) -> WorldState:
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a mapping")

    turn_index = _required_int(payload.get("turn_index", 0), field_name="turn_index")
    raw_flags = payload.get("world_flags", {})
    if not isinstance(raw_flags, Mapping):
        raise ValueError("world_flags must be a mapping")
    world_flags = {str(flag_id): str(status) for flag_id, status in raw_flags.items()}
    quests = _deserialize_quests(payload.get("quests"))
    factions = _deserialize_factions(payload.get("factions"))

    return WorldState(
        turn_index=turn_index,
        world_flags=world_flags,
        quests=quests,
        factions=factions,
    )


def _serialize_adventuring_actor_state(actor: AdventuringActorState) -> dict[str, Any]:
    return {
        "actor_id": actor.actor_id,
        "hit_points": actor.hit_points,
        "max_hit_points": actor.max_hit_points,
        "resources": dict(actor.resources),
        "max_resources": dict(actor.max_resources),
        "short_rest_recovery": list(actor.short_rest_recovery),
        "conditions": list(actor.conditions),
    }


def _deserialize_adventuring_actor_state(payload: Mapping[str, Any]) -> AdventuringActorState:
    if not isinstance(payload, Mapping):
        raise ValueError("actor payload must be a mapping")

    return AdventuringActorState(
        actor_id=_required_text(payload.get("actor_id"), field_name="actor_id"),
        hit_points=_required_int(payload.get("hit_points"), field_name="hit_points"),
        max_hit_points=_required_int(payload.get("max_hit_points"), field_name="max_hit_points"),
        resources=dict(payload.get("resources", {})),
        max_resources=dict(payload.get("max_resources", {})),
        short_rest_recovery=tuple(payload.get("short_rest_recovery", ())),
        conditions=tuple(payload.get("conditions", ())),
    )


def _serialize_adventuring_party(
    party: Mapping[str, AdventuringActorState],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for actor_id, actor in sorted(dict(party).items()):
        if actor.actor_id != actor_id:
            raise ValueError("party actor key must match actor_id")
        rows.append(_serialize_adventuring_actor_state(actor))
    return rows


def _deserialize_adventuring_party(raw: Any) -> dict[str, AdventuringActorState]:
    if raw is None:
        return {}

    rows: list[tuple[str, Mapping[str, Any]]] = []
    if isinstance(raw, Mapping):
        for actor_id, payload in sorted(raw.items()):
            if not isinstance(payload, Mapping):
                raise ValueError("party mapping values must be mappings")
            merged_payload = dict(payload)
            merged_payload.setdefault("actor_id", actor_id)
            rows.append((str(actor_id), merged_payload))
    elif isinstance(raw, list):
        for payload in raw:
            if not isinstance(payload, Mapping):
                raise ValueError("party list entries must be mappings")
            actor_id = _required_text(payload.get("actor_id"), field_name="actor_id")
            rows.append((actor_id, payload))
    else:
        raise ValueError("party must be a list or mapping")

    party: dict[str, AdventuringActorState] = {}
    for actor_id, payload in rows:
        actor = _deserialize_adventuring_actor_state(payload)
        if actor.actor_id != actor_id:
            raise ValueError("party actor key must match actor_id")
        party[actor_id] = actor
    return party


def serialize_adventuring_day_state(state: AdventuringDayState) -> dict[str, Any]:
    if not isinstance(state, AdventuringDayState):
        raise ValueError("state must be an AdventuringDayState")

    return {
        "campaign_id": state.campaign_id,
        "day_number": state.day_number,
        "encounter_order": list(state.encounter_order),
        "current_encounter_index": state.current_encounter_index,
        "completed": state.completed,
        "party": _serialize_adventuring_party(state.party),
        "world_state": serialize_world_exploration_state(state.world_state),
        "encounter_history": [
            {
                "encounter_id": checkpoint.encounter_id,
                "outcome": checkpoint.outcome,
                "rest_applied": checkpoint.rest_applied,
                "world_day": checkpoint.world_day,
                "world_minute_of_day": checkpoint.world_minute_of_day,
                "party": _serialize_adventuring_party(checkpoint.party),
            }
            for checkpoint in state.encounter_history
        ],
    }


def deserialize_adventuring_day_state(payload: Mapping[str, Any]) -> AdventuringDayState:
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a mapping")

    encounter_order_raw = payload.get("encounter_order", [])
    if not isinstance(encounter_order_raw, (list, tuple)):
        raise ValueError("encounter_order must be a list or tuple")
    encounter_order = tuple(
        _required_text(entry, field_name="encounter_order entry") for entry in encounter_order_raw
    )

    completed_raw = payload.get("completed", False)
    if not isinstance(completed_raw, bool):
        raise ValueError("completed must be a bool")

    history_raw = payload.get("encounter_history", [])
    if not isinstance(history_raw, list):
        raise ValueError("encounter_history must be a list")
    encounter_history: list[EncounterCheckpoint] = []
    for row in history_raw:
        if not isinstance(row, Mapping):
            raise ValueError("encounter_history entries must be mappings")
        encounter_history.append(
            EncounterCheckpoint(
                encounter_id=_required_text(row.get("encounter_id"), field_name="encounter_id"),
                outcome=_required_text(row.get("outcome"), field_name="outcome"),
                rest_applied=_required_text(
                    row.get("rest_applied", row.get("rest", "none")),
                    field_name="rest_applied",
                ),
                party=_deserialize_adventuring_party(row.get("party")),
                world_day=_required_int(row.get("world_day"), field_name="world_day"),
                world_minute_of_day=_required_int(
                    row.get("world_minute_of_day"),
                    field_name="world_minute_of_day",
                ),
            )
        )

    world_state_payload = payload.get("world_state")
    if not isinstance(world_state_payload, Mapping):
        raise ValueError("world_state must be a mapping")

    return AdventuringDayState(
        campaign_id=_required_text(payload.get("campaign_id"), field_name="campaign_id"),
        day_number=_required_int(payload.get("day_number"), field_name="day_number"),
        encounter_order=encounter_order,
        current_encounter_index=_required_int(
            payload.get("current_encounter_index"),
            field_name="current_encounter_index",
        ),
        party=_deserialize_adventuring_party(payload.get("party")),
        world_state=deserialize_world_exploration_state(world_state_payload),
        encounter_history=tuple(encounter_history),
        completed=completed_raw,
    )
