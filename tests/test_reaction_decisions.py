from __future__ import annotations

import pytest

from dnd_sim.engine_runtime import _run_opportunity_attacks_for_movement
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.reaction_runtime import (
    ReactionDecisionValidationError,
    build_opportunity_attack_window,
    build_strategy_reaction_decision_provider,
)
from dnd_sim.strategy_api import (
    ActorView,
    BaseStrategy,
    BattleStateView,
    ReactionDecision,
    ReactionOptionView,
    ReactionTriggerView,
    ReactionWindowView,
    TargetRef,
)


class _SequenceRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, low: int, high: int) -> int:
        if not self.values:
            raise AssertionError("unexpected RNG consumption")
        value = self.values.pop(0)
        assert low <= value <= high
        return value


def _actor(
    actor_id: str,
    *,
    team: str,
    hp: int = 20,
    max_hp: int = 20,
) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id.title(),
        max_hp=max_hp,
        hp=hp,
        temp_hp=0,
        ac=10,
        initiative_mod=0,
        str_mod=0,
        dex_mod=0,
        con_mod=0,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={},
        actions=[],
        uses_death_saves=False,
    )


def _attack(
    name: str,
    *,
    to_hit: int = 5,
    damage: str = "1",
    attack_delivery: str | None = "melee_weapon_attack",
    resource_cost: dict[str, int] | None = None,
) -> ActionDefinition:
    return ActionDefinition(
        name=name,
        action_type="attack",
        attack_delivery=attack_delivery,
        action_cost="action",
        to_hit=to_hit,
        damage=damage,
        damage_type="slashing",
        reach_ft=5,
        range_ft=5,
        resource_cost=dict(resource_cost or {}),
    )


