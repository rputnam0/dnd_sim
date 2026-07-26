from __future__ import annotations

import logging
import statistics

from dnd_sim.models import SimulationSummary, SummaryMetric, TrialResult

logger = logging.getLogger(__name__)

_TERMINAL_STATE_CONTRACT: dict[str, tuple[str, bool]] = {
    "party_victory": ("party", False),
    "enemy_victory": ("enemy", False),
    "draw": ("draw", False),
    "timeout": ("draw", True),
    "censored": ("draw", True),
}


def _normalized_trial_outcome(trial: TrialResult) -> str:
    outcome = str(trial.outcome or "").strip().lower()
    aliases = {
        "enemy_defeat": "party_victory",
        "party": "party_victory",
        "party_defeat": "enemy_victory",
        "enemy": "enemy_victory",
    }
    if outcome:
        return aliases.get(outcome, outcome)
    if trial.winner == "party":
        return "party_victory"
    if trial.winner == "enemy":
        return "enemy_victory"
    return "draw"


def _summary_metric(values: list[float]) -> SummaryMetric:
    ordered = sorted(values)
    return SummaryMetric(
        mean=float(statistics.mean(ordered)),
        median=float(statistics.median(ordered)),
        p10=float(ordered[int(0.10 * (len(ordered) - 1))]),
        p90=float(ordered[int(0.90 * (len(ordered) - 1))]),
        p95=float(ordered[int(0.95 * (len(ordered) - 1))]),
    )


def build_simulation_summary(
    *,
    run_id: str,
    scenario_id: str,
    trials: int,
    trial_results: list[TrialResult],
    tracked_resource_names: dict[str, set[str]],
) -> SimulationSummary:
    if trials <= 0:
        raise ValueError("trials must be greater than zero")
    if trials != len(trial_results):
        raise ValueError("trials must equal len(trial_results)")

    outcomes = [_normalized_trial_outcome(trial) for trial in trial_results]
    for trial, outcome in zip(trial_results, outcomes, strict=True):
        expected = _TERMINAL_STATE_CONTRACT.get(outcome)
        winner = str(trial.winner).strip().lower()
        actual = (winner, bool(trial.censored))
        if expected is None or actual != expected:
            raise ValueError(
                "invalid terminal state for trial "
                f"{trial.trial_index}: outcome={outcome!r}, winner={winner!r}, "
                f"censored={bool(trial.censored)!r}"
            )

    censored_flags = [bool(trial.censored) for trial in trial_results]
    party_wins = sum(
        outcome == "party_victory" and not is_censored
        for outcome, is_censored in zip(outcomes, censored_flags, strict=True)
    )
    enemy_wins = sum(
        outcome == "enemy_victory" and not is_censored
        for outcome, is_censored in zip(outcomes, censored_flags, strict=True)
    )
    draws = sum(
        outcome == "draw" and not is_censored
        for outcome, is_censored in zip(outcomes, censored_flags, strict=True)
    )
    timeouts = sum(outcome == "timeout" for outcome in outcomes)
    censored = sum(censored_flags)
    resolved = sum(not flag for flag in censored_flags)

    actor_ids = sorted(trial_results[0].damage_taken.keys()) if trial_results else []

    per_actor_damage_taken = {
        actor_id: _summary_metric([trial.damage_taken.get(actor_id, 0) for trial in trial_results])
        for actor_id in actor_ids
    }
    per_actor_damage_dealt = {
        actor_id: _summary_metric([trial.damage_dealt.get(actor_id, 0) for trial in trial_results])
        for actor_id in actor_ids
    }

    resources_all: dict[str, dict[str, list[float]]] = {actor_id: {} for actor_id in actor_ids}
    for trial in trial_results:
        for actor_id in actor_ids:
            for resource_name in tracked_resource_names.get(actor_id, set()):
                resources_all[actor_id].setdefault(resource_name, [])
            for resource_name, amount in trial.resources_spent.get(actor_id, {}).items():
                resources_all[actor_id].setdefault(resource_name, []).append(float(amount))
            for resource_name in resources_all[actor_id]:
                if resource_name not in trial.resources_spent.get(actor_id, {}):
                    resources_all[actor_id][resource_name].append(0.0)

    per_actor_resources_spent: dict[str, dict[str, SummaryMetric]] = {}
    for actor_id, resource_map in resources_all.items():
        per_actor_resources_spent[actor_id] = {
            resource_name: _summary_metric(values) for resource_name, values in resource_map.items()
        }

    per_actor_downed = {
        actor_id: _summary_metric([trial.downed_counts.get(actor_id, 0) for trial in trial_results])
        for actor_id in actor_ids
    }
    per_actor_deaths = {
        actor_id: _summary_metric([trial.death_counts.get(actor_id, 0) for trial in trial_results])
        for actor_id in actor_ids
    }
    per_actor_remaining_hp = {
        actor_id: _summary_metric([trial.remaining_hp.get(actor_id, 0) for trial in trial_results])
        for actor_id in actor_ids
    }

    return SimulationSummary(
        run_id=run_id,
        scenario_id=scenario_id,
        trials=trials,
        party_win_rate=party_wins / trials,
        enemy_win_rate=enemy_wins / trials,
        draw_rate=draws / trials,
        timeout_rate=timeouts / trials,
        censored_rate=censored / trials,
        resolved_rate=resolved / trials,
        rounds=_summary_metric([trial.rounds for trial in trial_results]),
        per_actor_damage_taken=per_actor_damage_taken,
        per_actor_damage_dealt=per_actor_damage_dealt,
        per_actor_resources_spent=per_actor_resources_spent,
        per_actor_downed=per_actor_downed,
        per_actor_deaths=per_actor_deaths,
        per_actor_remaining_hp=per_actor_remaining_hp,
    )
