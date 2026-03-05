from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts/ai/run_benchmarks.py"

spec = importlib.util.spec_from_file_location("run_benchmarks", SCRIPT_PATH)
if spec is None or spec.loader is None:  # pragma: no cover
    raise RuntimeError(f"Unable to load module from {SCRIPT_PATH}")
run_benchmarks = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = run_benchmarks
spec.loader.exec_module(run_benchmarks)


def _write_corpus(tmp_path: Path, payload: dict[str, object]) -> Path:
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return corpus_path


def test_load_benchmark_corpus_requires_all_required_categories(tmp_path: Path) -> None:
    payload = json.loads(run_benchmarks.DEFAULT_CORPUS_PATH.read_text(encoding="utf-8"))
    payload["benchmarks"] = [
        row for row in payload["benchmarks"] if row.get("category") != "legendary_recharge"
    ]
    corpus_path = _write_corpus(tmp_path, payload)

    with pytest.raises(ValueError, match="legendary_recharge"):
        run_benchmarks.load_benchmark_corpus(corpus_path)


def test_run_benchmark_suite_primary_beats_baselines_and_has_rationale() -> None:
    result = run_benchmarks.run_benchmark_suite()

    assert result["all_passed"] is True
    assert result["required_category_coverage_pass"] is True
    assert result["rationale_coverage"]["pass"] is True

    thresholds = result["thresholds"]
    for case in result["benchmarks"]:
        assert case["pass"] is True
        assert case["primary_margin_vs_base"] >= thresholds["minimum_primary_margin_vs_base"]
        assert (
            case["primary_margin_vs_highest_threat"]
            >= thresholds["minimum_primary_margin_vs_highest_threat"]
        )
        assert case["strategies"]["primary"]["rationale"]["has_action_selection"] is True


def test_run_benchmark_suite_fails_unreachable_rationale_threshold(tmp_path: Path) -> None:
    payload = json.loads(run_benchmarks.DEFAULT_CORPUS_PATH.read_text(encoding="utf-8"))
    payload["thresholds"]["minimum_primary_rationale_coverage"] = 1.01
    corpus_path = _write_corpus(tmp_path, payload)

    result = run_benchmarks.run_benchmark_suite(corpus_path)

    assert result["rationale_coverage"]["pass"] is False
    assert result["all_passed"] is False
