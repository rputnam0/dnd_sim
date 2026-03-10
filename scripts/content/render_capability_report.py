from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from dnd_sim.capability_manifest import (
    CapabilityRecord,
    build_class_capability_manifest,
    build_feature_capability_manifest,
    build_item_capability_manifest,
    build_monster_capability_manifest,
    build_spell_capability_manifest,
    build_subclass_capability_manifest,
)

REPORT_VERSION = "1.0"
DEFAULT_JSON_OUT = REPO_ROOT / "artifacts" / "capabilities" / "coverage_report.json"
DEFAULT_MARKDOWN_OUT = REPO_ROOT / "docs" / "program" / "capability_report.md"
_LAST_UPDATED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render deterministic machine-readable and markdown capability coverage reports."
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=DEFAULT_JSON_OUT,
        help="Destination path for the machine-readable JSON report.",
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        default=DEFAULT_MARKDOWN_OUT,
        help="Destination path for the markdown capability report.",
    )
    parser.add_argument(
        "--last-updated",
        default=None,
        help=(
            "Metadata date for markdown output (YYYY-MM-DD). "
            "Defaults to existing report metadata when available."
        ),
    )
    return parser.parse_args(argv)


def _record_sort_key(record: CapabilityRecord) -> tuple[str, str]:
    return (record.content_type.casefold(), record.content_id.casefold())


def _normalized_support_state(record: CapabilityRecord) -> str:
    if record.support_state is not None:
        normalized = record.support_state.strip().lower()
        if normalized:
            return normalized
    return "unsupported" if record.states.blocked else "supported"


def collect_capability_records() -> list[CapabilityRecord]:
    records: list[CapabilityRecord] = []
    for manifest in (
        build_spell_capability_manifest(),
        build_feature_capability_manifest(),
        build_monster_capability_manifest(),
        build_item_capability_manifest(),
        build_class_capability_manifest(),
        build_subclass_capability_manifest(),
    ):
        records.extend(manifest.records)
    return sorted(records, key=_record_sort_key)


def build_coverage_report(*, records: list[CapabilityRecord]) -> dict[str, Any]:
    sorted_records = sorted(records, key=_record_sort_key)

    by_content_type: dict[str, dict[str, int | str]] = {}
    unsupported_reason_counts: dict[str, int] = {}

    total_records = len(sorted_records)
    supported_records = 0
    blocked_records = 0
    schema_valid_records = 0
    executable_records = 0
    tested_records = 0

    report_records: list[dict[str, Any]] = []

    for record in sorted_records:
        states = record.states
        support_state = _normalized_support_state(record)

        bucket = by_content_type.setdefault(
            record.content_type,
            {
                "content_type": record.content_type,
                "total_records": 0,
                "supported_records": 0,
                "blocked_records": 0,
                "schema_valid_records": 0,
                "executable_records": 0,
                "tested_records": 0,
            },
        )
        bucket["total_records"] = int(bucket["total_records"]) + 1

        if states.blocked:
            blocked_records += 1
            bucket["blocked_records"] = int(bucket["blocked_records"]) + 1
            reason = str(states.unsupported_reason or "").strip()
            if reason:
                unsupported_reason_counts[reason] = unsupported_reason_counts.get(reason, 0) + 1
        else:
            supported_records += 1
            bucket["supported_records"] = int(bucket["supported_records"]) + 1

        if states.schema_valid:
            schema_valid_records += 1
            bucket["schema_valid_records"] = int(bucket["schema_valid_records"]) + 1
        if states.executable:
            executable_records += 1
            bucket["executable_records"] = int(bucket["executable_records"]) + 1
        if states.tested:
            tested_records += 1
            bucket["tested_records"] = int(bucket["tested_records"]) + 1

        report_records.append(
            {
                "content_id": record.content_id,
                "content_type": record.content_type,
                "runtime_hook_family": record.runtime_hook_family,
                "support_state": support_state,
                "states": {
                    "cataloged": states.cataloged,
                    "schema_valid": states.schema_valid,
                    "executable": states.executable,
                    "tested": states.tested,
                    "blocked": states.blocked,
                    "unsupported_reason": states.unsupported_reason,
                },
            }
        )

    content_type_coverage = sorted(
        by_content_type.values(),
        key=lambda row: str(row["content_type"]).casefold(),
    )
    unsupported_reason_coverage = [
        {
            "unsupported_reason": reason,
            "count": unsupported_reason_counts[reason],
        }
        for reason in sorted(unsupported_reason_counts)
    ]

    return {
        "report_version": REPORT_VERSION,
        "summary": {
            "total_records": total_records,
            "supported_records": supported_records,
            "blocked_records": blocked_records,
            "schema_valid_records": schema_valid_records,
            "executable_records": executable_records,
            "tested_records": tested_records,
        },
        "content_type_coverage": content_type_coverage,
        "unsupported_reason_coverage": unsupported_reason_coverage,
        "records": report_records,
    }


