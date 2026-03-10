from __future__ import annotations

from typing import Any

from dnd_sim.action_legality import TurnDeclarationValidationError
from dnd_sim.engine_runtime import SimulationArtifacts, SimulationCoreResult
from dnd_sim.io import LoadedScenario
from dnd_sim.replay import build_trial_rows
from dnd_sim.reporting_runtime import build_simulation_summary


def _build_simulation_artifacts(
    *,
    core_result: SimulationCoreResult,
    run_id: str,
    scenario_id: str,
    trials: int,
) -> SimulationArtifacts:
    trial_rows = build_trial_rows(core_result.trial_results)
    summary = build_simulation_summary(
        run_id=run_id,
        scenario_id=scenario_id,
        trials=trials,
        trial_results=core_result.trial_results,
        tracked_resource_names=core_result.tracked_resource_names,
    )
    return SimulationArtifacts(
        trial_results=core_result.trial_results,
        trial_rows=trial_rows,
        summary=summary,
    )


def run_simulation(
    scenario: LoadedScenario,
    character_db: dict[str, dict[str, Any]],
    traits_db: dict[str, dict[str, Any]],
    strategy_registry: dict[str, Any],
    *,
    trials: int,
    seed: int,
    run_id: str,
) -> SimulationArtifacts:
    from dnd_sim.engine_runtime import run_simulation_core

    core_result = run_simulation_core(
        scenario,
        character_db,
        traits_db,
        strategy_registry,
        trials=trials,
        seed=seed,
        run_id=run_id,
    )
    return _build_simulation_artifacts(
        core_result=core_result,
        run_id=run_id,
        scenario_id=scenario.config.scenario_id,
        trials=trials,
    )


__all__ = ["SimulationArtifacts", "TurnDeclarationValidationError", "run_simulation"]
