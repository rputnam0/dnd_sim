from __future__ import annotations

import copy
import random

import dnd_sim.engine_runtime as engine_runtime
from dnd_sim.engine import (
    CombatTurnContext,
    CombatTurnDecision,
    CombatTurnPrompt,
    CombatTurnResult,
    prepare_combat_turn,
    resolve_combat_turn,
    resolve_prompted_combat_turn,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.strategy_api import DeclaredAction, TargetRef, TurnDeclaration


def _actor(
    actor_id: str,
    *,
    team: str,
    hp: int = 30,
    actions: list[ActionDefinition] | None = None,
) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id.title(),
        max_hp=30,
        hp=hp,
        temp_hp=0,
        ac=12,
        initiative_mod=0,
        str_mod=0,
        dex_mod=0,
        con_mod=0,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        actions=list(actions or []),
        movement_remaining=0.0,
        reaction_available=False,
        bonus_available=False,
        position=(0.0, 0.0, 0.0),
    )


def _context(*, round_number: int = 2, hero_hp: int = 30) -> CombatTurnContext:
    strike = ActionDefinition(
        name="strike",
        action_type="attack",
        action_cost="action",
        target_mode="single_enemy",
        to_hit=20,
        damage="4",
        damage_type="slashing",
        reach_ft=5,
    )
    hero = _actor("hero", team="party", hp=hero_hp, actions=[strike])
    enemy = _actor("enemy", team="enemy")
    enemy.position = (5.0, 0.0, 0.0)
    actors = {hero.actor_id: hero, enemy.actor_id: enemy}
    return CombatTurnContext(
        actors=actors,
        initiative_order=[hero.actor_id, enemy.actor_id],
        round_number=round_number,
        damage_dealt={actor_id: 0 for actor_id in actors},
        damage_taken={actor_id: 0 for actor_id in actors},
        threat_scores={actor_id: 0 for actor_id in actors},
        resources_spent={actor_id: {} for actor_id in actors},
        active_hazards=[],
        telemetry=[],
        rule_trace=[],
        obstacles=[],
        light_level="bright",
        burst_round_threshold=3,
        strategy_overrides={},
        timing_engine=engine_runtime._create_combat_timing_engine(),
        party_defeat_rule="all_unconscious_or_dead",
        enemy_defeat_rule="all_dead",
    )


def _decision() -> CombatTurnDecision:
    return CombatTurnDecision(
        strategy_name="interactive",
        declaration=TurnDeclaration(
            action=DeclaredAction(
                action_name="strike",
                targets=[TargetRef(actor_id="enemy")],
            )
        ),
    )


def _context_observables(context: CombatTurnContext) -> tuple[object, ...]:
    return (
        context.actors,
        context.initiative_order,
        context.round_number,
        context.damage_dealt,
        context.damage_taken,
        context.threat_scores,
        context.resources_spent,
        context.active_hazards,
        context.telemetry,
        context.rule_trace,
        context.obstacles,
        context.light_level,
        context.burst_round_threshold,
        context.strategy_overrides,
        context.timing_engine._next_subscription_id,
        context.timing_engine._next_event_sequence,
    )


