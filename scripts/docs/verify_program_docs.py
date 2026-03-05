from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_GOVERNANCE_PATH = Path("docs/program/doc_governance.md")
PROGRAM_README_PATH = Path("docs/program/README.md")
STATUS_BOARD_PATH = Path("docs/program/status_board.md")
BACKLOG_PATH = Path("docs/program/backlog.csv")

LIVE_ENTRYPOINTS = (
    Path("docs/program/README.md"),
    Path("docs/plan.md"),
    Path("docs/agent_feature_assignments.md"),
)

REQUIRED_METADATA_KEYS = ("Status", "Owner", "Last updated", "Canonical source")
ALLOWED_REGISTRY_STATUSES = {"canonical", "historical", "canonical after CAP-06"}
ALLOWED_METADATA_RULES = {"required", "not_applicable"}
ACTIVE_TASK_STATUSES = {"in_progress", "blocked", "pr_open"}
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
INLINE_DOC_PATH_RE = re.compile(r"`((?:\./)?docs/[^`\s]+)`")
LAST_UPDATED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    path: Path | None = None
    line: int | None = None

    def render(self) -> str:
        location = ""
        if self.path is not None:
            location = str(self.path)
            if self.line is not None:
                location = f"{location}:{self.line}"
            location = f" [{location}]"
        return f"{self.code}{location}: {self.message}"


@dataclass(frozen=True)
class RegistryRow:
    path: str
    status: str
    owner: str
    metadata_header: str


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalize_doc_path(path_text: str) -> str:
    normalized = path_text.strip().strip("`")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith("/"):
        normalized = normalized[1:]
    return normalized


def parse_metadata_header(markdown: str) -> dict[str, str]:
    header: dict[str, str] = {}
    for line in markdown.splitlines()[1:30]:
        stripped = line.strip()
        if not stripped and header:
            break
        match = re.match(
            r"^(Status|Owner|Last updated|Canonical source):\s*(.+?)\s*$",
            stripped,
        )
        if match:
            header[match.group(1)] = match.group(2)
        elif header and stripped:
            break

    missing = [key for key in REQUIRED_METADATA_KEYS if key not in header]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"Missing metadata header keys: {missing_text}")
    return header