def report_to_json_text(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def _repo_relative_display(path: Path) -> str:
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def render_markdown_report(
    *,
    report: dict[str, Any],
    json_path: Path,
    last_updated: str,
) -> str:
    json_display = _repo_relative_display(json_path)
    summary = report["summary"]
    by_type = report["content_type_coverage"]
    by_reason = report["unsupported_reason_coverage"]

    lines = [
        "# Capability Report",
        "",
        "Status: canonical",
        "Owner: content-manifest",
        f"Last updated: {last_updated}",
        f"Canonical source: `{json_display}`",
        "",
        "This report is generated by `scripts/content/render_capability_report.py`.",
        "Do not edit manually.",
        "",
        "## Artifacts",
        "",
        f"- Machine-readable JSON: `{json_display}`",
        "",
        "## Coverage Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Total records | {summary['total_records']} |",
        f"| Supported records | {summary['supported_records']} |",
        f"| Blocked records | {summary['blocked_records']} |",
        f"| Schema-valid records | {summary['schema_valid_records']} |",
        f"| Executable records | {summary['executable_records']} |",
        f"| Tested records | {summary['tested_records']} |",
        "",
        "## Coverage By Content Type",
        "",
        "| Content type | Total | Supported | Blocked | Schema valid | Executable | Tested |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for row in by_type:
        lines.append(
            "| "
            f"{row['content_type']} | {row['total_records']} | {row['supported_records']} | "
            f"{row['blocked_records']} | {row['schema_valid_records']} | "
            f"{row['executable_records']} | {row['tested_records']} |"
        )

    lines.extend(
        [
            "",
            "## Unsupported Reason Coverage",
            "",
            "| Unsupported reason | Count |",
            "|---|---:|",
        ]
    )

    if by_reason:
        for row in by_reason:
            lines.append(f"| {row['unsupported_reason']} | {row['count']} |")
    else:
        lines.append("| (none) | 0 |")

    return "\n".join(lines) + "\n"


def write_json_report(*, report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_to_json_text(report), encoding="utf-8")


def write_markdown_report(*, markdown_text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_text, encoding="utf-8")


def _parse_last_updated_from_file(path: Path) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines()[:30]:
        if line.startswith("Last updated:"):
            candidate = line.split(":", maxsplit=1)[1].strip()
            if _LAST_UPDATED_RE.fullmatch(candidate):
                return candidate
            return None
    return None


def _resolve_last_updated(*, requested: str | None, markdown_path: Path) -> str:
    if requested is not None:
        candidate = requested.strip()
        if not _LAST_UPDATED_RE.fullmatch(candidate):
            raise SystemExit("--last-updated must be in YYYY-MM-DD format")
        return candidate

    existing = _parse_last_updated_from_file(markdown_path)
    return existing or "1970-01-01"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    json_out = args.json_out.resolve()
    markdown_out = args.markdown_out.resolve()
    last_updated = _resolve_last_updated(
        requested=args.last_updated,
        markdown_path=markdown_out,
    )

    report = build_coverage_report(records=collect_capability_records())
    write_json_report(report=report, path=json_out)
    markdown = render_markdown_report(
        report=report,
        json_path=json_out,
        last_updated=last_updated,
    )
    write_markdown_report(markdown_text=markdown, path=markdown_out)

    print(f"Capability coverage report JSON: {json_out}")
    print(f"Capability coverage report Markdown: {markdown_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
