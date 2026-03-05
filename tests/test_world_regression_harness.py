from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType


def _load_harness_module() -> ModuleType:
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts/perf/run_world_regressions.py"
    spec = importlib.util.spec_from_file_location("world_regressions_harness", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load world regression harness module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _copy_corpus_to_tmp(tmp_path: Path) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    source = repo_root / "artifacts/world_regressions"
    destination = tmp_path / "world_regressions"
    shutil.copytree(source, destination)
    return destination


def _load_case(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected case payload in {path}")
    return payload


def test_world_regression_suite_passes_on_canonical_corpus(tmp_path: Path) -> None:
    harness = _load_harness_module()
    corpus_dir = _copy_corpus_to_tmp(tmp_path)

    result = harness.run_regression_suite(corpus_dir=corpus_dir)

    assert result.passed is True
    assert result.total_cases == 3
    assert result.failed_cases == 0
    assert result.diff_failures == 0
    assert result.performance_failures == 0


def test_world_regression_suite_detects_replay_diff(tmp_path: Path) -> None:
    harness = _load_harness_module()
    corpus_dir = _copy_corpus_to_tmp(tmp_path)
    case_path = corpus_dir / "exploration_day_cycle.json"
    case_payload = _load_case(case_path)
    expected = case_payload["expected_replay"]
    if not isinstance(expected, dict):
        raise RuntimeError("expected_replay must be a mapping for this test")
    expected["turn_index"] = 999
    case_path.write_text(
        json.dumps(case_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    result = harness.run_regression_suite(corpus_dir=corpus_dir, tolerance_pct=1000.0)

    assert result.passed is False
    assert result.diff_failures == 1
    diff_case = next(
        case for case in result.case_results if case.case_id == "exploration_day_cycle"
    )
    assert diff_case.passed is False
    assert any("$.turn_index" in line for line in diff_case.replay_diffs)


def test_world_regression_suite_updates_snapshots_when_requested(tmp_path: Path) -> None:
    harness = _load_harness_module()
    corpus_dir = _copy_corpus_to_tmp(tmp_path)
    case_path = corpus_dir / "world_state_lifecycle.json"
    case_payload = _load_case(case_path)
    case_payload["expected_replay"] = {}
    case_path.write_text(
        json.dumps(case_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    updated = harness.run_regression_suite(corpus_dir=corpus_dir, update_snapshots=True)
    rerun = harness.run_regression_suite(corpus_dir=corpus_dir)

    assert updated.passed is True
    assert rerun.passed is True
    refreshed_payload = _load_case(case_path)
    assert isinstance(refreshed_payload.get("expected_replay"), dict)
    assert refreshed_payload["expected_replay"] != {}


def test_world_regression_suite_detects_performance_regression(tmp_path: Path) -> None:
    harness = _load_harness_module()
    corpus_dir = _copy_corpus_to_tmp(tmp_path)
    case_path = corpus_dir / "encounter_wave_progression.json"
    case_payload = _load_case(case_path)
    case_payload["performance_baseline_ms"] = 0.0001
    case_path.write_text(
        json.dumps(case_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    result = harness.run_regression_suite(
        corpus_dir=corpus_dir,
        tolerance_pct=0.0,
        fail_on_perf=True,
    )

    assert result.passed is False
    assert result.performance_failures == 1
    perf_case = next(
        case for case in result.case_results if case.case_id == "encounter_wave_progression"
    )
    assert perf_case.performance_regression is True
