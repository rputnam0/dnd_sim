from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from dnd_sim.ai.scoring import candidate_snapshots, enumerate_legal_action_candidates
from dnd_sim.strategies.defaults import (
    BossHighestThreatTargetStrategy,
    OptimalExpectedDamageStrategy,
)
from dnd_sim.strategy_api import (
    ActorView,
    BaseStrategy,
    BattleStateView,
    TargetRef,
    TurnDeclaration,
)

REQUIRED_BENCHMARK_CATEGORIES = frozenset(
    {"hazard_heavy", "objective_heavy", "summon_heavy", "legendary_recharge"}
)
STRATEGY_ALIASES = {
    "optimal_expected_damage": "primary",
    "base_strategy": "base",
    "highest_threat": "highest_threat",
}
DEFAULT_CORPUS_PATH = (
    Path(__file__).resolve().parents[2] / "artifacts" / "ai_benchmarks" / "corpus.json"
)


def _default_save_mods() -> dict[str, int]:
    return {"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0}


def _coerce_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"benchmark corpus must be a JSON object: {path}")
    return payload


def load_benchmark_corpus(path: Path | str | None = None) -> dict[str, Any]:
    corpus_path = Path(path) if path is not None else DEFAULT_CORPUS_PATH
    payload = _load_json(corpus_path)
    benchmarks = payload.get("benchmarks")
    if not isinstance(benchmarks, list) or not benchmarks:
        raise ValueError("benchmark corpus must include a non-empty 'benchmarks' list")
    categories = {str(row.get("category", "")).strip() for row in benchmarks}
    missing_categories = sorted(REQUIRED_BENCHMARK_CATEGORIES.difference(categories))
    if missing_categories:
        raise ValueError(
            "benchmark corpus missing required categories: " + ", ".join(missing_categories)
        )
    return payload


def _actor_view(payload: dict[str, Any]) -> ActorView:
    actor_id = str(payload.get("actor_id", "")).strip()
    if not actor_id:
        raise ValueError("benchmark actor is missing actor_id")
    team = str(payload.get("team", "")).strip() or "party"
    hp = _coerce_int(payload.get("hp"), default=1)
    max_hp = max(1, _coerce_int(payload.get("max_hp"), default=hp))
    ac = _coerce_int(payload.get("ac"), default=10)
    save_mods = payload.get("save_mods")
    if not isinstance(save_mods, dict):
        save_mods = _default_save_mods()
    resources = payload.get("resources")
    if not isinstance(resources, dict):
        resources = {}
    conditions = payload.get("conditions")
    condition_set = {str(entry).strip().lower() for entry in conditions or [] if str(entry).strip()}
    position_raw = payload.get("position", (0, 0, 0))
    if not isinstance(position_raw, (list, tuple)) or len(position_raw) != 3:
        position_raw = (0, 0, 0)
    position = (
        _coerce_float(position_raw[0]),
        _coerce_float(position_raw[1]),
        _coerce_float(position_raw[2]),
    )
    traits = payload.get("traits")
    if not isinstance(traits, dict):
        traits = {}

    return ActorView(
        actor_id=actor_id,
        team=team,
        hp=max(0, hp),
        max_hp=max_hp,
        ac=ac,
        save_mods={str(k): _coerce_int(v) for k, v in save_mods.items()},
        resources={str(k): _coerce_int(v) for k, v in resources.items()},
        conditions=condition_set,
        position=position,
        speed_ft=max(0, _coerce_int(payload.get("speed_ft"), default=30)),
        movement_remaining=max(0.0, _coerce_float(payload.get("movement_remaining"), default=30.0)),
        traits=traits,
        concentrating=bool(payload.get("concentrating", False)),
    )


def _merge_metadata(
    case: dict[str, Any],
    *,
    action_catalog: dict[str, list[dict[str, Any]]],
    available_actions: dict[str, list[str]],
) -> dict[str, Any]:
    metadata = case.get("metadata")
    merged = dict(metadata) if isinstance(metadata, dict) else {}
    merged["action_catalog"] = action_catalog
    merged["available_actions"] = available_actions
    return merged