def _trackers(
    *actors: ActorRuntimeState,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    return (
        {actor.actor_id: 0 for actor in actors},
        {actor.actor_id: 0 for actor in actors},
        {actor.actor_id: 0 for actor in actors},
        {actor.actor_id: {} for actor in actors},
    )


def test_opportunity_reaction_ids_are_deterministic_and_bind_delimited_identities() -> None:
    action = _attack("spear:guard")

    def build(
        *,
        reactor_id: str,
        mover_id: str,
    ) -> ReactionWindowView:
        return build_opportunity_attack_window(
            reactor=_actor(reactor_id, team="party"),
            mover=_actor(mover_id, team="enemy"),
            candidates=[(action, 5.0)],
            trigger_point=(5.0, 0.0, 0.0),
            trigger_distance=5.0,
            round_number=1,
            turn_token="1:turn",
            window_ordinal=0,
            movement_source="movement",
            mover_disengaged=False,
        )

    left = build(reactor_id="reactor:x", mover_id="y")
    repeated = build(reactor_id="reactor:x", mover_id="y")
    delimiter_collision = build(reactor_id="reactor", mover_id="x:y")
    different_target = build(reactor_id="reactor:x", mover_id="other:y")

    assert repeated.window_id == left.window_id
    assert repeated.options[0].option_id == left.options[0].option_id
    assert delimiter_collision.window_id != left.window_id
    assert different_target.options[0].option_id != left.options[0].option_id


def _run(
    *,
    rng: _SequenceRng,
    mover: ActorRuntimeState,
    reactor: ActorRuntimeState,
    provider,
    telemetry: list[dict] | None = None,
) -> tuple[dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    actors = {mover.actor_id: mover, reactor.actor_id: reactor}
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(mover, reactor)
    _run_opportunity_attacks_for_movement(
        rng=rng,
        mover=mover,
        start_pos=(0.0, 0.0, 0.0),
        end_pos=(15.0, 0.0, 0.0),
        movement_path=[(0.0, 0.0, 0.0), (15.0, 0.0, 0.0)],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        reaction_decision_provider=provider,
        telemetry=telemetry,
        round_number=2,
        turn_token="2:mover",
    )
    return damage_dealt, damage_taken, resources_spent


def _position_for_opportunity_attack(
    mover: ActorRuntimeState,
    reactor: ActorRuntimeState,
) -> None:
    mover.position = (0.0, 0.0, 0.0)
    reactor.position = (5.0, 0.0, 0.0)


def test_explicit_reaction_pass_has_no_state_or_rng_side_effects() -> None:
    mover = _actor("mover", team="party")
    reactor = _actor("reactor", team="enemy")
    _position_for_opportunity_attack(mover, reactor)
    reactor.actions = [_attack("spear", resource_cost={"ammo": 1})]
    reactor.resources["ammo"] = 1
    telemetry: list[dict] = []
    windows: list[ReactionWindowView] = []

    def pass_provider(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _, _, resources_spent = _run(
        rng=_SequenceRng([]),
        mover=mover,
        reactor=reactor,
        provider=pass_provider,
        telemetry=telemetry,
    )

    assert len(windows) == 1
    assert mover.hp == mover.max_hp
    assert reactor.reaction_available is True
    assert reactor.resources["ammo"] == 1
    assert resources_spent[reactor.actor_id] == {}
    assert [row["telemetry_type"] for row in telemetry] == [
        "reaction_window_opened",
        "reaction_decision",
        "reaction_window_closed",
    ]
    assert telemetry[-1]["status"] == "passed"


def test_sentinel_still_receives_typed_opportunity_window_against_disengage() -> None:
    mover = _actor("mover", team="party")
    reactor = _actor("reactor", team="enemy")
    _position_for_opportunity_attack(mover, reactor)
    mover.conditions.add("disengaging")
    reactor.traits = {"sentinel": {}}
    reactor.actions = [_attack("spear")]
    windows: list[ReactionWindowView] = []

    def pass_provider(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _run(
        rng=_SequenceRng([]),
        mover=mover,
        reactor=reactor,
        provider=pass_provider,
    )

    assert len(windows) == 1
    assert windows[0].trigger.kind == "opportunity_attack"
    assert windows[0].trigger.mover_disengaged is True
    assert windows[0].options[0].on_hit_effects == ("speed_zero_for_turn",)
    assert reactor.reaction_available is True
    assert mover.hp == mover.max_hp


def test_reaction_decision_selects_an_explicit_attack_option() -> None:
    mover = _actor("mover", team="party")
    reactor = _actor("reactor", team="enemy")
    _position_for_opportunity_attack(mover, reactor)
    heavy = _attack("heavy", to_hit=5, damage="5")
    heavy.mechanics = [{"effect_type": "extra_attack", "count": 2}]
    reactor.actions = [_attack("accurate", to_hit=10, damage="1"), heavy]

    def choose_heavy(window: ReactionWindowView) -> ReactionDecision:
        option = next(option for option in window.options if option.action_name == "heavy")
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=option.option_id,
            targets=[TargetRef(mover.actor_id)],
        )

    _run(
        rng=_SequenceRng([15]),
        mover=mover,
        reactor=reactor,
        provider=choose_heavy,
    )

    assert mover.hp == 15
    assert reactor.reaction_available is False
    assert reactor.per_action_uses["heavy"] == 1


def test_opportunity_window_excludes_exhausted_limited_attacks() -> None:
    mover = _actor("mover", team="party")
    reactor = _actor("reactor", team="enemy")
    _position_for_opportunity_attack(mover, reactor)
    limited = _attack("limited")
    limited.max_uses = 1
    reactor.actions = [limited]
    reactor.per_action_uses[limited.name] = 1
    windows: list[ReactionWindowView] = []

    def capture(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _run(
        rng=_SequenceRng([]),
        mover=mover,
        reactor=reactor,
        provider=capture,
    )

    assert windows == []
    assert reactor.reaction_available is True


def test_opportunity_reaction_can_declare_a_melee_knockout() -> None:
    mover = _actor("mover", team="party", hp=1, max_hp=10)
    reactor = _actor("reactor", team="enemy")
    _position_for_opportunity_attack(mover, reactor)
    reactor.actions = [_attack("club")]

    def knock_out(window: ReactionWindowView) -> ReactionDecision:
        option = window.options[0]
        assert option.legal_zero_hp_intents == ("normal", "knock_out")
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=option.option_id,
            zero_hp_intent="knock_out",
        )

    rng = _SequenceRng([15, 2])
    _run(rng=rng, mover=mover, reactor=reactor, provider=knock_out)

    assert mover.hp == 0
    assert mover.stable is True
    assert mover.dead is False
    assert mover.stable_recovery_hours_remaining == 2
    assert rng.values == []


def test_illegal_knockout_reaction_is_atomic_and_consumes_no_rng() -> None:
    mover = _actor("mover", team="party", hp=1, max_hp=10)
    reactor = _actor("reactor", team="enemy")
    _position_for_opportunity_attack(mover, reactor)
    reactor.actions = [
        _attack(
            "legacy_club",
            attack_delivery=None,
            resource_cost={"ammo": 1},
        )
    ]
    reactor.resources["ammo"] = 1
    rng = _SequenceRng([])

    def illegal_knockout(window: ReactionWindowView) -> ReactionDecision:
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=window.options[0].option_id,
            zero_hp_intent="knock_out",
        )

    with pytest.raises(ReactionDecisionValidationError) as exc_info:
        _run(rng=rng, mover=mover, reactor=reactor, provider=illegal_knockout)

    assert exc_info.value.code == "illegal_zero_hp_intent"
    assert mover.hp == 1
    assert reactor.reaction_available is True
    assert reactor.resources["ammo"] == 1
    assert rng.values == []


def test_stale_reaction_window_id_is_rejected_atomically() -> None:
    mover = _actor("mover", team="party")
    reactor = _actor("reactor", team="enemy")
    _position_for_opportunity_attack(mover, reactor)
    reactor.actions = [_attack("spear")]

    def stale(window: ReactionWindowView) -> ReactionDecision:
        return ReactionDecision(
            window_id=f"{window.window_id}:stale",
            choice="use",
            option_id=window.options[0].option_id,
        )

    with pytest.raises(ReactionDecisionValidationError) as exc_info:
        _run(rng=_SequenceRng([]), mover=mover, reactor=reactor, provider=stale)

    assert exc_info.value.code == "stale_reaction_window"
    assert mover.hp == mover.max_hp
    assert reactor.reaction_available is True


def test_opportunity_window_and_option_ids_are_deterministic() -> None:
    mover = _actor("mover", team="party")
    reactor = _actor("reactor", team="enemy")
    _position_for_opportunity_attack(mover, reactor)
    reactor.actions = [_attack("spear"), _attack("club")]
    windows: list[ReactionWindowView] = []

    def capture(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _run(rng=_SequenceRng([]), mover=mover, reactor=reactor, provider=capture)
    _run(rng=_SequenceRng([]), mover=mover, reactor=reactor, provider=capture)

    assert len(windows) == 2
    assert windows[0] == windows[1]
    assert len({option.option_id for option in windows[0].options}) == 2


def test_opportunity_window_excludes_spells_and_non_action_attacks() -> None:
    mover = _actor("mover", team="party")
    reactor = _actor("reactor", team="enemy")
    _position_for_opportunity_attack(mover, reactor)
    bonus_attack = _attack("bonus_strike")
    bonus_attack.action_cost = "bonus"
    reaction_attack = _attack("special_reaction")
    reaction_attack.action_cost = "reaction"
    spell_attack = _attack("shocking_grasp", attack_delivery="melee_spell_attack")
    spell_attack.tags = ["spell"]
    reactor.actions = [
        _attack("club"),
        bonus_attack,
        reaction_attack,
        spell_attack,
    ]
    windows: list[ReactionWindowView] = []

    def capture(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _run(rng=_SequenceRng([]), mover=mover, reactor=reactor, provider=capture)

    assert len(windows) == 1
    assert [option.action_name for option in windows[0].options] == ["club"]


def test_strategy_reaction_provider_uses_reactor_strategy_and_live_state() -> None:
    reactor = ActorView(
        actor_id="reactor",
        team="enemy",
        hp=20,
        max_hp=20,
        ac=15,
        save_mods={},
        resources={},
        conditions=set(),
        position=(5.0, 0.0, 0.0),
        speed_ft=30,
        movement_remaining=30.0,
        traits={},
    )
    state_calls = 0

    def current_state() -> BattleStateView:
        nonlocal state_calls
        state_calls += 1
        return BattleStateView(
            round_number=2,
            actors={reactor.actor_id: reactor},
            actor_order=[reactor.actor_id],
            metadata={"state_generation": state_calls},
        )

    class PassingStrategy:
        def decide_reaction(self, actor, window, state):
            assert actor is reactor
            assert state.metadata["state_generation"] == state_calls
            return ReactionDecision(
                window_id=window.window_id,
                choice="pass",
                rationale={"strategy": "passing"},
            )

    window = ReactionWindowView(
        window_id="2:opportunity_attack:reactor:mover:0:5,0,0",
        reactor_id=reactor.actor_id,
        round_number=2,
        turn_token="2:mover",
        trigger=ReactionTriggerView(
            kind="opportunity_attack",
            source_actor_id="mover",
            target_actor_id=reactor.actor_id,
        ),
        options=(ReactionOptionView(option_id="club", action_name="club", attack_bonus=5),),
    )
    provider = build_strategy_reaction_decision_provider(
        state_provider=current_state,
        strategy_registry={"enemy_default": object(), "reactor_override": PassingStrategy()},
        actor_strategy_overrides={reactor.actor_id: "reactor_override"},
        party_default_strategy="party_default",
        enemy_default_strategy="enemy_default",
    )

    first = provider(window)
    second = provider(window)
    legacy_provider = build_strategy_reaction_decision_provider(
        state_provider=current_state,
        strategy_registry={"enemy_default": object()},
        actor_strategy_overrides={},
        party_default_strategy="party_default",
        enemy_default_strategy="enemy_default",
    )
    legacy_fallback = legacy_provider(window)

    assert first.choice == second.choice == "pass"
    assert first.rationale == second.rationale == {"strategy": "passing"}
    assert legacy_fallback.choice == "use"
    assert legacy_fallback.option_id == "club"
    assert state_calls == 3


def test_base_strategy_avoids_friendly_fire_for_trait_reactions() -> None:
    reactor = ActorView(
        actor_id="reactor",
        team="party",
        hp=20,
        max_hp=20,
        ac=15,
        save_mods={},
        resources={},
        conditions=set(),
        position=(0.0, 0.0, 0.0),
        speed_ft=30,
        movement_remaining=30.0,
        traits={"sentinel": {}},
    )
    ally = ActorView(
        actor_id="ally",
        team="party",
        hp=20,
        max_hp=20,
        ac=15,
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
        actors={reactor.actor_id: reactor, ally.actor_id: ally},
        actor_order=[reactor.actor_id, ally.actor_id],
        metadata={},
    )
    window = ReactionWindowView(
        window_id="1:trait:reactor:ally",
        reactor_id=reactor.actor_id,
        round_number=1,
        turn_token="1:ally",
        trigger=ReactionTriggerView(
            kind="trait",
            source_actor_id=ally.actor_id,
            target_actor_id="enemy",
            feature_name="Sentinel",
        ),
        options=(
            ReactionOptionView(
                option_id="reactor:trait:spear",
                action_name="spear",
                fixed_target_ids=(ally.actor_id,),
                legal_target_ids=(ally.actor_id,),
            ),
        ),
    )

    decision = BaseStrategy().decide_reaction(reactor, window, state)
    legacy_decision = build_strategy_reaction_decision_provider(
        state_provider=lambda: state,
        strategy_registry={"party_default": object()},
        actor_strategy_overrides={},
        party_default_strategy="party_default",
        enemy_default_strategy="enemy_default",
    )(window)

    assert decision.choice == "pass"
    assert decision.option_id is None
    assert decision.rationale == {"reason": "avoid_friendly_fire"}
    assert legacy_decision.choice == "pass"
    assert legacy_decision.option_id is None

    counterspell_window = ReactionWindowView(
        window_id="1:counterspell:reactor:ally",
        reactor_id=reactor.actor_id,
        round_number=1,
        turn_token="1:ally",
        trigger=ReactionTriggerView(
            kind="counterspell",
            source_actor_id=ally.actor_id,
            action_name="Arcane Seal",
            spell_level=3,
        ),
        options=(
            ReactionOptionView(
                option_id="reactor:counterspell:slot3",
                action_name="Counterspell",
                fixed_target_ids=(ally.actor_id,),
                legal_target_ids=(ally.actor_id,),
                legal_spell_slot_levels=(3,),
                resource_cost=(("spell_slot_3", 1),),
            ),
        ),
    )
    counterspell_decision = BaseStrategy().decide_reaction(reactor, counterspell_window, state)
    counterspell_legacy = build_strategy_reaction_decision_provider(
        state_provider=lambda: state,
        strategy_registry={"party_default": object()},
        actor_strategy_overrides={},
        party_default_strategy="party_default",
        enemy_default_strategy="enemy_default",
    )(counterspell_window)

    assert counterspell_decision.choice == "pass"
    assert counterspell_legacy.choice == "pass"
