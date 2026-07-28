from __future__ import annotations

from dnd_sim.strategy_api import (
    ActorView,
    BaseStrategy,
    BattleStateView,
    DeclaredAction,
    ReactionOptionView,
    ReactionTriggerView,
    ReactionWindowView,
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


def test_same_strategy_with_different_tactical_bonus_action_choices_produces_distinct_plans() -> (
    None
):
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


def test_base_strategy_can_declare_stabilization_for_a_downed_creature() -> None:
    healer, state = _build_state()
    downed = ActorView(
        actor_id="downed",
        team="party",
        hp=0,
        max_hp=20,
        ac=12,
        save_mods={},
        resources={},
        conditions={"unconscious"},
        position=(5.0, 0.0, 0.0),
        speed_ft=30,
        movement_remaining=0.0,
        traits={},
        uses_death_saves=True,
    )
    state.actors[downed.actor_id] = downed
    state.actor_order.append(downed.actor_id)
    state.metadata = {
        "available_actions": {healer.actor_id: ["stabilize"]},
        "action_catalog": {
            healer.actor_id: [
                {
                    "name": "stabilize",
                    "action_type": "utility",
                    "target_mode": "single_creature",
                    "reach_ft": 5,
                    "mechanics": [
                        {
                            "effect_type": "stabilize",
                            "target": "target",
                            "check_skill": "medicine",
                            "check_dc": 10,
                        }
                    ],
                }
            ]
        },
    }

    declaration = BaseStrategy().declare_turn(healer, state)

    assert declaration is not None
    assert declaration.action is not None
    assert declaration.action.action_name == "stabilize"
    assert declaration.action.targets == [TargetRef(actor_id="downed")]


def test_base_strategy_uses_deterministic_reaction_option_priority() -> None:
    actor, state = _build_state()
    window = ReactionWindowView(
        window_id="1:opportunity_attack:hero:enemy:0:5,0,0",
        reactor_id=actor.actor_id,
        round_number=1,
        turn_token="1:enemy",
        trigger=ReactionTriggerView(
            kind="opportunity_attack",
            source_actor_id="enemy",
            target_actor_id=actor.actor_id,
        ),
        options=(
            ReactionOptionView(
                option_id="heavy",
                action_name="heavy",
                attack_bonus=5,
                reach_ft=5,
            ),
            ReactionOptionView(
                option_id="accurate",
                action_name="accurate",
                attack_bonus=8,
                reach_ft=5,
            ),
        ),
    )

    decision = BaseStrategy().decide_reaction(actor, window, state)

    assert decision.window_id == window.window_id
    assert decision.choice == "use"
    assert decision.option_id == "accurate"


def test_base_strategy_passes_same_team_counterspell_and_uses_optimal_hostile_slot() -> None:
    actor, state = _build_state()
    window = ReactionWindowView(
        window_id="counterspell-window",
        reactor_id=actor.actor_id,
        round_number=1,
        turn_token="1:enemy",
        trigger=ReactionTriggerView(
            kind="counterspell",
            source_actor_id="enemy",
            target_actor_id=actor.actor_id,
            action_name="Arcane Seal",
            spell_level=5,
        ),
        options=(
            ReactionOptionView(
                option_id="slot-3",
                action_name="Counterspell",
                fixed_target_ids=("enemy",),
                legal_spell_slot_levels=(3,),
                resource_cost=(("spell_slot_3", 1),),
            ),
            ReactionOptionView(
                option_id="slot-5",
                action_name="Counterspell",
                fixed_target_ids=("enemy",),
                legal_spell_slot_levels=(5,),
                resource_cost=(("spell_slot_5", 1),),
            ),
        ),
    )

    hostile = BaseStrategy().decide_reaction(actor, window, state)
    assert hostile.choice == "use"
    assert hostile.option_id == "slot-5"
    assert hostile.spell_slot_level == 5

    state.actors["enemy"].team = actor.team
    friendly = BaseStrategy().decide_reaction(actor, window, state)
    assert friendly.choice == "pass"
    assert friendly.option_id is None
    assert friendly.spell_slot_level is None


def test_base_strategy_can_select_slotless_counterspell_option() -> None:
    actor, state = _build_state()
    window = ReactionWindowView(
        window_id="innate-counterspell-window",
        reactor_id=actor.actor_id,
        round_number=1,
        turn_token="1:enemy",
        trigger=ReactionTriggerView(
            kind="counterspell",
            source_actor_id="enemy",
            spell_level=3,
        ),
        options=(
            ReactionOptionView(
                option_id="innate-counterspell",
                action_name="Counterspell",
                fixed_target_ids=("enemy",),
                effective_spell_level=3,
            ),
        ),
    )

    decision = BaseStrategy().decide_reaction(actor, window, state)

    assert decision.choice == "use"
    assert decision.option_id == "innate-counterspell"
    assert decision.spell_slot_level is None


def test_default_counterspell_prefers_free_guaranteed_option_before_lower_level_slot() -> None:
    actor, state = _build_state()
    window = ReactionWindowView(
        window_id="counterspell-resource-priority",
        reactor_id=actor.actor_id,
        round_number=1,
        turn_token="1:enemy",
        trigger=ReactionTriggerView(
            kind="counterspell",
            source_actor_id="enemy",
            spell_level=3,
        ),
        options=(
            ReactionOptionView(
                option_id="paid-level-three",
                action_name="Counterspell",
                legal_spell_slot_levels=(3,),
                resource_cost=(("spell_slot_3", 1),),
                effective_spell_level=3,
            ),
            ReactionOptionView(
                option_id="free-innate-level-four",
                action_name="Counterspell",
                effective_spell_level=4,
            ),
        ),
    )

    decision = BaseStrategy().decide_reaction(actor, window, state)

    assert decision.option_id == "free-innate-level-four"
    assert decision.spell_slot_level is None
