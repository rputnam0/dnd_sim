from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from dnd_sim.interactive.dnd_contracts import (
    TURN_CHOICES_SCHEMA_VERSION,
    ActionChoicePayload,
    MovementChoicePayload,
    TurnChoicesPayload,
    TurnDeclarationPayload,
)
from dnd_sim.strategy_api import (
    DeclaredAction,
    ReactionPolicy,
    ReadyDeclaration,
    ResourceSpend,
    TargetRef,
    TurnDeclaration,
)


def test_turn_declaration_payload_round_trips_complete_domain_declaration() -> None:
    declaration = TurnDeclaration(
        movement_path=[(0.0, 0.0, 0.0), (5.0, 10.0, 0.0)],
        action=DeclaredAction(
            action_name="longsword",
            targets=[TargetRef(actor_id="goblin-1")],
            resource_spend=ResourceSpend(amounts={"superiority_die": 1}),
            spell_slot_level=2,
            rationale={"reason": "protect wizard"},
        ),
        bonus_action=DeclaredAction(action_name="second_wind"),
        reaction_policy=ReactionPolicy(mode="none", rationale={"reason": "save shield"}),
        ready=ReadyDeclaration(
            trigger="enemy enters reach",
            response_action_name="longsword",
            rationale={"source": "player"},
        ),
        rationale={"plan": ["advance", "strike"]},
    )

    payload = TurnDeclarationPayload.from_domain(declaration)
    restored = payload.to_domain()

    assert restored == declaration
    assert payload.model_dump(mode="json")["movement_path"] == [
        [0.0, 0.0, 0.0],
        [5.0, 10.0, 0.0],
    ]


@pytest.mark.parametrize(
    "patch",
    [
        {"extra": True},
        {"movement_path": [[0.0, 0.0]]},
        {"movement_path": [[0.0, math.inf, 0.0]]},
        {"reaction_policy": {"mode": "manual", "rationale": {}}},
        {"action": {"action_name": "strike", "targets": [], "unknown": 1}},
        {
            "action": {
                "action_name": "strike",
                "targets": [],
                "resource_spend": {"amounts": {"ki": True}},
            }
        },
    ],
)
def test_turn_declaration_payload_rejects_noncanonical_or_unsupported_input(
    patch: dict,
) -> None:
    source = {
        "movement_path": [],
        "action": None,
        "bonus_action": None,
        "reaction_policy": {"mode": "auto", "rationale": {}},
        "ready": None,
        "rationale": {},
    }
    source.update(patch)

    with pytest.raises((ValidationError, ValueError)):
        TurnDeclarationPayload.model_validate(source)


def test_turn_choices_payload_is_versioned_strict_and_json_canonical() -> None:
    choices = TurnChoicesPayload(
        actor_id="hero",
        movement=MovementChoicePayload(
            origin=(0.0, 5.0, 0.0),
            remaining_ft=25.0,
        ),
        actions=(
            ActionChoicePayload(
                action_name="strike",
                action_cost="action",
                target_mode="single_enemy",
                requires_explicit_targets=True,
                selectable_target_ids=("enemy-a", "enemy-b"),
                legal_target_ids=("enemy-a", "enemy-b"),
            ),
        ),
    )

    assert choices.model_dump(mode="json") == {
        "schema_version": TURN_CHOICES_SCHEMA_VERSION,
        "actor_id": "hero",
        "movement": {
            "origin": [0.0, 5.0, 0.0],
            "remaining_ft": 25.0,
        },
        "actions": [
            {
                "action_name": "strike",
                "action_cost": "action",
                "target_mode": "single_enemy",
                "requires_explicit_targets": True,
                "selectable_target_ids": ["enemy-a", "enemy-b"],
                "legal_target_ids": ["enemy-a", "enemy-b"],
                "reason": None,
            }
        ],
        "reason": None,
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TurnChoicesPayload.model_validate({**choices.model_dump(mode="json"), "unexpected": True})


@pytest.mark.parametrize(
    "patch",
    [
        {"legal_target_ids": [], "reason": None},
        {"selectable_target_ids": ["enemy-b", "enemy-a"]},
        {"selectable_target_ids": ["enemy-a", "enemy-a"]},
        {"selectable_target_ids": [], "legal_target_ids": ["enemy-a"]},
        {"legal_target_ids": ["enemy-b", "enemy-a"], "reason": None},
        {"legal_target_ids": ["enemy-a"], "reason": "no_legal_targets"},
        {"requires_explicit_targets": False},
    ],
)
def test_action_choice_payload_requires_consistent_target_reason(patch: dict) -> None:
    source = {
        "action_name": "strike",
        "action_cost": "action",
        "target_mode": "single_enemy",
        "requires_explicit_targets": True,
        "selectable_target_ids": ["enemy-a"],
        "legal_target_ids": ["enemy-a"],
        "reason": None,
    }
    source.update(patch)

    with pytest.raises(ValidationError):
        ActionChoicePayload.model_validate(source)


def test_explicit_action_can_be_selectable_before_it_is_currently_legal() -> None:
    choice = ActionChoicePayload(
        action_name="strike",
        action_cost="action",
        target_mode="single_enemy",
        requires_explicit_targets=True,
        selectable_target_ids=("enemy-a",),
        legal_target_ids=(),
        reason="no_legal_targets",
    )

    assert choice.selectable_target_ids == ("enemy-a",)
    assert choice.legal_target_ids == ()


def test_empty_turn_choices_require_an_explicit_reason() -> None:
    with pytest.raises(ValidationError):
        TurnChoicesPayload(
            actor_id="hero",
            movement=MovementChoicePayload(
                origin=(0.0, 0.0, 0.0),
                remaining_ft=0.0,
            ),
            actions=(),
        )
