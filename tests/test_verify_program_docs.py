from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts/docs/verify_program_docs.py"
FIXTURE_ROOT = REPO_ROOT / "tests/fixtures/doc_checker"

spec = importlib.util.spec_from_file_location("verify_program_docs", SCRIPT_PATH)
if spec is None or spec.loader is None:  # pragma: no cover
    raise RuntimeError(f"Unable to load module from {SCRIPT_PATH}")
verify_program_docs = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = verify_program_docs
spec.loader.exec_module(verify_program_docs)


def test_parse_metadata_header_requires_all_keys() -> None:
    markdown = (
        "# Example\n\n"
        "Status: canonical\n"
        "Owner: program-control\n"
        "Last updated: 2026-03-05\n"
        "Canonical source: `docs/program/README.md`\n\n"
    )
    parsed = verify_program_docs.parse_metadata_header(markdown)
    assert parsed["Status"] == "canonical"
    assert parsed["Owner"] == "program-control"
    assert parsed["Last updated"] == "2026-03-05"
    assert parsed["Canonical source"] == "`docs/program/README.md`"

    missing_owner = (
        "# Example\n\n"
        "Status: canonical\n"
        "Last updated: 2026-03-05\n"
        "Canonical source: `docs/program/README.md`\n\n"
    )
    with pytest.raises(ValueError, match="Owner"):
        verify_program_docs.parse_metadata_header(missing_owner)


def test_parse_markdown_table_returns_expected_rows() -> None:
    markdown = (
        "# Example\n\n"
        "## Planning\n\n"
        "| Path | Status |\n"
        "|---|---|\n"
        "| `docs/program/README.md` | canonical |\n"
    )
    rows = verify_program_docs.parse_markdown_table(markdown, "## Planning")
    assert rows == [{"Path": "`docs/program/README.md`", "Status": "canonical"}]


@pytest.mark.parametrize(
    ("task_statuses", "expected"),
    [
        (["blocked", "in_progress"], "blocked"),
        (["in_progress", "pr_open"], "in_progress"),
        (["pr_open"], "pr_open"),
        (["merged", "merged"], "merged"),
        (["not_started"], "not_started"),
        ([], "not_started"),
    ],
)
def test_expected_track_status_prioritizes_highest_progress_state(
    task_statuses: list[str],
    expected: str,
) -> None:
    assert verify_program_docs.expected_track_status(task_statuses) == expected


def test_verify_program_docs_detects_stale_status_fixture() -> None:
    fixture_root = FIXTURE_ROOT / "stale_status"
    issues = verify_program_docs.verify_program_docs(fixture_root)
    issue_codes = {issue.code for issue in issues}
    assert "DOC-SYNC-008" in issue_codes


def test_verify_program_docs_detects_missing_metadata_fixture() -> None:
    fixture_root = FIXTURE_ROOT / "missing_metadata"
    issues = verify_program_docs.verify_program_docs(fixture_root)
    issue_codes = {issue.code for issue in issues}
    assert "DOC-LIVE-005" in issue_codes
