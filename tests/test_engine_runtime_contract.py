from __future__ import annotations

import json
from pathlib import Path

import dnd_sim.engine as engine_module
import dnd_sim.engine_runtime as engine_runtime
from dnd_sim.io import load_character_db, load_scenario, load_strategy_registry
from tests.helpers import build_character, build_enemy
from tests.runtime_test_support import _setup_env


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


def test_runtime_applies_configured_precombat_interaction_state(
    tmp_path: Path, monkeypatch
) -> None:
    scenario_path = _setup_env(
        tmp_path,
        party=[build_character("rogue", "Rogue", 18, 14, 5, "1d6+3")],
        enemies=[
            build_enemy(enemy_id="guard", name="Guard", hp=12, ac=12, to_hit=3, damage="1d6+1")
        ],
        assumption_overrides={
            "party_strategy": "focus_fire_lowest_hp",
            "enemy_strategy": "boss_highest_threat_target",
        },
        max_rounds=1,
    )

    scenario_payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario_payload["stealth_actors"] = [
        {"actor_id": "rogue", "team": "party", "hidden": False, "detected_by": []},
        {
            "actor_id": "guard",
            "team": "enemy",
            "hidden": False,
            "detected_by": ["rogue"],
            "passive_perception": 10,
        },
    ]
    scenario_payload["interaction_actions"] = [
        {
            "action": "contested_stealth",
            "actor_id": "rogue",
            "check_total": 17,
            "target_actor_ids": ["guard"],
        },
        {
            "action": "surprise",
            "teams": {"rogue": "party", "guard": "enemy"},
        },
    ]
    scenario_path.write_text(json.dumps(scenario_payload, indent=2), encoding="utf-8")

    loaded = load_scenario(scenario_path)
    registry = load_strategy_registry(loaded)
    db = load_character_db(Path(loaded.config.character_db_dir))
    captured: dict[str, dict[str, object]] = {}
    original_build_actor_views = engine_runtime._build_actor_views

    def capture_initial_view(actors, actor_order, round_number, metadata):
        if round_number == 1 and not captured:
            for actor_id, actor in actors.items():
                captured[actor_id] = {
                    "hidden": actor.hidden,
                    "detected_by": set(actor.detected_by),
                    "surprised": actor.surprised,
                }
        return original_build_actor_views(actors, actor_order, round_number, metadata)

    monkeypatch.setattr(engine_runtime, "_build_actor_views", capture_initial_view)

    engine_runtime.run_simulation(
        loaded,
        db,
        {},
        registry,
        trials=1,
        seed=11,
        run_id="precombat_interaction_runtime",
    )

    assert captured["rogue"]["hidden"] is True
    assert captured["rogue"]["detected_by"] == set()
    assert captured["guard"]["surprised"] is True
