from __future__ import annotations

from dnd_sim.engine_runtime import _arm_pending_smite, _execute_action
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.strategy_api import ReactionDecision, ReactionWindowView


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
        name=actor_id,
        max_hp=30,
        hp=30,
        temp_hp=0,
        ac=10,
        initiative_mod=0,
        str_mod=0,
        dex_mod=0,
        con_mod=0,
        int_mod=0,
        wis_mod=3,
        cha_mod=0,
        save_mods={"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def _melee_attack(name: str, *, tags: list[str] | None = None) -> ActionDefinition:
    return ActionDefinition(
        name=name,
        action_type="attack",
        attack_delivery="melee_weapon_attack",
        action_cost="action",
        target_mode="single_enemy",
        to_hit=100,
        damage="1",
        damage_type="bludgeoning",
        reach_ft=5,
        range_ft=5,
        tags=list(tags or []),
    )


def _on_move_observers() -> tuple[ActorRuntimeState, ActorRuntimeState]:
    listener = _actor("movement_listener", team="party")
    listener.position = (0.0, 20.0, 0.0)
    listener.actions = [
        ActionDefinition(
            name="movement_listener_attack",
            action_type="attack",
            attack_delivery="ranged_weapon_attack",
            action_cost="none",
            event_trigger="on_move",
            target_mode="single_enemy",
            to_hit=100,
            damage="1",
            damage_type="piercing",
            range_ft=120,
        )
    ]

    reactor = _actor("movement_reactor", team="enemy")
    reactor.position = (5.0, 20.0, 0.0)
    reactor.actions = [_melee_attack("reaction_spear")]
    reactor.traits = {
        "battle_reflexes": {
            "name": "Battle Reflexes",
            "source_type": "feat",
            "mechanics": [
                {
                    "effect_type": "reaction_attack",
                    "trigger": "creature_attacks_ally_within_5ft",
                }
            ],
        }
    }
    return listener, reactor


def _execute_and_assert_single_movement_chain(
    *,
    source: ActorRuntimeState,
    target: ActorRuntimeState,
    attack: ActionDefinition,
    expected_position: tuple[float, float, float],
    rng: _SequenceRng,
    strategy_name: str,
) -> None:
    listener, reactor = _on_move_observers()
    actors = {actor.actor_id: actor for actor in (source, target, listener, reactor)}
    damage_dealt = {actor_id: 0 for actor_id in actors}
    damage_taken = {actor_id: 0 for actor_id in actors}
    threat_scores = {actor_id: 0 for actor_id in actors}
    resources_spent = {actor_id: {} for actor_id in actors}
    rule_trace: list[dict] = []
    telemetry: list[dict] = []
    windows: list[ReactionWindowView] = []

    def pass_reaction(window: ReactionWindowView) -> ReactionDecision:
        windows.append(window)
        return ReactionDecision(window_id=window.window_id, choice="pass")

    _execute_action(
        rng=rng,
        actor=source,
        action=attack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        round_number=3,
        turn_token=f"3:{source.actor_id}",
        rule_trace=rule_trace,
        telemetry=telemetry,
        strategy_name=strategy_name,
        reaction_decision_provider=pass_reaction,
    )

    assert target.position == expected_position
    movement_rows = [
        row
        for row in rule_trace
        if row.get("event") == "on_move"
        and row.get("actor_id") == listener.actor_id
        and row.get("action") == listener.actions[0].name
    ]
    assert len(movement_rows) == 1
    assert movement_rows[0]["result"] == "executed"
    assert movement_rows[0]["round"] == 3
    assert movement_rows[0]["turn"] == f"3:{source.actor_id}"

    assert len(windows) == 1
    assert windows[0].trigger.source_actor_id == listener.actor_id
    opened_rows = [
        row
        for row in telemetry
        if row.get("telemetry_type") == "reaction_window_opened"
        and row.get("source_actor_id") == listener.actor_id
    ]
    assert len(opened_rows) == 1
    assert opened_rows[0]["round"] == 3
    assert opened_rows[0]["turn_token"] == f"3:{source.actor_id}"
    assert opened_rows[0]["trigger_action"] == listener.actions[0].name
    assert rng.values == []


def test_open_hand_push_preserves_on_move_context_once() -> None:
    monk = _actor("open_hand_monk", team="party")
    monk.level = 5
    monk.position = (0.0, 0.0, 0.0)
    monk.traits = {"open hand technique": {}}
    target = _actor("open_hand_target", team="enemy")
    target.position = (5.0, 0.0, 0.0)
    attack = _melee_attack(
        "flurry_push",
        tags=["flurry_of_blows", "open_hand_rider:push"],
    )

    _execute_and_assert_single_movement_chain(
        source=monk,
        target=target,
        attack=attack,
        expected_position=(20.0, 0.0, 0.0),
        rng=_SequenceRng([15, 1, 15, 15]),
        strategy_name="open_hand_strategy",
    )


def test_failed_thunderous_smite_save_preserves_on_move_context_once() -> None:
    paladin = _actor("thunderous_paladin", team="party")
    paladin.position = (0.0, 0.0, 0.0)
    target = _actor("thunderous_target", team="enemy")
    target.position = (5.0, 0.0, 0.0)
    thunderous_smite = ActionDefinition(
        name="Thunderous Smite",
        action_type="utility",
        action_cost="bonus",
        target_mode="self",
        save_dc=14,
        save_ability="str",
        mechanics=[
            {
                "effect_type": "push",
                "distance": 10,
                "direction": "away_from_source",
            }
        ],
        tags=["spell", "smite_variant"],
    )
    _arm_pending_smite(paladin, thunderous_smite)

    _execute_and_assert_single_movement_chain(
        source=paladin,
        target=target,
        attack=_melee_attack("warhammer"),
        expected_position=(15.0, 0.0, 0.0),
        rng=_SequenceRng([15, 1, 15, 15]),
        strategy_name="thunderous_strategy",
    )
