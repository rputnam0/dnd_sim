"""Difficulty summaries retain unresolved trials and distinguish defeat from death."""

from __future__ import annotations

from collections import Counter
import logging
from statistics import mean
from typing import Any

from dnd_sim.benchmarks.trials import RecordedTrial, wilson_interval

logger = logging.getLogger(__name__)


def trial_row(trial: RecordedTrial, party_ids: set[str]) -> dict[str, Any]:
    result = trial.result
    decisions = [
        row
        for row in result.telemetry
        if row.get("telemetry_type") == "decision" and row.get("team") == "party"
    ]
    actions = Counter(
        f"{row['actor_id']}:{row['action_plan']}" for row in decisions if row.get("action_plan")
    )
    bonuses = Counter(
        f"{row['actor_id']}:{row['bonus_action_plan']}"
        for row in decisions
        if row.get("bonus_action_plan")
    )
    resources = {
        f"{actor}:{key}": value
        for actor, amounts in result.resources_spent.items()
        if actor in party_ids
        for key, value in amounts.items()
    }
    return dict(
        trial_index=result.trial_index,
        seed=trial.seed,
        outcome=result.outcome,
        termination_reason=result.termination_reason,
        censored=result.censored,
        rounds=result.rounds,
        party_hp=sum(result.remaining_hp.get(a, 0) for a in party_ids),
        any_down=any(result.downed_counts.get(a, 0) for a in party_ids),
        any_death=any(result.death_counts.get(a, 0) for a in party_ids),
        all_dead_at_stop=all(result.death_counts.get(a, 0) for a in party_ids),
        resources_spent=resources,
        actions=dict(actions),
        bonuses=dict(bonuses),
        movement_turns=sum(bool(row.get("movement_path")) for row in decisions),
        turns=len(decisions),
    )


