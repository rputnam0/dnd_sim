from __future__ import annotations

from pathlib import Path
import re

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_GOVERNANCE_PATH = REPO_ROOT / "docs/program/doc_governance.md"
PROGRAM_README_PATH = REPO_ROOT / "docs/program/README.md"
REQUIRED_METADATA_KEYS = ("Status", "Owner", "Last updated", "Canonical source")


def _parse_metadata_header(markdown: str) -> dict[str, str]:
    header: dict[str, str] = {}
    for line in markdown.splitlines()[1:24]:
        stripped = line.strip()
        if not stripped and header:
            break
        match = re.match(r"^(Status|Owner|Last updated|Canonical source):\s*(.+?)\s*$", stripped)
        if match:
            header[match.group(1)] = match.group(2)
        elif header and stripped:
            break

    missing = [key for key in REQUIRED_METADATA_KEYS if key not in header]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"Missing metadata header keys: {missing_text}")
    return header


def _parse_markdown_table(markdown: str, heading: str) -> list[dict[str, str]]:
    lines = markdown.splitlines()
    try:
        heading_index = lines.index(heading)
    except ValueError as error:
        raise AssertionError(f"Heading '{heading}' not found.") from error

    table_start: int | None = None
    for index in range(heading_index + 1, len(lines)):
        if lines[index].startswith("|"):
            table_start = index
            break
    if table_start is None:
        raise AssertionError(f"No markdown table found under heading '{heading}'.")

    table_lines: list[str] = []
    for line in lines[table_start:]:
        if not line.startswith("|"):
            break
        table_lines.append(line)

    if len(table_lines) < 2:
        raise AssertionError(f"Table under '{heading}' is incomplete.")

    headers = [cell.strip() for cell in table_lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for raw_row in table_lines[2:]:
        values = [cell.strip() for cell in raw_row.strip("|").split("|")]
        if len(values) != len(headers):
            continue
        rows.append(dict(zip(headers, values, strict=True)))
    return rows


def _normalize_path(path_cell: str) -> str:
    return path_cell.strip().strip("`")


def test_metadata_header_parser_requires_all_required_fields() -> None:
    canonical_doc = (
        "# Example\n\n"
        "Status: canonical\n"
        "Owner: doc_control_a\n"
        "Last updated: 2026-03-05\n"
        "Canonical source: `docs/program/README.md`\n\n"
        "Body.\n"
    )
    parsed = _parse_metadata_header(canonical_doc)
    assert parsed["Status"] == "canonical"
    assert parsed["Owner"] == "doc_control_a"
    assert parsed["Last updated"] == "2026-03-05"
    assert parsed["Canonical source"] == "`docs/program/README.md`"

    missing_owner = (
        "# Example\n\n"
        "Status: canonical\n"
        "Last updated: 2026-03-05\n"
        "Canonical source: `docs/program/README.md`\n\n"
    )
    with pytest.raises(ValueError, match="Owner"):
        _parse_metadata_header(missing_owner)


def test_doc_governance_registry_is_complete_and_headers_exist_for_live_markdown_docs() -> None:
    governance_text = DOC_GOVERNANCE_PATH.read_text(encoding="utf-8")
    readme_text = PROGRAM_README_PATH.read_text(encoding="utf-8")

    governance_rows = _parse_markdown_table(
        governance_text,
        "## Live planning registry and ownership",
    )
    readme_rows = _parse_markdown_table(readme_text, "## Planning document registry")

    governance_paths = {_normalize_path(row["Path"]) for row in governance_rows}
    readme_paths = {_normalize_path(row["Path"]) for row in readme_rows}
    assert governance_paths == readme_paths

    for row in governance_rows:
        path_text = _normalize_path(row["Path"])
        path = REPO_ROOT / path_text
        assert path.exists(), f"Registered planning path is missing: {path_text}"
        assert row["Owner"] not in {"", "-"}, f"Missing owner for {path_text}"

        status = row["Status"]
        assert status in {"canonical", "historical", "canonical after CAP-06"}

        metadata_requirement = row["Metadata header"].lower()
        assert metadata_requirement in {"required", "not_applicable"}
        if metadata_requirement == "required":
            assert (
                path.suffix == ".md"
            ), f"Metadata header should apply to markdown only: {path_text}"
            _parse_metadata_header(path.read_text(encoding="utf-8"))
