from __future__ import annotations

import random

import dnd_sim.engine_runtime as engine_runtime
from dnd_sim.engine import (
    CombatTurnContext,
    CombatTurnDecision,
    resolve_combat_turn,
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


def _context(*, hero: ActorRuntimeState, enemy: ActorRuntimeState, round_number: int):
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


def test_resolve_combat_turn_runs_provider_between_start_and_end_lifecycle(
    monkeypatch,
) -> None:
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
    hero = _actor("hero", team="party", actions=[strike])
    enemy = _actor("enemy", team="enemy")
    enemy.position = (5.0, 0.0, 0.0)
    context = _context(hero=hero, enemy=enemy, round_number=2)
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

    provider_calls = 0

    def provide_decision(actor_view, state_view):
        nonlocal provider_calls
        provider_calls += 1
        lifecycle.append("provider")
        assert actor_view.actor_id == "hero"
        assert actor_view.movement_remaining == 30.0
        assert context.actors["hero"].bonus_available is True
        assert context.actors["hero"].reaction_available is True
        assert state_view.round_number == 2
        assert state_view.actor_order == ["hero", "enemy"]
        return CombatTurnDecision(
            strategy_name="interactive",
            declaration=TurnDeclaration(
                action=DeclaredAction(
                    action_name="strike",
                    targets=[TargetRef(actor_id="enemy")],
                )
            ),
        )

    result = resolve_combat_turn(
        rng=random.Random(13),
        context=context,
        actor_id="hero",
        decision_provider=provide_decision,
    )

    assert result.actor_id == "hero"
    assert result.round_number == 2
    assert result.turn_token == "2:hero"
    assert result.status == "resolved"
    assert result.strategy_name == "interactive"
    assert provider_calls == 1
    assert context.actors["enemy"].hp == 26
    assert [
        marker
        for marker in lifecycle
        if marker in {"turn_start", "provider", "after_action", "turn_end", "legendary_actions"}
    ] == ["turn_start", "provider", "after_action", "turn_end", "legendary_actions"]

    trace_types = [row.get("event_type") for row in context.telemetry]
    assert trace_types[-4:] == [
        "declaration_validation",
        "action_selection",
        "action_resolution",
        "action_outcome",
    ]


def test_resolve_combat_turn_resolves_death_save_without_calling_provider(
    monkeypatch,
) -> None:
    hero = _actor("hero", team="party", hp=0)
    hero.uses_death_saves = True
    hero.update_manual_conditions({"unconscious", "incapacitated", "prone"})
    enemy = _actor("enemy", team="enemy")
    context = _context(hero=hero, enemy=enemy, round_number=3)
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

    def forbidden_provider(_actor_view, _state_view):
        raise AssertionError("a zero-HP automatic turn must not request a declaration")

    result = resolve_combat_turn(
        rng=random.Random(7),
        context=context,
        actor_id="hero",
        decision_provider=forbidden_provider,
    )

    assert result.actor_id == "hero"
    assert result.round_number == 3
    assert result.turn_token == "3:hero"
    assert result.status == "death_save"
    assert result.strategy_name is None
    assert context.actors["hero"].death_successes == 1
    assert context.actors["hero"].death_failures == 0
    assert context.actors["hero"].movement_remaining == 30.0
    assert context.actors["hero"].bonus_available is True
    assert context.actors["hero"].reaction_available is True
    assert lifecycle == ["turn_end", "legendary_actions"]
