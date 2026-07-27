from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from dnd_sim.interactive.dnd_contracts import TurnDeclarationPayload
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
