from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from dnd_sim import capability_manifest
from dnd_sim.capability_manifest import (
    CapabilityRecord,
    CapabilityStates,
    CapabilityManifest,
    apply_capability_evidence,
    build_manifest,
    manifest_to_json_text,
    read_manifest,
    write_manifest,
)
from dnd_sim.capability_evidence import CapabilityTestEvidenceRegistry, EvidenceRecord


def _states(*, blocked: bool = False, unsupported_reason: str | None = None) -> dict[str, object]:
    return {
        "cataloged": True,
        "schema_valid": True,
        "executable": not blocked,
        "tested": not blocked,
        "blocked": blocked,
        "unsupported_reason": unsupported_reason,
    }


def _record(
    *,
    content_id: str,
    content_type: str,
    blocked: bool = False,
    unsupported_reason: str | None = None,
) -> dict[str, object]:
    return {
        "content_id": content_id,
        "content_type": content_type,
        "states": _states(blocked=blocked, unsupported_reason=unsupported_reason),
        "evidence_ids": [] if blocked else ["pytest.fixture.behavior.v1"],
    }


def test_tested_state_requires_traceable_evidence_ids() -> None:
    payload = _record(content_id="spell:shield|PHB", content_type="spell")
    payload["evidence_ids"] = []

    with pytest.raises(ValidationError, match="tested must equal bool\\(evidence_ids\\)"):
        CapabilityRecord.model_validate(payload)


def test_evidence_ids_require_tested_executable_unblocked_content() -> None:
    payload = _record(
        content_id="feat:alert|PHB",
        content_type="feat",
        blocked=True,
        unsupported_reason="runtime_missing",
    )
    states = payload["states"]
    assert isinstance(states, dict)
    states["tested"] = True
    payload["evidence_ids"] = ["pytest.fixture.behavior.v1"]

    with pytest.raises(
        ValidationError,
        match="evidence_ids require schema-valid, executable, unblocked content",
    ):
        CapabilityRecord.model_validate(payload)


def test_evidence_ids_are_unique_valid_and_canonically_sorted() -> None:
    payload = _record(content_id="spell:shield|PHB", content_type="spell")
    payload["evidence_ids"] = ["pytest.zeta.v1", "pytest.alpha.v1"]

    record = CapabilityRecord.model_validate(payload)
    assert record.evidence_ids == ("pytest.alpha.v1", "pytest.zeta.v1")

    payload["evidence_ids"] = ["pytest.duplicate.v1", "pytest.duplicate.v1"]
    with pytest.raises(ValidationError, match="evidence_ids must be unique"):
        CapabilityRecord.model_validate(payload)

    payload["evidence_ids"] = ["invalid evidence id"]
    with pytest.raises(ValidationError, match="invalid evidence identifier"):
        CapabilityRecord.model_validate(payload)


def test_apply_capability_evidence_overlays_exact_test_provenance() -> None:
    records = [
        CapabilityRecord(
            content_id="spell:shield",
            content_type="spell",
            states=CapabilityStates(
                cataloged=True,
                schema_valid=True,
                executable=True,
                tested=False,
                blocked=False,
                unsupported_reason=None,
            ),
        ),
        CapabilityRecord(
            content_id="spell:untested",
            content_type="spell",
            states=CapabilityStates(
                cataloged=True,
                schema_valid=True,
                executable=True,
                tested=False,
                blocked=False,
                unsupported_reason=None,
            ),
        ),
    ]
    registry = CapabilityTestEvidenceRegistry(
        schema_version="1.0",
        ruleset="2014",
        evidence=(
            EvidenceRecord(
                evidence_id="pytest.spell.shield.base_effect.v1",
                kind="pytest",
                content_id="spell:shield",
                claims=("base_effect_resolution",),
                pytest_node_ids=(
                    "tests/test_capability_manifest_schema.py::test_apply_capability_evidence_overlays_exact_test_provenance",
                ),
            ),
        ),
    )

    overlaid = apply_capability_evidence(records=records, registry=registry)
    by_id = {record.content_id: record for record in overlaid}

    assert by_id["spell:shield"].states.tested is True
    assert by_id["spell:shield"].evidence_ids == ("pytest.spell.shield.base_effect.v1",)
    assert by_id["spell:untested"].states.tested is False
    assert by_id["spell:untested"].evidence_ids == ()


def test_manifest_schema_requires_all_capability_states() -> None:
    payload = {
        "manifest_version": "1.0",
        "records": [
            {
                "content_id": "spell:acid_splash|PHB",
                "content_type": "spell",
                "states": {
                    "cataloged": True,
                    "executable": True,
                    "tested": True,
                    "blocked": False,
                    "unsupported_reason": None,
                },
            }
        ],
    }

    with pytest.raises(ValidationError, match="schema_valid"):
        CapabilityManifest.model_validate(payload)


def test_manifest_schema_requires_unsupported_reason_when_blocked() -> None:
    payload = {
        "manifest_version": "1.0",
        "records": [
            _record(
                content_id="trait:arcane_recovery|PHB",
                content_type="trait",
                blocked=True,
                unsupported_reason=None,
            )
        ],
    }

    with pytest.raises(ValidationError, match="unsupported_reason"):
        CapabilityManifest.model_validate(payload)


def test_manifest_schema_rejects_unsupported_reason_for_supported_record() -> None:
    payload = {
        "manifest_version": "1.0",
        "records": [
            _record(
                content_id="spell:shield|PHB",
                content_type="spell",
                blocked=False,
                unsupported_reason="not_implemented",
            )
        ],
    }

    with pytest.raises(ValidationError, match="unsupported_reason"):
        CapabilityManifest.model_validate(payload)


def test_manifest_round_trip_uses_canonical_ordering(tmp_path: Path) -> None:
    manifest = build_manifest(
        records=[
            _record(content_id="spell:shield|PHB", content_type="spell"),
            _record(
                content_id="feat:alert|PHB",
                content_type="feat",
                blocked=True,
                unsupported_reason="runtime_missing",
            ),
        ],
        manifest_version="1.0",
    )
    out_path = tmp_path / "capabilities.json"

    write_manifest(manifest, out_path)
    loaded = read_manifest(out_path)

    assert [row.content_id for row in loaded.records] == ["feat:alert|PHB", "spell:shield|PHB"]
    assert loaded.model_dump(mode="json") == manifest.model_dump(mode="json")
    assert out_path.read_text(encoding="utf-8") == manifest_to_json_text(loaded)


def test_capability_manifest_cli_smoke_emits_deterministic_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = {
        "manifest_version": "1.0",
        "records": [
            _record(content_id="spell:shield|PHB", content_type="spell"),
            _record(
                content_id="feat:alert|PHB",
                content_type="feat",
                blocked=True,
                unsupported_reason="runtime_missing",
            ),
        ],
    }
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(input_payload), encoding="utf-8")

    out_path = tmp_path / "artifacts" / "capabilities" / "manifest.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dnd_sim.capability_manifest",
            "--input",
            str(input_path),
            "--out",
            str(out_path),
        ],
    )

    capability_manifest.main()

    emitted = read_manifest(out_path)
    assert [row.content_id for row in emitted.records] == ["feat:alert|PHB", "spell:shield|PHB"]
    assert out_path.read_text(encoding="utf-8") == manifest_to_json_text(emitted)
