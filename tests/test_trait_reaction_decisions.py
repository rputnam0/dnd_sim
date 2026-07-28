from __future__ import annotations

import pytest

from dnd_sim.engine_runtime import (
    _dispatch_combat_event,
    _execute_action,
    _execute_declared_turn_or_error,
    _run_lair_actions,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.reaction_runtime import ReactionDecisionValidationError
from dnd_sim.rules_2014 import ActionDeclaredEvent, CombatTimingEngine
from dnd_sim.spatial import AABB
from dnd_sim.strategy_api import (
    DeclaredAction,
    ReactionDecision,
    ReactionWindowView,
    TargetRef,
    TurnDeclaration,
)


class _NoRollRng:
    def randint(self, _low: int, _high: int) -> int:
        raise AssertionError("reaction pass must not consume RNG")


class _SequenceRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, low: int, high: int) -> int:
        if not self.values:
            raise AssertionError("unexpected RNG consumption")
        value = self.values.pop(0)
        assert low <= value <= high
        return value


def _actor(actor_id: str, *, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id.title(),
        max_hp=30,
        hp=30,
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
    )


def _attack(
    name: str,
    *,
    to_hit: int = 5,
    damage: str = "1",
    attack_count: int = 1,
    resource_cost: dict[str, int] | None = None,
) -> ActionDefinition:
    return ActionDefinition(
        name=name,
        action_type="attack",
        attack_delivery="melee_weapon_attack",
        action_cost="action",
        to_hit=to_hit,
        damage=damage,
        damage_type="slashing",
        attack_count=attack_count,
        reach_ft=5,
        range_ft=5,
        target_mode="single_enemy",
        resource_cost=dict(resource_cost or {}),
    )


def _reaction_trait(
    *,
    name: str = "Battle Reflexes",
    trigger: str = "creature_attacks_ally_within_5ft",
    source_type: str = "subclass",
) -> dict[str, dict]:
    return {
        name.lower().replace(" ", "_"): {
            "name": name,
            "source_type": source_type,
            "mechanics": [
                {
                    "effect_type": "reaction_attack",
                    "trigger": trigger,
                }
            ],
        }
    }


def _dispatch(
    *,
    rng,
    reactor: ActorRuntimeState,
    trigger_actor: ActorRuntimeState,
    trigger_target: ActorRuntimeState,
    trigger_action: ActionDefinition,
    provider,
    telemetry: list[dict] | None = None,
    event: str = "on_hit",
    obstacles: list[AABB] | None = None,
) -> tuple[dict[str, int], dict[str, dict[str, int]], list[dict]]:
    actors = {
        trigger_actor.actor_id: trigger_actor,
        trigger_target.actor_id: trigger_target,
        reactor.actor_id: reactor,
    }
    damage_dealt = {actor_id: 0 for actor_id in actors}
    damage_taken = {actor_id: 0 for actor_id in actors}
    threat_scores = {actor_id: 0 for actor_id in actors}
    resources_spent = {actor_id: {} for actor_id in actors}
    trace: list[dict] = []
    _dispatch_combat_event(
        rng=rng,
        event=event,
        trigger_actor=trigger_actor,
        trigger_target=trigger_target,
        trigger_action=trigger_action,
        actors=actors,
        round_number=2,
        turn_token="2:trigger",
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        obstacles=obstacles,
        rule_trace=trace,
        telemetry=telemetry,
        reaction_decision_provider=provider,
    )
    return damage_dealt, resources_spent, trace


def _sentinel_fixture() -> tuple[
    ActorRuntimeState,
    ActorRuntimeState,
    ActorRuntimeState,
    ActionDefinition,
]:
    reactor = _actor("reactor", team="party")
    attacker = _actor("attacker", team="enemy")
    ally = _actor("ally", team="party")
    reactor.position = (0.0, 0.0, 0.0)
    attacker.position = (5.0, 0.0, 0.0)
    ally.position = (0.0, 5.0, 0.0)
    reactor.traits = _reaction_trait()
    trigger_action = _attack("enemy_slash")
    return reactor, attacker, ally, trigger_action


