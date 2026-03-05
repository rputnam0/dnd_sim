from __future__ import annotations

import pytest

import dnd_sim.action_legality as action_legality
import dnd_sim.strategy_api as strategy_api
from dnd_sim.action_legality import (
    TurnDeclarationValidationError,
    apply_declared_reaction_policy_or_error,
    declared_action_or_error,
    declared_movement_path_or_error,
    validate_strategy_instance,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.strategy_api import DeclaredAction, ReactionPolicy, TurnDeclaration


def _actor(
    *, actor_id: str = "hero", actions: list[ActionDefinition] | None = None
) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team="party",
        name=actor_id,
        max_hp=30,
        hp=30,
        temp_hp=0,
        ac=14,
        initiative_mod=2,
        str_mod=1,
        dex_mod=2,
        con_mod=1,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 1, "dex": 2, "con": 1, "int": 0, "wis": 0, "cha": 0},
        actions=list(actions or []),
        position=(0.0, 0.0, 0.0),
    )


def test_validate_strategy_instance_requires_declare_turn_and_on_round_start() -> None:
    class MissingHooks:
        pass

    with pytest.raises(ValueError, match="missing required methods"):
        validate_strategy_instance(MissingHooks())


def test_strategy_api_validation_routes_through_action_legality(monkeypatch) -> None:
    called: dict[str, object] = {}

    def fake_validate(strategy: object) -> None:
        called["strategy"] = strategy

    monkeypatch.setattr(action_legality, "validate_strategy_instance", fake_validate)

    class ValidStrategy:
        def declare_turn(self, actor, state):
            return TurnDeclaration()

        def on_round_start(self, state):
            return None

    strategy = ValidStrategy()
    strategy_api.validate_strategy_instance(strategy)

    assert called["strategy"] is strategy


def test_strategy_api_validation_rejects_legacy_methods_after_delegation(monkeypatch) -> None:
    called: dict[str, object] = {}

    def fake_validate(strategy: object) -> None:
        called["strategy"] = strategy

    monkeypatch.setattr(action_legality, "validate_strategy_instance", fake_validate)

    class LegacyMethodStrategy:
        def declare_turn(self, actor, state):
            return TurnDeclaration()

        def choose_action(self, actor, state):
            return None

        def on_round_start(self, state):
            return None

    strategy = LegacyMethodStrategy()
    with pytest.raises(ValueError, match="removed legacy methods: choose_action"):
        strategy_api.validate_strategy_instance(strategy)

    assert called["strategy"] is strategy


def test_declared_action_or_error_emits_structured_unknown_action_error() -> None:
    actor = _actor(actions=[ActionDefinition(name="basic", action_type="attack")])

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        declared_action_or_error(
            actor,
            DeclaredAction(action_name="missing_action"),
            field_prefix="action",
            expected_cost="action",
        )

    assert exc_info.value.code == "unknown_action"
    assert exc_info.value.field == "action.action_name"
    assert exc_info.value.actor_id == "hero"


def test_declared_movement_path_or_error_rejects_start_position_mismatch() -> None:
    actor = _actor(actions=[ActionDefinition(name="basic", action_type="attack")])

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        declared_movement_path_or_error(
            actor,
            TurnDeclaration(movement_path=[(5.0, 0.0, 0.0)]),
        )

    assert exc_info.value.code == "movement_path_start_mismatch"
    assert exc_info.value.field == "movement_path[0]"


def test_apply_declared_reaction_policy_or_error_rejects_unknown_mode() -> None:
    actor = _actor(actions=[ActionDefinition(name="basic", action_type="attack")])

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        apply_declared_reaction_policy_or_error(
            actor,
            TurnDeclaration(reaction_policy=ReactionPolicy(mode="manual")),
            supported_modes={"auto", "none"},
        )

    assert exc_info.value.code == "invalid_reaction_policy"
    assert exc_info.value.field == "reaction_policy.mode"