def _build_case_state(case: dict[str, Any]) -> tuple[ActorView, BattleStateView]:
    actors_raw = case.get("actors")
    if not isinstance(actors_raw, list) or not actors_raw:
        raise ValueError("benchmark case must include a non-empty actors list")
    actors = {}
    actor_order: list[str] = []
    for actor_payload in actors_raw:
        if not isinstance(actor_payload, dict):
            raise ValueError("benchmark case actor entries must be objects")
        view = _actor_view(actor_payload)
        actors[view.actor_id] = view
        actor_order.append(view.actor_id)

    actor_id = str(case.get("actor_id", "")).strip()
    actor = actors.get(actor_id)
    if actor is None:
        raise ValueError(f"benchmark actor_id '{actor_id}' not present in actors list")

    raw_catalog = case.get("action_catalog")
    if not isinstance(raw_catalog, dict):
        raise ValueError("benchmark case must include action_catalog mapping")
    action_catalog: dict[str, list[dict[str, Any]]] = {}
    for owner, actions in raw_catalog.items():
        if not isinstance(actions, list):
            raise ValueError(f"action_catalog[{owner}] must be a list")
        action_catalog[str(owner)] = [row for row in actions if isinstance(row, dict)]

    raw_available = case.get("available_actions")
    if isinstance(raw_available, dict):
        available_actions = {
            str(owner): [str(name) for name in names if str(name).strip()]
            for owner, names in raw_available.items()
            if isinstance(names, list)
        }
    else:
        available_actions = {
            owner: [str(row.get("name", "")) for row in rows if str(row.get("name", "")).strip()]
            for owner, rows in action_catalog.items()
        }

    state = BattleStateView(
        round_number=max(1, _coerce_int(case.get("round_number"), default=1)),
        actors=actors,
        actor_order=actor_order,
        metadata=_merge_metadata(
            case,
            action_catalog=action_catalog,
            available_actions=available_actions,
        ),
    )
    return actor, state


def _strategy_instance(strategy_alias: str):
    canonical = STRATEGY_ALIASES.get(strategy_alias, strategy_alias)
    if canonical == "primary":
        return OptimalExpectedDamageStrategy()
    if canonical == "base":
        return BaseStrategy()
    if canonical == "highest_threat":
        return BossHighestThreatTargetStrategy()
    raise ValueError(f"unsupported benchmark strategy alias '{strategy_alias}'")


def _selected_target_ids(declaration: TurnDeclaration) -> tuple[str, ...]:
    if declaration.action is None:
        return ()
    targets: list[str] = []
    for target in declaration.action.targets:
        if isinstance(target, TargetRef) and str(target.actor_id).strip():
            targets.append(str(target.actor_id))
    return tuple(targets)


def _select_snapshot_for_declaration(
    actor: ActorView,
    state: BattleStateView,
    declaration: TurnDeclaration,
) -> dict[str, Any] | None:
    if declaration.action is None or not declaration.action.action_name:
        return None

    selected_action = str(declaration.action.action_name)
    selected_targets = _selected_target_ids(declaration)
    candidates = enumerate_legal_action_candidates(actor, state)
    snapshots = candidate_snapshots(candidates)
    action_only: dict[str, Any] | None = None
    for row, snapshot in zip(candidates, snapshots):
        if row.action_name != selected_action:
            continue
        if action_only is None:
            action_only = snapshot
        if tuple(row.target_ids) == selected_targets:
            return snapshot
    return action_only


def _action_for_declaration(state: BattleStateView, actor: ActorView, declaration: TurnDeclaration):
    if declaration.action is None or not declaration.action.action_name:
        return None
    for row in state.metadata.get("action_catalog", {}).get(actor.actor_id, []):
        if str(row.get("name", "")) == declaration.action.action_name:
            return row
    return None


def _objective_bonus_for_action(action: dict[str, Any], state: BattleStateView) -> float:
    objective_scores = state.metadata.get("objective_scores", {})
    if not isinstance(objective_scores, dict):
        objective_scores = {}
    total = _coerce_float(objective_scores.get(str(action.get("name", ""))), default=0.0)
    for tag in action.get("tags", []) or []:
        text = str(tag).strip()
        if not text.startswith("objective:"):
            continue
        _, objective_id = text.split(":", 1)
        total += _coerce_float(objective_scores.get(objective_id), default=0.0)
    return total


