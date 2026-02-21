from __future__ import annotations

import argparse
from pathlib import Path

from dnd_sim.engine import run_simulation
from dnd_sim.io import (
    build_run_dir,
    default_results_dir,
    load_character_db,
    load_custom_simulation_runner,
    load_scenario,
    load_strategy_registry,
    load_traits_db,
    write_json,
    write_trial_rows,
)
from dnd_sim.reporting import build_report_markdown, generate_plots_from_trials


def _load_traits_db_for_run(character_db_dir: Path) -> dict:
    # Canonical rules DB traits live in repo-root `db/rules/2014/traits`.
    canonical = (Path(__file__).resolve().parents[2] / "db" / "rules" / "2014" / "traits").resolve()
    traits = load_traits_db(canonical)

    # Scenario-local overrides are optional: `<character_db_dir>/../traits`.
    local = (character_db_dir.parent / "traits").resolve()
    if local.exists():
        traits.update(load_traits_db(local))
    return traits


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run encounter simulation.")
    parser.add_argument("--scenario", required=True, type=Path, help="Path to scenario JSON")
    parser.add_argument("--trials", type=int, default=5000, help="Number of Monte Carlo trials")
    parser.add_argument("--seed", type=int, default=1, help="Random seed")
    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Descriptive run name suffix (defaults to scenario_id).",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    loaded = load_scenario(args.scenario)
    db_dir = (Path(loaded.config.character_db_dir)).resolve()
    character_db = load_character_db(db_dir)
    traits_db = _load_traits_db_for_run(db_dir)
    results_root = default_results_dir().resolve()
    run_name = args.name or loaded.config.scenario_id
    run_dir = build_run_dir(results_root, run_name)
    run_id = run_dir.name

    custom_runner = load_custom_simulation_runner(loaded)
    if custom_runner is not None:
        custom_output = custom_runner(
            scenario=loaded,
            character_db=character_db,
            traits_db=traits_db,
            trials=args.trials,
            seed=args.seed,
            run_dir=run_dir,
        )
        if not isinstance(custom_output, dict):
            raise ValueError("Custom simulation runner must return a dictionary payload.")
        if "summary" not in custom_output or "trial_rows" not in custom_output:
            raise ValueError("Custom simulation output must include 'summary' and 'trial_rows'.")

        summary_payload = custom_output["summary"]
        trial_rows = custom_output["trial_rows"]
        report_md = custom_output.get("report_markdown")
        plot_paths = custom_output.get("plot_paths", {})
        trial_path = write_trial_rows(run_dir / "trial_rows", trial_rows)
        write_json(run_dir / "summary.json", summary_payload)
    else:
        strategy_registry = load_strategy_registry(loaded)
        artifacts = run_simulation(
            loaded,
            character_db,
            traits_db,
            strategy_registry,
            trials=args.trials,
            seed=args.seed,
            run_id=run_id,
        )
        trial_path = write_trial_rows(run_dir / "trial_rows", artifacts.trial_rows)
        summary_payload = artifacts.summary.to_dict()
        write_json(run_dir / "summary.json", summary_payload)
        plot_paths = generate_plots_from_trials(artifacts.trial_results, run_dir / "plots")
        report_md = build_report_markdown(
            summary=summary_payload,
            run_config={
                "scenario_id": loaded.config.scenario_id,
                "scenario_path": str(args.scenario.resolve()),
                "seed": args.seed,
                "trials": args.trials,
                "trial_rows_path": str(trial_path),
                "ruleset": loaded.config.ruleset,
                "results_root": str(results_root),
                "run_name": run_name,
            },
            plot_paths=plot_paths,
        )

    run_config = {
        "scenario_id": loaded.config.scenario_id,
        "scenario_path": str(args.scenario.resolve()),
        "seed": args.seed,
        "trials": args.trials,
        "trial_rows_path": str(trial_path),
        "ruleset": loaded.config.ruleset,
        "results_root": str(results_root),
        "run_name": run_name,
        "custom_simulation": bool(custom_runner),
    }
    write_json(run_dir / "run_config.json", run_config)

    if not isinstance(report_md, str) or not report_md.strip():
        report_md = (
            "# Encounter Simulation Report\n\n"
            "Custom simulation runner did not provide a report body.\n\n"
            f"Summary JSON: `{run_dir / 'summary.json'}`\n"
        )
    (run_dir / "report.md").write_text(report_md, encoding="utf-8")

    print(f"Simulation complete: {run_dir}")
    print(f"Summary: {run_dir / 'summary.json'}")
    print(f"Report: {run_dir / 'report.md'}")


if __name__ == "__main__":
    main()