def _distribution(values: list[int | float]) -> dict[str, float]:
    values = sorted(values)

    def quantile(p):
        index = (len(values) - 1) * p
        lower = int(index)
        upper = min(lower + 1, len(values) - 1)
        return values[lower] + (values[upper] - values[lower]) * (index - lower)

    return dict(mean=mean(values), p10=quantile(0.1), median=quantile(0.5), p90=quantile(0.9))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("Cannot summarize an empty benchmark sample")

    def rate(predicate):
        count = sum(bool(predicate(row)) for row in rows)
        return dict(
            count=count, rate=count / len(rows), ci95=list(wilson_interval(count, len(rows)))
        )

    summary = dict(
        n=len(rows),
        win=rate(lambda r: r["outcome"] == "party_victory"),
        defeat=rate(lambda r: r["outcome"] == "enemy_victory"),
    )
    for key in ("any_down", "any_death", "all_dead_at_stop", "censored"):
        summary[key] = rate(lambda r, key=key: r[key])
    for key in ("rounds", "party_hp", "movement_turns", "turns"):
        summary[key] = _distribution([row[key] for row in rows])
    keys = sorted({key for row in rows for key in row["resources_spent"]})
    summary["resources_spent"] = {
        key: _distribution([row["resources_spent"].get(key, 0) for row in rows]) for key in keys
    }
    for key in ("actions", "bonuses"):
        counter = Counter()
        for row in rows:
            counter.update(row[key])
        summary[key] = dict(sorted(counter.items()))
    summary["convergence"] = []
    for n in sorted({max(1, len(rows) // 4), max(1, len(rows) // 2), len(rows)}):
        wins = sum(row["outcome"] == "party_victory" for row in rows[:n])
        summary["convergence"].append(
            dict(n=n, win_rate=wins / n, ci95=list(wilson_interval(wins, n)))
        )
    return summary


def _percent(metric: dict[str, Any]) -> str:
    lo, hi = metric["ci95"]
    return f"{100 * metric['rate']:.1f}% [{100 * lo:.1f}, {100 * hi:.1f}]"


def render_roll_excerpt(records: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| # | Source → target | Action / fact | Dice faces | Total / outcome |",
        "|---:|---|---|---|---|",
    ]
    for record in records:
        fact = record["fact"]
        roll = fact.get("roll", fact)
        faces = ", ".join(f"{f['value']}({f['status']})" for f in roll.get("faces", []))
        if fact["kind"] == "damage":
            result = (
                f"{fact['raw_damage']} raw → {fact['applied_damage']} applied {fact['damage_type']}"
            )
        elif fact["kind"] == "healing":
            result = f"{fact['rolled_healing']} rolled → {fact['effective_healing']} healed"
        else:
            outcome = fact.get("outcome", "success" if fact.get("succeeded") else "failure")
            result = f"{roll.get('total')} vs {fact.get('threshold', fact.get('dc'))}: {outcome}"
        lines.append(
            f"| {record['sequence']} | {record['source_actor_id']} → {record['target_actor_id']} | "
            f"{record['action_id']} / {fact['kind']} | `{roll.get('expression', '')}`: {faces} | {result} |"
        )
    return lines


def render_report(report: dict[str, Any]) -> str:
    lines = [
        "# Level-five encounter stress test",
        "",
        f"Fixed design: **{report['trials_per_group']} trials per encounter/policy**, "
        f"master seed **{report['master_seed']}**. {len(report['groups'])} groups. "
        f"Source fingerprint: `{report['provenance']['source_sha256']}`.",
        "",
        "Four combat archetypes: Mara (fighter, HP49/AC18), Kestrel (rogue, HP38/AC16), "
        "Iona (cleric, HP38/AC18), Orrin (wizard, HP32/AC12). These are explicitly bounded "
        "subclass-neutral loadouts, not complete character sheets. "
        "See [mechanics and assumptions](../../../docs/level_five_benchmark.md).",
        "",
        "## Encounter outcomes",
        "",
        "Every percentage includes its two-sided 95% Wilson interval. All trials stay in "
        "the denominator, including censored trials. The three policies differ in willingness "
        "to spend resources; enemies use the same aggressive policy throughout.",
        "",
        "| Encounter | Policy | Win % [95% CI] | Any down % [95% CI] | Any death % [95% CI] | Mean rounds | Median HP left |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for group in report["groups"]:
        s = group["summary"]
        lines.append(
            f"| {group['scenario']} | {group['policy']} | {_percent(s['win'])} | "
            f"{_percent(s['any_down'])} | {_percent(s['any_death'])} | "
            f"{s['rounds']['mean']:.1f} | {s['party_hp']['median']:.0f}/157 |"
        )
    lines += [
        "",
        "## Policy sensitivity",
        "",
        "This spread is a sensitivity analysis, not another confidence interval. "
        "It excludes differences between these bots and actual human players.",
        "",
        "| Encounter | Win-rate range across tested policies | Largest win CI half-width |",
        "|---|---:|---:|",
    ]
    for scenario in sorted({g["scenario"] for g in report["groups"]}):
        groups = [g for g in report["groups"] if g["scenario"] == scenario]
        wins = [g["summary"]["win"]["rate"] for g in groups]
        width = max(
            (g["summary"]["win"]["ci95"][1] - g["summary"]["win"]["ci95"][0]) / 2 for g in groups
        )
        lines.append(
            f"| {scenario} | {100*min(wins):.1f}–{100*max(wins):.1f}% | ±{100*width:.1f} pp |"
        )
    lines += [
        "",
        "## Defeat, death, and unresolved fights",
        "",
        "Defeat means all party members are unconscious or dead. **All dead at stop** "
        "counts only confirmed deaths at termination; it is not eventual TPK probability. "
        "The model stops at defeat and does not simulate executions, capture, or later recovery.",
        "",
        "| Encounter / policy | Defeat % [95% CI] | All dead at stop % [95% CI] | Censored % [95% CI] |",
        "|---|---:|---:|---:|",
    ]
    for g in report["groups"]:
        s = g["summary"]
        lines.append(
            f"| {g['scenario']} / {g['policy']} | {_percent(s['defeat'])} | "
            f"{_percent(s['all_dead_at_stop'])} | {_percent(s['censored'])} |"
        )
    lines += [
        "",
        "## Resources and action diagnostics",
        "",
        "Actions below are declared plans. A target killed by the primary attack can cancel "
        "a planned bonus attack. Resources are actual engine spending, not plans.",
        "",
    ]
    for g in report["groups"]:
        s = g["summary"]
        lines += [
            f"### {g['scenario']} / {g['policy']}",
            "",
            f"Rounds p10/median/p90: {s['rounds']['p10']:g}/{s['rounds']['median']:g}/{s['rounds']['p90']:g}; "
            f"remaining HP p10/median/p90: {s['party_hp']['p10']:g}/{s['party_hp']['median']:g}/{s['party_hp']['p90']:g}.",
            "",
            "| Resource | Mean spent | p10 / median / p90 |",
            "|---|---:|---:|",
        ]
        for key, d in s["resources_spent"].items():
            lines.append(
                f"| {key} | {d['mean']:.2f} | {d['p10']:g} / {d['median']:g} / {d['p90']:g} |"
            )
        lines += [
            "",
            "Primary plans: " + ", ".join(f"`{k}` ×{v}" for k, v in s["actions"].items()) + ".",
            "",
            "Bonus plans: "
            + (", ".join(f"`{k}` ×{v}" for k, v in s["bonuses"].items()) or "none")
            + ".",
            "",
            "Win convergence: "
            + "; ".join(
                f"n={v['n']}: {100*v['win_rate']:.1f}% "
                f"[{100*v['ci95'][0]:.1f}, {100*v['ci95'][1]:.1f}]"
                for v in s["convergence"]
            )
            + ".",
            "",
        ]
    lines += [
        "## Rolls, replay, and interpretation",
        "",
        "[Readable roll excerpts](rolls.md), [machine-readable summary](summary.json), "
        "[every compact trial](trials.jsonl.gz), and `samples/*.json.gz` include seeds, "
        "authoritative roll facts, actual integer draws, planned turns, and terminal snapshots. "
        "The first trial and first instance of each additional outcome are retained per group. "
        "Each recorded sample was rerun and compared against its original complete engine result.",
        "",
        f"Conformance evidence: **{report['verification']['status']}**. "
        "See `verification.txt` and the mechanic-to-test map in the fixture directory.",
        "",
        "Confidence intervals quantify Monte Carlo sampling error under this exact model. "
        "They do not quantify omitted rules, tactical quality, encounter realism, or "
        "uncertainty about human play. Intervals are marginal, not simultaneous across all "
        "cells; cross-policy differences have not been given significance tests. "
        "Sample sizes were fixed before the final run. Quantile ranges describe outcomes, "
        "not uncertainty in their means.",
        "",
        "Wilson reference: [NIST proportion intervals](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm). "
        "Rules: [Wizards SRD 5.1](https://media.wizards.com/2023/downloads/dnd/SRD_CC_v5.1.pdf).",
        "",
    ]
    return "\n".join(lines)
