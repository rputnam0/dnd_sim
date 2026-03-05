from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "release" / "prepare_fin06_release.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("prepare_fin06_release", SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"Unable to load module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_backlog(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["task_id", "title", "status"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_read_backlog_rows_handles_valid_empty_and_missing_csv(tmp_path: Path) -> None:
    module = _load_module()
    valid_path = tmp_path / "docs/program/backlog.csv"
    _write_backlog(
        valid_path,
        rows=[{"task_id": "FIN-02", "title": "capability gate", "status": "merged"}],
    )
    rows = module._read_backlog_rows(valid_path)
    assert len(rows) == 1
    assert rows[0]["task_id"] == "FIN-02"

    empty_path = tmp_path / "docs/program/empty_backlog.csv"
    empty_path.parent.mkdir(parents=True, exist_ok=True)
    empty_path.write_text("task_id,title,status\n", encoding="utf-8")
    with pytest.raises(ValueError, match="backlog.csv is empty"):
        module._read_backlog_rows(empty_path)

    with pytest.raises(FileNotFoundError):
        module._read_backlog_rows(tmp_path / "docs/program/missing.csv")


def test_backlog_by_task_ignores_rows_without_task_id() -> None:
    module = _load_module()
    rows = [
        {"task_id": "FIN-02", "title": "capability gate", "status": "merged"},
        {"task_id": " ", "title": "blank", "status": "merged"},
        {"task_id": "", "title": "empty", "status": "merged"},
    ]
    by_task = module._backlog_by_task(rows)
    assert set(by_task) == {"FIN-02"}


def test_dependency_status_rows_handles_merged_blocked_and_missing() -> None:
    module = _load_module()
    by_task = {
        "FIN-02": {"task_id": "FIN-02", "title": "capability gate", "status": "merged"},
        "FIN-03": {"task_id": "FIN-03", "title": "replay gate", "status": "in_progress"},
    }
    ready, blockers = module._dependency_status_rows(
        by_task,
        ("FIN-02", "FIN-03", "FIN-04"),
    )

    assert [row["task_id"] for row in ready] == ["FIN-02"]
    blocker_statuses = {row["task_id"]: row["status"] for row in blockers}
    assert blocker_statuses == {"FIN-03": "in_progress", "FIN-04": "missing"}


def test_render_markdown_snapshot_renders_ready_and_blocked_states() -> None:
    module = _load_module()
    ready_markdown = module._render_markdown_snapshot(
        generated_date="2026-03-05",
        fin06_branch="codex/feat/fin-06-cut-release-baseline-archive-prior-program-artifac",
        ready=[{"task_id": "FIN-02", "status": "merged"}],
        blockers=[],
    )
    assert "# FIN-06 Release Prep Snapshot (historical)" in ready_markdown
    assert "Readiness state: `ready`" in ready_markdown
    assert "- FIN-02: `merged`" in ready_markdown
    assert "- None; FIN-06 dependency gate is clear." in ready_markdown

    blocked_markdown = module._render_markdown_snapshot(
        generated_date="2026-03-05",
        fin06_branch="codex/feat/fin-06-cut-release-baseline-archive-prior-program-artifac",
        ready=[],
        blockers=[{"task_id": "FIN-03", "status": "in_progress", "detail": "Replay gate"}],
    )
    assert "Readiness state: `blocked`" in blocked_markdown
    assert "- FIN-03: `in_progress` (Replay gate)" in blocked_markdown
    assert "- FIN-03 is `in_progress`" in blocked_markdown


def test_prepare_fin06_release_snapshot_writes_output_file(tmp_path: Path) -> None:
    module = _load_module()
    backlog_path = Path("docs/program/backlog.csv")
    _write_backlog(
        tmp_path / backlog_path,
        rows=[
            {"task_id": "FIN-02", "title": "capability gate", "status": "merged"},
            {"task_id": "FIN-03", "title": "replay gate", "status": "merged"},
            {"task_id": "FIN-04", "title": "integration gate", "status": "merged"},
            {"task_id": "FIN-05", "title": "maintenance gate", "status": "merged"},
        ],
    )

    output_path = Path("docs/archive/release_prep/test_snapshot.md")
    result = module.prepare_fin06_release_snapshot(
        repo_root=tmp_path,
        backlog_path=backlog_path,
        output_path=output_path,
        generated_date="2026-03-05",
    )

    rendered = (tmp_path / output_path).read_text(encoding="utf-8")
    assert result["readiness_state"] == "ready"
    assert "Readiness state: `ready`" in rendered
    assert "- FIN-05: `merged`" in rendered


def test_main_returns_expected_exit_codes_for_ready_and_blocked_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    backlog_path = tmp_path / "docs/program/backlog.csv"

    module.REPO_ROOT = tmp_path
    module.DEFAULT_BACKLOG_PATH = Path("docs/program/backlog.csv")
    module.DEFAULT_OUTPUT_PATH = Path("docs/archive/release_prep/test_snapshot.md")

    _write_backlog(
        backlog_path,
        rows=[
            {"task_id": "FIN-02", "title": "capability gate", "status": "merged"},
            {"task_id": "FIN-03", "title": "replay gate", "status": "merged"},
            {"task_id": "FIN-04", "title": "integration gate", "status": "merged"},
            {"task_id": "FIN-05", "title": "maintenance gate", "status": "merged"},
        ],
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["prepare_fin06_release.py", "--generated-date", "2026-03-05"],
    )
    assert module.main() == 0

    _write_backlog(
        backlog_path,
        rows=[
            {"task_id": "FIN-02", "title": "capability gate", "status": "in_progress"},
            {"task_id": "FIN-03", "title": "replay gate", "status": "not_started"},
            {"task_id": "FIN-04", "title": "integration gate", "status": "not_started"},
            {"task_id": "FIN-05", "title": "maintenance gate", "status": "not_started"},
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["prepare_fin06_release.py", "--generated-date", "2026-03-05"],
    )
    assert module.main() == 2

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare_fin06_release.py",
            "--generated-date",
            "2026-03-05",
            "--allow-blocked",
        ],
    )
    assert module.main() == 0
