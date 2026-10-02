"""Hand-calculated SRD 5.1 cases for the exact benchmark character loadouts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from dnd_sim.combat_roll_runtime import combat_roll_journal_scope
from dnd_sim.engine_runtime import (
    _build_actor_from_character,
    _build_actor_from_enemy,
    _execute_action,
    _roll_recharge_for_actor,
    _tick_conditions_for_actor,
    _build_initiative_order_with_scores,
    create_declared_turn_runtime_state,
    resolve_declared_turn,
)
from dnd_sim.io import load_public_scenario
from dnd_sim.benchmarks.level_five import load_party
from dnd_sim.roll_journal import EngineRollJournalRecorder
from dnd_sim.rules_2014 import resolve_death_save
from dnd_sim.spatial import AABB
from dnd_sim.strategy_api import DeclaredAction, TargetRef, TurnDeclaration
from tests.test_cover_rules import CountingRng

ROOT = Path(__file__).resolve().parents[1] / "data/benchmarks/level_five"


def _actors():
    characters = load_party()
    scenario = load_public_scenario(ROOT / "scenarios/02_veteran_line.json")
    actors = {key: _build_actor_from_character(row, {}) for key, row in characters.items()}
    actors.update(
        {key: _build_actor_from_enemy(row, {}) for key, row in sorted(scenario.enemies.items())}
    )
    for index, actor in enumerate(actors.values()):
        actor.position = (float(index * 10), 0, 0)
    return actors


def _state(actors, actor_id, obstacles=()):
    return create_declared_turn_runtime_state(
        actors=actors,
        damage_dealt=dict.fromkeys(actors, 0),
        damage_taken=dict.fromkeys(actors, 0),
        threat_scores=dict.fromkeys(actors, 0),
        resources_spent={key: {} for key in actors},
        active_hazards=[],
        round_number=1,
        turn_token=f"1:{actor_id}",
        obstacles=list(obstacles),
    )


def _turn(actors, actor_id, action_name, target_id, dice, *, bonus=None, obstacles=()):
    state = _state(actors, actor_id, obstacles)
    declaration = TurnDeclaration(
        action=DeclaredAction(action_name=action_name, targets=[TargetRef(target_id)]),
        bonus_action=bonus,
    )
    recorder = EngineRollJournalRecorder.empty("conformance")
    rng = CountingRng(dice)
    with combat_roll_journal_scope(recorder):
        resolve_declared_turn(
            state=state,
            rng=rng,
            actor_id=actor_id,
            declaration=declaration,
            strategy_name="conformance",
        )
    assert not rng.values, "Expected independent dice sequence was not fully consumed"
    return state, recorder.journal


def test_level_five_extra_attack_surge_and_second_wind_exact_arithmetic() -> None:
    actors = _actors()
    fighter, enemy = actors["fighter"], actors["veteran_1"]
    enemy.position = (5, 0, 0)
    fighter.hp = 20
    state, journal = _turn(
        actors,
        "fighter",
        "action_surge",
        "veteran_1",
        [15, 4] * 4 + [6],
        bonus=DeclaredAction(action_name="second_wind", targets=[TargetRef("fighter")]),
    )
    assert enemy.hp == 58 - 4 * (4 + 4)
    assert fighter.hp == 31  # d10=6 + fighter level 5
    assert state.resources_spent["fighter"] == {"action_surge": 1, "second_wind": 1}
    assert sum(record.fact.kind == "d20" for record in journal.records) == 4


def test_level_five_sneak_attack_is_three_d6_once_across_both_weapons() -> None:
    actors = _actors()
    actors["rogue"].position = (5, 0, 0)
    actors["veteran_1"].position = (5, 5, 0)
    actors["fighter"].position = (0, 5, 0)
    state, _ = _turn(
        actors,
        "rogue",
        "basic",
        "veteran_1",
        [15, 3, 4, 4, 4, 15, 3],
        bonus=DeclaredAction(action_name="off_hand_attack", targets=[TargetRef("veteran_1")]),
    )
    assert state.damage_dealt["rogue"] == (3 + 4 + 12) + 3
    assert actors["rogue"].bonus_available is False


def test_scorching_ray_rolls_three_separate_attacks_and_spends_one_second_level_slot() -> None:
    actors = _actors()
    state, journal = _turn(actors, "wizard", "Scorching Ray", "veteran_1", [15, 2, 3] * 3)
    assert state.damage_dealt["wizard"] == 15
    assert state.resources_spent["wizard"] == {"spell_slot_2": 1}
    assert sum(record.fact.kind == "d20" for record in journal.records) == 3


def test_fire_bolt_level_five_and_critical_double_dice_without_doubling_modifiers() -> None:
    actors = _actors()
    state, _ = _turn(actors, "wizard", "Fire Bolt", "veteran_1", [20, 2, 3, 4, 5])
    assert state.damage_dealt["wizard"] == 14  # critical doubles 2d10 to 4d10
    assert state.resources_spent["wizard"] == {}


@pytest.mark.parametrize("slot,face,expected", [(1, 3, 7), (2, 3, 10), (3, 3, 13)])
def test_healing_word_upcast_rescues_zero_hp_ally_with_exact_slot_and_amount(
    slot, face, expected
) -> None:
    actors = _actors()
    target = actors["fighter"]
    target.hp = 0
    target.conditions.add("unconscious")
    target.death_failures = 2
    name = "Healing Word" if slot == 1 else f"Healing Word (slot {slot})"
    state, journal = _turn(
        actors,
        "cleric",
        "Sacred Flame",
        "veteran_1",
        [2, 3, 20] + [face] * slot,
        bonus=DeclaredAction(
            action_name=name, targets=[TargetRef("fighter")], spell_slot_level=slot
        ),
    )
    assert target.hp == expected
    assert target.death_failures == 0
    assert "unconscious" not in target.conditions
    assert state.resources_spent["cleric"] == {f"spell_slot_{slot}": 1}
    heals = [record.fact for record in journal.records if record.fact.kind == "healing"]
    assert len(heals) == 1 and heals[0].effective_healing == expected


@pytest.mark.parametrize("slot", [1, 2, 3])
def test_cure_wounds_healing_is_capped_and_higher_slots_add_d8(slot) -> None:
    actors = _actors()
    actors["fighter"].position = (20, 5, 0)
    actors["fighter"].hp -= 5
    name = "Cure Wounds" if slot == 1 else f"Cure Wounds (slot {slot})"
    state, journal = _turn(actors, "cleric", name, "fighter", [6] * slot)
    assert actors["fighter"].hp == actors["fighter"].max_hp
    heal = next(record.fact for record in journal.records if record.fact.kind == "healing")
    assert heal.rolled_healing == slot * 6 + 4
    assert heal.effective_healing == 5
    assert state.resources_spent["cleric"] == {f"spell_slot_{slot}": 1}


def test_sacred_flame_ignores_half_cover_and_deals_nothing_on_success() -> None:
    for save, damage in [(12, 5), (13, 0)]:  # DC15, defender +2: cover must not add +2
        actors = _actors()
        actors["cleric"].position = (0, 0, 0)
        actors["veteran_1"].position = (30, 0, 0)
        state, _ = _turn(
            actors,
            "cleric",
            "Sacred Flame",
            "veteran_1",
            [2, 3, save],
            obstacles=[AABB((10, -1, -1), (20, 1, 1), "HALF")],
        )
        assert state.damage_dealt["cleric"] == damage


def test_fireball_uses_one_damage_roll_and_includes_allies_and_caster_in_sphere() -> None:
    actors = _actors()
    actors = {key: actors[key] for key in ("wizard", "fighter", "veteran_1", "veteran_2")}
    for key, point in {
        "wizard": (15, 0, 0),
        "fighter": (35, 0, 0),
        "veteran_1": (30, 0, 0),
        "veteran_2": (35, 5, 0),
    }.items():
        actors[key].position = point
    state, journal = _turn(actors, "wizard", "Fireball", "veteran_1", [1] * 8 + [1] * 4)
    assert all(value == 8 for value in state.damage_taken.values())
    assert state.resources_spent["wizard"] == {"spell_slot_3": 1}
    assert sum(record.fact.kind == "saving_throw" for record in journal.records) == 4
    damage = [record.fact for record in journal.records if record.fact.kind == "damage"]
    assert len(damage) == 4
    assert all(fact.raw_damage == 8 for fact in damage)


def test_binomial_hit_probability_matches_all_twenty_possible_faces() -> None:
    hits = 0
    for face in range(1, 21):
        actors = _actors()
        actor, target = actors["fighter"], actors["veteran_1"]
        target.position = (5, 0, 0)
        target.ac = 16
        action = replace(actor.actions[0], attack_count=1, damage="1")
        state = _state(actors, "fighter")
        _execute_action(
            rng=CountingRng([face]),
            actor=actor,
            action=action,
            targets=[target],
            actors=actors,
            damage_dealt=state.damage_dealt,
            damage_taken=state.damage_taken,
            threat_scores=state.threat_scores,
            resources_spent=state.resources_spent,
            active_hazards=[],
            round_number=1,
            turn_token="1:fighter",
        )
        hits += target.hp < target.max_hp
    assert hits == 12  # +7 vs AC16: faces 9..20; natural 1 fails


def test_cinder_sentinel_resists_fire_and_successful_save_halves_again() -> None:
    actors = _actors()
    scenario = load_public_scenario(ROOT / "scenarios/04_cinder_sentinel.json")
    boss = _build_actor_from_enemy(scenario.enemies["cinder_sentinel"], {})
    actors = {"wizard": actors["wizard"], "cinder_sentinel": boss}
    actors["wizard"].position = (0, 0, 0)
    boss.position = (50, 0, 0)
    state, _ = _turn(actors, "wizard", "Fireball", boss.actor_id, [2] * 7 + [3, 20])
    assert state.damage_taken[boss.actor_id] == 4  # floor(floor(17/2)/2)


@pytest.mark.parametrize("face,ready", [(1, False), (4, False), (5, True), (6, True)])
def test_cinder_burst_recharges_only_on_five_or_six(face, ready) -> None:
    scenario = load_public_scenario(ROOT / "scenarios/04_cinder_sentinel.json")
    boss = _build_actor_from_enemy(scenario.enemies["cinder_sentinel"], {})
    name = next(action.name for action in boss.actions if action.recharge)
    boss.recharge_ready[name] = False
    _roll_recharge_for_actor(CountingRng([face]), boss)
    assert boss.recharge_ready[name] is ready


def test_cinder_burst_hits_multiple_creatures_and_spends_recharge() -> None:
    party = _actors()
    scenario = load_public_scenario(ROOT / "scenarios/04_cinder_sentinel.json")
    boss = _build_actor_from_enemy(scenario.enemies["cinder_sentinel"], {})
    boss.position = (30, 0, 0)
    party["fighter"].position = (0, 0, 0)
    party["rogue"].position = (5, 0, 0)
    actors = {"fighter": party["fighter"], "rogue": party["rogue"], "cinder_sentinel": boss}
    # Resolver orders these victims by HP: rogue first, then fighter.
    state, _ = _turn(actors, boss.actor_id, "Cinder Burst", "fighter", [3] * 5 + [20, 1])
    assert state.damage_taken["fighter"] == 15
    assert state.damage_taken["rogue"] == 7
    assert boss.recharge_ready["Cinder Burst"] is False


def test_area_damage_includes_unconscious_creatures_and_causes_death_failure() -> None:
    party = _actors()
    scenario = load_public_scenario(ROOT / "scenarios/04_cinder_sentinel.json")
    boss = _build_actor_from_enemy(scenario.enemies["cinder_sentinel"], {})
    boss.position = (30, 0, 0)
    fighter, rogue = party["fighter"], party["rogue"]
    fighter.position, rogue.position = (0, 0, 0), (5, 0, 0)
    rogue.hp = 0
    rogue.conditions.add("unconscious")
    actors = {"fighter": fighter, "rogue": rogue, "cinder_sentinel": boss}
    _turn(actors, boss.actor_id, "Cinder Burst", "fighter", [3] * 5 + [20])
    assert rogue.death_failures == 1  # auto-failed Dex save; damage at zero HP


def test_generated_wizard_shield_spends_one_reaction_and_slot_for_two_attacks() -> None:
    actors = _actors()
    actors["veteran_1"].position = (40, 0, 0)
    actors["wizard"].position = (35, 0, 0)
    # +6, rolls 9 = 15. AC12 would be hit; Shield raises it to17 for both attacks.
    state, _ = _turn(actors, "veteran_1", "basic", "wizard", [9, 9])
    assert state.damage_taken["wizard"] == 0
    assert state.resources_spent["wizard"] == {"spell_slot_1": 1}
    assert not actors["wizard"].reaction_available


def test_generated_rogue_uncanny_dodge_halves_only_one_attack_per_reaction() -> None:
    actors = _actors()
    actors["veteran_1"].position = (40, 0, 0)
    actors["rogue"].position = (35, 0, 0)
    state, _ = _turn(actors, "veteran_1", "basic", "rogue", [15, 4, 15, 4])
    assert state.damage_taken["rogue"] == 3 + 7
    assert not actors["rogue"].reaction_available


@pytest.mark.parametrize(
    "face,successes,failures,hp", [(1, 0, 2, 0), (9, 0, 1, 0), (10, 1, 0, 0), (20, 0, 0, 1)]
)
def test_generated_party_death_save_boundaries(face, successes, failures, hp) -> None:
    fighter = _actors()["fighter"]
    fighter.hp = 0
    fighter.conditions.add("unconscious")
    resolve_death_save(CountingRng([face]), fighter)
    assert (fighter.death_successes, fighter.death_failures, fighter.hp) == (
        successes,
        failures,
        hp,
    )


def test_dodge_disadvantage_persists_until_next_turn_start() -> None:
    actors = _actors()
    actors["veteran_1"].position = (5, 0, 0)
    _turn(actors, "fighter", "dodge", "fighter", [])
    fighter = actors["fighter"]
    _tick_conditions_for_actor(CountingRng([]), fighter, boundary="turn_end")
    assert "dodging" in fighter.conditions
    state, _ = _turn(actors, "veteran_1", "basic", "fighter", [20, 2, 20, 2])
    assert state.damage_taken["fighter"] == 0
    _tick_conditions_for_actor(CountingRng([]), fighter, boundary="turn_start")
    assert "dodging" not in fighter.conditions


def test_initiative_uses_dexterity_and_documents_engine_tie_roll() -> None:
    actors = _actors()
    actors = {k: actors[k] for k in ("fighter", "rogue")}
    order, scores = _build_initiative_order_with_scores(
        CountingRng([10, 1, 10, 1]), actors, "individual"
    )
    assert scores == {"fighter": 11, "rogue": 14}
    assert order == ["rogue", "fighter"]
