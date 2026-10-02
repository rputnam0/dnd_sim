from __future__ import annotations

from pathlib import Path

from dnd_sim.engine_runtime import _build_actor_from_character
from dnd_sim.io import load_public_scenario
from dnd_sim.benchmarks.level_five import load_party

ROOT = Path(__file__).resolve().parents[1] / "data/benchmarks/level_five"


def test_benchmark_party_has_four_level_five_members_and_declared_spell_scaling() -> None:
    characters = load_party()
    assert set(characters) == {"fighter", "rogue", "cleric", "wizard"}
    assert all(sum(row["class_levels"].values()) == 5 for row in characters.values())
    actors = {key: _build_actor_from_character(row, {}) for key, row in characters.items()}
    assert {key: actor.max_hp for key, actor in actors.items()} == {
        "fighter": 10 + 4 * 6 + 5 * 3,
        "rogue": 8 + 4 * 5 + 5 * 2,
        "cleric": 8 + 4 * 5 + 5 * 2,
        "wizard": 6 + 4 * 4 + 5 * 2,
    }
    assert {key: actor.ac for key, actor in actors.items()} == {
        "fighter": 18,
        "rogue": 16,
        "cleric": 18,
        "wizard": 12,
    }
    assert actors["fighter"].actions[0].damage_type == "slashing"
    assert actors["cleric"].actions[0].damage_type == "bludgeoning"
    actions = {key: {a.name: a for a in actor.actions} for key, actor in actors.items()}
    assert actions["fighter"]["basic"].attack_count == 2
    assert actions["fighter"]["action_surge"].attack_count == 4
    assert actions["fighter"]["second_wind"].effects[0]["amount"] == "1d10+5"
    assert actions["rogue"]["off_hand_attack"].damage == "1d6"
    assert actions["cleric"]["Sacred Flame"].damage == "2d8"
    assert actions["wizard"]["Fire Bolt"].damage == "2d10"
    assert actions["wizard"]["Scorching Ray"].attack_count == 3
    assert actions["wizard"]["Fireball"].include_self is True
    for name in ("cleric", "wizard"):
        assert [actors[name].resources[f"spell_slot_{level}"] for level in (1, 2, 3)] == [4, 3, 2]


def test_all_benchmark_scenarios_load_through_public_content_contract() -> None:
    paths = sorted((ROOT / "scenarios").glob("*.json"))
    assert len(paths) >= 6
    for path in paths:
        scenario = load_public_scenario(path)
        assert scenario.config.internal_harness is None
        assert set(scenario.config.party) == {"fighter", "rogue", "cleric", "wizard"}
        positions = scenario.config.battlefield["starting_positions"]
        assert len({tuple(point) for point in positions.values()}) == len(positions)
        assert all(enemy.actions for enemy in scenario.enemies.values())
