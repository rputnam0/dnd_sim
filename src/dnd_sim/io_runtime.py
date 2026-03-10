from __future__ import annotations

import csv
import importlib
import importlib.util
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dnd_sim.io_models import LoadedScenario
from dnd_sim.strategy_api import BaseStrategy, validate_strategy_instance

_DEFAULT_BUILTIN_STRATEGY_MODULE = "dnd_sim.strategies.defaults"
_APPROVED_BUILTIN_STRATEGY_MODULES = {_DEFAULT_BUILTIN_STRATEGY_MODULE}
_APPROVED_BUILTIN_CUSTOM_SIMULATION_MODULES: set[str] = set()


def _import_encounter_strategy(module_name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load strategy module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _encounter_internal_strategy_dir(scenario: LoadedScenario) -> Path:
    scenario_path = Path(scenario.scenario_path)
    return scenario_path.parent.parent / "internal_harness" / "strategies"


def _resolve_encounter_strategy_module_path(scenario: LoadedScenario, module_name: str) -> Path:
    strategy_dir = _encounter_internal_strategy_dir(scenario)
    candidate = strategy_dir / f"{module_name}.py"
    if candidate.exists():
        return candidate
    raise ValueError(f"Strategy module file not found: {candidate}")


def load_strategy_registry(
    scenario: LoadedScenario,
) -> dict[str, BaseStrategy]:
    registry: dict[str, BaseStrategy] = {}
    default_module = importlib.import_module(_DEFAULT_BUILTIN_STRATEGY_MODULE)
    default_classes = {
        "focus_fire_lowest_hp": "FocusFireLowestHPStrategy",
        "boss_highest_threat_target": "BossHighestThreatTargetStrategy",
        "conserve_resources_then_burst": "ConserveResourcesThenBurstStrategy",
        "always_use_signature_ability_if_ready": "AlwaysUseSignatureAbilityStrategy",
        "optimal_expected_damage": "OptimalExpectedDamageStrategy",
        "pack_tactics": "PackTacticsStrategy",
        "healer": "HealerStrategy",
        "skirmisher": "SkirmisherStrategy",
    }
    for name, class_name in default_classes.items():
        cls = getattr(default_module, class_name)
        instance = cls()
        validate_strategy_instance(instance)
        registry[name] = instance

    harness = scenario.config.internal_harness
    strategy_modules = harness.strategy_modules if harness is not None else []
    for cfg in strategy_modules:
        if cfg.source == "builtin":
            module_name = cfg.module or _DEFAULT_BUILTIN_STRATEGY_MODULE
            if module_name not in _APPROVED_BUILTIN_STRATEGY_MODULES:
                raise ValueError(
                    f"Builtin strategy module is not in the approved registry: {module_name}"
                )
            module = importlib.import_module(module_name)
        else:
            if not cfg.module:
                raise ValueError(
                    f"Strategy module name is required for encounter strategy: {cfg.name}"
                )
            module_path = _resolve_encounter_strategy_module_path(scenario, cfg.module)
            module = _import_encounter_strategy(cfg.module, module_path)

        cls = getattr(module, cfg.class_name, None)
        if cls is None:
            raise ValueError(
                f"Strategy class {cfg.class_name} not found in module "
                f"{cfg.module or 'dnd_sim.strategies.defaults'}"
            )

        strategy = cls()
        validate_strategy_instance(strategy)
        registry[cfg.name] = strategy

    return registry


def load_custom_simulation_runner(scenario: LoadedScenario) -> Any | None:
    harness = scenario.config.internal_harness
    cfg = harness.custom_simulation if harness is not None else None
    if cfg is None:
        return None

    if cfg.source == "builtin":
        if cfg.module not in _APPROVED_BUILTIN_CUSTOM_SIMULATION_MODULES:
            raise ValueError(
                f"Builtin custom simulation module is not in the approved registry: {cfg.module}"
            )
        module = importlib.import_module(cfg.module)
    else:
        module_path = _resolve_encounter_strategy_module_path(scenario, cfg.module)
        module = _import_encounter_strategy(cfg.module, module_path)

    runner = getattr(module, cfg.callable, None)
    if runner is None or not callable(runner):
        raise ValueError(
            f"Custom simulation callable '{cfg.callable}' not found in module '{cfg.module}'"
        )
    return runner


def default_results_dir() -> Path:
    """Canonical results root for all simulation outputs."""
    return Path(__file__).resolve().parents[2] / "river_line" / "results"


def _slugify_run_name(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "simulation_run"


def build_run_dir(base_out_dir: Path, scenario_id: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = base_out_dir / f"{stamp}_{_slugify_run_name(scenario_id)}"
    path.mkdir(parents=True, exist_ok=True)
    (path / "plots").mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_trial_rows(path: Path, rows: list[dict[str, Any]]) -> Path:
    try:
        import pandas as pd  # type: ignore

        df = pd.DataFrame(rows)
        parquet_path = path.with_suffix(".parquet")
        df.to_parquet(parquet_path, index=False)
        return parquet_path
    except Exception:
        csv_path = path.with_suffix(".csv")
        if not rows:
            csv_path.write_text("", encoding="utf-8")
            return csv_path

        fieldnames = sorted(rows[0].keys())
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return csv_path


def load_summary(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
