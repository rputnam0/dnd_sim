from __future__ import annotations

import json
from pathlib import Path

import dnd_sim.engine as engine_module
import dnd_sim.engine_runtime as engine_runtime
from dnd_sim.io import load_character_db, load_scenario, load_strategy_registry
from tests.helpers import build_character, build_enemy
from tests.test_engine_integration import _setup_env


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


def test_runtime_uses_configured_defeat_rules_for_all_termination_checks(
    tmp_path: Path, monkeypatch
) -> None:
    scenario_path = _setup_env(
        tmp_path,
        party=[build_character("hero", "Hero", 20, 14, 4, "1d6+2")],
        enemies=[
            build_enemy(enemy_id="enemy", name="Enemy", hp=20, ac=12, to_hit=4, damage="1d6+2")
        ],
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
        max_rounds=2,
    )

    scenario_payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario_payload["termination_rules"]["party_defeat"] = "any_dead"
    scenario_payload["termination_rules"]["enemy_defeat"] = "any_downed"
    scenario_path.write_text(json.dumps(scenario_payload, indent=2), encoding="utf-8")

    loaded = load_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    db = load_character_db(Path(loaded.config.character_db_dir))

    original_party_defeated = engine_runtime._party_defeated
    original_enemies_defeated = engine_runtime._enemies_defeated
    seen = {"party": 0, "enemy": 0}

    def _party_defeated_with_rule(actors, rule_spec=None):
        assert rule_spec == "any_dead"
        seen["party"] += 1
        return original_party_defeated(actors, rule_spec)

    def _enemies_defeated_with_rule(actors, rule_spec=None):
        assert rule_spec == "any_downed"
        seen["enemy"] += 1
        return original_enemies_defeated(actors, rule_spec)

    monkeypatch.setattr(engine_runtime, "_party_defeated", _party_defeated_with_rule)
    monkeypatch.setattr(engine_runtime, "_enemies_defeated", _enemies_defeated_with_rule)

    engine_runtime.run_simulation(
        loaded,
        db,
        {},
        registry,
        trials=1,
        seed=19,
        run_id="termination_rule_regression",
    )

    assert seen["party"] > 0
    assert seen["enemy"] > 0
