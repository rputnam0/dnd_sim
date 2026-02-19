from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from dnd_sim.models import TrialResult
from dnd_sim.reporting import build_report_markdown, generate_plots_from_trials


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate markdown report from simulation run outputs."
    )
    parser.add_argument("--run", required=True, type=Path, help="Path to summary.json")
    parser.add_argument("--out", required=True, type=Path, help="Output directory")
    return parser


def _parse_int_field(value: Any, *, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid integer value for '{field_name}': {value!r}") from exc


def _parse_json_object_field(value: Any, *, field_name: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(key): payload for key, payload in value.items()}
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return {str(key): payload for key, payload in parsed.items()}
    raise ValueError(f"Invalid JSON object for '{field_name}': {value!r}")


def _parse_json_int_dict_field(value: Any, *, field_name: str) -> dict[str, int]:
    parsed = _parse_json_object_field(value, field_name=field_name)
    return {str(key): int(amount) for key, amount in parsed.items()}


def _parse_resources_spent_field(value: Any) -> dict[str, dict[str, int]]:
    parsed = _parse_json_object_field(value, field_name="resources_spent")
    resources: dict[str, dict[str, int]] = {}
    for actor_id, resource_map in parsed.items():
        if not isinstance(resource_map, dict):
            raise ValueError(
                f"Invalid JSON object for 'resources_spent.{actor_id}': {resource_map!r}"
            )
        resources[actor_id] = {str(name): int(amount) for name, amount in resource_map.items()}
    return resources


def _trial_result_from_row(row: dict[str, Any]) -> TrialResult:
    return TrialResult(
        trial_index=_parse_int_field(row.get("trial_index"), field_name="trial_index"),
        rounds=_parse_int_field(row.get("rounds"), field_name="rounds"),
        winner=str(row.get("winner", "draw")),
        damage_taken=_parse_json_int_dict_field(row.get("damage_taken"), field_name="damage_taken"),
        damage_dealt=_parse_json_int_dict_field(row.get("damage_dealt"), field_name="damage_dealt"),
        resources_spent=_parse_resources_spent_field(row.get("resources_spent")),
        downed_counts=_parse_json_int_dict_field(row.get("downed_counts"), field_name="downed_counts"),
        death_counts=_parse_json_int_dict_field(row.get("death_counts"), field_name="death_counts"),
        remaining_hp=_parse_json_int_dict_field(row.get("remaining_hp"), field_name="remaining_hp"),
    )


def _load_trial_results(trial_rows_path: Path) -> list[TrialResult]:
    if not trial_rows_path.exists():
        return []

    suffix = trial_rows_path.suffix.lower()
    if suffix == ".parquet":
        try:
            import pandas as pd  # type: ignore
        except Exception as exc:  # pragma: no cover - import error path depends on env.
            raise ValueError(
                f"Cannot read parquet trial rows at {trial_rows_path}: pandas/parquet support missing"
            ) from exc

        frame = pd.read_parquet(trial_rows_path)
        return [_trial_result_from_row(row) for row in frame.to_dict(orient="records")]

    if suffix == ".csv":
        rows: list[TrialResult] = []
        with trial_rows_path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                rows.append(_trial_result_from_row(row))
        return rows

    raise ValueError(f"Unsupported trial rows format: {trial_rows_path}")


def _resolve_trial_rows_path(run_dir: Path, run_config: dict[str, Any]) -> Path:
    configured = run_config.get("trial_rows_path")
    if isinstance(configured, str) and configured.strip():
        configured_path = Path(configured)
        if not configured_path.is_absolute():
            configured_path = run_dir / configured_path
        return configured_path

    parquet_path = run_dir / "trial_rows.parquet"
    if parquet_path.exists():
        return parquet_path
    return run_dir / "trial_rows.csv"


def main() -> None:
    args = build_parser().parse_args()
    summary_path = args.run.resolve()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    run_dir = summary_path.parent
    run_config_path = run_dir / "run_config.json"
    run_config = {}
    if run_config_path.exists():
        run_config = json.loads(run_config_path.read_text(encoding="utf-8"))

    trial_rows_path = _resolve_trial_rows_path(run_dir, run_config)
    if not trial_rows_path.exists():
        fallback_csv = run_dir / "trial_rows.csv"
        if trial_rows_path != fallback_csv and fallback_csv.exists():
            trial_rows_path = fallback_csv

    trial_results = _load_trial_results(trial_rows_path)
    plot_paths = {}
    if trial_results:
        plot_paths = generate_plots_from_trials(trial_results, args.out.resolve() / "plots")

    report = build_report_markdown(summary=summary, run_config=run_config, plot_paths=plot_paths)
    out_path = args.out.resolve() / "report.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"Report written: {out_path}")


if __name__ == "__main__":
    main()
