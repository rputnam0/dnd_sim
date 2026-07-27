from __future__ import annotations

from typing import Any

from dnd_sim.engine_runtime import _bundled_attack_damage_effects, _execute_action
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.rules_2014 import CombatTimingEngine, DamageResolvedEvent


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
        save_mods={"str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0},
        actions=[],
        uses_death_saves=False,
    )


def _attack(
    *,
    damage: str | None = "1",
    effects: list[dict[str, Any]] | None = None,
    mechanics: list[dict[str, Any]] | None = None,
    attack_count: int = 1,
) -> ActionDefinition:
    return ActionDefinition(
        name="test_strike",
        action_type="attack",
        attack_delivery="melee_weapon_attack",
        to_hit=5,
        damage=damage,
        damage_type="slashing",
        attack_count=attack_count,
        effects=list(effects or []),
        mechanics=list(mechanics or []),
    )


def _execute(
    *,
    rng: _SequenceRng,
    action: ActionDefinition,
    actor: ActorRuntimeState | None = None,
    target: ActorRuntimeState | None = None,
    zero_hp_intent: str = "normal",
    timing_engine: CombatTimingEngine | None = None,
    telemetry: list[dict[str, Any]] | None = None,
) -> tuple[ActorRuntimeState, ActorRuntimeState, dict[str, int], dict[str, int]]:
    actor = actor or _actor("attacker", team="party")
    target = target or _actor("target", team="enemy")
    actor.actions = [action]
    actors = {actor.actor_id: actor, target.actor_id: target}
    damage_dealt = {actor.actor_id: 0, target.actor_id: 0}
    damage_taken = {actor.actor_id: 0, target.actor_id: 0}
    threat_scores = {actor.actor_id: 0, target.actor_id: 0}
    resources_spent = {actor.actor_id: {}, target.actor_id: {}}

    _execute_action(
        rng=rng,
        actor=actor,
        action=action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        timing_engine=timing_engine,
        telemetry=telemetry,
        zero_hp_intent=zero_hp_intent,
    )
    return actor, target, damage_dealt, damage_taken


def test_small_immediate_rider_does_not_kill_a_knocked_out_target() -> None:
    action = _attack(
        effects=[
            {
                "effect_type": "damage",
                "apply_on": "hit",
                "target": "target",
                "damage": "1",
                "damage_type": "fire",
            }
        ]
    )
    target = _actor("target", team="enemy", hp=1, max_hp=10)
    rng = _SequenceRng([15, 3])

    _, target, damage_dealt, _ = _execute(
        rng=rng,
        action=action,
        target=target,
        zero_hp_intent="knock_out",
    )

    assert target.hp == 0
    assert target.stable is True
    assert target.dead is False
    assert target.stable_recovery_hours_remaining == 3
    assert damage_dealt["attacker"] == 2
    assert rng.values == []


def test_combined_immediate_damage_checks_massive_death_before_recovery_rng() -> None:
    action = _attack(
        effects=[
            {
                "effect_type": "damage",
                "apply_on": "hit",
                "target": "target",
                "damage": "10",
                "damage_type": "fire",
            }
        ]
    )
    target = _actor("target", team="enemy", hp=1, max_hp=10)
    rng = _SequenceRng([15])

    _, target, damage_dealt, _ = _execute(
        rng=rng,
        action=action,
        target=target,
        zero_hp_intent="knock_out",
    )

    assert target.hp == 0
    assert target.stable is False
    assert target.dead is True
    assert damage_dealt["attacker"] == 11
    assert rng.values == []


def test_damage_event_contains_base_and_rider_packets_with_per_type_mitigation() -> None:
    action = _attack(
        effects=[
            {
                "effect_type": "damage",
                "apply_on": "hit",
                "target": "target",
                "damage": "4",
                "damage_type": "fire",
            }
        ]
    )
    target = _actor("target", team="enemy")
    target.damage_resistances = {"fire"}
    timing_engine = CombatTimingEngine()
    resolved_events: list[DamageResolvedEvent] = []
    timing_engine.subscribe(
        DamageResolvedEvent,
        resolved_events.append,
        name="capture_unified_damage",
    )
    telemetry: list[dict[str, Any]] = []

    _, target, damage_dealt, _ = _execute(
        rng=_SequenceRng([15]),
        action=action,
        target=target,
        timing_engine=timing_engine,
        telemetry=telemetry,
    )

    assert target.hp == 17
    assert damage_dealt["attacker"] == 3
    assert len(resolved_events) == 1
    event = resolved_events[0]
    assert event.raw_damage == 5
    assert event.applied_damage == 3
    assert event.bundle is not None
    assert [packet.source for packet in event.bundle.packets] == [
        "attack",
        "effect:effects:0",
    ]
    assert event.resolution is not None
    assert [packet.applied_amount for packet in event.resolution.packets] == [1, 2]
    assert any(
        row.get("telemetry_type") == "effect_contribution"
        and row.get("source_bucket") == "effects"
        and row.get("effect_index") == 0
        and row.get("applied_amount") == 2
        for row in telemetry
    )


def test_hit_damage_rider_dice_expand_on_a_critical_hit() -> None:
    action = _attack(
        effects=[
            {
                "effect_type": "damage",
                "apply_on": "hit",
                "target": "target",
                "damage": "1d4",
                "damage_type": "fire",
            }
        ]
    )
    rng = _SequenceRng([20, 2, 3])

    _, target, damage_dealt, _ = _execute(rng=rng, action=action)

    assert target.hp == 14
    assert damage_dealt["attacker"] == 6
    assert rng.values == []


