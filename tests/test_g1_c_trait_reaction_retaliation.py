from __future__ import annotations

import csv
import json
from pathlib import Path

from dnd_sim.capability_manifest import build_feature_capability_manifest
from dnd_sim.mechanics_schema import validate_rule_mechanics_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_REGISTRY_PATH = REPO_ROOT / "docs" / "program" / "parity_batch_registry.csv"
TRAITS_DIR = REPO_ROOT / "db" / "rules" / "2014" / "traits"
G1_C_IDS = {
    "trait:master_transmuter",
    "trait:misty_escape",
    "trait:opportunist",
    "trait:planar_warrior",
    "trait:psychic_blades",
    "trait:relentless_avenger",
    "trait:rend_mind",
    "trait:shadowy_dodge",
    "trait:spreading_spores",
    "trait:stalker_s_flurry",
}


def _owned_g1_c_trait_ids() -> set[str]:
    owned: set[str] = set()
    with BATCH_REGISTRY_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if (
                row.get("batch_id") == "G1-C"
                and row.get("leaf_task_id") == "W6-PAR-05G1"
                and row.get("content_type") == "trait"
                and row.get("prompt_family") == "trait_reaction_retaliation"
                and row.get("target_test_file")
                == "tests/test_g1_c_trait_reaction_retaliation.py"
                and row.get("branch_name")
                == "codex/feat/g1-c-trait-reaction-retaliation"
            ):
                content_id = str(row.get("content_id", "")).strip()
                if content_id:
                    owned.add(content_id)

    assert owned == G1_C_IDS
    return owned


def test_g1_c_owned_trait_records_are_supported() -> None:
    owned_ids = _owned_g1_c_trait_ids()
    manifest = build_feature_capability_manifest()
    by_id = {record.content_id: record for record in manifest.records}

    missing_ids = sorted(owned_ids - set(by_id))
    assert missing_ids == []

    blocked_traits_missing_hook = {
        record.content_id
        for record in manifest.records
        if record.content_type == "trait"
        and record.states.unsupported_reason == "missing_runtime_hook_family"
    }
    assert blocked_traits_missing_hook.isdisjoint(owned_ids)

    for content_id in sorted(owned_ids):
        record = by_id[content_id]
        assert record.content_type == "trait"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.states.unsupported_reason is None
        assert record.runtime_hook_family == "meta"


def test_g1_c_trait_files_use_canonical_mechanics_rows() -> None:
    owned_ids = _owned_g1_c_trait_ids()

    for content_id in sorted(owned_ids):
        trait_id = content_id.split(":", 1)[1]
        path = TRAITS_DIR / f"{trait_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))

        mechanics = payload.get("mechanics")
        assert isinstance(mechanics, list), f"{content_id} mechanics must be a list"
        assert mechanics, f"{content_id} mechanics must not be empty"

        for idx, row in enumerate(mechanics):
            assert isinstance(row, dict), f"{content_id} mechanics[{idx}] must be object"
            assert str(
                row.get("meta_type", "")
            ).strip(), f"{content_id} mechanics[{idx}] missing meta_type"

        issues = validate_rule_mechanics_payload(kind="trait", payload=payload)
        assert issues == [], f"{content_id} has schema issues: {issues}"


def test_g1_c_trait_rows_capture_owned_intent() -> None:
    master = json.loads((TRAITS_DIR / "master_transmuter.json").read_text(encoding="utf-8"))["mechanics"]
    assert any(row.get("meta_type") == "consume_transmuter_stone_support" for row in master if isinstance(row, dict))
    assert any(row.get("meta_type") == "panacea_restoration_support" for row in master if isinstance(row, dict))

    misty = json.loads((TRAITS_DIR / "misty_escape.json").read_text(encoding="utf-8"))["mechanics"]
    assert any(row.get("meta_type") == "reactive_invisibility_teleport_support" for row in misty if isinstance(row, dict))

    opportunist = json.loads((TRAITS_DIR / "opportunist.json").read_text(encoding="utf-8"))["mechanics"]
    assert any(row.get("meta_type") == "reaction_followup_attack_support" for row in opportunist if isinstance(row, dict))

    planar = json.loads((TRAITS_DIR / "planar_warrior.json").read_text(encoding="utf-8"))["mechanics"]
    assert any(row.get("meta_type") == "planar_warrior_mark_support" for row in planar if isinstance(row, dict))

    psychic = json.loads((TRAITS_DIR / "psychic_blades.json").read_text(encoding="utf-8"))["mechanics"]
    assert any(row.get("meta_type") == "psychic_blades_extra_damage_support" for row in psychic if isinstance(row, dict))

    avenger = json.loads((TRAITS_DIR / "relentless_avenger.json").read_text(encoding="utf-8"))["mechanics"]
    assert any(row.get("meta_type") == "opportunity_attack_reposition_support" for row in avenger if isinstance(row, dict))

    rend = json.loads((TRAITS_DIR / "rend_mind.json").read_text(encoding="utf-8"))["mechanics"]
    assert any(row.get("meta_type") == "rend_mind_stun_support" for row in rend if isinstance(row, dict))

    dodge = json.loads((TRAITS_DIR / "shadowy_dodge.json").read_text(encoding="utf-8"))["mechanics"]
    assert any(row.get("meta_type") == "reaction_disadvantage_imposition_support" for row in dodge if isinstance(row, dict))

    spores = json.loads((TRAITS_DIR / "spreading_spores.json").read_text(encoding="utf-8"))["mechanics"]
    assert any(row.get("meta_type") == "spore_zone_deployment_support" for row in spores if isinstance(row, dict))
    assert any(row.get("meta_type") == "spore_zone_damage_support" for row in spores if isinstance(row, dict))

    flurry = json.loads((TRAITS_DIR / "stalker_s_flurry.json").read_text(encoding="utf-8"))["mechanics"]
    assert any(row.get("meta_type") == "miss_followup_attack_support" for row in flurry if isinstance(row, dict))