def test_prepare_stops_at_prompt_then_resolution_completes_lifecycle(monkeypatch) -> None:
    context = _context()
    rng = random.Random(13)
    lifecycle: list[str] = []

    real_dispatch = engine_runtime._dispatch_combat_event

    def observing_dispatch(**kwargs):
        lifecycle.append(str(kwargs["event"]))
        return real_dispatch(**kwargs)

    real_readied = engine_runtime._trigger_readied_actions

    def observing_readied(**kwargs):
        lifecycle.append("readied_actions")
        return real_readied(**kwargs)

    real_legendary = engine_runtime._run_legendary_actions

    def observing_legendary(**kwargs):
        lifecycle.append("legendary_actions")
        return real_legendary(**kwargs)

    monkeypatch.setattr(engine_runtime, "_dispatch_combat_event", observing_dispatch)
    monkeypatch.setattr(engine_runtime, "_trigger_readied_actions", observing_readied)
    monkeypatch.setattr(engine_runtime, "_run_legendary_actions", observing_legendary)

    prompt = prepare_combat_turn(
        rng=rng,
        context=context,
        actor_id="hero",
    )

    assert isinstance(prompt, CombatTurnPrompt)
    assert prompt.actor_id == "hero"
    assert prompt.round_number == 2
    assert prompt.turn_token == "2:hero"
    assert prompt.actor_view.actor_id == "hero"
    assert prompt.actor_view.movement_remaining == 30.0
    assert prompt.state_view.round_number == 2
    assert prompt.state_view.actor_order == ["hero", "enemy"]
    assert context.actors["hero"].movement_remaining == 30.0
    assert context.actors["hero"].bonus_available is True
    assert context.actors["hero"].reaction_available is True
    assert context.actors["enemy"].hp == 30
    assert context.telemetry == []
    assert lifecycle == ["turn_start", "readied_actions"]

    result = resolve_prompted_combat_turn(
        rng=rng,
        context=context,
        prompt=prompt,
        decision=_decision(),
    )

    assert result == CombatTurnResult(
        actor_id="hero",
        round_number=2,
        turn_token="2:hero",
        status="resolved",
        strategy_name="interactive",
    )
    assert context.actors["enemy"].hp == 26
    assert [
        marker
        for marker in lifecycle
        if marker
        in {"turn_start", "readied_actions", "after_action", "turn_end", "legendary_actions"}
    ] == [
        "turn_start",
        "readied_actions",
        "after_action",
        "turn_end",
        "legendary_actions",
    ]


def test_split_prompt_path_matches_synchronous_turn_state_events_and_rng() -> None:
    split_context = _context()
    synchronous_context = copy.deepcopy(split_context)
    split_rng = random.Random(29)
    synchronous_rng = random.Random(29)

    prompt = prepare_combat_turn(
        rng=split_rng,
        context=split_context,
        actor_id="hero",
    )
    assert isinstance(prompt, CombatTurnPrompt)
    split_result = resolve_prompted_combat_turn(
        rng=split_rng,
        context=split_context,
        prompt=prompt,
        decision=_decision(),
    )
    synchronous_result = resolve_combat_turn(
        rng=synchronous_rng,
        context=synchronous_context,
        actor_id="hero",
        decision_provider=lambda _actor_view, _state_view: _decision(),
    )

    assert split_result == synchronous_result
    assert _context_observables(split_context) == _context_observables(synchronous_context)
    assert split_rng.getstate() == synchronous_rng.getstate()


def test_prepare_resolves_zero_hp_automatic_path_without_returning_prompt(
    monkeypatch,
) -> None:
    context = _context(round_number=3, hero_hp=0)
    hero = context.actors["hero"]
    hero.uses_death_saves = True
    hero.update_manual_conditions({"unconscious", "incapacitated", "prone"})
    lifecycle: list[str] = []

    real_dispatch = engine_runtime._dispatch_combat_event

    def observing_dispatch(**kwargs):
        lifecycle.append(str(kwargs["event"]))
        return real_dispatch(**kwargs)

    real_legendary = engine_runtime._run_legendary_actions

    def observing_legendary(**kwargs):
        lifecycle.append("legendary_actions")
        return real_legendary(**kwargs)

    monkeypatch.setattr(engine_runtime, "_dispatch_combat_event", observing_dispatch)
    monkeypatch.setattr(engine_runtime, "_run_legendary_actions", observing_legendary)

    outcome = prepare_combat_turn(
        rng=random.Random(7),
        context=context,
        actor_id="hero",
    )

    assert isinstance(outcome, CombatTurnResult)
    assert not isinstance(outcome, CombatTurnPrompt)
    assert outcome == CombatTurnResult(
        actor_id="hero",
        round_number=3,
        turn_token="3:hero",
        status="death_save",
    )
    assert hero.death_successes == 1
    assert hero.death_failures == 0
    assert lifecycle == ["turn_end", "legendary_actions"]
