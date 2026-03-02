from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Sequence

from dnd_sim.engine import run_simulation
from dnd_sim.io import load_character_db, load_scenario, load_strategy_registry

_METRIC_ALIASES = {
    "party_win_rate": "party_win_rate",
    "enemy_win_rate": "enemy_win_rate",
    "rounds_mean": "rounds.mean",
    "rounds_median": "rounds.median",
    "rounds_p10": "rounds.p10",
    "rounds_p90": "rounds.p90",
    "rounds_p95": "rounds.p95",
}


def _extract_metric(summary: dict[str, Any], metric_name: str) -> float:
    path = _METRIC_ALIASES.get(metric_name, metric_name)
    cursor: Any = summary
    for segment in path.split("."):
        if not isinstance(cursor, dict) or segment not in cursor:
            raise ValueError(f"Metric not found in summary: {metric_name}")
        cursor = cursor[segment]
    if not isinstance(cursor, (int, float)):
        raise ValueError(f"Metric is not numeric: {metric_name}")
    return float(cursor)


def _evaluate_metric_expectation(
    *,
    actual: float,
    expectation: Any,
    default_tolerance: float,
) -> dict[str, Any]:
    if isinstance(expectation, (int, float)):
        target = float(expectation)
        tolerance = float(default_tolerance)
        error = actual - target
        return {
            "actual": actual,
            "expected": {"target": target, "tolerance": tolerance},
            "error": error,
            "pass": abs(error) <= tolerance,
        }

    if not isinstance(expectation, dict):
        raise ValueError(f"Unsupported expectation payload: {expectation!r}")

    if "target" in expectation:
        target = float(expectation["target"])
        tolerance = float(expectation.get("tolerance", default_tolerance))
        error = actual - target
        return {
            "actual": actual,
            "expected": {"target": target, "tolerance": tolerance},
            "error": error,
            "pass": abs(error) <= tolerance,
        }

    lower = float(expectation.get("min", -math.inf))
    upper = float(expectation.get("max", math.inf))
    if lower > upper:
        raise ValueError(f"Invalid range expectation (min > max): {expectation!r}")
    if lower <= actual <= upper:
        error = 0.0
    elif actual < lower:
        error = actual - lower
    else:
        error = actual - upper
    return {
        "actual": actual,
        "expected": {
            "min": None if math.isinf(lower) else lower,
            "max": None if math.isinf(upper) else upper,
        },
        "error": error,
        "pass": lower <= actual <= upper,
    }


def run_calibration_harness(
    scenario_paths: Sequence[Path | str],
    *,
    trials: int = 100,
    seed: int = 1,
    default_tolerance: float = 0.05,
) -> dict[str, Any]:
    if trials <= 0:
        raise ValueError("trials must be >= 1")
    if default_tolerance < 0:
        raise ValueError("default_tolerance must be >= 0")

    benchmark_rows: list[dict[str, Any]] = []
    for idx, raw_path in enumerate(scenario_paths):
        scenario_path = Path(raw_path)
        loaded = load_scenario(scenario_path)
        character_db = load_character_db(Path(loaded.config.character_db_dir))
        strategy_registry = load_strategy_registry(loaded)
        artifacts = run_simulation(
            loaded,
            character_db,
            {},
            strategy_registry,
            trials=trials,
            seed=seed + idx,
            run_id=f"calibration_{idx}",
        )
        summary_payload = artifacts.summary.to_dict()

        raw_expectations = loaded.config.assumption_overrides.get("benchmark_expectations", {})
        expectations = raw_expectations if isinstance(raw_expectations, dict) else {}
        metric_results: dict[str, dict[str, Any]] = {}
        scenario_passed = True

        for metric_name, expectation in expectations.items():
            metric_key = str(metric_name)
            try:
                actual = _extract_metric(summary_payload, metric_key)
                metric_result = _evaluate_metric_expectation(
                    actual=actual,
                    expectation=expectation,
                    default_tolerance=default_tolerance,
                )
            except Exception as exc:  # pragma: no cover - defensive path
                metric_result = {
                    "actual": None,
                    "expected": expectation,
                    "error": None,
                    "pass": False,
                    "message": str(exc),
                }
            metric_results[metric_key] = metric_result
            scenario_passed = scenario_passed and bool(metric_result.get("pass"))

        pass_count = sum(1 for row in metric_results.values() if bool(row.get("pass")))
        metric_count = len(metric_results)
        benchmark_rows.append(
            {
                "scenario_id": loaded.config.scenario_id,
                "scenario_path": str(scenario_path.resolve()),
                "passed": scenario_passed,
                "metrics": metric_results,
                "pass_rate": (pass_count / metric_count) if metric_count else 1.0,
            }
        )

    return {
        "trials": trials,
        "seed": seed,
        "default_tolerance": default_tolerance,
        "all_passed": all(row["passed"] for row in benchmark_rows),
        "benchmarks": benchmark_rows,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run calibration checks for one or more benchmark scenarios."
    )
    parser.add_argument(
        "--scenario",
        action="append",
        required=True,
        type=Path,
        help="Path to benchmark scenario JSON. Provide multiple times for multiple scenarios.",
    )
    parser.add_argument("--trials", type=int, default=100, help="Trials per benchmark scenario.")
    parser.add_argument("--seed", type=int, default=1, help="Base RNG seed.")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.05,
        help="Default absolute tolerance for scalar target expectations.",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Optional path to write JSON output."
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    payload = run_calibration_harness(
        args.scenario,
        trials=args.trials,
        seed=args.seed,
        default_tolerance=args.tolerance,
    )
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out is not None:
        out_path = args.out.resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"Calibration output written: {out_path}")
    else:
        print(text)


if __name__ == "__main__":
    main()
