from __future__ import annotations

import sqlite3

import pytest

from dnd_sim import db_schema
from dnd_sim.snapshot_store import (
    load_campaign_snapshot,
    load_encounter_snapshot,
    save_campaign_snapshot,
    save_encounter_snapshot,
)


def _memory_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _campaign_snapshot() -> dict[str, object]:
    return {
        "party_state": {
            "hero": {"hp": 19, "position": [10.0, 5.0, 0.0]},
            "cleric": {"hp": 22, "position": [5.0, 5.0, 0.0]},
        },
        "resources": {
            "hero": {"ki": 3},
            "cleric": {"spell_slot_1": 2},
        },
        "active_effects": [
            {"source_id": "hero", "target_id": "hero", "condition": "hasted"},
            {"source_id": "cleric", "target_id": "hero", "condition": "bless"},
        ],
        "initiative_context": {
            "round": 4,
            "initiative_order": ["hero", "boss", "cleric"],
            "current_actor_id": "boss",
        },
        "replay_bundle_id": "replay_0007",
    }


def test_campaign_state_round_trip_preserves_canonical_snapshot_and_hash() -> None:
    with _memory_connection() as conn:
        db_schema.create_campaign_state_tables(conn)
        snapshot = _campaign_snapshot()

        save_campaign_snapshot(conn, campaign_id="campaign_alpha", snapshot=snapshot)
        first_hash = conn.execute(
            "SELECT snapshot_hash FROM campaign_states WHERE campaign_id = ?",
            ("campaign_alpha",),
        ).fetchone()[0]

        # Equivalent payload with different key order should yield same deterministic hash.
        save_campaign_snapshot(
            conn,
            campaign_id="campaign_alpha",
            snapshot={
                "initiative_context": snapshot["initiative_context"],
                "active_effects": snapshot["active_effects"],
                "resources": snapshot["resources"],
                "party_state": snapshot["party_state"],
                "replay_bundle_id": snapshot["replay_bundle_id"],
            },
        )
        second_hash = conn.execute(
            "SELECT snapshot_hash FROM campaign_states WHERE campaign_id = ?",
            ("campaign_alpha",),
        ).fetchone()[0]
        loaded = load_campaign_snapshot(conn, campaign_id="campaign_alpha")

    assert first_hash == second_hash
    assert loaded["campaign_id"] == "campaign_alpha"
    assert loaded["party_state"] == snapshot["party_state"]
    assert loaded["resources"] == snapshot["resources"]
    assert loaded["active_effects"] == snapshot["active_effects"]
    assert loaded["initiative_context"] == snapshot["initiative_context"]
    assert loaded["replay_bundle_id"] == "replay_0007"


def test_encounter_state_round_trip_links_campaign_and_replay() -> None:
    with _memory_connection() as conn:
        db_schema.create_campaign_state_tables(conn)
        save_campaign_snapshot(
            conn,
            campaign_id="campaign_alpha",
            snapshot=_campaign_snapshot(),
        )

        encounter_snapshot = {
            "party_state": {"hero": {"hp": 15}},
            "resources": {"hero": {"ki": 2}},
            "active_effects": [{"target_id": "hero", "condition": "bless"}],
            "initiative_context": {"round": 1, "initiative_order": ["hero", "ogre"]},
            "replay_bundle_id": "replay_encounter_001",
        }
        save_encounter_snapshot(
            conn,
            campaign_id="campaign_alpha",
            encounter_id="encounter_bridge_01",
            snapshot=encounter_snapshot,
        )
        loaded = load_encounter_snapshot(
            conn,
            campaign_id="campaign_alpha",
            encounter_id="encounter_bridge_01",
        )

    assert loaded["campaign_id"] == "campaign_alpha"
    assert loaded["encounter_id"] == "encounter_bridge_01"
    assert loaded["party_state"] == {"hero": {"hp": 15}}
    assert loaded["resources"] == {"hero": {"ki": 2}}
    assert loaded["active_effects"] == [{"target_id": "hero", "condition": "bless"}]
    assert loaded["initiative_context"]["initiative_order"] == ["hero", "ogre"]
    assert loaded["replay_bundle_id"] == "replay_encounter_001"


def test_campaign_snapshot_rejects_legacy_shape_under_hard_cut_policy() -> None:
    with _memory_connection() as conn:
        db_schema.create_campaign_state_tables(conn)
        with pytest.raises(ValueError, match="missing required keys|unexpected keys"):
            save_campaign_snapshot(
                conn,
                campaign_id="legacy_campaign",
                snapshot={
                    "party": {"hero": {"hp": 10}},
                    "resource_state": {"hero": {"ki": 1}},
                    "effects": [{"condition": "bless", "target_id": "hero"}],
                    "initiative": {"round": 2},
                    "replay": {"bundle_id": "legacy_replay_42"},
                },
            )


def test_load_campaign_snapshot_rejects_corrupt_json_payload() -> None:
    with _memory_connection() as conn:
        db_schema.create_campaign_state_tables(conn)
        save_campaign_snapshot(conn, campaign_id="campaign_alpha", snapshot=_campaign_snapshot())
        conn.execute(
            "UPDATE campaign_states SET active_effects_json = ? WHERE campaign_id = ?",
            ("not-json", "campaign_alpha"),
        )
        conn.commit()

        with pytest.raises(ValueError, match="active_effects_json"):
            load_campaign_snapshot(conn, campaign_id="campaign_alpha")


def test_load_campaign_snapshot_rejects_hash_mismatch_corruption() -> None:
    with _memory_connection() as conn:
        db_schema.create_campaign_state_tables(conn)
        save_campaign_snapshot(conn, campaign_id="campaign_alpha", snapshot=_campaign_snapshot())
        conn.execute(
            "UPDATE campaign_states SET snapshot_hash = ? WHERE campaign_id = ?",
            ("sha256:deadbeef", "campaign_alpha"),
        )
        conn.commit()

        with pytest.raises(ValueError, match="snapshot hash mismatch"):
            load_campaign_snapshot(conn, campaign_id="campaign_alpha")
