from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from dnd_sim.capability_manifest import CapabilityRecord, CapabilityStates

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts/content/render_capability_report.py"

spec = importlib.util.spec_from_file_location("render_capability_report", SCRIPT_PATH)
if spec is None or spec.loader is None:  # pragma: no cover
    raise RuntimeError(f"Unable to load module from {SCRIPT_PATH}")
render_capability_report = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = render_capability_report
spec.loader.exec_module(render_capability_report)


def _record(
    *,
    content_id: str,
    content_type: str,
    blocked: bool,
    unsupported_reason: str | None = None,
    support_state: str | None = None,
    runtime_hook_family: str | None = None,
) -> CapabilityRecord:
    return CapabilityRecord(
        content_id=content_id,
        content_type=content_type,
        support_state=support_state,
        runtime_hook_family=runtime_hook_family,
        states=CapabilityStates(
            cataloged=True,
            schema_valid=True,
            executable=not blocked,
            tested=not blocked,
            blocked=blocked,
            unsupported_reason=unsupported_reason,
        ),
    )


def test_build_coverage_report_aggregates_expected_counts() -> None:
    report = render_capability_report.build_coverage_report(
        records=[
            _record(
                content_id="spell:arc_flash",
                content_type="spell",
                blocked=False,
                support_state="supported",
                runtime_hook_family="effect",
            ),
            _record(
                content_id="monster_action:ogre:stone_throw",
                content_type="monster_action",
                blocked=True,
                unsupported_reason="unsupported_action_cost",
            ),
            _record(
                content_id="feat:warding_guard",
                content_type="feat",
                blocked=True,
                support_state="unsupported",
                unsupported_reason="missing_runtime_hook_family",
                runtime_hook_family="narrative",
            ),
        ]
    )

    assert report["summary"] == {
        "total_records": 3,
        "supported_records": 1,
        "blocked_records": 2,
        "schema_valid_records": 3,
        "executable_records": 1,
        "tested_records": 1,
    }
    assert report["unsupported_reason_coverage"] == [
        {"count": 1, "unsupported_reason": "missing_runtime_hook_family"},
        {"count": 1, "unsupported_reason": "unsupported_action_cost"},
    ]


def test_cli_outputs_are_stable_and_sorted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    records = [
        _record(content_id="spell:zeta", content_type="spell", blocked=False),
        _record(
            content_id="feat:alpha",
            content_type="feat",
            blocked=True,
            unsupported_reason="missing_runtime_hook_family",
        ),
        _record(content_id="spell:alpha", content_type="spell", blocked=False),
    ]

    json_out = tmp_path / "artifacts" / "capabilities" / "coverage_report.json"
    markdown_out = tmp_path / "docs" / "program" / "capability_report.md"

    monkeypatch.setattr(
        render_capability_report,
        "collect_capability_records",
        lambda: list(records),
    )
    assert (
        render_capability_report.main(
            [
                "--json-out",
                str(json_out),
                "--markdown-out",
                str(markdown_out),
                "--last-updated",
                "2026-03-05",
            ]
        )
        == 0
    )

    first_json = json_out.read_text(encoding="utf-8")
    payload = json.loads(first_json)
    assert [row["content_id"] for row in payload["records"]] == [
        "feat:alpha",
        "spell:alpha",
        "spell:zeta",
    ]

    records.reverse()
    assert (
        render_capability_report.main(
            [
                "--json-out",
                str(json_out),
                "--markdown-out",
                str(markdown_out),
                "--last-updated",
                "2026-03-05",
            ]
        )
        == 0
    )
    second_json = json_out.read_text(encoding="utf-8")

    assert first_json == second_json


def test_render_markdown_report_snapshot() -> None:
    report = render_capability_report.build_coverage_report(
        records=[
            _record(
                content_id="feat:alpha",
                content_type="feat",
                blocked=False,
                support_state="supported",
                runtime_hook_family="effect",
            ),
            _record(
                content_id="spell:beta",
                content_type="spell",
                blocked=True,
                unsupported_reason="unsupported_effect_type",
            ),
        ]
    )

    markdown = render_capability_report.render_markdown_report(
        report=report,
        json_path=Path("artifacts/capabilities/coverage_report.json"),
        last_updated="2026-03-05",
    )

    expected = """# Capability Report

Status: canonical
Owner: content-manifest
Last updated: 2026-03-05
Canonical source: `artifacts/capabilities/coverage_report.json`

This report is generated by `scripts/content/render_capability_report.py`.
Do not edit manually.

## Artifacts

- Machine-readable JSON: `artifacts/capabilities/coverage_report.json`

## Coverage Summary

| Metric | Value |
|---|---:|
| Total records | 2 |
| Supported records | 1 |
| Blocked records | 1 |
| Schema-valid records | 2 |
| Executable records | 1 |
| Tested records | 1 |

## Coverage By Content Type

| Content type | Total | Supported | Blocked | Schema valid | Executable | Tested |
|---|---:|---:|---:|---:|---:|---:|
| feat | 1 | 1 | 0 | 1 | 1 | 1 |
| spell | 1 | 0 | 1 | 1 | 0 | 0 |

## Unsupported Reason Coverage

| Unsupported reason | Count |
|---|---:|
| unsupported_effect_type | 1 |
"""

    assert markdown == expected
