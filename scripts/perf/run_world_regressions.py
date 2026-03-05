from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from dnd_sim.encounter_script import (
    EncounterRunState,
    advance_encounter_wave,
    create_encounter_run,
    parse_encounter_script,
    set_encounter_objective,
    trigger_map_hook,
)
from dnd_sim.world_runtime import (
    ExplorationState,
    LightSourceState,
    create_exploration_state,
    run_exploration_turn,
)
from dnd_sim.world_state import (
    FactionState,
    QuestState,
    WorldState,
    apply_faction_reputation_delta,
    create_world_state,
    transition_quest_state,
    transition_world_flag,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS_DIR = REPO_ROOT / "artifacts/world_regressions"
CASE_GLOB = "*.json"


def _required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _required_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _required_float(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric")
    return float(value)


def _required_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    return value


def _normalize_light_sources(raw: Any) -> dict[str, int | LightSourceState]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("initial_state.light_sources must be a mapping")

    normalized: dict[str, int | LightSourceState] = {}
    for source_id, payload in sorted(raw.items()):
        normalized_id = _required_text(source_id, field_name="source_id")
        if isinstance(payload, int) and not isinstance(payload, bool):
            if payload < 0:
                raise ValueError("light source integer minutes must be >= 0")
            normalized[normalized_id] = payload
            continue

        mapping_payload = _required_mapping(payload, field_name=f"light_sources[{normalized_id}]")
        remaining_minutes = _required_int(
            mapping_payload.get("remaining_minutes"),
            field_name=f"light_sources[{normalized_id}].remaining_minutes",
        )
        if remaining_minutes < 0:
            raise ValueError("remaining_minutes must be >= 0")
        is_lit_raw = mapping_payload.get("is_lit", remaining_minutes > 0)
        if not isinstance(is_lit_raw, bool):
            raise ValueError(f"light_sources[{normalized_id}].is_lit must be a bool")

        normalized[normalized_id] = LightSourceState(
            source_id=normalized_id,
            remaining_minutes=remaining_minutes,
            is_lit=is_lit_raw,
        )
    return normalized


def _build_exploration_state(initial_state: Mapping[str, Any]) -> ExplorationState:
    day = _required_int(initial_state.get("day"), field_name="initial_state.day")
    hour = _required_int(initial_state.get("hour"), field_name="initial_state.hour")
    minute = _required_int(initial_state.get("minute"), field_name="initial_state.minute")
    turn_index = _required_int(
        initial_state.get("turn_index", 0), field_name="initial_state.turn_index"
    )
    location_id = initial_state.get("location_id")
    if location_id is not None:
        location_id = _required_text(location_id, field_name="initial_state.location_id")

    return create_exploration_state(
        day=day,
        hour=hour,
        minute=minute,
        turn_index=turn_index,
        location_id=location_id,
        light_sources=_normalize_light_sources(initial_state.get("light_sources")),
    )


def _build_world_state(initial_state: Mapping[str, Any]) -> WorldState:
    raw_quests = initial_state.get("quests", {})
    if not isinstance(raw_quests, Mapping):
        raise ValueError("initial_state.quests must be a mapping")
    quests: dict[str, QuestState] = {}
    for quest_id, payload in sorted(raw_quests.items()):
        normalized_id = _required_text(quest_id, field_name="quest_id")
        quest_payload = _required_mapping(payload, field_name=f"quests[{normalized_id}]")
        quests[normalized_id] = QuestState(
            quest_id=normalized_id,
            status=quest_payload.get("status", "not_started"),
            stage_id=quest_payload.get("stage_id"),
            objective_flags=dict(quest_payload.get("objective_flags", {})),
        )

    raw_factions = initial_state.get("factions", {})
    if not isinstance(raw_factions, Mapping):
        raise ValueError("initial_state.factions must be a mapping")
    factions: dict[str, FactionState] = {}
    for faction_id, payload in sorted(raw_factions.items()):
        normalized_id = _required_text(faction_id, field_name="faction_id")
        if isinstance(payload, int) and not isinstance(payload, bool):
            reputation = payload
        else:
            payload_mapping = _required_mapping(payload, field_name=f"factions[{normalized_id}]")
            reputation = _required_int(
                payload_mapping.get("reputation", 0),
                field_name=f"factions[{normalized_id}].reputation",
            )
        factions[normalized_id] = FactionState(
            faction_id=normalized_id,
            reputation=reputation,
        )

    raw_world_flags = initial_state.get("world_flags", {})
    if not isinstance(raw_world_flags, Mapping):
        raise ValueError("initial_state.world_flags must be a mapping")
    world_flags = {
        _required_text(flag_id, field_name="flag_id"): _required_text(status, field_name="status")
        for flag_id, status in sorted(raw_world_flags.items())
    }

    turn_index = _required_int(
        initial_state.get("turn_index", 0), field_name="initial_state.turn_index"
    )
    return create_world_state(
        turn_index=turn_index,
        world_flags=world_flags,
        quests=quests,
        factions=factions,
    )


def _snapshot_exploration_state(state: ExplorationState) -> dict[str, Any]:
    return {
        "turn_index": state.turn_index,
        "clock": {
            "day": state.clock.day,
            "minute_of_day": state.clock.minute_of_day,
            "hour": state.clock.hour,
            "minute": state.clock.minute,
        },
        "location_id": state.location_id,
        "light_sources": {
            source_id: {
                "remaining_minutes": light.remaining_minutes,
                "is_lit": light.is_lit,
            }
            for source_id, light in sorted(state.light_sources.items())
        },
    }


def _snapshot_world_state(state: WorldState) -> dict[str, Any]:
    return {
        "turn_index": state.turn_index,
        "world_flags": dict(sorted(state.world_flags.items())),
        "quests": {
            quest_id: {
                "status": quest.status,
                "stage_id": quest.stage_id,
                "objective_flags": dict(sorted((quest.objective_flags or {}).items())),
            }
            for quest_id, quest in sorted(state.quests.items())
        },
        "factions": {
            faction_id: {
                "reputation": faction.reputation,
                "standing": faction.standing,
            }
            for faction_id, faction in sorted(state.factions.items())
        },
    }


def _snapshot_encounter_state(
    world_state: WorldState, run: EncounterRunState | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "world_state": _snapshot_world_state(world_state),
        "encounter": None,
    }
    if run is None:
        return payload
    payload["encounter"] = {
        "encounter_id": run.encounter_id,
        "status": run.status,
        "active_wave_id": run.active_wave_id,
        "wave_statuses": dict(sorted(run.wave_statuses.items())),
        "objective_statuses": dict(sorted(run.objective_statuses.items())),
        "triggered_hooks": list(run.triggered_hooks),
    }
    return payload


def _diff_values(expected: Any, actual: Any, *, path: str = "$") -> list[str]:
    if type(expected) is not type(actual):
        return [
            f"{path}: type mismatch expected {type(expected).__name__}, got {type(actual).__name__}"
        ]

    if isinstance(expected, Mapping):
        issues: list[str] = []
        expected_keys = set(expected)
        actual_keys = set(actual)
        for missing_key in sorted(expected_keys - actual_keys):
            issues.append(f"{path}.{missing_key}: missing in actual")
        for extra_key in sorted(actual_keys - expected_keys):
            issues.append(f"{path}.{extra_key}: unexpected in actual")
        for key in sorted(expected_keys & actual_keys):
            child_path = f"{path}.{key}"
            issues.extend(_diff_values(expected[key], actual[key], path=child_path))
        return issues

    if isinstance(expected, list):
        issues = []
        if len(expected) != len(actual):
            issues.append(f"{path}: list length expected {len(expected)}, got {len(actual)}")
            return issues
        for index, (exp_item, act_item) in enumerate(zip(expected, actual, strict=True)):
            issues.extend(_diff_values(exp_item, act_item, path=f"{path}[{index}]"))
        return issues

    if expected != actual:
        return [f"{path}: expected {expected!r}, got {actual!r}"]
    return []


def _run_exploration_case(case: Mapping[str, Any]) -> dict[str, Any]:
    initial_state = _required_mapping(case.get("initial_state"), field_name="initial_state")
    state = _build_exploration_state(initial_state)
    steps = case.get("steps", [])
    if not isinstance(steps, list):
        raise ValueError("steps must be a list")

    for step in steps:
        step_payload = _required_mapping(step, field_name="step")
        kind = _required_text(step_payload.get("kind"), field_name="step.kind")
        if kind != "exploration_turn":
            raise ValueError(f"Unsupported exploration step kind: {kind}")
        activity = _required_text(step_payload.get("activity"), field_name="step.activity")
        elapsed_minutes = _required_int(
            step_payload.get("elapsed_minutes"), field_name="step.elapsed_minutes"
        )
        state = run_exploration_turn(
            state,
            activity=activity,
            elapsed_minutes=elapsed_minutes,
        ).state
    return _snapshot_exploration_state(state)


def _run_world_state_case(case: Mapping[str, Any]) -> dict[str, Any]:
    initial_state = _required_mapping(case.get("initial_state"), field_name="initial_state")
    state = _build_world_state(initial_state)
    steps = case.get("steps", [])
    if not isinstance(steps, list):
        raise ValueError("steps must be a list")

    for step in steps:
        step_payload = _required_mapping(step, field_name="step")
        kind = _required_text(step_payload.get("kind"), field_name="step.kind")
        if kind == "world_flag":
            state = transition_world_flag(
                state,
                flag_id=step_payload.get("flag_id"),
                to_status=step_payload.get("to_status"),
            )
        elif kind == "quest":
            state = transition_quest_state(
                state,
                quest_id=step_payload.get("quest_id"),
                to_status=step_payload.get("to_status"),
                stage_id=step_payload.get("stage_id"),
                objective_updates=dict(step_payload.get("objective_updates", {})),
            )
        elif kind == "faction":
            state = apply_faction_reputation_delta(
                state,
                faction_id=step_payload.get("faction_id"),
                delta=step_payload.get("delta"),
            )
        else:
            raise ValueError(f"Unsupported world_state step kind: {kind}")
    return _snapshot_world_state(state)


def _run_encounter_case(case: Mapping[str, Any]) -> dict[str, Any]:
    initial_state = _required_mapping(case.get("initial_state"), field_name="initial_state")
    world_state = _build_world_state(
        _required_mapping(initial_state.get("world_state"), field_name="initial_state.world_state")
    )
    script_payload = _required_mapping(
        initial_state.get("script"), field_name="initial_state.script"
    )
    script = parse_encounter_script(script_payload)
    run: EncounterRunState | None = None

    steps = case.get("steps", [])
    if not isinstance(steps, list):
        raise ValueError("steps must be a list")

    for step in steps:
        step_payload = _required_mapping(step, field_name="step")
        kind = _required_text(step_payload.get("kind"), field_name="step.kind")
        if kind == "create_run":
            run, world_state = create_encounter_run(script, world_state)
        elif kind == "set_objective":
            if run is None:
                raise ValueError("set_objective requires an active run")
            completed = step_payload.get("completed", True)
            if not isinstance(completed, bool):
                raise ValueError("step.completed must be a bool")
            run, world_state = set_encounter_objective(
                script,
                run,
                world_state,
                objective_id=step_payload.get("objective_id"),
                completed=completed,
            )
        elif kind == "advance_wave":
            if run is None:
                raise ValueError("advance_wave requires an active run")
            run, world_state = advance_encounter_wave(script, run, world_state)
        elif kind == "trigger_hook":
            if run is None:
                raise ValueError("trigger_hook requires an active run")
            run, world_state = trigger_map_hook(
                script,
                run,
                world_state,
                hook_id=step_payload.get("hook_id"),
            )
        else:
            raise ValueError(f"Unsupported encounter step kind: {kind}")

    return _snapshot_encounter_state(world_state, run)


def execute_world_regression_case(case: Mapping[str, Any]) -> dict[str, Any]:
    mode = _required_text(case.get("mode"), field_name="mode")
    if mode == "exploration":
        return _run_exploration_case(case)
    if mode == "world_state":
        return _run_world_state_case(case)
    if mode == "encounter":
        return _run_encounter_case(case)
    raise ValueError("mode must be one of: exploration, world_state, encounter")


@dataclass(frozen=True, slots=True)
class RegressionCaseResult:
    case_id: str
    path: str
    runtime_ms: float
    baseline_ms: float | None
    allowed_ms: float | None
    replay_diffs: tuple[str, ...]
    performance_regression: bool
    passed: bool
    error: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "path": self.path,
            "runtime_ms": round(self.runtime_ms, 4),
            "baseline_ms": self.baseline_ms,
            "allowed_ms": self.allowed_ms,
            "replay_diffs": list(self.replay_diffs),
            "performance_regression": self.performance_regression,
            "passed": self.passed,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class RegressionSuiteResult:
    corpus_dir: str
    total_cases: int
    failed_cases: int
    diff_failures: int
    performance_failures: int
    case_results: tuple[RegressionCaseResult, ...]

    @property
    def passed(self) -> bool:
        return self.failed_cases == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "corpus_dir": self.corpus_dir,
            "total_cases": self.total_cases,
            "failed_cases": self.failed_cases,
            "diff_failures": self.diff_failures,
            "performance_failures": self.performance_failures,
            "passed": self.passed,
            "case_results": [result.as_dict() for result in self.case_results],
        }


def _load_case(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    case_id = _required_text(payload.get("case_id"), field_name="case_id")
    payload["case_id"] = case_id
    payload["mode"] = _required_text(payload.get("mode"), field_name="mode")
    if "steps" not in payload:
        raise ValueError(f"{path} is missing 'steps'")
    if not isinstance(payload["steps"], list):
        raise ValueError(f"{path} field 'steps' must be a list")
    return payload


def _discover_case_paths(corpus_dir: Path) -> tuple[Path, ...]:
    if not corpus_dir.exists():
        raise ValueError(f"Corpus directory does not exist: {corpus_dir}")
    if not corpus_dir.is_dir():
        raise ValueError(f"Corpus path must be a directory: {corpus_dir}")
    return tuple(sorted(path for path in corpus_dir.glob(CASE_GLOB) if path.is_file()))


def run_regression_suite(
    *,
    corpus_dir: Path = DEFAULT_CORPUS_DIR,
    update_snapshots: bool = False,
    tolerance_pct: float = 20.0,
    fail_on_perf: bool = True,
) -> RegressionSuiteResult:
    tolerance_value = _required_float(tolerance_pct, field_name="tolerance_pct")
    if tolerance_value < 0:
        raise ValueError("tolerance_pct must be >= 0")

    case_paths = _discover_case_paths(corpus_dir)
    case_results: list[RegressionCaseResult] = []
    diff_failures = 0
    performance_failures = 0

    for path in case_paths:
        case_id = path.stem
        try:
            case_payload = _load_case(path)
            case_id = case_payload["case_id"]
            start = time.perf_counter()
            actual_snapshot = execute_world_regression_case(case_payload)
            runtime_ms = (time.perf_counter() - start) * 1000.0

            expected_snapshot = case_payload.get("expected_replay")
            replay_diffs: list[str] = []
            if expected_snapshot is None:
                replay_diffs = ["$.expected_replay: missing expected replay snapshot"]
            else:
                replay_diffs = _diff_values(expected_snapshot, actual_snapshot)

            if update_snapshots and replay_diffs:
                case_payload["expected_replay"] = actual_snapshot
                path.write_text(
                    json.dumps(case_payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                replay_diffs = []

            baseline_ms: float | None = None
            allowed_ms: float | None = None
            performance_regression = False
            if "performance_baseline_ms" in case_payload:
                baseline_ms = _required_float(
                    case_payload["performance_baseline_ms"],
                    field_name=f"{case_id}.performance_baseline_ms",
                )
                if baseline_ms <= 0:
                    raise ValueError("performance_baseline_ms must be > 0")
                allowed_ms = baseline_ms * (1 + (tolerance_value / 100.0))
                performance_regression = runtime_ms > allowed_ms

            failed_for_diff = bool(replay_diffs)
            failed_for_perf = performance_regression and fail_on_perf
            if failed_for_diff:
                diff_failures += 1
            if failed_for_perf:
                performance_failures += 1

            case_results.append(
                RegressionCaseResult(
                    case_id=case_id,
                    path=str(path),
                    runtime_ms=runtime_ms,
                    baseline_ms=baseline_ms,
                    allowed_ms=allowed_ms,
                    replay_diffs=tuple(replay_diffs),
                    performance_regression=performance_regression,
                    passed=not (failed_for_diff or failed_for_perf),
                    error=None,
                )
            )
        except Exception as error:  # noqa: BLE001
            case_results.append(
                RegressionCaseResult(
                    case_id=case_id,
                    path=str(path),
                    runtime_ms=0.0,
                    baseline_ms=None,
                    allowed_ms=None,
                    replay_diffs=(),
                    performance_regression=False,
                    passed=False,
                    error=str(error),
                )
            )

    failed_cases = sum(1 for result in case_results if not result.passed)
    return RegressionSuiteResult(
        corpus_dir=str(corpus_dir),
        total_cases=len(case_results),
        failed_cases=failed_cases,
        diff_failures=diff_failures,
        performance_failures=performance_failures,
        case_results=tuple(case_results),
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic world regression corpus checks with replay diffing and "
            "performance-baseline enforcement."
        )
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=DEFAULT_CORPUS_DIR,
        help=f"Path to world regression corpus directory (default: {DEFAULT_CORPUS_DIR})",
    )
    parser.add_argument(
        "--update-snapshots",
        action="store_true",
        help="Rewrite expected_replay snapshots when diffs are found.",
    )
    parser.add_argument(
        "--tolerance-pct",
        type=float,
        default=20.0,
        help="Allowed runtime increase over performance_baseline_ms (percent).",
    )
    parser.add_argument(
        "--no-fail-on-perf",
        action="store_true",
        help="Record performance regressions without failing the run.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Optional path to write machine-readable suite results as JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    suite_result = run_regression_suite(
        corpus_dir=args.corpus_dir,
        update_snapshots=args.update_snapshots,
        tolerance_pct=args.tolerance_pct,
        fail_on_perf=not args.no_fail_on_perf,
    )

    for case_result in suite_result.case_results:
        status = "PASS" if case_result.passed else "FAIL"
        print(f"{status} {case_result.case_id} ({case_result.runtime_ms:.3f} ms)")
        if case_result.error is not None:
            print(f"  error: {case_result.error}")
        for diff in case_result.replay_diffs:
            print(f"  diff: {diff}")
        if case_result.performance_regression:
            print(
                "  perf: runtime exceeded allowed baseline "
                f"({case_result.runtime_ms:.3f} > {case_result.allowed_ms:.3f} ms)"
            )

    summary = (
        "World regression suite: "
        f"{suite_result.total_cases} total, "
        f"{suite_result.failed_cases} failed, "
        f"{suite_result.diff_failures} replay diffs, "
        f"{suite_result.performance_failures} performance failures."
    )
    print(summary)

    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(suite_result.as_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return 0 if suite_result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
