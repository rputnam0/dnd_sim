from __future__ import annotations

import sqlite3

import dnd_sim.db as db_module
import pytest
from dnd_sim.persistence import (
    load_faction_snapshot,
    load_world_snapshot,
    save_campaign_snapshot,
    save_faction_snapshot,
    save_world_snapshot,
)


def _memory_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _campaign_snapshot() -> dict[str, object]:
    return {
        "party_state": {"hero": {"hp": 21}},
        "resources": {"hero": {"ki": 3}},
        "active_effects": [{"target_id": "hero", "condition": "bless"}],
        "initiative_context": {"round": 1, "initiative_order": ["hero", "ogre"]},
        "replay_bundle_id": "campaign_replay_001",
    }


def test_world_state_lifecycle_persists_flags_and_wave_progression() -> None:
    with _memory_connection() as conn:
        db_module.create_campaign_state_tables(conn)
        save_campaign_snapshot(conn, campaign_id="campaign_alpha", snapshot=_campaign_snapshot())

        initial_snapshot = {
            "world_flags": {
                "storm_active": True,
                "bridge_raised": False,
            },
            "objectives": {
                "rescue_envoy": {"status": "active", "progress": 1},
            },
            "map_state": {
                "current_region": "stone_pass",
                "revealed_nodes": ["trailhead", "camp"],
            },
            "encounter_state": {
                "encounter_id": "stone_pass_ambush",
                "current_wave": 1,
                "completed_waves": [0],
            },
            "replay_bundle_id": "world_replay_001",
        }
        save_world_snapshot(conn, campaign_id="campaign_alpha", snapshot=initial_snapshot)

        first_hash = conn.execute(
            "SELECT snapshot_hash FROM world_states WHERE campaign_id = ?",
            ("campaign_alpha",),
        ).fetchone()[0]

        save_world_snapshot(
            conn,
            campaign_id="campaign_alpha",
            snapshot={
                "encounter_state": initial_snapshot["encounter_state"],
                "map_state": initial_snapshot["map_state"],
                "objectives": initial_snapshot["objectives"],
                "world_flags": initial_snapshot["world_flags"],
                "replay_bundle_id": initial_snapshot["replay_bundle_id"],
            },
        )
        second_hash = conn.execute(
            "SELECT snapshot_hash FROM world_states WHERE campaign_id = ?",
            ("campaign_alpha",),
        ).fetchone()[0]

        save_world_snapshot(
            conn,
            campaign_id="campaign_alpha",
            snapshot={
                "world_flags": {
                    "storm_active": False,
                    "bridge_raised": True,
                },
                "objectives": {
                    "rescue_envoy": {"status": "complete", "progress": 2},
                },
                "map_state": {
                    "current_region": "stone_pass",
                    "revealed_nodes": ["trailhead", "camp", "bridge"],
                },
                "encounter_state": {
                    "encounter_id": "stone_pass_ambush",
                    "current_wave": 2,
                    "completed_waves": [0, 1],
                },
                "replay_bundle_id": "world_replay_002",
            },
        )
        loaded = load_world_snapshot(conn, campaign_id="campaign_alpha")

    assert first_hash == second_hash
    assert loaded["world_flags"] == {
        "storm_active": False,
        "bridge_raised": True,
    }
    assert loaded["objectives"]["rescue_envoy"]["status"] == "complete"
    assert loaded["encounter_state"]["current_wave"] == 2
    assert loaded["replay_bundle_id"] == "world_replay_002"


def test_world_snapshot_rejects_legacy_shape_under_hard_cut_policy() -> None:
    with _memory_connection() as conn:
        db_module.create_campaign_state_tables(conn)
        save_campaign_snapshot(conn, campaign_id="campaign_beta", snapshot=_campaign_snapshot())
        with pytest.raises(ValueError, match="missing required keys|unexpected keys"):
            save_world_snapshot(
                conn,
                campaign_id="campaign_beta",
                snapshot={
                    "flags": {"rift_sealed": True},
                    "objective_state": {
                        "seal_the_rift": {"status": "complete", "progress": {"sigils": 3}},
                    },
                    "map": {
                        "region": "sunken_temple",
                        "checkpoints": {"altar": "claimed"},
                    },
                    "encounter": {
                        "encounter_id": "sunken_temple_finale",
                        "wave_progression": {"current": 3, "remaining": [4, 5]},
                    },
                    "replay": {"bundle_id": "world_replay_legacy"},
                },
            )


