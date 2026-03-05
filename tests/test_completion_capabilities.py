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


def _record(
    *,
    content_id: str,
    cataloged: bool = True,
    schema_valid: bool = True,
    executable: bool = False,
    tested: bool = False,
    blocked: bool = True,
    unsupported_reason: str | None = "runtime_hook_missing",
) -> dict[str, object]:
    return {
        "content_id": content_id,
        "states": {
            "cataloged": cataloged,
            "schema_valid": schema_valid,
            "executable": executable,
            "tested": tested,
            "blocked": blocked,
            "unsupported_reason": unsupported_reason,
        },
    }


def test_repository_manifest_passes_completion_capability_gate() -> None:
    issues = verify_completion_capabilities.verify_completion_capabilities(REPO_ROOT)
    assert issues == []


def test_manifest_completeness_gate_detects_missing_records() -> None:
    payload = {
        "manifest_version": "1.0",
        "generated_at": None,
        "records": [
            _record(content_id="spell:acid_splash")
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
        "manifest_version": "1.0",
        "generated_at": None,
        "records": [
            _record(
                content_id="trait:rage",
                unsupported_reason=unsupported_reason,
            )
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
        "{}",
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
