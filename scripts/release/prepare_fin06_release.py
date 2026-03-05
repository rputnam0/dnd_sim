from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BACKLOG_PATH = Path("docs/program/backlog.csv")
DEFAULT_OUTPUT_PATH = Path("docs/archive/release_prep/fin06_release_prep_20260305.md")
FIN06_DEPENDENCIES = ("FIN-02", "FIN-03", "FIN-04", "FIN-05")


def _read_backlog_rows(backlog_path: Path) -> list[dict[str, str]]:
    with backlog_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("backlog.csv is empty")
    return rows


def _backlog_by_task(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    by_task: dict[str, dict[str, str]] = {}
    for row in rows:
        task_id = str(row.get("task_id", "")).strip()
        if task_id:
            by_task[task_id] = row
    return by_task


def _dependency_status_rows(
    by_task: dict[str, dict[str, str]],
    dependencies: tuple[str, ...],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    ready: list[dict[str, str]] = []
    blockers: list[dict[str, str]] = []
    for task_id in dependencies:
        row = by_task.get(task_id)
        if row is None:
            blockers.append(
                {
                    "task_id": task_id,
                    "status": "missing",
                    "detail": "dependency is not present in backlog.csv",
                }
            )
            continue
        status = str(row.get("status", "")).strip()
        entry = {
            "task_id": task_id,
            "status": status,
            "detail": str(row.get("title", "")).strip(),
        }
        if status == "merged":
            ready.append(entry)
        else:
            blockers.append(entry)
    return ready, blockers


def _render_markdown_snapshot(
    *,
    generated_date: str,
    fin06_branch: str,
    ready: list[dict[str, str]],
    blockers: list[dict[str, str]],
) -> str:
    dependency_lines = []
    for row in ready:
        dependency_lines.append(f"- {row['task_id']}: `{row['status']}`")
    for row in blockers:
        dependency_lines.append(f"- {row['task_id']}: `{row['status']}` ({row['detail']})")
    if not dependency_lines:
        dependency_lines.append("- None")

    blocker_lines = []
    if blockers:
        for row in blockers:
            blocker_lines.append(f"- {row['task_id']} is `{row['status']}`")
    else:
        blocker_lines.append("- None; FIN-06 dependency gate is clear.")

    readiness_state = "blocked" if blockers else "ready"
    return "\n".join(
        [
            "# FIN-06 Release Prep Snapshot (historical)",
            "",
            "Status: historical  ",
            "Owner: release_lead  ",
            f"Last updated: {generated_date}  ",
            "Canonical source: `docs/program/README.md`",
            "",
            "This snapshot captures FIN-06 prep work while dependency gates are evaluated.",
            "",
            f"Current prep branch: `{fin06_branch}`",
            f"Readiness state: `{readiness_state}`",
            "",
            "## Dependency Gate Status",
            "",
            *dependency_lines,
            "",
            "## Blockers",
            "",
            *blocker_lines,
            "",
            "## Parked FIN-06 Finalization Checklist",
            "",
            "- [ ] Confirm FIN-02, FIN-03, FIN-04, and FIN-05 are all `merged` in `docs/program/backlog.csv`.",
            "- [ ] Cut release baseline tag and archive superseded program artifacts.",
            "- [ ] Update `docs/program/status_board.md` to show completion-gate closure and backend completion status.",
            "- [ ] Update `docs/program/README.md` and `docs/archive/README.md` with final release baseline references.",
            "- [ ] Run final full-suite and release smoke checks before final FIN-06 merge.",
        ]
    )


def prepare_fin06_release_snapshot(
    *,
    repo_root: Path,
    backlog_path: Path = DEFAULT_BACKLOG_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    generated_date: str | None = None,
    fin06_branch: str = "codex/feat/fin-06-cut-release-baseline-archive-prior-program-artifac",
) -> dict[str, Any]:
    rows = _read_backlog_rows(repo_root / backlog_path)
    by_task = _backlog_by_task(rows)
    ready, blockers = _dependency_status_rows(by_task, FIN06_DEPENDENCIES)

    date_text = generated_date or dt.date.today().isoformat()
    markdown = _render_markdown_snapshot(
        generated_date=date_text,
        fin06_branch=fin06_branch,
        ready=ready,
        blockers=blockers,
    )

    absolute_output = repo_root / output_path
    absolute_output.parent.mkdir(parents=True, exist_ok=True)
    absolute_output.write_text(markdown + "\n", encoding="utf-8")

    return {
        "ready": ready,
        "blockers": blockers,
        "output_path": str(output_path),
        "readiness_state": "blocked" if blockers else "ready",
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare a dependency-aware FIN-06 release snapshot."
    )
    parser.add_argument(
        "--backlog-path",
        type=Path,
        default=DEFAULT_BACKLOG_PATH,
        help="Path to backlog.csv relative to the repository root.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path to snapshot markdown output relative to the repository root.",
    )
    parser.add_argument(
        "--generated-date",
        type=str,
        default=None,
        help="Override ISO date used in the snapshot header.",
    )
    parser.add_argument(
        "--allow-blocked",
        action="store_true",
        help="Exit zero even when FIN-06 dependencies are still blocked.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    result = prepare_fin06_release_snapshot(
        repo_root=REPO_ROOT,
        backlog_path=args.backlog_path,
        output_path=args.output_path,
        generated_date=args.generated_date,
    )

    blockers = result["blockers"]
    if blockers:
        print(f"FIN-06 release prep is blocked by {len(blockers)} dependency task(s).")
        for blocker in blockers:
            print(f"- {blocker['task_id']}: {blocker['status']}")
        if not args.allow_blocked:
            return 2
    else:
        print("FIN-06 release prep dependencies are merged and ready for finalization.")

    print(f"Snapshot written to {result['output_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