def test_faction_state_round_trip_preserves_reputation_and_state() -> None:
    with _memory_connection() as conn:
        db_module.create_campaign_state_tables(conn)
        save_campaign_snapshot(conn, campaign_id="campaign_gamma", snapshot=_campaign_snapshot())
        save_world_snapshot(
            conn,
            campaign_id="campaign_gamma",
            snapshot={
                "world_flags": {"city_alert": True},
                "objectives": {"hold_the_wall": {"status": "active"}},
                "map_state": {"district": "north_gate"},
                "encounter_state": {"current_wave": 1},
            },
        )

        save_faction_snapshot(
            conn,
            campaign_id="campaign_gamma",
            faction_id="iron_council",
            snapshot={
                "reputation": {
                    "party_alpha": 12,
                    "party_beta": -3,
                },
                "faction_state": {
                    "disposition": "wary",
                    "influence": {"capital": 2, "frontier": 1},
                },
            },
        )
        first_hash = conn.execute(
            "SELECT snapshot_hash FROM faction_states WHERE campaign_id = ? AND faction_id = ?",
            ("campaign_gamma", "iron_council"),
        ).fetchone()[0]

        save_faction_snapshot(
            conn,
            campaign_id="campaign_gamma",
            faction_id="iron_council",
            snapshot={
                "faction_state": {
                    "influence": {"capital": 2, "frontier": 1},
                    "disposition": "wary",
                },
                "reputation": {
                    "party_beta": -3,
                    "party_alpha": 12,
                },
            },
        )
        second_hash = conn.execute(
            "SELECT snapshot_hash FROM faction_states WHERE campaign_id = ? AND faction_id = ?",
            ("campaign_gamma", "iron_council"),
        ).fetchone()[0]

        save_faction_snapshot(
            conn,
            campaign_id="campaign_gamma",
            faction_id="iron_council",
            snapshot={
                "reputation": {
                    "party_alpha": 16,
                    "party_beta": -5,
                },
                "faction_state": {
                    "disposition": "allied",
                    "influence": {"capital": 3, "frontier": 2},
                },
            },
        )
        loaded = load_faction_snapshot(
            conn,
            campaign_id="campaign_gamma",
            faction_id="iron_council",
        )

    assert first_hash == second_hash
    assert loaded["reputation"] == {
        "party_alpha": 16,
        "party_beta": -5,
    }
    assert loaded["faction_state"]["disposition"] == "allied"
    assert loaded["faction_id"] == "iron_council"


def test_faction_snapshot_rejects_legacy_alias_keys_under_hard_cut_policy() -> None:
    with _memory_connection() as conn:
        db_module.create_campaign_state_tables(conn)
        save_campaign_snapshot(conn, campaign_id="campaign_hard_cut", snapshot=_campaign_snapshot())
        save_world_snapshot(
            conn,
            campaign_id="campaign_hard_cut",
            snapshot={
                "world_flags": {"city_alert": True},
                "objectives": {"hold_gate": {"status": "active"}},
                "map_state": {"district": "wall"},
                "encounter_state": {"current_wave": 1},
            },
        )

        with pytest.raises(ValueError, match="missing required keys|unexpected keys"):
            save_faction_snapshot(
                conn,
                campaign_id="campaign_hard_cut",
                faction_id="emerald_circle",
                snapshot={
                    "reputations": {"party_alpha": 4},
                    "state": {"disposition": "neutral"},
                },
            )


def test_load_world_snapshot_rejects_corrupt_json_payload() -> None:
    with _memory_connection() as conn:
        db_module.create_campaign_state_tables(conn)
        save_campaign_snapshot(conn, campaign_id="campaign_delta", snapshot=_campaign_snapshot())
        save_world_snapshot(
            conn,
            campaign_id="campaign_delta",
            snapshot={
                "world_flags": {"mist_active": True},
                "objectives": {"escape": {"status": "active"}},
                "map_state": {"region": "crypt"},
                "encounter_state": {"current_wave": 1},
            },
        )
        conn.execute(
            "UPDATE world_states SET objectives_json = ? WHERE campaign_id = ?",
            ("not-json", "campaign_delta"),
        )
        conn.commit()

        with pytest.raises(ValueError, match="objectives_json"):
            load_world_snapshot(conn, campaign_id="campaign_delta")


def test_load_faction_snapshot_rejects_hash_mismatch_corruption() -> None:
    with _memory_connection() as conn:
        db_module.create_campaign_state_tables(conn)
        save_campaign_snapshot(conn, campaign_id="campaign_epsilon", snapshot=_campaign_snapshot())
        save_world_snapshot(
            conn,
            campaign_id="campaign_epsilon",
            snapshot={
                "world_flags": {"city_alert": True},
                "objectives": {"hold_gate": {"status": "active"}},
                "map_state": {"district": "wall"},
                "encounter_state": {"current_wave": 2},
            },
        )
        save_faction_snapshot(
            conn,
            campaign_id="campaign_epsilon",
            faction_id="emerald_circle",
            snapshot={
                "reputation": {"party_alpha": 4},
                "faction_state": {"disposition": "neutral"},
            },
        )
        conn.execute(
            """
            UPDATE faction_states
            SET snapshot_hash = ?
            WHERE campaign_id = ? AND faction_id = ?
            """,
            ("sha256:deadbeef", "campaign_epsilon", "emerald_circle"),
        )
        conn.commit()

        with pytest.raises(ValueError, match="snapshot hash mismatch"):
            load_faction_snapshot(
                conn,
                campaign_id="campaign_epsilon",
                faction_id="emerald_circle",
            )
