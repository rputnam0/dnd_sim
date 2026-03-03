from __future__ import annotations

from dataclasses import dataclass

from dnd_sim.engine import _create_combat_timing_engine, _execute_action
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.rules_2014 import (
    ActionDeclaredEvent,
    AttackResolvedEvent,
    AttackRollEvent,
    CombatEvent,
    CombatTimingEngine,
    DamageResolvedEvent,
    ReactionWindowOpenedEvent,
)


class _SequenceRng:
    def __init__(self, values: list[int]) -> None:
        self._values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self._values:
            raise AssertionError("RNG exhausted")
        return self._values.pop(0)


@dataclass(slots=True)
class _ProbeEvent(CombatEvent):
    marker: str = "probe"


def _base_actor(*, actor_id: str, team: str) -> ActorRuntimeState:
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
        actions=[],
    )


def _execute_basic_attack(
    *,
    rng: _SequenceRng,
    timing_engine: CombatTimingEngine,
    attacker: ActorRuntimeState,
    target: ActorRuntimeState,
) -> None:
    action = ActionDefinition(
        name="basic",
        action_type="attack",
        to_hit=5,
        damage="1d8",
        damage_type="slashing",
    )
    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt = {attacker.actor_id: 0, target.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, target.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, target.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=rng,
        actor=attacker,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        timing_engine=timing_engine,
    )


def test_listener_ordering_is_deterministic() -> None:
    timing_engine = CombatTimingEngine()
    order: list[str] = []

    timing_engine.subscribe(
        _ProbeEvent,
        lambda _event: order.append("beta"),
        priority=10,
        name="beta",
    )
    timing_engine.subscribe(
        _ProbeEvent,
        lambda _event: order.append("alpha"),
        priority=10,
        name="alpha",
    )
    timing_engine.subscribe(
        _ProbeEvent,
        lambda _event: order.append("omega"),
        priority=5,
        name="omega",
    )

    timing_engine.emit(_ProbeEvent())

    assert order == ["alpha", "beta", "omega"]


def test_cancelling_declaration_event_blocks_downstream_resolution() -> None:
    timing_engine = _create_combat_timing_engine()
    attacker = _base_actor(actor_id="attacker", team="party")
    target = _base_actor(actor_id="target", team="enemy")

    observed: list[str] = []

    def _cancel(event: ActionDeclaredEvent) -> None:
        observed.append("declaration")
        event.cancel("test-cancel")

    def _observe_roll(_event: AttackRollEvent) -> None:
        observed.append("roll")

    timing_engine.subscribe(ActionDeclaredEvent, _cancel, priority=999, name="cancel")
    timing_engine.subscribe(AttackRollEvent, _observe_roll, priority=999, name="observe_roll")

    _execute_basic_attack(
        rng=_SequenceRng([15, 4]),
        timing_engine=timing_engine,
        attacker=attacker,
        target=target,
    )

    assert observed == ["declaration"]
    assert target.hp == target.max_hp


def test_attack_flow_emits_declaration_roll_hit_and_damage_in_order() -> None:
    timing_engine = _create_combat_timing_engine()
    attacker = _base_actor(actor_id="attacker", team="party")
    target = _base_actor(actor_id="target", team="enemy")
    target.ac = 10

    observed: list[str] = []

    def _capture(event: CombatEvent) -> None:
        if isinstance(event, ActionDeclaredEvent):
            observed.append("declaration")
        elif isinstance(event, AttackRollEvent):
            observed.append("roll")
        elif isinstance(event, AttackResolvedEvent):
            observed.append("hit" if event.roll.hit else "miss")
        elif isinstance(event, DamageResolvedEvent):
            observed.append("damage")

    timing_engine.subscribe(CombatEvent, _capture, priority=-999, name="capture")

    _execute_basic_attack(
        rng=_SequenceRng([13, 4]),
        timing_engine=timing_engine,
        attacker=attacker,
        target=target,
    )

    assert observed == ["declaration", "roll", "hit", "damage"]


def test_reaction_windows_open_only_when_legal() -> None:
    legal_engine = _create_combat_timing_engine()
    legal_windows: list[str] = []
    legal_engine.subscribe(
        ReactionWindowOpenedEvent,
        lambda event: legal_windows.append(event.window),
        name="capture_windows",
    )

    attacker = _base_actor(actor_id="attacker", team="enemy")
    defender = _base_actor(actor_id="defender", team="party")
    defender.ac = 15
    defender.resources = {"spell_slot_1": 1}
    defender.actions = [
        ActionDefinition(
            name="shield",
            action_type="utility",
            action_cost="reaction",
            tags=["reaction", "shield_spell"],
        )
    ]

    _execute_basic_attack(
        rng=_SequenceRng([12, 4]),
        timing_engine=legal_engine,
        attacker=attacker,
        target=defender,
    )

    assert legal_windows == ["shield"]

    illegal_engine = _create_combat_timing_engine()
    illegal_windows: list[str] = []
    illegal_engine.subscribe(
        ReactionWindowOpenedEvent,
        lambda event: illegal_windows.append(event.window),
        name="capture_windows",
    )

    attacker_crit = _base_actor(actor_id="attacker_crit", team="enemy")
    defender_crit = _base_actor(actor_id="defender_crit", team="party")
    defender_crit.ac = 15
    defender_crit.resources = {"spell_slot_1": 1}
    defender_crit.actions = [
        ActionDefinition(
            name="shield",
            action_type="utility",
            action_cost="reaction",
            tags=["reaction", "shield_spell"],
        )
    ]

    _execute_basic_attack(
        rng=_SequenceRng([20, 4, 4]),
        timing_engine=illegal_engine,
        attacker=attacker_crit,
        target=defender_crit,
    )

    assert illegal_windows == []


def test_removed_listener_no_longer_fires() -> None:
    timing_engine = _create_combat_timing_engine()
    attacker = _base_actor(actor_id="attacker", team="party")
    target = _base_actor(actor_id="target", team="enemy")

    triggered: list[str] = []
    subscription = timing_engine.subscribe(
        ActionDeclaredEvent,
        lambda _event: triggered.append("called"),
        name="probe_listener",
    )

    _execute_basic_attack(
        rng=_SequenceRng([14, 4]),
        timing_engine=timing_engine,
        attacker=attacker,
        target=target,
    )
    assert triggered == ["called"]

    removed = timing_engine.unsubscribe(subscription)
    assert removed is True

    _execute_basic_attack(
        rng=_SequenceRng([14, 4]),
        timing_engine=timing_engine,
        attacker=attacker,
        target=target,
    )
    assert triggered == ["called"]
