from __future__ import annotations

from pathlib import Path

import pytest

from dnd_sim.benchmarks.policies import TacticalPolicy
from dnd_sim.benchmarks.trials import run_trial
from dnd_sim.engine_runtime import (
    _build_actor_from_character,
    _build_actor_from_enemy,
    _build_actor_views,
    _build_round_metadata,
    create_declared_turn_runtime_state,
    resolve_declared_turn,
)
from dnd_sim.strategy_api import DeclaredAction, TargetRef, TurnDeclaration
from tests.test_cover_rules import CountingRng
from dnd_sim.io import load_public_scenario
from dnd_sim.benchmarks.level_five import load_party

ROOT = Path(__file__).resolve().parents[1] / "data/benchmarks/level_five"


def _battle():
    characters = load_party()
    scenario = load_public_scenario(ROOT / "scenarios/02_veteran_line.json")
    actors = {key: _build_actor_from_character(row, {}) for key, row in characters.items()}
    actors.update(
        {key: _build_actor_from_enemy(row, {}) for key, row in sorted(scenario.enemies.items())}
    )
    for key, actor in actors.items():
        actor.position = tuple(scenario.config.battlefield["starting_positions"][key])
        actor.movement_remaining = actor.speed_ft
    return scenario, characters, actors


def _view(actors):
    metadata = _build_round_metadata(
        actors=actors,
        threat_scores={},
        burst_round_threshold=2,
        active_hazards=[],
        light_level="bright",
        strategy_overrides={},
    )
    return _build_actor_views(actors, list(actors), 1, metadata)


def test_fighter_moves_attacks_and_uses_second_wind_in_one_turn() -> None:
    _, _, actors = _battle()
    actors["fighter"].hp = 15
    state = _view(actors)
    turn = TacticalPolicy("typical").declare_turn(state.actors["fighter"], state)
    assert turn.movement_path
    assert turn.action is not None
    assert turn.bonus_action.action_name == "second_wind"
    assert turn.reaction_policy.mode == "auto"


def test_rogue_combines_light_weapon_attack_and_off_hand_attack() -> None:
    _, _, actors = _battle()
    actors["rogue"].position = (10, 25, 0)
    actors["fighter"].position = (5, 30, 0)
    state = _view(actors)
    turn = TacticalPolicy("typical").declare_turn(state.actors["rogue"], state)
    assert turn.bonus_action.action_name == "off_hand_attack"
    assert turn.action.action_name in {"basic", "attack_1", "attack_2", "signature"}
    catalog = {a["name"]: a for a in state.metadata["action_catalog"]["rogue"]}
    assert (
        catalog[turn.action.action_name]["weapon_id"]
        != catalog[turn.bonus_action.action_name]["weapon_id"]
    )


def test_cleric_rescues_downed_ally_and_casts_cantrip_without_double_slot_spend() -> None:
    _, _, actors = _battle()
    actors["fighter"].hp = 0
    actors["fighter"].conditions.add("unconscious")
    state = _view(actors)
    turn = TacticalPolicy("typical").declare_turn(state.actors["cleric"], state)
    assert turn.action.action_name == "Sacred Flame"
    assert turn.bonus_action.action_name == "Healing Word"
    assert turn.bonus_action.targets[0].actor_id == "fighter"


def test_fireball_is_rejected_if_any_ally_is_in_its_template() -> None:
    _, _, actors = _battle()
    actors["fighter"].position = (10, 30, 0)
    state = _view(actors)
    turn = TacticalPolicy("aggressive").declare_turn(state.actors["wizard"], state)
    assert turn.action.action_name != "Fireball"


def test_prone_actor_reserves_half_speed_to_stand_before_moving() -> None:
    _, _, actors = _battle()
    fighter = actors["fighter"]
    fighter.conditions.add("prone")
    state = _view(actors)
    turn = TacticalPolicy().declare_turn(state.actors["fighter"], state)
    assert len(turn.movement_path) <= 4  # start plus three 5-foot steps


def test_primary_kill_cancels_planned_off_hand_without_spending_bonus_or_rolling() -> None:
    _, _, actors = _battle()
    rogue = actors["rogue"]
    rogue.position = (10, 25, 0)
    target = actors["veteran_2"]
    target.hp = 1
    actors = {"rogue": rogue, "veteran_2": target}
    state = create_declared_turn_runtime_state(
        actors=actors,
        damage_dealt=dict.fromkeys(actors, 0),
        damage_taken=dict.fromkeys(actors, 0),
        threat_scores=dict.fromkeys(actors, 0),
        resources_spent={key: {} for key in actors},
        active_hazards=[],
        round_number=1,
        turn_token="1:rogue",
    )
    declaration = TurnDeclaration(
        action=DeclaredAction(action_name="basic", targets=[TargetRef("veteran_2")]),
        bonus_action=DeclaredAction(
            action_name="off_hand_attack", targets=[TargetRef("veteran_2")]
        ),
    )
    rng = CountingRng([15, 4])
    resolve_declared_turn(
        state=state, rng=rng, actor_id="rogue", declaration=declaration, strategy_name="benchmark"
    )
    assert target.dead
    assert rogue.bonus_available
    assert rng.calls == 2
    assert any(row.get("reason") == "planned_targets_defeated" for row in state.telemetry)


@pytest.mark.parametrize("policy", ["conservative", "typical", "aggressive"])
def test_all_public_encounters_accept_complete_tactical_declarations(policy: str) -> None:
    characters = load_party()
    initial_resources = {
        key: _build_actor_from_character(row, {}).resources for key, row in characters.items()
    }
    for path in sorted((ROOT / "scenarios").glob("*.json")):
        scenario = load_public_scenario(path)
        for seed in range(3):
            trial = run_trial(
                scenario,
                characters,
                {},
                lambda: {"benchmark": TacticalPolicy(policy)},
                trial_index=seed,
                seed=seed,
            ).result
            assert trial.outcome in {"party_victory", "enemy_victory", "timeout"}
            for snapshot in trial.state_snapshots:
                for actor in snapshot["party"].values():
                    assert 0 <= actor["hp"] <= actor["max_hp"]
                    assert all(value >= 0 for value in actor["resources"].values())
            for key, final in trial.state_snapshots[-1]["party"].items():
                for resource, initial in initial_resources[key].items():
                    assert (
                        trial.resources_spent[key].get(resource, 0)
                        == initial - final["resources"][resource]
                    )
