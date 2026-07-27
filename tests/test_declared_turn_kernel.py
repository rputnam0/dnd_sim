from __future__ import annotations

import copy
import random

import pytest

from dnd_sim.action_legality import TurnDeclarationValidationError
from dnd_sim.engine import (
    create_declared_turn_runtime_state,
    resolve_declared_turn_atomic,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.strategy_api import DeclaredAction, TargetRef, TurnDeclaration


def _actor(
    *,
    actor_id: str,
    team: str,
    actions: list[ActionDefinition] | None = None,
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=30,
        hp=30,
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
        movement_remaining=30.0,
        position=position,
    )


def _state():
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
    hero = _actor(actor_id="hero", team="party", actions=[strike])
    enemy = _actor(actor_id="enemy", team="enemy", position=(10.0, 0.0, 0.0))
    actors = {actor.actor_id: actor for actor in (hero, enemy)}
    return create_declared_turn_runtime_state(
        actors=actors,
        damage_dealt={actor_id: 0 for actor_id in actors},
        damage_taken={actor_id: 0 for actor_id in actors},
        threat_scores={actor_id: 0 for actor_id in actors},
        resources_spent={actor_id: {} for actor_id in actors},
        active_hazards=[],
        telemetry=[{"before": True}],
        obstacles=[],
        light_level="bright",
        round_number=1,
        turn_token="1:hero",
        rule_trace=[{"before": True}],
    )


def _primary_declaration(*, with_invalid_bonus: bool = False) -> TurnDeclaration:
    return TurnDeclaration(
        movement_path=[(0.0, 0.0, 0.0), (5.0, 0.0, 0.0)],
        action=DeclaredAction(
            action_name="strike",
            targets=[TargetRef(actor_id="enemy")],
        ),
        bonus_action=(
            DeclaredAction(
                action_name="missing_bonus",
                targets=[TargetRef(actor_id="enemy")],
            )
            if with_invalid_bonus
            else None
        ),
    )


def _state_observables(state) -> tuple[object, ...]:
    return (
        state.actors,
        state.damage_dealt,
        state.damage_taken,
        state.threat_scores,
        state.resources_spent,
        state.active_hazards,
        state.telemetry,
        state.obstacles,
        state.light_level,
        state.round_number,
        state.turn_token,
        state.rule_trace,
        state.timing_engine._next_subscription_id,
        state.timing_engine._next_event_sequence,
    )


def test_success_returns_detached_candidate_and_advances_rng_only_on_commit() -> None:
    state = _state()
    before = copy.deepcopy(_state_observables(state))
    rng = random.Random(41)
    rng_before = rng.getstate()

    candidate = resolve_declared_turn_atomic(
        state=state,
        rng=rng,
        actor_id="hero",
        declaration=_primary_declaration(),
        strategy_name="interactive",
    )

    assert _state_observables(state) == before
    assert candidate is not state
    assert candidate.actors["hero"] is not state.actors["hero"]
    assert candidate.actors["hero"].position == (5.0, 0.0, 0.0)
    assert candidate.actors["enemy"].hp < state.actors["enemy"].hp
    assert rng.getstate() != rng_before


def test_invalid_bonus_rolls_back_movement_action_metrics_trace_timing_and_rng() -> None:
    state = _state()
    before = copy.deepcopy(_state_observables(state))
    rng = random.Random(41)
    rng_before = rng.getstate()

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        resolve_declared_turn_atomic(
            state=state,
            rng=rng,
            actor_id="hero",
            declaration=_primary_declaration(with_invalid_bonus=True),
            strategy_name="interactive",
        )

    assert exc_info.value.code == "unknown_action"
    assert exc_info.value.field == "bonus_action.action_name"
    assert _state_observables(state) == before
    assert rng.getstate() == rng_before


def test_preview_and_commit_from_same_state_and_seed_are_identical() -> None:
    state = _state()
    preview_rng = random.Random(97)
    commit_rng = random.Random(97)

    preview = resolve_declared_turn_atomic(
        state=state,
        rng=preview_rng,
        actor_id="hero",
        declaration=_primary_declaration(),
        strategy_name="interactive",
    )
    committed = resolve_declared_turn_atomic(
        state=state,
        rng=commit_rng,
        actor_id="hero",
        declaration=_primary_declaration(),
        strategy_name="interactive",
    )

    assert _state_observables(preview) == _state_observables(committed)
    assert preview_rng.getstate() == commit_rng.getstate()