def test_trait_reaction_pass_is_atomic_and_uses_no_rng() -> None:
    reactor, attacker, ally, trigger_action = _sentinel_fixture()
    reactor.actions = [_attack("spear", resource_cost={"ammo": 1})]
    reactor.resources["ammo"] = 1
    windows: list[ReactionWindowView] = []
    telemetry: list[dict] = []

    def pass_reaction(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _, resources_spent, _ = _dispatch(
        rng=_NoRollRng(),
        reactor=reactor,
        trigger_actor=attacker,
        trigger_target=ally,
        trigger_action=trigger_action,
        provider=pass_reaction,
        telemetry=telemetry,
    )

    assert len(windows) == 1
    assert windows[0].trigger.kind == "trait"
    assert windows[0].trigger.feature_name == "Battle Reflexes"
    assert windows[0].trigger.feature_trigger == "creature_attacks_ally_within_5ft"
    assert reactor.reaction_available is True
    assert reactor.resources["ammo"] == 1
    assert resources_spent[reactor.actor_id] == {}
    assert attacker.hp == attacker.max_hp
    assert [row["telemetry_type"] for row in telemetry] == [
        "reaction_window_opened",
        "reaction_decision",
        "reaction_window_closed",
    ]
    assert telemetry[-1]["status"] == "passed"


def test_trait_reaction_uses_selected_single_attack_and_bookkeeping() -> None:
    reactor, attacker, ally, trigger_action = _sentinel_fixture()
    heavy = _attack("heavy", to_hit=5, damage="5", attack_count=2, resource_cost={"ammo": 1})
    heavy.mechanics = [{"effect_type": "extra_attack", "count": 2}]
    reactor.actions = [
        _attack("accurate", to_hit=10, damage="1"),
        heavy,
    ]
    reactor.resources["ammo"] = 1

    def choose_heavy(window: ReactionWindowView) -> ReactionDecision:
        option = next(option for option in window.options if option.action_name == "heavy")
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=option.option_id,
        )

    damage_dealt, resources_spent, trace = _dispatch(
        rng=_SequenceRng([15]),
        reactor=reactor,
        trigger_actor=attacker,
        trigger_target=ally,
        trigger_action=trigger_action,
        provider=choose_heavy,
    )

    assert attacker.hp == 25
    assert damage_dealt[reactor.actor_id] == 5
    assert reactor.reaction_available is False
    assert reactor.resources["ammo"] == 0
    assert resources_spent[reactor.actor_id] == {"ammo": 1}
    assert reactor.per_action_uses == {"heavy": 1}
    assert reactor.position == (0.0, 0.0, 0.0)
    assert any(row.get("result") == "executed" for row in trace)


def test_trait_reaction_window_requires_range_and_reaction_capability() -> None:
    reactor, attacker, ally, trigger_action = _sentinel_fixture()
    reactor.actions = [_attack("spear")]
    opened: list[ReactionWindowView] = []

    def capture(window: ReactionWindowView) -> ReactionDecision:
        opened.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    attacker.position = (10.0, 0.0, 0.0)
    _dispatch(
        rng=_NoRollRng(),
        reactor=reactor,
        trigger_actor=attacker,
        trigger_target=ally,
        trigger_action=trigger_action,
        provider=capture,
    )
    reactor.conditions.add("incapacitated")
    attacker.position = (5.0, 0.0, 0.0)
    _dispatch(
        rng=_NoRollRng(),
        reactor=reactor,
        trigger_actor=attacker,
        trigger_target=ally,
        trigger_action=trigger_action,
        provider=capture,
    )

    assert opened == []
    assert reactor.reaction_available is True
    assert reactor.position == (0.0, 0.0, 0.0)


def test_trait_reaction_window_excludes_exhausted_limited_attacks() -> None:
    reactor, attacker, ally, trigger_action = _sentinel_fixture()
    limited = _attack("limited")
    limited.max_uses = 1
    reactor.actions = [limited]
    reactor.per_action_uses[limited.name] = 1
    opened: list[ReactionWindowView] = []

    def capture(window: ReactionWindowView) -> ReactionDecision:
        opened.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _dispatch(
        rng=_NoRollRng(),
        reactor=reactor,
        trigger_actor=attacker,
        trigger_target=ally,
        trigger_action=trigger_action,
        provider=capture,
    )

    assert opened == []
    assert reactor.reaction_available is True


def test_trait_reaction_window_excludes_attacks_blocked_by_total_cover() -> None:
    reactor, attacker, ally, trigger_action = _sentinel_fixture()
    reactor.actions = [_attack("spear", resource_cost={"ammo": 1})]
    reactor.resources["ammo"] = 1
    opened: list[ReactionWindowView] = []

    def capture(window: ReactionWindowView) -> ReactionDecision:
        opened.append(window)
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=window.options[0].option_id,
        )

    damage_dealt, resources_spent, trace = _dispatch(
        rng=_NoRollRng(),
        reactor=reactor,
        trigger_actor=attacker,
        trigger_target=ally,
        trigger_action=trigger_action,
        provider=capture,
        obstacles=[
            AABB(
                min_pos=(2.0, -1.0, -1.0),
                max_pos=(3.0, 1.0, 1.0),
                cover_level="TOTAL",
            )
        ],
    )

    assert opened == []
    assert reactor.reaction_available is True
    assert reactor.resources["ammo"] == 1
    assert resources_spent[reactor.actor_id] == {}
    assert attacker.hp == attacker.max_hp
    assert damage_dealt[reactor.actor_id] == 0
    assert any(row.get("reason") == "no_legal_attacks" for row in trace)


@pytest.mark.parametrize(
    ("target_mode", "tags"),
    [
        ("self", []),
        ("single_enemy", ["requires_target_trait:undead"]),
    ],
)
def test_trait_reaction_window_excludes_illegal_fixed_target_attacks(
    target_mode: str,
    tags: list[str],
) -> None:
    reactor, attacker, ally, trigger_action = _sentinel_fixture()
    self_attack = _attack("self_strike", resource_cost={"ammo": 1})
    self_attack.target_mode = target_mode
    self_attack.tags = tags
    reactor.actions = [self_attack]
    reactor.resources["ammo"] = 1
    opened: list[ReactionWindowView] = []

    def capture(window: ReactionWindowView) -> ReactionDecision:
        opened.append(window)
        return ReactionDecision(
            window_id=window.window_id,
            choice="use",
            option_id=window.options[0].option_id,
        )

    damage_dealt, resources_spent, trace = _dispatch(
        rng=_NoRollRng(),
        reactor=reactor,
        trigger_actor=attacker,
        trigger_target=ally,
        trigger_action=trigger_action,
        provider=capture,
    )

    assert opened == []
    assert reactor.reaction_available is True
    assert reactor.resources["ammo"] == 1
    assert resources_spent[reactor.actor_id] == {}
    assert attacker.hp == attacker.max_hp
    assert damage_dealt[reactor.actor_id] == 0
    assert any(row.get("reason") == "no_legal_attacks" for row in trace)