def _candidate_quality_bonus(snapshot: dict[str, Any] | None) -> float:
    if snapshot is None:
        return 0.0
    inputs = snapshot.get("scoring_inputs", {})
    objective_tradeoff = inputs.get("objective_tradeoff", {})
    timing = inputs.get("timing", {})
    spatial = inputs.get("spatial", {})
    bonus = 0.0
    bonus += _coerce_float(objective_tradeoff.get("objective_race_score"), default=0.0)
    bonus += _coerce_float(objective_tradeoff.get("focus_fire_score"), default=0.0)
    bonus += _coerce_float(timing.get("recharge_timing_score"), default=0.0)
    bonus += _coerce_float(timing.get("legendary_action_window_score"), default=0.0)
    bonus += _coerce_float(timing.get("reaction_bait_score"), default=0.0)
    penalty = 0.0
    penalty += _coerce_float(spatial.get("friendly_fire_penalty"), default=0.0) * 0.5
    penalty += _coerce_float(spatial.get("line_of_effect_penalty"), default=0.0) * 0.5
    penalty += _coerce_float(spatial.get("cover_penalty"), default=0.0) * 0.5
    return bonus - penalty


def _objective_adjusted_outcome(
    *,
    action: dict[str, Any] | None,
    snapshot: dict[str, Any] | None,
    state: BattleStateView,
) -> float:
    if action is None:
        return 0.0
    base_score = _coerce_float(action.get("benchmark_outcome_score"), default=0.0)
    objective_bonus = _objective_bonus_for_action(action, state)
    quality_bonus = _candidate_quality_bonus(snapshot)
    return base_score + objective_bonus + quality_bonus


def _primary_rationale_status(declaration: TurnDeclaration) -> dict[str, Any]:
    rationale = declaration.rationale if isinstance(declaration.rationale, dict) else {}
    action_selection = rationale.get("action_selection")
    has_action_selection = (
        isinstance(action_selection, dict)
        and bool(action_selection.get("selected"))
        and _coerce_int(action_selection.get("candidate_count"), default=0) > 0
    )
    return {
        "has_rationale": bool(rationale),
        "has_action_selection": has_action_selection,
        "rationale": rationale,
    }


def _evaluate_case(
    case: dict[str, Any],
    *,
    primary_strategy_alias: str,
    baseline_aliases: list[str],
    global_thresholds: dict[str, Any],
) -> dict[str, Any]:
    actor, state = _build_case_state(case)

    case_row = {
        "benchmark_id": str(case.get("benchmark_id", "")),
        "category": str(case.get("category", "")),
        "strategies": {},
        "pass": True,
        "failures": [],
    }

    strategy_aliases = [primary_strategy_alias, *baseline_aliases]
    for alias in strategy_aliases:
        strategy = _strategy_instance(alias)
        declaration = strategy.declare_turn(actor, state)
        if declaration is None:
            declaration = TurnDeclaration()
        snapshot = _select_snapshot_for_declaration(actor, state, declaration)
        action = _action_for_declaration(state, actor, declaration)
        outcome = _objective_adjusted_outcome(action=action, snapshot=snapshot, state=state)
        strategy_row = {
            "selected_action": (
                str(declaration.action.action_name)
                if declaration.action is not None and declaration.action.action_name is not None
                else None
            ),
            "selected_targets": list(_selected_target_ids(declaration)),
            "objective_adjusted_outcome": outcome,
            "snapshot": snapshot,
        }
        if STRATEGY_ALIASES.get(alias, alias) == "primary":
            strategy_row["rationale"] = _primary_rationale_status(declaration)
        case_row["strategies"][STRATEGY_ALIASES.get(alias, alias)] = strategy_row

    thresholds = dict(global_thresholds)
    overrides = case.get("threshold_overrides")
    if isinstance(overrides, dict):
        thresholds.update(overrides)

    primary_outcome = _coerce_float(
        case_row["strategies"]["primary"]["objective_adjusted_outcome"], default=0.0
    )
    base_outcome = _coerce_float(
        case_row["strategies"]["base"]["objective_adjusted_outcome"], default=0.0
    )
    highest_outcome = _coerce_float(
        case_row["strategies"]["highest_threat"]["objective_adjusted_outcome"], default=0.0
    )

    margin_vs_base = primary_outcome - base_outcome
    margin_vs_highest = primary_outcome - highest_outcome
    case_row["primary_margin_vs_base"] = margin_vs_base
    case_row["primary_margin_vs_highest_threat"] = margin_vs_highest

    min_base = _coerce_float(thresholds.get("minimum_primary_margin_vs_base"), default=0.0)
    min_highest = _coerce_float(
        thresholds.get("minimum_primary_margin_vs_highest_threat"), default=0.0
    )
    if margin_vs_base < min_base:
        case_row["pass"] = False
        case_row["failures"].append(
            f"primary margin vs base {margin_vs_base:.3f} < required {min_base:.3f}"
        )
    if margin_vs_highest < min_highest:
        case_row["pass"] = False
        case_row["failures"].append(
            f"primary margin vs highest_threat {margin_vs_highest:.3f} < required {min_highest:.3f}"
        )

    primary_rationale = case_row["strategies"]["primary"]["rationale"]
    if not bool(primary_rationale.get("has_action_selection")):
        case_row["pass"] = False
        case_row["failures"].append(
            "primary strategy rationale is missing action_selection payload"
        )

    return case_row


