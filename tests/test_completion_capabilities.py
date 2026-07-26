from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest
from dnd_sim.capability_evidence import PytestEvidenceRun
from dnd_sim.capability_manifest import manifest_to_json_text

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts/content/verify_completion_capabilities.py"
REBUILD_SCRIPT_PATH = REPO_ROOT / "scripts/content/rebuild_capability_artifacts.py"

spec = importlib.util.spec_from_file_location("verify_completion_capabilities", SCRIPT_PATH)
if spec is None or spec.loader is None:  # pragma: no cover
    raise RuntimeError(f"Unable to load module from {SCRIPT_PATH}")
verify_completion_capabilities = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = verify_completion_capabilities
spec.loader.exec_module(verify_completion_capabilities)

rebuild_spec = importlib.util.spec_from_file_location(
    "rebuild_capability_artifacts", REBUILD_SCRIPT_PATH
)
if rebuild_spec is None or rebuild_spec.loader is None:  # pragma: no cover
    raise RuntimeError(f"Unable to load module from {REBUILD_SCRIPT_PATH}")
rebuild_capability_artifacts = importlib.util.module_from_spec(rebuild_spec)
sys.modules[rebuild_spec.name] = rebuild_capability_artifacts
rebuild_spec.loader.exec_module(rebuild_capability_artifacts)


def _record(
    *,
    content_id: str,
    cataloged: bool = True,
    schema_valid: bool = True,
    executable: bool = False,
    tested: bool = False,
    blocked: bool = True,
    unsupported_reason: str | None = "runtime_hook_missing",
    evidence_ids: tuple[str, ...] | None = None,
) -> dict[str, object]:
    resolved_evidence_ids = evidence_ids
    if resolved_evidence_ids is None:
        resolved_evidence_ids = ("pytest.synthetic.v1",) if tested else ()
    return {
        "content_id": content_id,
        "evidence_ids": list(resolved_evidence_ids),
        "states": {
            "cataloged": cataloged,
            "schema_valid": schema_valid,
            "executable": executable,
            "tested": tested,
            "blocked": blocked,
            "unsupported_reason": unsupported_reason,
        },
    }


def _evidence_registry_payload(
    *,
    content_id: str = "spell:acid_arrow",
    evidence_id: str = "pytest.spell.acid_arrow.base_hit.v1",
    claims: tuple[str, ...] = ("base_hit_damage_resolution",),
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "ruleset": "2014",
        "evidence": [
            {
                "evidence_id": evidence_id,
                "kind": "pytest",
                "content_id": content_id,
                "claims": list(claims),
                "pytest_node_ids": ["tests/test_spell_evidence.py::test_acid_arrow_base_hit"],
            }
        ],
    }


def _supported_pack_payload(
    *,
    content_id: str = "spell:acid_arrow",
    claims: tuple[str, ...] = ("base_hit_damage_resolution",),
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "pack_id": "combat_primitives_v0",
        "ruleset": "2014",
        "support_contract": "verified_primary_combat_resolution_v1",
        "entries": [
            {
                "content_id": content_id,
                "required_claims": list(claims),
            }
        ],
    }


def _supported_manifest_payload(
    *,
    content_id: str = "spell:acid_arrow",
    tested: bool = True,
    evidence_ids: tuple[str, ...] = ("pytest.spell.acid_arrow.base_hit.v1",),
) -> dict[str, object]:
    record = _record(
        content_id=content_id,
        executable=True,
        tested=tested,
        blocked=False,
        unsupported_reason=None,
    )
    record["evidence_ids"] = list(evidence_ids)
    return {
        "manifest_version": "1.1",
        "generated_at": None,
        "records": [record],
    }


def test_repository_manifest_matches_canonical_builder_snapshot() -> None:
    canonical = rebuild_capability_artifacts.build_repository_manifest()
    manifest_path = REPO_ROOT / "artifacts" / "capabilities" / "manifest_2014.json"

    assert manifest_path.read_text(encoding="utf-8") == manifest_to_json_text(canonical)


