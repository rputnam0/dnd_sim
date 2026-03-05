from __future__ import annotations

from pathlib import Path

import pytest

from dnd_sim.runtime_contracts import (
    AgentMaintenanceContractError,
    evaluate_agent_maintenance_contracts,
    assert_agent_maintenance_contracts,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_agent_index(
    repo_root: Path,
    *,
    owner_module: str,
    invariants: list[str],
    default_max_file_lines: int = 1500,
    waivers: list[tuple[str, int, str]] | None = None,
) -> None:
    waiver_rows = waivers or []
    waiver_blocks = [
        "\n".join(
            [
                "      - module: " + module,
                f"        max_lines: {max_lines}",
                f'        reason: "{reason}"',
            ]
        )
        for module, max_lines, reason in waiver_rows
    ]
    waiver_text = "\n".join(waiver_blocks)
    if not waiver_text:
        waiver_text = (
            "      - module: src/dnd_sim/does_not_match.py\n"
            "        max_lines: 5\n"
            '        reason: "no-op waiver for tests"'
        )

    invariants_text = "\n".join([f'      - "{row}"' for row in invariants])
    content = (
        "subsystems:\n"
        "  test_runtime:\n"
        "    owner_pool: integration_agent_gate\n"
        "    owner_task: FIN-05\n"
        f"    owner_module: {owner_module}\n"
        "    invariants:\n"
        f"{invariants_text}\n"
        "    safe_edit_boundaries:\n"
        '      - "Safe: task-pure edits only."\n'
        "policies:\n"
        "  maintenance_gate:\n"
        "    ownership_globs:\n"
        '      - "src/dnd_sim/*.py"\n'
        f"    default_max_file_lines: {default_max_file_lines}\n"
        "    file_size_waivers:\n"
        f"{waiver_text}\n"
    )

    path = repo_root / "docs" / "agent_index.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_runtime_module(repo_root: Path, relative_path: str, lines: int = 1) -> None:
    module_path = repo_root / relative_path
    module_path.parent.mkdir(parents=True, exist_ok=True)
    source = "\n".join([f"line_{idx} = {idx}" for idx in range(lines)])
    module_path.write_text(source + "\n", encoding="utf-8")


def test_agent_maintenance_gate_passes_for_current_repo_contract_surface() -> None:
    report = evaluate_agent_maintenance_contracts(REPO_ROOT)
    assert report.issues == ()
    assert report.trace
    assert any(entry["check"] == "ownership_coverage" for entry in report.trace)
    assert any(entry["check"] == "structured_error_contract" for entry in report.trace)
    assert any(entry["check"] == "trace_emission_contract" for entry in report.trace)
    assert any(entry["check"] == "file_size_threshold" for entry in report.trace)


def test_missing_ownership_coverage_is_reported_with_structured_issue(tmp_path: Path) -> None:
    _write_runtime_module(tmp_path, "src/dnd_sim/foo.py", lines=5)
    _write_agent_index(
        tmp_path,
        owner_module="src/dnd_sim/bar.py",
        invariants=[
            "Runtime boundaries publish structured errors with deterministic codes.",
            "Runtime boundaries emit deterministic trace events.",
        ],
    )

    report = evaluate_agent_maintenance_contracts(tmp_path)

    issue_codes = {issue.code for issue in report.issues}
    assert "AGENT-MAINT-OWN-001" in issue_codes
    ownership_trace = [row for row in report.trace if row["check"] == "ownership_coverage"]
    assert ownership_trace
    assert any(row["result"] == "failed" for row in ownership_trace)


def test_missing_structured_error_contract_is_reported(tmp_path: Path) -> None:
    _write_runtime_module(tmp_path, "src/dnd_sim/foo.py", lines=5)
    _write_agent_index(
        tmp_path,
        owner_module="src/dnd_sim/*.py",
        invariants=[
            "Runtime boundaries emit deterministic trace events for maintenance.",
        ],
    )

    report = evaluate_agent_maintenance_contracts(tmp_path)

    issue_codes = {issue.code for issue in report.issues}
    assert "AGENT-MAINT-ERR-001" in issue_codes


def test_missing_trace_emission_contract_is_reported(tmp_path: Path) -> None:
    _write_runtime_module(tmp_path, "src/dnd_sim/foo.py", lines=5)
    _write_agent_index(
        tmp_path,
        owner_module="src/dnd_sim/*.py",
        invariants=[
            "Runtime boundaries publish structured errors with deterministic codes.",
        ],
    )

    report = evaluate_agent_maintenance_contracts(tmp_path)

    issue_codes = {issue.code for issue in report.issues}
    assert "AGENT-MAINT-TRC-001" in issue_codes


def test_file_size_threshold_violations_are_reported_without_matching_waiver(
    tmp_path: Path,
) -> None:
    _write_runtime_module(tmp_path, "src/dnd_sim/foo.py", lines=4)
    _write_agent_index(
        tmp_path,
        owner_module="src/dnd_sim/*.py",
        invariants=[
            "Runtime boundaries publish structured errors with deterministic codes.",
            "Runtime boundaries emit deterministic trace events for maintenance.",
        ],
        default_max_file_lines=3,
        waivers=[
            ("src/dnd_sim/not_foo.py", 20, "not applicable"),
        ],
    )

    report = evaluate_agent_maintenance_contracts(tmp_path)

    issue_codes = {issue.code for issue in report.issues}
    assert "AGENT-MAINT-SIZE-001" in issue_codes


def test_assertion_raises_structured_error_with_issue_payload(tmp_path: Path) -> None:
    _write_runtime_module(tmp_path, "src/dnd_sim/foo.py", lines=5)
    _write_agent_index(
        tmp_path,
        owner_module="src/dnd_sim/bar.py",
        invariants=[
            "Runtime boundaries publish structured errors with deterministic codes.",
            "Runtime boundaries emit deterministic trace events for maintenance.",
        ],
    )

    with pytest.raises(AgentMaintenanceContractError) as error:
        assert_agent_maintenance_contracts(tmp_path)

    assert error.value.code == "AGENT-MAINT-FAIL"
    assert error.value.details["issues"]
    assert error.value.details["issues"][0]["code"].startswith("AGENT-MAINT-")
