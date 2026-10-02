"""Independent trial identity, observational rolls, and binomial uncertainty."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import math
import random
from typing import Any

from dnd_sim.combat_roll_runtime import combat_roll_journal_scope
from dnd_sim.engine_runtime import run_simulation_core
from dnd_sim.io_models import LoadedScenario
from dnd_sim.models import TrialResult
from dnd_sim.roll_journal import EngineRollJournalRecorder


@dataclass(frozen=True)
class RecordedTrial:
    seed: int
    result: TrialResult
    random_draws: list[dict[str, int]]
    roll_records: list[dict[str, Any]]


class _ObservedRandom(random.Random):
    """Record authoritative integer draws without adding or replacing any draw."""

    def __init__(self, seed: int):
        super().__init__(seed)
        self.draws: list[dict[str, int]] = []

    def randint(self, a: int, b: int) -> int:
        value = super().randint(a, b)
        self.draws.append({"index": len(self.draws), "minimum": a, "maximum": b, "value": value})
        return value


def derive_trial_seed(master_seed: int, scenario_id: str, trial_index: int) -> int:
    """Stable v1 seeds independent of policy, batching, process, and execution order."""
    if type(master_seed) is not int or type(trial_index) is not int or trial_index < 0:
        raise ValueError("seed and non-negative trial_index must be integers")
    payload = json.dumps(["dnd-benchmark-seed-v1", master_seed, scenario_id, trial_index])
    return int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], "big")


def run_trial(
    scenario: LoadedScenario,
    character_db: dict[str, dict[str, Any]],
    traits_db: dict[str, dict[str, Any]],
    strategy_factory: Callable[[], dict[str, Any]],
    *,
    trial_index: int,
    seed: int,
    record_rolls: bool = False,
) -> RecordedTrial:
    """Run one fresh shared-engine trial, optionally preserving actual roll facts.

    Strategies are constructed per trial so stateful policies cannot leak across
    experiments. The legacy batch RNG behavior is unchanged.
    """
    if type(trial_index) is not int or trial_index < 0 or type(seed) is not int:
        raise ValueError("seed and non-negative trial_index must be integers")
    rng = _ObservedRandom(seed) if record_rolls else random.Random(seed)
    recorder = EngineRollJournalRecorder.empty(f"trial:{trial_index}") if record_rolls else None
    with combat_roll_journal_scope(recorder):
        core = run_simulation_core(
            scenario,
            character_db,
            traits_db,
            strategy_factory(),
            trials=1,
            seed=seed,
            run_id=f"trial_{trial_index}",
            rng=rng,
        )
    result = core.trial_results[0]
    result.trial_index = trial_index
    return RecordedTrial(
        seed=seed,
        result=result,
        random_draws=rng.draws if isinstance(rng, _ObservedRandom) else [],
        roll_records=(
            [record.model_dump(mode="json") for record in recorder.journal.records]
            if recorder is not None
            else []
        ),
    )


def wilson_interval(successes: int, trials: int) -> tuple[float, float]:
    """Two-sided 95% Wilson score interval, including zero/all-success samples."""
    if (
        type(successes) is not int
        or type(trials) is not int
        or trials <= 0
        or not 0 <= successes <= trials
    ):
        raise ValueError("binomial counts require 0 <= successes <= trials and trials > 0")
    z = 1.959963984540054
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    radius = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return max(0.0, center - radius), min(1.0, center + radius)
