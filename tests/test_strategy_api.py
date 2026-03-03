from __future__ import annotations

from dnd_sim.strategy_api import (
    ActorView,
    BaseStrategy,
    BattleStateView,
    DeclaredAction,
    TargetRef,
    TurnDeclaration,
)


class TacticalBonusChoiceStrategy(BaseStrategy):
    def __init__(self, *, bonus_action_name: str | None):
        self._bonus_action_name = bonus_action_name

    def declare_turn(self, actor, state):
        enemies = [
            view for view in state.actors.values() if view.team != actor.team and view.hp > 0
        ]
        if not enemies:
            return TurnDeclaration()
        target = enemies[0]
        bonus_action = None
        if self._bonus_action_name is not None:
            bonus_action = DeclaredAction(
                action_name=self._bonus_action_name,
                targets=[TargetRef(actor_id=target.actor_id)],
            )
        return TurnDeclaration(
            action=DeclaredAction(
                action_name="basic",
                targets=[TargetRef(actor_id=target.actor_id)],
            ),
            bonus_action=bonus_action,
            rationale={"tactical_choices": {"bonus_action": self._bonus_action_name}},
        )


def _build_state() -> tuple[ActorView, BattleStateView]:
    hero = ActorView(
        actor_id="hero",
        team="party",
        hp=30,
        max_hp=30,
        ac=16,
        save_mods={},
        resources={},
        conditions=set(),
        position=(0.0, 0.0, 0.0),
        speed_ft=30,
        movement_remaining=30.0,
        traits={},
    )
    enemy = ActorView(
        actor_id="enemy",
        team="enemy",
        hp=40,
        max_hp=40,
        ac=13,
        save_mods={},
        resources={},
        conditions=set(),
        position=(5.0, 0.0, 0.0),
        speed_ft=30,
        movement_remaining=30.0,
        traits={},
    )
    state = BattleStateView(
        round_number=1,
        actors={"hero": hero, "enemy": enemy},
        actor_order=["hero", "enemy"],
        metadata={},
    )
    return hero, state


def test_same_strategy_with_different_tactical_bonus_action_choices_produces_distinct_plans() -> None:
    actor, state = _build_state()

    with_offhand = TacticalBonusChoiceStrategy(bonus_action_name="off_hand_attack").declare_turn(
        actor, state
    )
    without_bonus = TacticalBonusChoiceStrategy(bonus_action_name=None).declare_turn(actor, state)

    assert with_offhand is not None
    assert with_offhand.action is not None
    assert with_offhand.action.action_name == "basic"
    assert with_offhand.bonus_action is not None
    assert with_offhand.bonus_action.action_name == "off_hand_attack"

    assert without_bonus is not None
    assert without_bonus.action is not None
    assert without_bonus.action.action_name == "basic"
    assert without_bonus.bonus_action is None


def test_turn_declaration_omitted_bonus_action_defaults_to_none() -> None:
    declaration = TurnDeclaration()
    assert declaration.bonus_action is None
