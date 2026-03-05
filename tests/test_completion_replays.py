from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from dnd_sim.replay import load_replay_bundle
from dnd_sim.replay_schema import GOLDEN_TRACE_MANIFEST_SCHEMA_VERSION, REPLAY_BUNDLE_SCHEMA_VERSION

REPO_ROOT = Path(__file__).resolve().parents[1]
COMBAT_CORPUS_DIR = REPO_ROOT / "artifacts/golden_traces"
WORLD_CORPUS_DIR = REPO_ROOT / "artifacts/world_regressions"
MANIFEST_FILE_NAME = "manifest.json"
MANIFEST_SCHEMA_VERSION = GOLDEN_TRACE_MANIFEST_SCHEMA_VERSION


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _bundle_digest(bundle: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(bundle).encode("utf-8")).hexdigest()


def _load_manifest(combat_dir: Path) -> dict[str, Any]:
    manifest_path = combat_dir / MANIFEST_FILE_NAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{manifest_path} must contain a JSON object")
    return payload


def _load_world_harness_module() -> ModuleType:
    script_path = REPO_ROOT / "scripts" / "perf" / "run_world_regressions.py"
    spec = importlib.util.spec_from_file_location(
        "world_regressions_harness_for_completion", script_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load world regression harness module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def evaluate_replay_corpus_gate(
    combat_dir: Path,
    world_dir: Path,
    *,
    approved_drift_ids: set[str] | None = None,
) -> list[str]:
    approved = approved_drift_ids or set()
    issues: list[str] = []

    if not combat_dir.exists():
        return [f"REPLAY-GATE-COMBAT-001 missing corpus directory: {combat_dir}"]
    if not combat_dir.is_dir():
        return [f"REPLAY-GATE-COMBAT-002 corpus path is not a directory: {combat_dir}"]

    bundle_paths = tuple(
        sorted(
            path
            for path in combat_dir.glob("*.json")
            if path.is_file() and path.name != MANIFEST_FILE_NAME
        )
    )
    if not bundle_paths:
        issues.append(f"REPLAY-GATE-COMBAT-003 no replay bundles found in: {combat_dir}")
        return issues

    try:
        manifest = _load_manifest(combat_dir)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        issues.append(f"REPLAY-GATE-COMBAT-004 invalid manifest: {error}")
        return issues

    schema_version = str(manifest.get("schema_version", "")).strip()
    if schema_version != MANIFEST_SCHEMA_VERSION:
        issues.append(
            f"REPLAY-GATE-COMBAT-005 manifest schema mismatch: expected {MANIFEST_SCHEMA_VERSION}, "
            f"got {schema_version!r}"
        )
        return issues

    bundle_schema_version = str(manifest.get("bundle_schema_version", "")).strip()
    if bundle_schema_version != REPLAY_BUNDLE_SCHEMA_VERSION:
        issues.append(
            f"REPLAY-GATE-COMBAT-006 bundle schema mismatch: expected {REPLAY_BUNDLE_SCHEMA_VERSION}, "
            f"got {bundle_schema_version!r}"
        )
        return issues

    raw_manifest_entries = manifest.get("bundles")
    if not isinstance(raw_manifest_entries, dict):
        issues.append("REPLAY-GATE-COMBAT-007 manifest 'bundles' must be an object")
        return issues

    expected_names = sorted(raw_manifest_entries)
    actual_names = [path.name for path in bundle_paths]
    if expected_names != actual_names:
        issues.append(
            "REPLAY-GATE-COMBAT-008 manifest bundle set mismatch: "
            f"expected={expected_names} actual={actual_names}"
        )
        return issues

    seen_ids: set[str] = set()
    for bundle_path in bundle_paths:
        try:
            bundle = load_replay_bundle(bundle_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            issues.append(f"REPLAY-GATE-COMBAT-009 {bundle_path}: {error}")
            continue

        scenario_id = str(bundle["scenario_id"]).strip()
        if scenario_id in seen_ids:
            issues.append(
                f"REPLAY-GATE-ID-001 duplicate scenario_id '{scenario_id}' in {bundle_path}"
            )
        seen_ids.add(scenario_id)

        manifest_entry = raw_manifest_entries.get(bundle_path.name)
        if not isinstance(manifest_entry, dict):
            issues.append(
                f"REPLAY-GATE-COMBAT-010 manifest entry must be an object: {bundle_path.name}"
            )
            continue
        expected_hash = str(manifest_entry.get("sha256", "")).strip()
        actual_hash = _bundle_digest(bundle)
        if expected_hash != actual_hash and scenario_id not in approved:
            issues.append(
                f"REPLAY-GATE-COMBAT-DIFF-001 unapproved replay drift for '{scenario_id}' "
                f"in {bundle_path.name}"
            )

    if not world_dir.exists():
        issues.append(f"REPLAY-GATE-WORLD-001 missing corpus directory: {world_dir}")
        return issues
    if not world_dir.is_dir():
        issues.append(f"REPLAY-GATE-WORLD-002 corpus path is not a directory: {world_dir}")
        return issues

    try:
        harness = _load_world_harness_module()
    except Exception as error:  # noqa: BLE001
        issues.append(f"REPLAY-GATE-WORLD-004 unable to load world harness: {error}")
        return issues

    try:
        suite_result = harness.run_regression_suite(corpus_dir=world_dir)
    except Exception as error:  # noqa: BLE001
        issues.append(f"REPLAY-GATE-WORLD-005 world harness execution failed: {error}")
        return issues
    for case_result in suite_result.case_results:
        if case_result.passed:
            continue

        case_id = str(case_result.case_id).strip()
        if case_id in approved:
            continue

        if case_result.error is not None:
            issues.append(
                f"REPLAY-GATE-WORLD-003 harness error for '{case_id}' in {case_result.path}: "
                f"{case_result.error}"
            )
            continue

        if case_result.replay_diffs:
            issues.append(f"REPLAY-GATE-WORLD-DIFF-001 unapproved replay drift for '{case_id}'")
        if case_result.performance_regression:
            issues.append(f"REPLAY-GATE-WORLD-PERF-001 performance regression for '{case_id}'")

    return issues


def test_repository_corpus_passes_deterministic_replay_gate() -> None:
    issues = evaluate_replay_corpus_gate(COMBAT_CORPUS_DIR, WORLD_CORPUS_DIR)
    assert issues == []


def test_combat_replay_gate_detects_unapproved_diff(tmp_path: Path) -> None:
    combat_dir = tmp_path / "golden_traces"
    world_dir = tmp_path / "world_regressions"
    shutil.copytree(COMBAT_CORPUS_DIR, combat_dir)
    shutil.copytree(WORLD_CORPUS_DIR, world_dir)

    scenario_path = combat_dir / "combat_duel_trace.json"
    payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    payload["summary"]["run_id"] = "drifted_run_id"
    scenario_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    issues = evaluate_replay_corpus_gate(combat_dir, world_dir)
    assert any("REPLAY-GATE-COMBAT-DIFF-001" in issue for issue in issues)


def test_world_replay_gate_detects_unapproved_diff(tmp_path: Path) -> None:
    combat_dir = tmp_path / "golden_traces"
    world_dir = tmp_path / "world_regressions"
    shutil.copytree(COMBAT_CORPUS_DIR, combat_dir)
    shutil.copytree(WORLD_CORPUS_DIR, world_dir)

    case_path = world_dir / "exploration_day_cycle.json"
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    expected = payload.get("expected_replay")
    assert isinstance(expected, dict)
    expected["turn_index"] = 999
    case_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    issues = evaluate_replay_corpus_gate(combat_dir, world_dir)
    assert any("REPLAY-GATE-WORLD-DIFF-001" in issue for issue in issues)


def test_diff_approval_path_allows_explicitly_approved_drift(tmp_path: Path) -> None:
    combat_dir = tmp_path / "golden_traces"
    world_dir = tmp_path / "world_regressions"
    shutil.copytree(COMBAT_CORPUS_DIR, combat_dir)
    shutil.copytree(WORLD_CORPUS_DIR, world_dir)

    scenario_path = combat_dir / "combat_duel_trace.json"
    payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    payload["summary"]["rounds"] = 999
    scenario_id = str(payload["scenario_id"])
    scenario_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    issues = evaluate_replay_corpus_gate(
        combat_dir,
        world_dir,
        approved_drift_ids={scenario_id},
    )
    assert issues == []


def test_world_replay_gate_reports_structured_harness_execution_failure(
    tmp_path: Path, monkeypatch
) -> None:
    combat_dir = tmp_path / "golden_traces"
    world_dir = tmp_path / "world_regressions"
    shutil.copytree(COMBAT_CORPUS_DIR, combat_dir)
    shutil.copytree(WORLD_CORPUS_DIR, world_dir)

    class _BrokenHarness:
        def run_regression_suite(self, *, corpus_dir: Path) -> Any:
            raise RuntimeError(f"broken harness for {corpus_dir.name}")

    monkeypatch.setattr(
        sys.modules[__name__],
        "_load_world_harness_module",
        lambda: _BrokenHarness(),
    )

    issues = evaluate_replay_corpus_gate(combat_dir, world_dir)
    assert issues == [
        "REPLAY-GATE-WORLD-005 world harness execution failed: broken harness for world_regressions"
    ]
