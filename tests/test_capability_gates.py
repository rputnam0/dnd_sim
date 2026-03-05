from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from dnd_sim import io
from dnd_sim.io import validate_capability_gate_records

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts/content/verify_capabilities.py"
FIXTURE_ROOT = REPO_ROOT / "tests/fixtures/capability_gates"

spec = importlib.util.spec_from_file_location("verify_capabilities", SCRIPT_PATH)
if spec is None or spec.loader is None:  # pragma: no cover
    raise RuntimeError(f"Unable to load module from {SCRIPT_PATH}")
verify_capabilities = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = verify_capabilities
spec.loader.exec_module(verify_capabilities)

SHARD_A_SPECIES_IDS = {
    "species:ambusher",
    "species:amorphous",
    "species:amphibious",
    "species:bestial_instincts",
    "species:black_blood_healing",
    "species:brave",
}
SHARD_B_SPECIES_IDS = {
    "species:cat_s_talents",
    "species:celestial_resistance",
    "species:climbing",
    "species:damage_resistance",
    "species:dwarven_combat_training",
    "species:emissary_of_the_sea",
}


def test_supported_scope_requires_schema_valid_and_tested() -> None:
    issues = validate_capability_gate_records(
        records=[
            {
                "content_id": "spell:arc_flash",
                "content_type": "spell",
                "states": {
                    "cataloged": True,
                    "schema_valid": True,
                    "executable": True,
                    "tested": False,
                    "blocked": False,
                    "unsupported_reason": None,
                },
            }
        ]
    )

    assert any("tested=true" in issue for issue in issues)


def test_blocked_record_fixture_requires_unsupported_reason() -> None:
    payload = json.loads((FIXTURE_ROOT / "blocked_missing_reason.json").read_text(encoding="utf-8"))

    issues = validate_capability_gate_records(records=payload["records"])

    assert any("unsupported_reason" in issue for issue in issues)


def test_import_path_gate_blocks_spell_db_load_on_capability_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "dnd_sim.io.capability_gate_issues_for_types",
        lambda *_args, **_kwargs: ["CAP-GATE-TEST: synthetic failure"],
    )

    with pytest.raises(ValueError, match="Capability manifest gate failed"):
        io.load_spell_db(io._spell_root_dir())


def test_verify_capabilities_cli_dry_run_returns_zero_when_issues_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "dnd_sim.io.capability_gate_issues_for_types",
        lambda *_args, **_kwargs: ["CAP-GATE-TEST: synthetic failure"],
    )

    assert verify_capabilities.main(["--dry-run"]) == 0
    assert verify_capabilities.main([]) == 1


def test_species_hook_shard_a_ids_are_supported_in_canonical_capability_records() -> None:
    io._canonical_capability_records.cache_clear()
    by_id = {record.content_id: record for record in io._canonical_capability_records()}

    missing_ids = sorted(SHARD_A_SPECIES_IDS - set(by_id))
    assert missing_ids == []

    for content_id in sorted(SHARD_A_SPECIES_IDS):
        record = by_id[content_id]
        assert record.content_type == "species"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.runtime_hook_family in {"effect", "effect_meta", "meta"}


def test_species_hook_shard_b_ids_are_supported_in_canonical_capability_records() -> None:
    io._canonical_capability_records.cache_clear()
    by_id = {record.content_id: record for record in io._canonical_capability_records()}

    missing_ids = sorted(SHARD_B_SPECIES_IDS - set(by_id))
    assert missing_ids == []

    for content_id in sorted(SHARD_B_SPECIES_IDS):
        record = by_id[content_id]
        assert record.content_type == "species"
        assert record.support_state == "supported"
        assert record.states.blocked is False
        assert record.runtime_hook_family in {"effect", "effect_meta", "meta"}
