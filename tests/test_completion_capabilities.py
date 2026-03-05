from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts/content/verify_completion_capabilities.py"

spec = importlib.util.spec_from_file_location("verify_completion_capabilities", SCRIPT_PATH)
if spec is None or spec.loader is None:  # pragma: no cover
    raise RuntimeError(f"Unable to load module from {SCRIPT_PATH}")
verify_completion_capabilities = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = verify_completion_capabilities
spec.loader.exec_module(verify_completion_capabilities)


def test_repository_manifest_passes_completion_capability_gate() -> None:
    issues = verify_completion_capabilities.verify_completion_capabilities(REPO_ROOT)
    assert issues == []


def test_manifest_completeness_gate_detects_missing_records() -> None:
    payload = {
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
        ]
    }
    issues = verify_completion_capabilities.verify_manifest_payload(
        payload,
        expected_content_ids=("spell:acid_splash", "spell:fire_bolt"),
    )
    codes = {issue.code for issue in issues}
    assert "CAP-GATE-004" in codes


def test_supported_scope_gate_requires_tested_for_executable_records() -> None:
    payload = {
        "records": [
            {
                "content_id": "spell:acid_splash",
                "cataloged": True,
                "schema_valid": True,
                "executable": True,
                "tested": False,
                "blocked": False,
                "unsupported_reason": "",
            }
        ]
    }
    issues = verify_completion_capabilities.verify_manifest_payload(
        payload,
        expected_content_ids=("spell:acid_splash",),
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
        "records": [
            {
                "content_id": "trait:rage",
                "cataloged": True,
                "schema_valid": True,
                "executable": False,
                "tested": False,
                "blocked": True,
                "unsupported_reason": unsupported_reason,
            }
        ]
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