def test_discover_shipped_ids_uses_canonical_builder_ids(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    spells_dir = repo_root / "db" / "rules" / "2014" / "spells"
    traits_dir = repo_root / "db" / "rules" / "2014" / "traits"
    monsters_dir = repo_root / "db" / "rules" / "2014" / "monsters"
    spells_dir.mkdir(parents=True, exist_ok=True)
    traits_dir.mkdir(parents=True, exist_ok=True)
    monsters_dir.mkdir(parents=True, exist_ok=True)

    (spells_dir / "acid_splash.json").write_text(
        json.dumps(
            {
                "name": "Acid Splash",
                "description": "You hurl acid at a creature.",
                "mechanics": [],
            }
        ),
        encoding="utf-8",
    )
    (traits_dir / "alert.json").write_text(
        json.dumps(
            {
                "name": "Alert",
                "source_type": "feat",
                "mechanics": [{"effect_type": "passive"}],
            }
        ),
        encoding="utf-8",
    )
    (monsters_dir / "elf,_drow.json").write_text(
        json.dumps(
            {
                "identity": {"enemy_id": "Elf, Drow"},
                "stat_block": {},
            }
        ),
        encoding="utf-8",
    )

    ids = verify_completion_capabilities.discover_shipped_2014_content_ids(repo_root)

    assert "spell:acid_splash" in ids
    assert "feat:alert" in ids
    assert "monster:elf_drow" in ids
    assert "monster:elf,_drow" not in ids


def test_manifest_completeness_gate_detects_missing_records() -> None:
    payload = {
        "manifest_version": "1.0",
        "generated_at": None,
        "records": [_record(content_id="spell:acid_splash")],
    }
    issues = verify_completion_capabilities.verify_manifest_payload(
        payload,
        expected_content_ids=("spell:acid_splash", "spell:fire_bolt"),
    )
    codes = {issue.code for issue in issues}
    assert "CAP-GATE-004" in codes


def test_default_gate_keeps_executable_and_tested_states_independent() -> None:
    payload = {
        "manifest_version": "1.0",
        "generated_at": None,
        "records": [
            _record(
                content_id="spell:acid_splash",
                executable=True,
                tested=False,
                blocked=False,
                unsupported_reason=None,
            )
        ],
    }
    issues = verify_completion_capabilities.verify_manifest_payload(
        payload,
        expected_content_ids=("spell:acid_splash",),
    )
    codes = {issue.code for issue in issues}
    assert "CAP-GATE-007" not in codes


@pytest.mark.parametrize(
    ("tested", "evidence_ids"),
    [
        (True, ()),
        (False, ("pytest.synthetic.v1",)),
    ],
)
def test_structural_gate_requires_tested_to_match_traceable_evidence(
    tested: bool,
    evidence_ids: tuple[str, ...],
) -> None:
    payload = {
        "manifest_version": "1.1",
        "generated_at": None,
        "records": [
            _record(
                content_id="spell:acid_arrow",
                executable=True,
                tested=tested,
                blocked=False,
                unsupported_reason=None,
                evidence_ids=evidence_ids,
            )
        ],
    }

    issues = verify_completion_capabilities.verify_manifest_payload(
        payload,
        expected_content_ids=("spell:acid_arrow",),
    )

    assert any(
        issue.code == "CAP-GATE-010" and "tested must equal bool(evidence_ids)" in issue.message
        for issue in issues
    )


def test_structural_gate_requires_evidence_ids_array() -> None:
    record = _record(content_id="spell:acid_arrow")
    del record["evidence_ids"]

    issues = verify_completion_capabilities.verify_manifest_payload(
        {
            "manifest_version": "1.1",
            "generated_at": None,
            "records": [record],
        },
        expected_content_ids=("spell:acid_arrow",),
    )

    assert any(
        issue.code == "CAP-GATE-003" and "evidence_ids must be an array" in issue.message
        for issue in issues
    )


def test_strict_gate_requires_tested_for_executable_records() -> None:
    payload = {
        "manifest_version": "1.0",
        "generated_at": None,
        "records": [
            _record(
                content_id="spell:acid_splash",
                executable=True,
                tested=False,
                blocked=False,
                unsupported_reason=None,
            )
        ],
    }

    issues = verify_completion_capabilities.verify_manifest_payload(
        payload,
        expected_content_ids=("spell:acid_splash",),
        strict=True,
    )
    codes = {issue.code for issue in issues}
    assert "CAP-GATE-007" in codes


@pytest.mark.parametrize(
    "unsupported_reason",
    ["", "runtime hook missing", "reason_a,reason_b"],
)
def test_unsupported_reason_coverage_gate_requires_single_reason_code(
    unsupported_reason: str,
) -> None:
    payload = {
        "manifest_version": "1.0",
        "generated_at": None,
        "records": [
            _record(
                content_id="trait:rage",
                unsupported_reason=unsupported_reason,
            )
        ],
    }
    issues = verify_completion_capabilities.verify_manifest_payload(
        payload,
        expected_content_ids=("trait:rage",),
    )
    codes = {issue.code for issue in issues}
    assert "CAP-GATE-009" in codes


def test_cli_returns_nonzero_on_invalid_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest_2014.json"
    manifest_path.write_text(json.dumps({"records": []}), encoding="utf-8")

    exit_code = verify_completion_capabilities.main(
        [
            "--repo-root",
            str(REPO_ROOT),
            "--manifest-path",
            str(manifest_path),
        ]
    )

    assert exit_code == 1


def test_legacy_flat_state_fields_are_rejected() -> None:
    payload = {
        "manifest_version": "1.0",
        "generated_at": None,
        "records": [
            {
                "content_id": "spell:acid_splash",
                "cataloged": True,
                "schema_valid": True,
                "executable": False,
                "tested": False,
                "blocked": True,
                "unsupported_reason": "runtime_hook_missing",
            }
        ],
    }

    issues = verify_completion_capabilities.verify_manifest_payload(
        payload,
        expected_content_ids=("spell:acid_splash",),
    )
    assert any(
        issue.code == "CAP-GATE-003" and "legacy flat capability fields" in issue.message
        for issue in issues
    )


def test_invalid_records_array_preserves_header_issues() -> None:
    payload = {
        "records": "oops",
    }

    issues = verify_completion_capabilities.verify_manifest_payload(
        payload,
        expected_content_ids=(),
    )
    messages = [issue.message for issue in issues]
    assert "manifest payload must declare non-empty manifest_version." in messages
    assert "manifest payload must contain a records array." in messages


def test_default_mode_allows_blocked_records_with_reason_code() -> None:
    payload = {
        "manifest_version": "1.0",
        "generated_at": None,
        "records": [
            _record(
                content_id="trait:rage",
                executable=False,
                tested=False,
                blocked=True,
                unsupported_reason="runtime_hook_missing",
            )
        ],
    }

    issues = verify_completion_capabilities.verify_manifest_payload(
        payload,
        expected_content_ids=("trait:rage",),
    )
    assert issues == []


def test_default_structural_mode_allows_schema_invalid_content_when_blocked() -> None:
    payload = {
        "manifest_version": "1.0",
        "generated_at": None,
        "records": [
            _record(
                content_id="trait:unsupported_shape",
                schema_valid=False,
                executable=False,
                tested=False,
                blocked=True,
                unsupported_reason="invalid_mechanics_schema",
            )
        ],
    }

    issues = verify_completion_capabilities.verify_manifest_payload(
        payload,
        expected_content_ids=("trait:unsupported_shape",),
    )

    assert issues == []


@pytest.mark.parametrize(
    "record",
    [
        _record(
            content_id="trait:bad_executable",
            schema_valid=False,
            executable=True,
            blocked=False,
            unsupported_reason=None,
        ),
        _record(
            content_id="trait:bad_tested",
            executable=False,
            tested=True,
            blocked=True,
            unsupported_reason="runtime_hook_missing",
        ),
    ],
)
def test_default_structural_mode_rejects_contradictory_state_dependencies(
    record: dict[str, object],
) -> None:
    content_id = str(record["content_id"])
    issues = verify_completion_capabilities.verify_manifest_payload(
        {
            "manifest_version": "1.0",
            "generated_at": None,
            "records": [record],
        },
        expected_content_ids=(content_id,),
    )

    assert any(issue.code == "CAP-GATE-010" for issue in issues)


def test_strict_mode_rejects_blocked_record_even_with_reason_code() -> None:
    payload = {
        "manifest_version": "1.0",
        "generated_at": None,
        "records": [
            _record(
                content_id="trait:rage",
                executable=False,
                tested=False,
                blocked=True,
                unsupported_reason="runtime_hook_missing",
            )
        ],
    }

    issues = verify_completion_capabilities.verify_manifest_payload(
        payload,
        expected_content_ids=("trait:rage",),
        strict=True,
    )
    assert any(issue.code == "CAP-GATE-011" for issue in issues)


def test_strict_mode_accepts_fully_green_record() -> None:
    payload = {
        "manifest_version": "1.0",
        "generated_at": None,
        "records": [
            _record(
                content_id="feat:sharpshooter",
                executable=True,
                tested=True,
                blocked=False,
                unsupported_reason=None,
            )
        ],
    }

    issues = verify_completion_capabilities.verify_manifest_payload(
        payload,
        expected_content_ids=("feat:sharpshooter",),
        strict=True,
    )
    assert issues == []


def test_cli_strict_returns_nonzero_for_blocked_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest_2014.json"
    payload = {
        "manifest_version": "1.0",
        "generated_at": None,
        "records": [
            _record(
                content_id="spell:acid_splash",
                executable=False,
                tested=False,
                blocked=True,
                unsupported_reason="runtime_hook_missing",
            )
        ],
    }
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    repo_root = tmp_path / "repo"
    (repo_root / "db" / "rules" / "2014" / "spells").mkdir(parents=True, exist_ok=True)
    (repo_root / "db" / "rules" / "2014" / "spells" / "acid_splash.json").write_text(
        json.dumps(
            {
                "name": "Acid Splash",
                "description": "You hurl acid at a creature.",
                "mechanics": [],
            }
        ),
        encoding="utf-8",
    )

    exit_code = verify_completion_capabilities.main(
        [
            "--repo-root",
            str(repo_root),
            "--manifest-path",
            str(manifest_path),
            "--strict",
        ]
    )
    assert exit_code == 1


def test_supported_pack_gate_requires_green_state_and_exact_evidence_ids(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    registry_path = tmp_path / "evidence.json"
    pack_path = tmp_path / "pack.json"
    manifest_path.write_text(
        json.dumps(
            _supported_manifest_payload(
                tested=False,
                evidence_ids=("pytest.spell.acid_arrow.wrong.v1",),
            )
        ),
        encoding="utf-8",
    )
    registry_path.write_text(json.dumps(_evidence_registry_payload()), encoding="utf-8")
    pack_path.write_text(json.dumps(_supported_pack_payload()), encoding="utf-8")

    plan, issues = verify_completion_capabilities.verify_supported_pack_capabilities(
        repo_root=tmp_path,
        manifest_path=manifest_path,
        supported_pack_path=pack_path,
        evidence_registry_path=registry_path,
    )

    assert plan is None
    assert {issue.code for issue in issues} == {"CAP-PACK-002", "CAP-PACK-003"}
    assert any("tested=true" in issue.message for issue in issues)
    assert any("exactly match" in issue.message for issue in issues)


def test_supported_pack_gate_rejects_unproven_required_claims(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    registry_path = tmp_path / "evidence.json"
    pack_path = tmp_path / "pack.json"
    manifest_path.write_text(json.dumps(_supported_manifest_payload()), encoding="utf-8")
    registry_path.write_text(json.dumps(_evidence_registry_payload()), encoding="utf-8")
    pack_path.write_text(
        json.dumps(_supported_pack_payload(claims=("failed_save_forced_movement",))),
        encoding="utf-8",
    )

    plan, issues = verify_completion_capabilities.verify_supported_pack_capabilities(
        repo_root=tmp_path,
        manifest_path=manifest_path,
        supported_pack_path=pack_path,
        evidence_registry_path=registry_path,
    )

    assert plan is None
    assert len(issues) == 1
    assert issues[0].code == "CAP-PACK-001"
    assert "missing required claims" in issues[0].message


def test_cli_supported_pack_executes_only_resolved_exact_evidence_nodes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = tmp_path / "repo"
    spells_dir = repo_root / "db" / "rules" / "2014" / "spells"
    spells_dir.mkdir(parents=True)
    (spells_dir / "acid_arrow.json").write_text(
        json.dumps(
            {
                "name": "Acid Arrow",
                "description": "A magical arrow deals acid damage.",
                "mechanics": [{"effect_type": "damage", "damage": "4d4"}],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = repo_root / "manifest.json"
    registry_path = repo_root / "evidence.json"
    pack_path = repo_root / "pack.json"
    manifest_path.write_text(json.dumps(_supported_manifest_payload()), encoding="utf-8")
    registry_path.write_text(json.dumps(_evidence_registry_payload()), encoding="utf-8")
    pack_path.write_text(json.dumps(_supported_pack_payload()), encoding="utf-8")

    observed: dict[str, object] = {}

    def _run_exact_nodes(node_ids, *, repo_root: Path):
        observed["node_ids"] = tuple(node_ids)
        observed["repo_root"] = repo_root
        return PytestEvidenceRun(
            node_ids=tuple(node_ids),
            passed_count=len(tuple(node_ids)),
        )

    monkeypatch.setattr(verify_completion_capabilities, "run_exact_pytest_nodes", _run_exact_nodes)

    exit_code = verify_completion_capabilities.main(
        [
            "--repo-root",
            str(repo_root),
            "--manifest-path",
            str(manifest_path),
            "--supported-pack",
            str(pack_path),
            "--evidence-registry",
            str(registry_path),
        ]
    )

    assert exit_code == 0
    assert observed == {
        "node_ids": ("tests/test_spell_evidence.py::test_acid_arrow_base_hit",),
        "repo_root": repo_root,
    }
    output = capsys.readouterr().out
    assert "combat_primitives_v0" in output
    assert "1 exact behavioral evidence test" in output


def test_cli_supported_pack_reports_evidence_execution_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = REPO_ROOT / "artifacts" / "capabilities" / "manifest_2014.json"
    registry_path = tmp_path / "evidence.json"
    pack_path = tmp_path / "pack.json"
    registry_path.write_text(json.dumps(_evidence_registry_payload()), encoding="utf-8")
    pack_path.write_text(json.dumps(_supported_pack_payload()), encoding="utf-8")

    monkeypatch.setattr(
        verify_completion_capabilities,
        "verify_completion_capabilities",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        verify_completion_capabilities,
        "run_exact_pytest_nodes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            verify_completion_capabilities.CapabilityEvidenceError("synthetic test failure")
        ),
    )
    monkeypatch.setattr(
        verify_completion_capabilities,
        "verify_supported_pack_capabilities",
        lambda **_kwargs: (
            verify_completion_capabilities.SupportedPackEvidencePlan(
                pack_id="combat_primitives_v0",
                ruleset="2014",
                content_ids=("spell:acid_arrow",),
                evidence_ids=("pytest.spell.acid_arrow.base_hit.v1",),
                pytest_node_ids=("tests/test_spell_evidence.py::test_acid_arrow_base_hit",),
            ),
            [],
        ),
    )

    exit_code = verify_completion_capabilities.main(
        [
            "--repo-root",
            str(REPO_ROOT),
            "--manifest-path",
            str(manifest_path),
            "--supported-pack",
            str(pack_path),
            "--evidence-registry",
            str(registry_path),
        ]
    )

    assert exit_code == 1
    assert "CAP-PACK-004: synthetic test failure" in capsys.readouterr().out


def test_capability_workflows_cover_canonical_content_and_current_pull_requests() -> None:
    completion_workflow = (
        REPO_ROOT / ".github/workflows/completion-capability-gate.yml"
    ).read_text(encoding="utf-8")
    content_workflow = (REPO_ROOT / ".github/workflows/content-capability-gate.yml").read_text(
        encoding="utf-8"
    )

    assert 'branches:\n      - "int/5i-completion-gates"' not in completion_workflow
    for required_path in (
        '"db/rules/2014/**"',
        '"src/dnd_sim/capability_manifest.py"',
        '"src/dnd_sim/mechanics_schema.py"',
    ):
        assert required_path in completion_workflow
        assert required_path in content_workflow


def test_rebuild_report_uses_the_regeneration_date(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class FixedDate(date):
        @classmethod
        def today(cls) -> "FixedDate":
            return cls(2026, 7, 26)

    def _record_call(args, **_kwargs) -> None:
        calls.append([str(value) for value in args])

    monkeypatch.setattr(rebuild_capability_artifacts, "date", FixedDate)
    monkeypatch.setattr(rebuild_capability_artifacts.subprocess, "run", _record_call)

    rebuild_capability_artifacts.rebuild_report()

    assert calls[0][-2:] == ["--last-updated", "2026-07-26"]