def run_benchmark_suite(corpus_path: Path | str | None = None) -> dict[str, Any]:
    payload = load_benchmark_corpus(corpus_path)
    thresholds = payload.get("thresholds")
    global_thresholds = dict(thresholds) if isinstance(thresholds, dict) else {}

    primary_strategy_alias = str(payload.get("primary_strategy", "optimal_expected_damage"))
    baseline_aliases_raw = payload.get("comparison_strategies", ["base_strategy", "highest_threat"])
    baseline_aliases = (
        [str(entry) for entry in baseline_aliases_raw if str(entry).strip()]
        if isinstance(baseline_aliases_raw, list)
        else ["base_strategy", "highest_threat"]
    )
    if len(baseline_aliases) < 2:
        raise ValueError(
            "comparison_strategies must include at least base_strategy and highest_threat"
        )

    case_rows: list[dict[str, Any]] = []
    for row in payload["benchmarks"]:
        if not isinstance(row, dict):
            raise ValueError("benchmark rows must be objects")
        case_rows.append(
            _evaluate_case(
                row,
                primary_strategy_alias=primary_strategy_alias,
                baseline_aliases=baseline_aliases[:2],
                global_thresholds=global_thresholds,
            )
        )

    categories_covered = sorted({row["category"] for row in case_rows})
    missing_categories = sorted(REQUIRED_BENCHMARK_CATEGORIES.difference(categories_covered))
    required_coverage_pass = not missing_categories

    primary_rationale_rows = [
        row["strategies"]["primary"]["rationale"]
        for row in case_rows
        if "primary" in row["strategies"]
    ]
    rationale_hits = sum(
        1 for row in primary_rationale_rows if bool(row.get("has_action_selection"))
    )
    rationale_coverage = (
        (rationale_hits / len(primary_rationale_rows)) if primary_rationale_rows else 0.0
    )
    required_coverage = _coerce_float(
        global_thresholds.get("minimum_primary_rationale_coverage"),
        default=1.0,
    )
    rationale_pass = rationale_coverage >= required_coverage

    strategy_averages = {}
    for strategy_key in ("primary", "base", "highest_threat"):
        values = [
            _coerce_float(
                row["strategies"][strategy_key]["objective_adjusted_outcome"], default=0.0
            )
            for row in case_rows
        ]
        strategy_averages[strategy_key] = {
            "mean_objective_adjusted_outcome": (sum(values) / len(values)) if values else 0.0
        }

    all_passed = required_coverage_pass and rationale_pass and all(row["pass"] for row in case_rows)
    return {
        "schema_version": str(payload.get("schema_version", "ai_benchmark.v1")),
        "required_categories": sorted(REQUIRED_BENCHMARK_CATEGORIES),
        "categories_covered": categories_covered,
        "missing_categories": missing_categories,
        "required_category_coverage_pass": required_coverage_pass,
        "thresholds": {
            "minimum_primary_margin_vs_base": _coerce_float(
                global_thresholds.get("minimum_primary_margin_vs_base"), default=0.0
            ),
            "minimum_primary_margin_vs_highest_threat": _coerce_float(
                global_thresholds.get("minimum_primary_margin_vs_highest_threat"), default=0.0
            ),
            "minimum_primary_rationale_coverage": required_coverage,
        },
        "rationale_coverage": {
            "primary_with_action_selection": rationale_coverage,
            "pass": rationale_pass,
        },
        "strategy_averages": strategy_averages,
        "benchmarks": case_rows,
        "all_passed": all_passed,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AI-06 benchmark corpus gates for decision-quality and rationale coverage."
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_CORPUS_PATH,
        help="Path to benchmark corpus JSON.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional output path for JSON benchmark report.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    payload = run_benchmark_suite(args.corpus)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out is not None:
        output_path = args.out.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
        print(f"Benchmark report written: {output_path}")
    else:
        print(text)
    if not bool(payload.get("all_passed")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