def test_trait_reaction_rejects_stale_decision_before_mutation() -> None:
    reactor, attacker, ally, trigger_action = _sentinel_fixture()
    reactor.actions = [_attack("spear", resource_cost={"ammo": 1})]
    reactor.resources["ammo"] = 1

    def stale(window: ReactionWindowView) -> ReactionDecision:
        return ReactionDecision(
            window_id=f"{window.window_id}:stale",
            choice="use",
            option_id=window.options[0].option_id,
        )

    with pytest.raises(ReactionDecisionValidationError) as exc_info:
        _dispatch(
            rng=_NoRollRng(),
            reactor=reactor,
            trigger_actor=attacker,
            trigger_target=ally,
            trigger_action=trigger_action,
            provider=stale,
        )

    assert exc_info.value.code == "stale_reaction_window"
    assert reactor.reaction_available is True
    assert reactor.resources["ammo"] == 1
    assert attacker.hp == attacker.max_hp


def test_mage_slayer_trait_reaction_requires_caster_within_five_feet() -> None:
    reactor = _actor("reactor", team="party")
    caster = _actor("caster", team="enemy")
    bystander = _actor("bystander", team="party")
    reactor.position = (0.0, 0.0, 0.0)
    caster.position = (5.0, 0.0, 0.0)
    reactor.traits = _reaction_trait(
        name="Mage Slayer",
        trigger="spell_cast_within_5ft",
        source_type="feat",
    )
    reactor.actions = [_attack("sword")]
    spell = ActionDefinition(name="spell", action_type="utility", tags=["spell"])
    windows: list[ReactionWindowView] = []

    def pass_reaction(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _dispatch(
        rng=_NoRollRng(),
        reactor=reactor,
        trigger_actor=caster,
        trigger_target=bystander,
        trigger_action=spell,
        provider=pass_reaction,
        event="after_action",
    )
    caster.position = (10.0, 0.0, 0.0)
    _dispatch(
        rng=_NoRollRng(),
        reactor=reactor,
        trigger_actor=caster,
        trigger_target=bystander,
        trigger_action=spell,
        provider=pass_reaction,
        event="after_action",
    )

    assert len(windows) == 1
    assert windows[0].trigger.feature_name == "Mage Slayer"


def test_top_level_spell_action_dispatches_mage_slayer_window() -> None:
    reactor = _actor("reactor", team="party")
    caster = _actor("caster", team="enemy")
    reactor.position = (0.0, 0.0, 0.0)
    caster.position = (5.0, 0.0, 0.0)
    reactor.traits = _reaction_trait(
        name="Mage Slayer",
        trigger="spell_cast_within_5ft",
        source_type="feat",
    )
    reactor.actions = [_attack("sword")]
    spell = ActionDefinition(
        name="minor_spell",
        action_type="utility",
        target_mode="single_enemy",
        tags=["spell"],
    )
    actors = {reactor.actor_id: reactor, caster.actor_id: caster}
    windows: list[ReactionWindowView] = []

    def pass_reaction(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _execute_action(
        rng=_NoRollRng(),
        actor=caster,
        action=spell,
        targets=[reactor],
        actors=actors,
        damage_dealt={actor_id: 0 for actor_id in actors},
        damage_taken={actor_id: 0 for actor_id in actors},
        threat_scores={actor_id: 0 for actor_id in actors},
        resources_spent={actor_id: {} for actor_id in actors},
        active_hazards=[],
        round_number=1,
        turn_token="1:caster",
        reaction_decision_provider=pass_reaction,
    )

    assert len(windows) == 1
    assert windows[0].trigger.feature_name == "Mage Slayer"
    assert reactor.reaction_available is True


def test_cancelled_top_level_spell_does_not_dispatch_mage_slayer_window() -> None:
    reactor = _actor("reactor", team="party")
    caster = _actor("caster", team="enemy")
    reactor.position = (0.0, 0.0, 0.0)
    caster.position = (5.0, 0.0, 0.0)
    reactor.traits = _reaction_trait(
        name="Mage Slayer",
        trigger="spell_cast_within_5ft",
        source_type="feat",
    )
    reactor.actions = [_attack("sword")]
    spell = ActionDefinition(
        name="cancelled_spell",
        action_type="utility",
        target_mode="single_enemy",
        tags=["spell"],
    )
    actors = {reactor.actor_id: reactor, caster.actor_id: caster}
    timing_engine = CombatTimingEngine()
    timing_engine.subscribe(
        ActionDeclaredEvent,
        lambda event: event.cancel("test cancellation"),
        name="cancel spell",
    )
    windows: list[ReactionWindowView] = []

    def pass_reaction(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _execute_action(
        rng=_NoRollRng(),
        actor=caster,
        action=spell,
        targets=[reactor],
        actors=actors,
        damage_dealt={actor_id: 0 for actor_id in actors},
        damage_taken={actor_id: 0 for actor_id in actors},
        threat_scores={actor_id: 0 for actor_id in actors},
        resources_spent={actor_id: {} for actor_id in actors},
        active_hazards=[],
        round_number=1,
        turn_token="1:caster",
        reaction_decision_provider=pass_reaction,
        timing_engine=timing_engine,
    )

    assert windows == []
    assert caster.next_combat_event_ordinal == 0


def test_component_blocked_top_level_spell_does_not_dispatch_after_action() -> None:
    reactor = _actor("reactor", team="party")
    caster = _actor("caster", team="enemy")
    reactor.position = (0.0, 0.0, 0.0)
    caster.position = (5.0, 0.0, 0.0)
    reactor.traits = _reaction_trait(
        name="Mage Slayer",
        trigger="spell_cast_within_5ft",
        source_type="feat",
    )
    reactor.actions = [_attack("sword")]
    caster.conditions.add("silenced")
    spell = ActionDefinition(
        name="blocked_spell",
        action_type="utility",
        target_mode="single_enemy",
        tags=["spell", "component:verbal"],
    )
    actors = {reactor.actor_id: reactor, caster.actor_id: caster}
    windows: list[ReactionWindowView] = []

    def pass_reaction(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _execute_action(
        rng=_NoRollRng(),
        actor=caster,
        action=spell,
        targets=[reactor],
        actors=actors,
        damage_dealt={actor_id: 0 for actor_id in actors},
        damage_taken={actor_id: 0 for actor_id in actors},
        threat_scores={actor_id: 0 for actor_id in actors},
        resources_spent={actor_id: {} for actor_id in actors},
        active_hazards=[],
        round_number=1,
        turn_token="1:caster",
        reaction_decision_provider=pass_reaction,
    )

    assert windows == []
    assert caster.next_combat_event_ordinal == 0


def test_countered_top_level_spell_dispatches_one_mage_slayer_cast_hook() -> None:
    mage_slayer = _actor("mage_slayer", team="party")
    counterspeller = _actor("counterspeller", team="party")
    caster = _actor("caster", team="enemy")
    mage_slayer.position = (5.0, 0.0, 0.0)
    counterspeller.position = (30.0, 0.0, 0.0)
    caster.position = (0.0, 0.0, 0.0)
    mage_slayer.traits = _reaction_trait(
        name="Mage Slayer",
        trigger="spell_cast_within_5ft",
        source_type="feat",
    )
    mage_slayer.actions = [_attack("sword")]
    counterspeller.actions = [
        ActionDefinition(
            name="Counterspell",
            action_type="utility",
            action_cost="reaction",
            target_mode="single_creature",
            range_ft=60,
            tags=["spell", "counterspell", "component:somatic"],
        )
    ]
    counterspeller.resources = {"spell_slot_3": 1}
    spell = ActionDefinition(
        name="countered_spell",
        action_type="utility",
        target_mode="single_enemy",
        effects=[
            {
                "effect_type": "apply_condition",
                "condition": "spell_resolved",
                "target": "target",
            }
        ],
        tags=["spell", "component:verbal", "component:somatic"],
    )
    actors = {
        mage_slayer.actor_id: mage_slayer,
        counterspeller.actor_id: counterspeller,
        caster.actor_id: caster,
    }
    windows: list[ReactionWindowView] = []

    def choose_counterspell_then_pass(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        if window.trigger.kind == "counterspell":
            option = window.options[0]
            return ReactionDecision(
                window_id=window.window_id,
                choice="use",
                option_id=option.option_id,
                spell_slot_level=option.legal_spell_slot_levels[0],
            )
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _execute_action(
        rng=_NoRollRng(),
        actor=caster,
        action=spell,
        targets=[mage_slayer],
        actors=actors,
        damage_dealt={actor_id: 0 for actor_id in actors},
        damage_taken={actor_id: 0 for actor_id in actors},
        threat_scores={actor_id: 0 for actor_id in actors},
        resources_spent={actor_id: {} for actor_id in actors},
        active_hazards=[],
        round_number=1,
        turn_token="1:caster",
        reaction_decision_provider=choose_counterspell_then_pass,
    )

    mage_slayer_windows = [
        window for window in windows if window.trigger.feature_name == "Mage Slayer"
    ]
    assert "spell_resolved" not in mage_slayer.conditions
    assert len(mage_slayer_windows) == 1
    assert caster.next_combat_event_ordinal == 1


def test_lair_spell_routes_mage_slayer_window_to_provider() -> None:
    reactor = _actor("reactor", team="party")
    caster = _actor("caster", team="enemy")
    reactor.position = (0.0, 0.0, 0.0)
    caster.position = (5.0, 0.0, 0.0)
    reactor.traits = _reaction_trait(
        name="Mage Slayer",
        trigger="spell_cast_within_5ft",
        source_type="feat",
    )
    reactor.actions = [_attack("sword")]
    caster.actions = [
        ActionDefinition(
            name="lair_spell",
            action_type="utility",
            action_cost="lair",
            target_mode="single_enemy",
            tags=["spell"],
        )
    ]
    actors = {reactor.actor_id: reactor, caster.actor_id: caster}
    windows: list[ReactionWindowView] = []

    def pass_reaction(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _run_lair_actions(
        rng=_NoRollRng(),
        actors=actors,
        damage_dealt={actor_id: 0 for actor_id in actors},
        damage_taken={actor_id: 0 for actor_id in actors},
        threat_scores={actor_id: 0 for actor_id in actors},
        resources_spent={actor_id: {} for actor_id in actors},
        active_hazards=[],
        round_number=1,
        reaction_decision_provider=pass_reaction,
    )

    assert len(windows) == 1
    assert windows[0].trigger.feature_name == "Mage Slayer"
    assert reactor.reaction_available is True


def test_trait_reaction_does_not_trigger_from_reactor_own_action() -> None:
    reactor, _attacker, ally, trigger_action = _sentinel_fixture()
    reactor.actions = [_attack("spear")]
    opened: list[ReactionWindowView] = []

    def capture(window: ReactionWindowView) -> ReactionDecision:
        opened.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _dispatch(
        rng=_NoRollRng(),
        reactor=reactor,
        trigger_actor=reactor,
        trigger_target=ally,
        trigger_action=trigger_action,
        provider=capture,
    )

    assert opened == []


def test_default_trait_reaction_policy_avoids_friendly_fire() -> None:
    reactor = _actor("reactor", team="party")
    friendly_attacker = _actor("friendly_attacker", team="party")
    enemy_target = _actor("enemy_target", team="enemy")
    reactor.position = (0.0, 0.0, 0.0)
    friendly_attacker.position = (5.0, 0.0, 0.0)
    reactor.traits = _reaction_trait(name="Sentinel", source_type="feat")
    reactor.actions = [_attack("spear")]

    _, _, trace = _dispatch(
        rng=_NoRollRng(),
        reactor=reactor,
        trigger_actor=friendly_attacker,
        trigger_target=enemy_target,
        trigger_action=_attack("friendly_slash"),
        provider=None,
    )

    assert reactor.reaction_available is True
    assert friendly_attacker.hp == friendly_attacker.max_hp
    assert any(row.get("result") == "passed" for row in trace)


def test_generic_ally_attack_trigger_preserves_team_semantics() -> None:
    reactor = _actor("reactor", team="party")
    friendly_attacker = _actor("friendly_attacker", team="party")
    enemy_target = _actor("enemy_target", team="enemy")
    reactor.position = (0.0, 0.0, 0.0)
    friendly_attacker.position = (5.0, 0.0, 0.0)
    reactor.traits = _reaction_trait()
    reactor.actions = [_attack("spear")]
    opened: list[ReactionWindowView] = []

    def capture(window: ReactionWindowView) -> ReactionDecision:
        opened.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _dispatch(
        rng=_NoRollRng(),
        reactor=reactor,
        trigger_actor=friendly_attacker,
        trigger_target=enemy_target,
        trigger_action=_attack("friendly_slash"),
        provider=capture,
    )

    assert opened == []


def test_trait_reaction_does_not_retarget_when_trigger_actor_is_downed() -> None:
    reactor, attacker, ally, trigger_action = _sentinel_fixture()
    bystander = _actor("bystander", team="enemy")
    reactor.actions = [_attack("spear")]
    attacker.hp = 0
    opened: list[ReactionWindowView] = []

    def capture(window: ReactionWindowView) -> ReactionDecision:
        opened.append(window)
        return ReactionDecision(
            window_id=window.window_id, choice="use", option_id=window.options[0].option_id
        )

    actors = {
        reactor.actor_id: reactor,
        attacker.actor_id: attacker,
        ally.actor_id: ally,
        bystander.actor_id: bystander,
    }
    damage_dealt = {actor_id: 0 for actor_id in actors}
    _dispatch_combat_event(
        rng=_NoRollRng(),
        event="on_hit",
        trigger_actor=attacker,
        trigger_target=ally,
        trigger_action=trigger_action,
        actors=actors,
        round_number=2,
        turn_token="2:attacker",
        damage_dealt=damage_dealt,
        damage_taken={actor_id: 0 for actor_id in actors},
        threat_scores={actor_id: 0 for actor_id in actors},
        resources_spent={actor_id: {} for actor_id in actors},
        active_hazards=[],
        reaction_decision_provider=capture,
    )

    assert opened == []
    assert bystander.hp == bystander.max_hp
    assert damage_dealt[reactor.actor_id] == 0


def test_hit_triggered_trait_reaction_opens_only_after_a_melee_hit() -> None:
    reactor = _actor("reactor", team="party")
    attacker = _actor("attacker", team="enemy")
    reactor.position = (0.0, 0.0, 0.0)
    attacker.position = (5.0, 0.0, 0.0)
    reactor.traits = _reaction_trait(
        name="Zhentarim Tactics",
        trigger="hit_by_melee_attack_within_5ft",
        source_type="feat",
    )
    reactor.actions = [_attack("riposte")]
    attack = _attack("slash", attack_count=2)
    attacker.actions = [attack]
    actors = {reactor.actor_id: reactor, attacker.actor_id: attacker}
    windows: list[ReactionWindowView] = []

    def pass_reaction(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    declaration = TurnDeclaration(
        action=DeclaredAction(
            action_name=attack.name,
            targets=[TargetRef(reactor.actor_id)],
        )
    )
    rng = _SequenceRng([10, 10])
    _execute_declared_turn_or_error(
        rng=rng,
        actor=attacker,
        declaration=declaration,
        strategy_name="attacker_strategy",
        actors=actors,
        damage_dealt={actor_id: 0 for actor_id in actors},
        damage_taken={actor_id: 0 for actor_id in actors},
        threat_scores={actor_id: 0 for actor_id in actors},
        resources_spent={actor_id: {} for actor_id in actors},
        active_hazards=[],
        round_number=1,
        turn_token="1:attacker",
        reaction_decision_provider=pass_reaction,
    )

    assert len(windows) == 2
    assert len({window.window_id for window in windows}) == 2
    assert windows[0].trigger.feature_trigger == "hit_by_melee_attack_within_5ft"
    assert windows[0].trigger.target_actor_id == reactor.actor_id
    assert rng.values == []


def test_declared_action_routes_trait_reaction_to_decision_provider() -> None:
    reactor, attacker, ally, trigger_action = _sentinel_fixture()
    trigger_action.attack_count = 2
    reactor.actions = [_attack("spear")]
    attacker.actions = [trigger_action]
    windows: list[ReactionWindowView] = []
    telemetry: list[dict] = []
    actors = {
        reactor.actor_id: reactor,
        attacker.actor_id: attacker,
        ally.actor_id: ally,
    }

    def pass_reaction(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    declaration = TurnDeclaration(
        action=DeclaredAction(
            action_name=trigger_action.name,
            targets=[TargetRef(ally.actor_id)],
        )
    )
    rng = _SequenceRng([10, 10])
    _execute_declared_turn_or_error(
        rng=rng,
        actor=attacker,
        declaration=declaration,
        strategy_name="attacker_strategy",
        actors=actors,
        damage_dealt={actor_id: 0 for actor_id in actors},
        damage_taken={actor_id: 0 for actor_id in actors},
        threat_scores={actor_id: 0 for actor_id in actors},
        resources_spent={actor_id: {} for actor_id in actors},
        active_hazards=[],
        telemetry=telemetry,
        round_number=1,
        turn_token="1:attacker",
        reaction_decision_provider=pass_reaction,
    )

    assert len(windows) == 2
    assert len({window.window_id for window in windows}) == 2
    assert windows[0].trigger.kind == "trait"
    assert windows[0].trigger.action_name == trigger_action.name
    assert windows[0].trigger.target_actor_id == ally.actor_id
    assert reactor.reaction_available is True
    assert rng.values == []
    assert any(
        row.get("telemetry_type") == "reaction_window_closed" and row.get("status") == "passed"
        for row in telemetry
    )


def test_trait_reaction_can_interrupt_remaining_multiattack_instances() -> None:
    reactor, attacker, ally, trigger_action = _sentinel_fixture()
    reactor.actions = [_attack("spear", to_hit=100, damage="1")]
    trigger_action.to_hit = 100
    trigger_action.attack_count = 2
    attacker.actions = [trigger_action]
    attacker.hp = 1
    actors = {
        reactor.actor_id: reactor,
        attacker.actor_id: attacker,
        ally.actor_id: ally,
    }
    rng = _SequenceRng([10, 10])

    _execute_declared_turn_or_error(
        rng=rng,
        actor=attacker,
        declaration=TurnDeclaration(
            action=DeclaredAction(
                action_name=trigger_action.name,
                targets=[TargetRef(ally.actor_id)],
            )
        ),
        strategy_name="attacker_strategy",
        actors=actors,
        damage_dealt={actor_id: 0 for actor_id in actors},
        damage_taken={actor_id: 0 for actor_id in actors},
        threat_scores={actor_id: 0 for actor_id in actors},
        resources_spent={actor_id: {} for actor_id in actors},
        active_hazards=[],
        round_number=1,
        turn_token="1:attacker",
    )

    assert ally.hp == ally.max_hp - 1
    assert attacker.hp == 0
    assert reactor.reaction_available is False
    assert rng.values == []


def test_repeated_attack_sequences_have_unique_trait_window_ids() -> None:
    reactor, attacker, ally, _trigger_action = _sentinel_fixture()
    reactor.actions = [_attack("spear")]
    claw = _attack("claw", to_hit=100)
    multiattack = ActionDefinition(
        name="multiattack",
        action_type="attack",
        action_cost="action",
        target_mode="single_enemy",
        mechanics=[
            {
                "effect_type": "attack_sequence",
                "sequence": [{"action_name": claw.name, "count": 2}],
            }
        ],
    )
    attacker.actions = [multiattack, claw]
    actors = {
        reactor.actor_id: reactor,
        attacker.actor_id: attacker,
        ally.actor_id: ally,
    }
    windows: list[ReactionWindowView] = []

    def pass_reaction(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    declaration = TurnDeclaration(
        action=DeclaredAction(
            action_name=multiattack.name,
            targets=[TargetRef(ally.actor_id)],
        )
    )
    rng = _SequenceRng([10, 10, 10, 10])
    for _ in range(2):
        _execute_declared_turn_or_error(
            rng=rng,
            actor=attacker,
            declaration=declaration,
            strategy_name="attacker_strategy",
            actors=actors,
            damage_dealt={actor_id: 0 for actor_id in actors},
            damage_taken={actor_id: 0 for actor_id in actors},
            threat_scores={actor_id: 0 for actor_id in actors},
            resources_spent={actor_id: {} for actor_id in actors},
            active_hazards=[],
            round_number=1,
            turn_token="1:attacker",
            reaction_decision_provider=pass_reaction,
        )

    assert len(windows) == 4
    assert len({window.window_id for window in windows}) == 4
    assert rng.values == []


def test_different_root_actions_have_unique_trait_window_ids() -> None:
    reactor, attacker, ally, _trigger_action = _sentinel_fixture()
    reactor.actions = [_attack("spear")]
    claw = _attack("claw", to_hit=100)

    def root_action(name: str) -> ActionDefinition:
        return ActionDefinition(
            name=name,
            action_type="attack",
            action_cost="action",
            target_mode="single_enemy",
            mechanics=[
                {
                    "effect_type": "attack_sequence",
                    "sequence": [{"action_name": claw.name, "count": 1}],
                }
            ],
        )

    multiattack_a = root_action("multiattack_a")
    multiattack_b = root_action("multiattack_b")
    attacker.actions = [multiattack_a, multiattack_b, claw]
    actors = {
        reactor.actor_id: reactor,
        attacker.actor_id: attacker,
        ally.actor_id: ally,
    }
    windows: list[ReactionWindowView] = []

    def pass_reaction(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    rng = _SequenceRng([10, 10])
    for action in (multiattack_a, multiattack_b):
        _execute_declared_turn_or_error(
            rng=rng,
            actor=attacker,
            declaration=TurnDeclaration(
                action=DeclaredAction(
                    action_name=action.name,
                    targets=[TargetRef(ally.actor_id)],
                )
            ),
            strategy_name="attacker_strategy",
            actors=actors,
            damage_dealt={actor_id: 0 for actor_id in actors},
            damage_taken={actor_id: 0 for actor_id in actors},
            threat_scores={actor_id: 0 for actor_id in actors},
            resources_spent={actor_id: {} for actor_id in actors},
            active_hazards=[],
            round_number=1,
            turn_token="1:attacker",
            reaction_decision_provider=pass_reaction,
        )

    assert len(windows) == 2
    assert len({window.window_id for window in windows}) == 2
    assert rng.values == []


def test_direct_action_calls_allocate_unique_trait_window_ids() -> None:
    reactor, attacker, ally, _trigger_action = _sentinel_fixture()
    reactor.actions = [_attack("spear")]
    claw = _attack("claw", to_hit=100)
    attacker.actions = [claw]
    actors = {
        reactor.actor_id: reactor,
        attacker.actor_id: attacker,
        ally.actor_id: ally,
    }
    windows: list[ReactionWindowView] = []

    def pass_reaction(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    rng = _SequenceRng([10, 10, 10])
    for turn_token in ("1:attacker", "2:attacker", "1:attacker"):
        _execute_action(
            rng=rng,
            actor=attacker,
            action=claw,
            targets=[ally],
            actors=actors,
            damage_dealt={actor_id: 0 for actor_id in actors},
            damage_taken={actor_id: 0 for actor_id in actors},
            threat_scores={actor_id: 0 for actor_id in actors},
            resources_spent={actor_id: {} for actor_id in actors},
            active_hazards=[],
            round_number=int(turn_token.split(":", maxsplit=1)[0]),
            turn_token=turn_token,
            reaction_decision_provider=pass_reaction,
        )

    assert len(windows) == 3
    assert len({window.window_id for window in windows}) == 3
    assert rng.values == []


def test_normalized_trait_hook_collisions_allocate_distinct_window_and_option_ids() -> None:
    reactor, attacker, ally, trigger_action = _sentinel_fixture()
    reactor.actions = [_attack("spear")]

    def trait_payload(name: str) -> dict:
        return {
            "name": name,
            "source_type": "feat",
            "mechanics": [
                {
                    "effect_type": "reaction_attack",
                    "trigger": "creature_attacks_ally_within_5ft",
                }
            ],
        }

    reactor.traits = {
        "echo-guard": trait_payload("Echo Guard (hyphen)"),
        "echo guard": trait_payload("Echo Guard (space)"),
    }
    windows: list[ReactionWindowView] = []

    def pass_reaction(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _dispatch(
        rng=_NoRollRng(),
        reactor=reactor,
        trigger_actor=attacker,
        trigger_target=ally,
        trigger_action=trigger_action,
        provider=pass_reaction,
    )

    assert len(windows) == 2
    assert len({window.window_id for window in windows}) == 2
    assert len({window.options[0].option_id for window in windows}) == 2


def test_trait_reaction_ids_do_not_collide_across_delimited_actor_and_action_ids() -> None:
    reactor = _actor("reactor", team="party")
    ally = _actor("ally", team="party")
    left_attacker = _actor("enemy:x", team="enemy")
    right_attacker = _actor("enemy", team="enemy")
    reactor.position = (0.0, 0.0, 0.0)
    ally.position = (0.0, 5.0, 0.0)
    left_attacker.position = (5.0, 0.0, 0.0)
    right_attacker.position = (5.0, 0.0, 0.0)
    reactor.actions = [_attack("spear:guard")]
    reactor.traits = _reaction_trait()
    windows: list[ReactionWindowView] = []

    def pass_reaction(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    for attacker, trigger_action in (
        (left_attacker, _attack("y")),
        (right_attacker, _attack("x:y")),
    ):
        _dispatch(
            rng=_NoRollRng(),
            reactor=reactor,
            trigger_actor=attacker,
            trigger_target=ally,
            trigger_action=trigger_action,
            provider=pass_reaction,
        )

    assert len(windows) == 2
    assert windows[0].trigger.source_actor_id != windows[1].trigger.source_actor_id
    assert windows[0].options[0].fixed_target_ids != windows[1].options[0].fixed_target_ids
    assert len({window.window_id for window in windows}) == 2
    assert len({window.options[0].option_id for window in windows}) == 2


@pytest.mark.parametrize("effect_type", ["forced_movement", "push"])
def test_forced_movement_event_preserves_nested_reaction_provider(effect_type: str) -> None:
    pusher = _actor("pusher", team="enemy")
    mover = _actor("mover", team="party")
    event_attacker = _actor("event_attacker", team="enemy")
    reactor = _actor("reactor", team="party")
    pusher.position = (0.0, 0.0, 0.0)
    mover.position = (5.0, 0.0, 0.0)
    event_attacker.position = (5.0, 5.0, 0.0)
    reactor.position = (0.0, 5.0, 0.0)
    reactor.traits = _reaction_trait()
    reactor.actions = [_attack("spear")]
    triggered_attack = _attack("movement_strike", to_hit=100)
    triggered_attack.event_trigger = "on_move"
    event_attacker.actions = [triggered_attack]
    shove = ActionDefinition(
        name="telekinetic_push",
        action_type="utility",
        target_mode="single_enemy",
        effects=[
            {
                "effect_type": effect_type,
                "target": "target",
                "distance_ft": 5,
                "direction": "away_from_source",
            }
        ],
    )
    actors = {
        pusher.actor_id: pusher,
        mover.actor_id: mover,
        event_attacker.actor_id: event_attacker,
        reactor.actor_id: reactor,
    }
    windows: list[ReactionWindowView] = []

    def pass_reaction(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    rng = _SequenceRng([10])
    _execute_action(
        rng=rng,
        actor=pusher,
        action=shove,
        targets=[mover],
        actors=actors,
        damage_dealt={actor_id: 0 for actor_id in actors},
        damage_taken={actor_id: 0 for actor_id in actors},
        threat_scores={actor_id: 0 for actor_id in actors},
        resources_spent={actor_id: {} for actor_id in actors},
        active_hazards=[],
        round_number=1,
        turn_token="1:pusher",
        reaction_decision_provider=pass_reaction,
    )

    assert len(windows) == 1
    assert windows[0].trigger.source_actor_id == event_attacker.actor_id
    assert reactor.reaction_available is True
    assert mover.hp == mover.max_hp - 1
    assert rng.values == []


def test_shove_event_preserves_nested_reaction_provider(monkeypatch) -> None:
    monkeypatch.setattr("dnd_sim.rules_2014.run_contested_check", lambda *_args: True)
    pusher = _actor("pusher", team="enemy")
    mover = _actor("mover", team="party")
    event_attacker = _actor("event_attacker", team="enemy")
    reactor = _actor("reactor", team="party")
    pusher.position = (0.0, 0.0, 0.0)
    mover.position = (5.0, 0.0, 0.0)
    event_attacker.position = (5.0, 5.0, 0.0)
    reactor.position = (0.0, 5.0, 0.0)
    reactor.traits = _reaction_trait()
    reactor.actions = [_attack("spear")]
    triggered_attack = _attack("movement_strike", to_hit=100)
    triggered_attack.event_trigger = "on_move"
    event_attacker.actions = [triggered_attack]
    shove = ActionDefinition(
        name="shove",
        action_type="shove",
        action_cost="action",
        target_mode="single_enemy",
        tags=["shove_mode:push"],
    )
    actors = {
        pusher.actor_id: pusher,
        mover.actor_id: mover,
        event_attacker.actor_id: event_attacker,
        reactor.actor_id: reactor,
    }
    windows: list[ReactionWindowView] = []

    def pass_reaction(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    rng = _SequenceRng([10])
    _execute_action(
        rng=rng,
        actor=pusher,
        action=shove,
        targets=[mover],
        actors=actors,
        damage_dealt={actor_id: 0 for actor_id in actors},
        damage_taken={actor_id: 0 for actor_id in actors},
        threat_scores={actor_id: 0 for actor_id in actors},
        resources_spent={actor_id: {} for actor_id in actors},
        active_hazards=[],
        round_number=1,
        turn_token="1:pusher",
        reaction_decision_provider=pass_reaction,
    )

    assert len(windows) == 1
    assert windows[0].trigger.source_actor_id == event_attacker.actor_id
    assert reactor.reaction_available is True
    assert mover.position == (10.0, 0.0, 0.0)
    assert mover.hp == mover.max_hp - 1
    assert rng.values == []
