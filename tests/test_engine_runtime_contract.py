from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import dnd_sim.engine as engine_module
import dnd_sim.engine_runtime as engine_runtime
from dnd_sim.io import load_character_db, load_runtime_scenario, load_strategy_registry
from dnd_sim.strategy_api import (
    BaseStrategy,
    ReactionDecision,
    ReactionOptionView,
    ReactionTriggerView,
    ReactionWindowView,
)
from tests.helpers import build_character, build_enemy
from tests.runtime_test_support import _setup_env


def test_engine_facade_delegates_to_engine_runtime(monkeypatch) -> None:
    captured: dict[str, object] = {}
    sentinel_rows = [{"trial_index": 0}]
    sentinel_summary = SimpleNamespace(trials=3)

    def fake_run_simulation_core(
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
        return engine_runtime.SimulationCoreResult(
            trial_results=["core_trial"],  # type: ignore[list-item]
            tracked_resource_names={"hero": {"ki"}},
        )

    monkeypatch.setattr(engine_runtime, "run_simulation_core", fake_run_simulation_core)
    monkeypatch.setattr(engine_module, "build_trial_rows", lambda trial_results: sentinel_rows)
    monkeypatch.setattr(
        engine_module,
        "build_simulation_summary",
        lambda **_: sentinel_summary,
    )

    scenario = SimpleNamespace(
        config=SimpleNamespace(scenario_id="fixture"),
        rules_profile=SimpleNamespace(
            profile_id="5e_2014_combat_foundation",
            profile_version="1.0.0",
        ),
    )
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

    assert result.trial_results == ["core_trial"]
    assert result.trial_rows == sentinel_rows
    assert result.summary is sentinel_summary
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

    loaded = load_runtime_scenario(scenario_path)
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

    engine_runtime.run_simulation_core(
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

    loaded = load_runtime_scenario(scenario_path)
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

    engine_runtime.run_simulation_core(
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


def test_runtime_routes_reaction_window_to_reactor_strategy(tmp_path: Path, monkeypatch) -> None:
    scenario_path = _setup_env(
        tmp_path,
        party=[build_character("hero", "Hero", 20, 14, 4, "1d6+2")],
        enemies=[
            build_enemy(enemy_id="enemy", name="Enemy", hp=20, ac=12, to_hit=4, damage="1d6+2")
        ],
        assumption_overrides={
            "party_strategy": "party_strategy",
            "enemy_strategy": "enemy_strategy",
        },
        max_rounds=1,
    )
    loaded = load_runtime_scenario(scenario_path)
    db = load_character_db(Path(loaded.config.character_db_dir))
    decisions: list[ReactionDecision] = []

    class PassingReactionStrategy(BaseStrategy):
        def decide_reaction(self, actor, window, state):
            assert actor.actor_id == "hero"
            assert state.actors[actor.actor_id].reaction_available is True
            return ReactionDecision(window_id=window.window_id, choice="pass")

    def capture_declared_turn(**kwargs):
        if decisions:
            return
        provider = kwargs.get("reaction_decision_provider")
        assert callable(provider)
        window = ReactionWindowView(
            window_id="1:opportunity_attack:hero:enemy:0:5,0,0",
            reactor_id="hero",
            round_number=1,
            turn_token="1:enemy",
            trigger=ReactionTriggerView(
                kind="opportunity_attack",
                source_actor_id="enemy",
                target_actor_id="hero",
            ),
            options=(
                ReactionOptionView(
                    option_id="hero:opportunity_attack:0:basic",
                    action_name="basic",
                    attack_bonus=4,
                ),
            ),
        )
        decisions.append(provider(window))

    monkeypatch.setattr(engine_runtime, "_execute_declared_turn_or_error", capture_declared_turn)

    engine_runtime.run_simulation_core(
        loaded,
        db,
        {},
        {
            "party_strategy": PassingReactionStrategy(),
            "enemy_strategy": BaseStrategy(),
        },
        trials=1,
        seed=31,
        run_id="reaction_strategy_routing",
    )

    assert len(decisions) == 1
    assert decisions[0].choice == "pass"
