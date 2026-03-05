from __future__ import annotations

import dnd_sim.engine as engine_module
import dnd_sim.engine_runtime as engine_runtime


def test_engine_facade_delegates_to_engine_runtime(monkeypatch) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_run_simulation(
        scenario,
        character_db,
        traits_db,
        strategy_registry,
        *,
        trials,
        seed,
        run_id,
    ):
        captured["scenario"] = scenario
        captured["character_db"] = character_db
        captured["traits_db"] = traits_db
        captured["strategy_registry"] = strategy_registry
        captured["trials"] = trials
        captured["seed"] = seed
        captured["run_id"] = run_id
        return sentinel

    monkeypatch.setattr(engine_runtime, "run_simulation", fake_run_simulation)

    scenario = object()
    character_db = {"hero": {"name": "Hero"}}
    traits_db = {"alert": {}}
    strategy_registry = {"focus": object()}

    result = engine_module.run_simulation(
        scenario,
        character_db,
        traits_db,
        strategy_registry,
        trials=3,
        seed=42,
        run_id="arc01_delegate",
    )

    assert result is sentinel
    assert captured == {
        "scenario": scenario,
        "character_db": character_db,
        "traits_db": traits_db,
        "strategy_registry": strategy_registry,
        "trials": 3,
        "seed": 42,
        "run_id": "arc01_delegate",
    }