def parse_markdown_table(markdown: str, heading: str) -> list[dict[str, str]]:
    lines = markdown.splitlines()
    heading_index: int | None = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            heading_index = index
            break
    if heading_index is None:
        raise ValueError(f"Heading '{heading}' not found")

    table_start: int | None = None
    for index in range(heading_index + 1, len(lines)):
        if lines[index].strip().startswith("|"):
            table_start = index
            break
        if lines[index].strip().startswith("#"):
            break
    if table_start is None:
        raise ValueError(f"No markdown table under heading '{heading}'")

    table_lines: list[str] = []
    for line in lines[table_start:]:
        if not line.strip().startswith("|"):
            break
        table_lines.append(line.strip())

    if len(table_lines) < 2:
        raise ValueError(f"Table under heading '{heading}' is incomplete")

    headers = [cell.strip() for cell in table_lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for raw_row in table_lines[2:]:
        values = [cell.strip() for cell in raw_row.strip("|").split("|")]
        if len(values) != len(headers):
            raise ValueError(
                f"Malformed row in table '{heading}': expected {len(headers)} cells, got {len(values)}"
            )
        rows.append(dict(zip(headers, values, strict=True)))
    return rows


def load_registry_rows(governance_text: str) -> dict[str, RegistryRow]:
    rows = parse_markdown_table(governance_text, "## Live planning registry and ownership")
    registry: dict[str, RegistryRow] = {}
    for row in rows:
        path_text = normalize_doc_path(row["Path"])
        registry[path_text] = RegistryRow(
            path=path_text,
            status=row["Status"].strip(),
            owner=row["Owner"].strip(),
            metadata_header=row["Metadata header"].strip().lower(),
        )
    return registry


def load_readme_registry_paths(readme_text: str) -> set[str]:
    rows = parse_markdown_table(readme_text, "## Planning document registry")
    return {normalize_doc_path(row["Path"]) for row in rows}


def load_backlog_rows(backlog_path: Path) -> list[dict[str, str]]:
    with backlog_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("backlog.csv is empty")
    return rows


def parse_status_board_tables(
    status_board_text: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    track_rows = parse_markdown_table(status_board_text, "## Active completion tracks")
    branch_rows = parse_markdown_table(status_board_text, "## Active branches")
    pr_rows = parse_markdown_table(status_board_text, "## Open PRs")
    return track_rows, branch_rows, pr_rows


def expected_track_status(task_statuses: list[str]) -> str:
    if any(status == "blocked" for status in task_statuses):
        return "blocked"
    if any(status == "in_progress" for status in task_statuses):
        return "in_progress"
    if any(status == "pr_open" for status in task_statuses):
        return "pr_open"
    if task_statuses and all(status == "merged" for status in task_statuses):
        return "merged"
    return "not_started"


def markdown_target(raw_target: str) -> tuple[str, str | None] | None:
    target = raw_target.strip()
    if not target:
        return None
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()

    if " " in target and not target.startswith(("http://", "https://", "mailto:", "tel:")):
        target = target.split(" ", 1)[0]

    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return None

    if target.startswith("#"):
        return ("", target[1:])

    path_part, _, fragment = target.partition("#")
    return (path_part, fragment or None)


def resolve_repo_path(repo_root: Path, source_path: Path, raw_target_path: str) -> Path | None:
    target_path = normalize_doc_path(unquote(raw_target_path))
    if not target_path:
        return source_path

    if raw_target_path.startswith("/"):
        candidate = (repo_root / target_path).resolve()
    else:
        candidate = (source_path.parent / target_path).resolve()

    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError:
        return None
    return candidate


def heading_to_anchor(heading: str) -> str:
    cleaned = heading.strip().lower()
    cleaned = re.sub(r"\s+#+\s*$", "", cleaned)
    cleaned = re.sub(r"[^\w\- ]", "", cleaned)
    cleaned = cleaned.replace(" ", "-")
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned


def collect_markdown_anchors(markdown: str) -> set[str]:
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for line in markdown.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if not match:
            continue
        base = heading_to_anchor(match.group(1))
        if not base:
            continue
        suffix = counts.get(base, 0)
        anchor = base if suffix == 0 else f"{base}-{suffix}"
        counts[base] = suffix + 1
        anchors.add(anchor)
    return anchors


def iter_markdown_links(markdown: str) -> list[tuple[int, str]]:
    links: list[tuple[int, str]] = []
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        for match in MARKDOWN_LINK_RE.finditer(line):
            links.append((line_number, match.group(1)))
    return links


def iter_code_doc_paths(markdown: str) -> list[tuple[int, str]]:
    references: list[tuple[int, str]] = []
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        for match in INLINE_DOC_PATH_RE.finditer(line):
            references.append((line_number, normalize_doc_path(match.group(1))))
    return references


def validate_registry(repo_root: Path) -> tuple[dict[str, RegistryRow], list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    governance_path = repo_root / DOC_GOVERNANCE_PATH
    readme_path = repo_root / PROGRAM_README_PATH
    if not governance_path.exists():
        issues.append(
            ValidationIssue(
                code="DOC-REGISTRY-001",
                message="Missing docs/program/doc_governance.md",
                path=DOC_GOVERNANCE_PATH,
            )
        )
        return {}, issues
    if not readme_path.exists():
        issues.append(
            ValidationIssue(
                code="DOC-REGISTRY-002",
                message="Missing docs/program/README.md",
                path=PROGRAM_README_PATH,
            )
        )
        return {}, issues

    try:
        registry_rows = load_registry_rows(read_text(governance_path))
    except (KeyError, ValueError) as error:
        issues.append(
            ValidationIssue(
                code="DOC-REGISTRY-003",
                message=f"Unable to parse doc governance registry: {error}",
                path=DOC_GOVERNANCE_PATH,
            )
        )
        return {}, issues

    try:
        readme_paths = load_readme_registry_paths(read_text(readme_path))
    except (KeyError, ValueError) as error:
        issues.append(
            ValidationIssue(
                code="DOC-REGISTRY-004",
                message=f"Unable to parse README registry: {error}",
                path=PROGRAM_README_PATH,
            )
        )
        return registry_rows, issues

    governance_paths = set(registry_rows)
    missing_in_readme = sorted(governance_paths - readme_paths)
    missing_in_governance = sorted(readme_paths - governance_paths)
    if missing_in_readme:
        issues.append(
            ValidationIssue(
                code="DOC-REGISTRY-005",
                message=(
                    "Paths present in doc_governance but missing from README registry: "
                    + ", ".join(missing_in_readme)
                ),
                path=PROGRAM_README_PATH,
            )
        )
    if missing_in_governance:
        issues.append(
            ValidationIssue(
                code="DOC-REGISTRY-006",
                message=(
                    "Paths present in README registry but missing from doc_governance: "
                    + ", ".join(missing_in_governance)
                ),
                path=DOC_GOVERNANCE_PATH,
            )
        )

    return registry_rows, issues


def validate_live_docs(
    repo_root: Path, registry_rows: dict[str, RegistryRow]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for row in registry_rows.values():
        doc_path = repo_root / row.path
        relative = Path(row.path)
        if not doc_path.exists():
            issues.append(
                ValidationIssue(
                    code="DOC-LIVE-001",
                    message="Registered live planning path is missing",
                    path=relative,
                )
            )
            continue

        if row.status not in ALLOWED_REGISTRY_STATUSES:
            issues.append(
                ValidationIssue(
                    code="DOC-LIVE-002",
                    message=f"Unknown registry status '{row.status}'",
                    path=DOC_GOVERNANCE_PATH,
                )
            )

        if row.metadata_header not in ALLOWED_METADATA_RULES:
            issues.append(
                ValidationIssue(
                    code="DOC-LIVE-003",
                    message=f"Unknown metadata header rule '{row.metadata_header}' for {row.path}",
                    path=DOC_GOVERNANCE_PATH,
                )
            )
            continue

        if row.metadata_header == "not_applicable":
            continue

        if doc_path.suffix != ".md":
            issues.append(
                ValidationIssue(
                    code="DOC-LIVE-004",
                    message="Metadata headers are only valid for markdown files",
                    path=relative,
                )
            )
            continue

        markdown = read_text(doc_path)
        try:
            metadata = parse_metadata_header(markdown)
        except ValueError as error:
            issues.append(
                ValidationIssue(
                    code="DOC-LIVE-005",
                    message=str(error),
                    path=relative,
                )
            )
            continue

        expected_status = "canonical" if row.status == "canonical after CAP-06" else row.status
        if metadata["Status"] != expected_status:
            issues.append(
                ValidationIssue(
                    code="DOC-LIVE-006",
                    message=(
                        "Metadata Status does not match registry "
                        f"(expected '{expected_status}', found '{metadata['Status']}')"
                    ),
                    path=relative,
                )
            )
        if metadata["Owner"] != row.owner:
            issues.append(
                ValidationIssue(
                    code="DOC-LIVE-007",
                    message=(
                        "Metadata Owner does not match registry "
                        f"(expected '{row.owner}', found '{metadata['Owner']}')"
                    ),
                    path=relative,
                )
            )
        if not LAST_UPDATED_RE.match(metadata["Last updated"]):
            issues.append(
                ValidationIssue(
                    code="DOC-LIVE-008",
                    message="Last updated must be in YYYY-MM-DD format",
                    path=relative,
                )
            )

    return issues


def validate_status_board(repo_root: Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    backlog_path = repo_root / BACKLOG_PATH
    status_board_path = repo_root / STATUS_BOARD_PATH
    if not backlog_path.exists():
        issues.append(
            ValidationIssue(
                code="DOC-SYNC-001",
                message="Missing docs/program/backlog.csv",
                path=BACKLOG_PATH,
            )
        )
        return issues
    if not status_board_path.exists():
        issues.append(
            ValidationIssue(
                code="DOC-SYNC-002",
                message="Missing docs/program/status_board.md",
                path=STATUS_BOARD_PATH,
            )
        )
        return issues

    try:
        backlog_rows = load_backlog_rows(backlog_path)
    except ValueError as error:
        issues.append(
            ValidationIssue(
                code="DOC-SYNC-003",
                message=f"Unable to parse backlog.csv: {error}",
                path=BACKLOG_PATH,
            )
        )
        return issues

    backlog_by_id = {row["task_id"].strip(): row for row in backlog_rows}
    try:
        track_rows, branch_rows, pr_rows = parse_status_board_tables(read_text(status_board_path))
    except (KeyError, ValueError) as error:
        issues.append(
            ValidationIssue(
                code="DOC-SYNC-004",
                message=f"Unable to parse status board tables: {error}",
                path=STATUS_BOARD_PATH,
            )
        )
        return issues

    active_from_backlog = {
        row["task_id"].strip()
        for row in backlog_rows
        if row["status"].strip() in ACTIVE_TASK_STATUSES
    }
    active_from_board = {row["Task ID"].strip() for row in branch_rows}
    missing_in_board = sorted(active_from_backlog - active_from_board)
    stale_in_board = sorted(active_from_board - active_from_backlog)
    if missing_in_board:
        issues.append(
            ValidationIssue(
                code="DOC-SYNC-005",
                message=(
                    "Tasks marked active in backlog.csv but missing from status_board active branches: "
                    + ", ".join(missing_in_board)
                ),
                path=STATUS_BOARD_PATH,
            )
        )
    if stale_in_board:
        issues.append(
            ValidationIssue(
                code="DOC-SYNC-006",
                message=(
                    "Tasks listed in status_board active branches but not active in backlog.csv: "
                    + ", ".join(stale_in_board)
                ),
                path=STATUS_BOARD_PATH,
            )
        )

    for row in branch_rows:
        task_id = row["Task ID"].strip()
        board_status = row["Status"].strip()
        if task_id not in backlog_by_id:
            issues.append(
                ValidationIssue(
                    code="DOC-SYNC-007",
                    message=f"Task '{task_id}' appears in status board but not in backlog.csv",
                    path=STATUS_BOARD_PATH,
                )
            )
            continue
        backlog_status = backlog_by_id[task_id]["status"].strip()
        if board_status != backlog_status:
            issues.append(
                ValidationIssue(
                    code="DOC-SYNC-008",
                    message=(
                        f"Stale status for {task_id}: status_board has '{board_status}', "
                        f"backlog.csv has '{backlog_status}'"
                    ),
                    path=STATUS_BOARD_PATH,
                )
            )

    pr_from_backlog = {
        row["task_id"].strip() for row in backlog_rows if row["status"].strip() == "pr_open"
    }
    pr_from_board = {row["Task ID"].strip() for row in pr_rows}
    missing_pr_rows = sorted(pr_from_backlog - pr_from_board)
    stale_pr_rows = sorted(pr_from_board - pr_from_backlog)
    if missing_pr_rows:
        issues.append(
            ValidationIssue(
                code="DOC-SYNC-009",
                message=(
                    "Tasks with status pr_open in backlog.csv but missing from status_board open PRs: "
                    + ", ".join(missing_pr_rows)
                ),
                path=STATUS_BOARD_PATH,
            )
        )
    if stale_pr_rows:
        issues.append(
            ValidationIssue(
                code="DOC-SYNC-010",
                message=(
                    "Tasks listed in status_board open PRs but not pr_open in backlog.csv: "
                    + ", ".join(stale_pr_rows)
                ),
                path=STATUS_BOARD_PATH,
            )
        )

    tasks_by_track: dict[str, list[str]] = {}
    for row in backlog_rows:
        tasks_by_track.setdefault(row["track"].strip(), []).append(row["status"].strip())
    board_track_codes = {row["Track"].strip() for row in track_rows}
    backlog_track_codes = set(tasks_by_track)
    missing_track_rows = sorted(backlog_track_codes - board_track_codes)
    extra_track_rows = sorted(board_track_codes - backlog_track_codes)
    if missing_track_rows:
        issues.append(
            ValidationIssue(
                code="DOC-SYNC-011",
                message=(
                    "Tracks present in backlog.csv but missing from status_board track table: "
                    + ", ".join(missing_track_rows)
                ),
                path=STATUS_BOARD_PATH,
            )
        )
    if extra_track_rows:
        issues.append(
            ValidationIssue(
                code="DOC-SYNC-012",
                message=(
                    "Tracks present in status_board track table but missing from backlog.csv: "
                    + ", ".join(extra_track_rows)
                ),
                path=STATUS_BOARD_PATH,
            )
        )

    for row in track_rows:
        track = row["Track"].strip()
        board_status = row["Status"].strip()
        if track not in tasks_by_track:
            continue
        expected = expected_track_status(tasks_by_track[track])
        if board_status != expected:
            issues.append(
                ValidationIssue(
                    code="DOC-SYNC-013",
                    message=(
                        f"Track '{track}' has stale status '{board_status}' in status_board.md; "
                        f"expected '{expected}' from backlog.csv"
                    ),
                    path=STATUS_BOARD_PATH,
                )
            )

    return issues


def validate_internal_markdown_links(
    repo_root: Path, registry_rows: dict[str, RegistryRow]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    anchors_cache: dict[Path, set[str]] = {}
    markdown_docs = [
        repo_root / row.path for row in registry_rows.values() if row.path.endswith(".md")
    ]
    for source_path in markdown_docs:
        if not source_path.exists():
            continue
        source_relative = source_path.relative_to(repo_root)
        markdown = read_text(source_path)
        for line_number, raw_target in iter_markdown_links(markdown):
            target = markdown_target(raw_target)
            if target is None:
                continue
            target_path, fragment = target
            resolved = resolve_repo_path(repo_root, source_path, target_path)
            if resolved is None:
                issues.append(
                    ValidationIssue(
                        code="DOC-LINK-001",
                        message=f"Link target escapes repository root: {raw_target}",
                        path=source_relative,
                        line=line_number,
                    )
                )
                continue
            if not resolved.exists():
                issues.append(
                    ValidationIssue(
                        code="DOC-LINK-002",
                        message=f"Broken internal doc link target: {raw_target}",
                        path=source_relative,
                        line=line_number,
                    )
                )
                continue

            if fragment and resolved.suffix == ".md":
                normalized_fragment = heading_to_anchor(unquote(fragment))
                anchor_set = anchors_cache.setdefault(
                    resolved,
                    collect_markdown_anchors(read_text(resolved)),
                )
                if normalized_fragment and normalized_fragment not in anchor_set:
                    issues.append(
                        ValidationIssue(
                            code="DOC-LINK-003",
                            message=f"Broken markdown anchor '{fragment}' in link target {raw_target}",
                            path=source_relative,
                            line=line_number,
                        )
                    )

    return issues


def validate_entrypoint_archive_links(repo_root: Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for relative_entrypoint in LIVE_ENTRYPOINTS:
        entrypoint_path = repo_root / relative_entrypoint
        if not entrypoint_path.exists():
            continue
        markdown = read_text(entrypoint_path)
        references: list[tuple[int, str]] = []

        for line_number, raw_target in iter_markdown_links(markdown):
            target = markdown_target(raw_target)
            if target is None:
                continue
            target_path, _ = target
            normalized = normalize_doc_path(target_path)
            if normalized:
                references.append((line_number, normalized))

        references.extend(iter_code_doc_paths(markdown))

        for line_number, reference in references:
            if not reference.startswith("docs/"):
                continue
            if "*" not in reference and not (repo_root / reference).exists():
                issues.append(
                    ValidationIssue(
                        code="DOC-ENTRY-001",
                        message=f"Broken internal doc reference in live entrypoint: {reference}",
                        path=relative_entrypoint,
                        line=line_number,
                    )
                )
            if reference.startswith("docs/archive/") and reference != "docs/archive/README.md":
                issues.append(
                    ValidationIssue(
                        code="DOC-ENTRY-002",
                        message=(
                            "Live entrypoints must not reference archived files directly; "
                            f"use docs/archive/README.md instead ({reference})"
                        ),
                        path=relative_entrypoint,
                        line=line_number,
                    )
                )

    return issues


def verify_program_docs(repo_root: Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    registry_rows, registry_issues = validate_registry(repo_root)
    issues.extend(registry_issues)
    issues.extend(validate_live_docs(repo_root, registry_rows))
    issues.extend(validate_status_board(repo_root))
    issues.extend(validate_internal_markdown_links(repo_root, registry_rows))
    issues.extend(validate_entrypoint_archive_links(repo_root))
    return issues


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify program docs consistency and fail on drift.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root path (defaults to auto-detected root).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    repo_root = args.root.resolve()
    issues = verify_program_docs(repo_root)
    if issues:
        print("Program docs verification failed:")
        for issue in issues:
            print(f"- {issue.render()}")
        return 1
    print("Program docs verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