def test_effect_only_hit_damage_uses_the_same_knockout_disposition() -> None:
    action = _attack(
        damage=None,
        effects=[
            {
                "effect_type": "damage",
                "apply_on": "hit",
                "target": "target",
                "damage": "3",
                "damage_type": "force",
            }
        ],
    )
    target = _actor("target", team="enemy", hp=3, max_hp=10)
    rng = _SequenceRng([15, 2])

    _, target, damage_dealt, _ = _execute(
        rng=rng,
        action=action,
        target=target,
        zero_hp_intent="knock_out",
    )

    assert target.hp == 0
    assert target.stable is True
    assert target.dead is False
    assert target.stable_recovery_hours_remaining == 2
    assert damage_dealt["attacker"] == 3
    assert rng.values == []


def test_once_per_action_rider_is_bundled_only_once_across_multiattack() -> None:
    action = _attack(
        attack_count=2,
        effects=[
            {
                "effect_type": "damage",
                "apply_on": "hit",
                "target": "target",
                "damage": "2",
                "damage_type": "fire",
                "once_per_action": True,
            }
        ],
    )

    _, target, damage_dealt, _ = _execute(
        rng=_SequenceRng([15, 15]),
        action=action,
    )

    assert target.hp == 16
    assert damage_dealt["attacker"] == 4


def test_attack_damage_seeds_effect_context_for_life_drain_healing() -> None:
    action = _attack(
        damage="4",
        effects=[
            {
                "effect_type": "heal",
                "apply_on": "hit",
                "target": "source",
                "amount": "last_damage_applied",
            }
        ],
    )
    attacker = _actor("attacker", team="party", hp=5, max_hp=10)

    attacker, target, _, _ = _execute(
        rng=_SequenceRng([15]),
        action=action,
        actor=attacker,
    )

    assert target.hp == 16
    assert attacker.hp == 9


def test_ordered_rider_updates_life_drain_context_to_its_applied_damage() -> None:
    action = _attack(
        damage="4",
        effects=[
            {
                "effect_type": "damage",
                "apply_on": "hit",
                "target": "target",
                "damage": "2",
                "damage_type": "necrotic",
            },
            {
                "effect_type": "heal",
                "apply_on": "hit",
                "target": "source",
                "amount": "last_damage_applied",
            },
        ],
    )
    attacker = _actor("attacker", team="party", hp=1, max_hp=10)

    attacker, target, _, _ = _execute(
        rng=_SequenceRng([15]),
        action=action,
        actor=attacker,
    )

    assert target.hp == 14
    assert attacker.hp == 3


def test_mechanics_bucket_hit_damage_is_included_in_the_attack_bundle() -> None:
    action = _attack(
        mechanics=[
            {
                "effect_type": "damage",
                "apply_on": "hit",
                "target": "target",
                "damage": "4",
                "damage_type": "cold",
            }
        ]
    )
    timing_engine = CombatTimingEngine()
    resolved_events: list[DamageResolvedEvent] = []
    timing_engine.subscribe(
        DamageResolvedEvent,
        resolved_events.append,
        name="capture_mechanics_damage",
    )

    _, target, damage_dealt, _ = _execute(
        rng=_SequenceRng([15]),
        action=action,
        timing_engine=timing_engine,
    )

    assert target.hp == 15
    assert damage_dealt["attacker"] == 5
    assert len(resolved_events) == 1
    assert resolved_events[0].bundle is not None
    assert [packet.source for packet in resolved_events[0].bundle.packets] == [
        "attack",
        "effect:mechanics:0",
    ]


def test_bundle_selector_excludes_saved_delayed_and_non_direct_damage() -> None:
    action = _attack(
        mechanics=[
            {
                "effect_type": "damage",
                "apply_on": "hit",
                "damage": "1",
                "save_dc": 10,
                "save_ability": "con",
            },
            {
                "effect_type": "damage",
                "apply_on": "hit",
                "damage": "1",
                "timing_round_end": True,
            },
            {
                "effect_type": "damage",
                "apply_on": "hit",
                "target": "source",
                "damage": "1",
            },
            {
                "effect_type": "damage",
                "apply_on": "hit",
                "target": "all_enemies",
                "damage": "1",
            },
            {
                "effect_type": "damage",
                "apply_on": "hit",
                "target": "target",
                "damage": "1",
            },
        ]
    )

    bundled = _bundled_attack_damage_effects(
        action,
        event="hit",
        once_per_action_used=set(),
    )

    assert [effect.effect_index for effect in bundled] == [4]


def test_always_damage_remains_a_separate_effect_and_applies_on_a_miss() -> None:
    action = _attack(
        effects=[
            {
                "effect_type": "damage",
                "apply_on": "always",
                "target": "target",
                "damage": "3",
                "damage_type": "force",
            }
        ]
    )
    target = _actor("target", team="enemy")
    target.ac = 30
    timing_engine = CombatTimingEngine()
    resolved_events: list[DamageResolvedEvent] = []
    timing_engine.subscribe(
        DamageResolvedEvent,
        resolved_events.append,
        name="capture_always_damage",
    )

    _, target, damage_dealt, _ = _execute(
        rng=_SequenceRng([2]),
        action=action,
        target=target,
        timing_engine=timing_engine,
    )

    assert target.hp == 17
    assert damage_dealt["attacker"] == 3
    assert resolved_events == []


def test_source_directed_damage_remains_a_separate_post_hit_effect() -> None:
    action = _attack(
        effects=[
            {
                "effect_type": "damage",
                "apply_on": "always",
                "target": "source",
                "damage": "2",
                "damage_type": "force",
            }
        ]
    )

    attacker, target, damage_dealt, damage_taken = _execute(
        rng=_SequenceRng([15]),
        action=action,
    )

    assert target.hp == 19
    assert attacker.hp == 18
    assert damage_dealt["attacker"] == 3
    assert damage_taken["attacker"] == 2
