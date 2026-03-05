from __future__ import annotations

from typing import Any

from dnd_sim.action_legality import TurnDeclarationValidationError
from dnd_sim.engine_runtime import SimulationArtifacts
from dnd_sim.io import LoadedScenario


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
    from dnd_sim.engine_runtime import run_simulation as _run_simulation_runtime

    return _run_simulation_runtime(
        scenario,
        character_db,
        traits_db,
        strategy_registry,
        trials=trials,
        seed=seed,
        run_id=run_id,
    )


__all__ = ["SimulationArtifacts", "TurnDeclarationValidationError", "run_simulation"]
