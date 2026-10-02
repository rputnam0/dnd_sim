"""Render source-backed Wilson-interval figures from a completed benchmark summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path)
    args = parser.parse_args()
    report = json.loads(args.summary.read_text())
    groups = report["groups"]
    scenarios = sorted({g["scenario"] for g in groups})
    profiles = [
        p
        for p in ("conservative", "typical", "aggressive")
        if any(g["policy"] == p for g in groups)
    ]
    labels = {
        "01_raider_patrol": "Clustered raiders",
        "02_veteran_line": "Three veterans",
        "03_archer_cover": "Archers behind cover",
        "04_cinder_sentinel": "Cinder Sentinel",
        "05_overwhelming_line": "Six veterans",
        "06_spread_patrol": "Spread raiders",
        "07_attrition": "Three waves, no rest",
        "08_five_veterans": "Five veterans",
    }
    colors = {"conservative": "#62748b", "typical": "#076b9c", "aggressive": "#c55225"}
    fig, axes = plt.subplots(1, 2, figsize=(12, 7), sharey=True, layout="constrained")
    for ax, metric, title in zip(
        axes, ("win", "any_down"), ("Party victory", "At least one party member downed")
    ):
        for index, profile in enumerate(profiles):
            rows = [
                next(g for g in groups if g["scenario"] == s and g["policy"] == profile)
                for s in scenarios
            ]
            p = [100 * g["summary"][metric]["rate"] for g in rows]
            low = [100 * g["summary"][metric]["ci95"][0] for g in rows]
            high = [100 * g["summary"][metric]["ci95"][1] for g in rows]
            y = [j + (index - (len(profiles) - 1) / 2) * 0.22 for j in range(len(rows))]
            ax.errorbar(
                p,
                y,
                xerr=[
                    [max(0, v - l) for v, l in zip(p, low)],
                    [max(0, h - v) for v, h in zip(p, high)],
                ],
                fmt="o",
                ms=5,
                capsize=3,
                lw=1.4,
                color=colors[profile],
                label=profile.title(),
            )
        ax.set_xlim(-3, 103)
        ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
        ax.set_title(title, loc="left", fontsize=12, fontweight="bold", pad=14)
        ax.grid(axis="x", color="#dce2e9", lw=0.7)
        ax.set_axisbelow(True)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(axis="both", length=0)
    axes[0].set_yticks(range(len(scenarios)), [labels.get(s, s) for s in scenarios], fontsize=10)
    axes[0].invert_yaxis()
    axes[1].legend(loc="upper center", bbox_to_anchor=(0.5, -0.10), ncol=3, frameon=False)
    fig.suptitle(
        f"Level-five encounter difficulty · {report['trials_per_group']*len(groups):,} trials\n"
        "Points: observed rates · Bars: 95% Wilson sampling intervals",
        fontsize=15,
        fontweight="bold",
    )
    fig.supxlabel(
        "Restricted loadouts and fixed enemy tactics. Policy differences and model limitations are separate from sampling error.",
        fontsize=9,
    )
    for suffix in ("png", "svg"):
        fig.savefig(
            args.summary.parent / f"difficulty.{suffix}",
            dpi=180,
            metadata={"Creator": "dnd-sim L5-01"},
        )
    plt.close(fig)
    report_path = args.summary.parent / "report.md"
    if report_path.exists():
        text = report_path.read_text()
        anchor = "## Encounter outcomes"
        figure = (
            "![Encounter victory and downing rates with 95% Wilson intervals](difficulty.png)\n\n"
        )
        if figure not in text:
            report_path.write_text(text.replace(anchor, figure + anchor, 1))


if __name__ == "__main__":
    main()
