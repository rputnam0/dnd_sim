from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from dnd_sim.models import TrialResult


def _extract_actor_names(summary: dict[str, Any]) -> list[str]:
    return sorted(summary.get("per_actor_damage_taken", {}).keys())


def generate_plots_from_trials(trials: list[TrialResult], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid")
    plot_paths: dict[str, str] = {}

    rounds = [trial.rounds for trial in trials]
    if rounds:
        plt.figure(figsize=(8, 4))
        sns.histplot(rounds, bins=min(20, max(rounds) - min(rounds) + 1), kde=False)
        plt.title("Rounds Distribution")
        plt.xlabel("Rounds")
        plt.ylabel("Count")
        path = out_dir / "rounds_histogram.png"
        plt.tight_layout()
        plt.savefig(path)
        plt.close()
        plot_paths["rounds_histogram"] = str(path)

    damage_rows = []
    for trial in trials:
        for actor_id, dmg in trial.damage_taken.items():
            damage_rows.append({"actor": actor_id, "damage_taken": dmg})

    if damage_rows:
        damage_df = pd.DataFrame(damage_rows)
        plt.figure(figsize=(10, 4))
        sns.boxplot(data=damage_df, x="actor", y="damage_taken")
        plt.title("Damage Taken Per Actor")
        plt.xticks(rotation=20)
        path = out_dir / "damage_taken_boxplot.png"
        plt.tight_layout()
        plt.savefig(path)
        plt.close()
        plot_paths["damage_taken_boxplot"] = str(path)

    resource_rows = []
    for trial in trials:
        for actor_id, resources in trial.resources_spent.items():
            for resource_name, spent in resources.items():
                resource_rows.append(
                    {
                        "actor": actor_id,
                        "resource": resource_name,
                        "spent": spent,
                    }
                )

    if resource_rows:
        resource_df = pd.DataFrame(resource_rows)
        plt.figure(figsize=(10, 4))
        sns.barplot(data=resource_df, x="actor", y="spent", hue="resource", estimator="mean")
        plt.title("Average Resource Spend")
        plt.xticks(rotation=20)
        path = out_dir / "resource_spend_bar.png"
        plt.tight_layout()
        plt.savefig(path)
        plt.close()
        plot_paths["resource_spend_bar"] = str(path)

    if rounds:
        max_round = max(rounds)
        cutoffs = list(range(1, max_round + 1))
        series = []
        for cutoff in cutoffs:
            party_wins = sum(
                1 for trial in trials if trial.winner == "party" and trial.rounds <= cutoff
            )
            series.append(party_wins / len(trials))

        plt.figure(figsize=(8, 4))
        sns.lineplot(x=cutoffs, y=series)
        plt.title("Party Win Rate by Round Cutoff")
        plt.xlabel("Round Cutoff")
        plt.ylabel("Win Rate")
        plt.ylim(0, 1)
        path = out_dir / "party_win_rate_by_round.png"
        plt.tight_layout()
        plt.savefig(path)
        plt.close()
        plot_paths["party_win_rate_by_round"] = str(path)

    return plot_paths


def build_report_markdown(
    *,
    summary: dict[str, Any],
    run_config: dict[str, Any],
    plot_paths: dict[str, str],
) -> str:
    lines = [
        "# Encounter Simulation Report",
        "",
        "## Scenario Config Snapshot",
        "",
        f"- Scenario ID: `{run_config.get('scenario_id', 'unknown')}`",
        f"- Run ID: `{summary.get('run_id', 'unknown')}`",
        f"- Trials: `{summary.get('trials', 0)}`",
        f"- Seed: `{run_config.get('seed', 'unknown')}`",
        "",
        "## Outcome Overview",
        "",
        f"- Party win rate: `{summary.get('party_win_rate', 0):.3f}`",
        f"- Enemy win rate: `{summary.get('enemy_win_rate', 0):.3f}`",
    ]

    rounds = summary.get("rounds", {})
    if rounds:
        lines.extend(
            [
                f"- Rounds mean/median/p10/p90/p95: `{rounds.get('mean', 0):.2f}` / "
                f"`{rounds.get('median', 0):.2f}` / `{rounds.get('p10', 0):.2f}` / "
                f"`{rounds.get('p90', 0):.2f}` / `{rounds.get('p95', 0):.2f}`",
                "",
            ]
        )

    lines.extend(
        [
            "## Per-Combatant Metrics",
            "",
            "| Actor | Damage Taken (mean) | Damage Dealt (mean) | Downed (mean) | Deaths (mean) |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )

    damage_taken = summary.get("per_actor_damage_taken", {})
    damage_dealt = summary.get("per_actor_damage_dealt", {})
    downed = summary.get("per_actor_downed", {})
    deaths = summary.get("per_actor_deaths", {})

    for actor in _extract_actor_names(summary):
        lines.append(
            f"| {actor} | {damage_taken.get(actor, {}).get('mean', 0):.2f} | "
            f"{damage_dealt.get(actor, {}).get('mean', 0):.2f} | "
            f"{downed.get(actor, {}).get('mean', 0):.2f} | "
            f"{deaths.get(actor, {}).get('mean', 0):.2f} |"
        )

    lines.extend(["", "## Resource Consumption", ""])
    resource_data = summary.get("per_actor_resources_spent", {})
    if not resource_data:
        lines.append("No tracked resource consumption in this run.")
    else:
        lines.extend(["| Actor | Resource | Mean Spent |", "| --- | --- | ---: |"])
        for actor, resources in sorted(resource_data.items()):
            for resource_name, metric in sorted(resources.items()):
                lines.append(f"| {actor} | {resource_name} | {metric.get('mean', 0):.2f} |")

    lines.extend(["", "## Notable Failure Modes", ""])
    lines.append(
        "- Review actors with high mean death counts or downed counts for tactical adjustments."
    )
    lines.append("- Compare party win rate against target success threshold for encounter tuning.")

    if plot_paths:
        lines.extend(["", "## Visualizations", ""])
        for label, path in sorted(plot_paths.items()):
            rel = Path(path).name
            lines.append(f"- {label}: `plots/{rel}`")

    return "\n".join(lines) + "\n"
