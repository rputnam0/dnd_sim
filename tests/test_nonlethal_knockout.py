from __future__ import annotations

import pytest

from dnd_sim.engine import TurnDeclarationValidationError
from dnd_sim.engine_runtime import _execute_declared_action_step_or_error
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.rules_2014 import DamageBundle, DamagePacket, apply_damage_bundle
from dnd_sim.strategy_api import DeclaredAction, TargetRef


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
    hp: int = 10,
    max_hp: int = 10,
    uses_death_saves: bool = False,
    actions: list[ActionDefinition] | None = None,
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
        actions=list(actions or []),
        uses_death_saves=uses_death_saves,
    )


def _damage_bundle(amount: int) -> DamageBundle:
    return DamageBundle(
        packets=[
            DamagePacket(
                amount=amount,
                damage_type="bludgeoning",
                source="attack",
            )
        ]
    )


def _trackers(*actors: ActorRuntimeState) -> tuple[dict, dict, dict, dict]:
    ids = [actor.actor_id for actor in actors]
    return (
        {actor_id: 0 for actor_id in ids},
        {actor_id: 0 for actor_id in ids},
        {actor_id: 0 for actor_id in ids},
        {actor_id: {} for actor_id in ids},
    )


def test_damage_bundle_can_knock_out_a_no_save_creature() -> None:
    target = _actor("target", team="enemy", hp=3)
    rng = _SequenceRng([2])

    resolution = apply_damage_bundle(
        target,
        _damage_bundle(3),
        knock_out_at_zero=True,
        knockout_recovery_rng=rng,
    )

    assert resolution.knocked_out is True
    assert target.hp == 0
    assert target.dead is False
    assert target.stable is True
    assert target.death_successes == 0
    assert target.death_failures == 0
    assert target.stable_recovery_hours_remaining == 2
    assert {"unconscious", "incapacitated", "prone"} <= target.conditions
    assert target.downed_count == 1
    assert rng.values == []


def test_ordinary_damage_still_kills_a_no_save_creature() -> None:
    target = _actor("target", team="enemy", hp=3)

    resolution = apply_damage_bundle(target, _damage_bundle(3))

    assert resolution.knocked_out is False
    assert target.dead is True
    assert target.stable is False


def test_massive_damage_overrides_knockout_without_recovery_roll() -> None:
    target = _actor("target", team="enemy", hp=3, max_hp=10)

    resolution = apply_damage_bundle(
        target,
        _damage_bundle(13),
        knock_out_at_zero=True,
        knockout_recovery_rng=_SequenceRng([]),
    )

    assert resolution.knocked_out is False
    assert target.dead is True
    assert target.stable is False


def test_non_dropping_knockout_attack_does_not_consume_recovery_roll() -> None:
    target = _actor("target", team="enemy", hp=3)

    resolution = apply_damage_bundle(
        target,
        _damage_bundle(1),
        knock_out_at_zero=True,
        knockout_recovery_rng=_SequenceRng([]),
    )

    assert resolution.knocked_out is False
    assert target.hp == 2
    assert target.dead is False


@pytest.mark.parametrize(
    "attack_delivery",
    ["melee_weapon_attack", "melee_spell_attack"],
)
def test_declared_melee_knockout_intent_reaches_damage_resolution(
    attack_delivery: str,
) -> None:
    action = ActionDefinition(
        name="club",
        action_type="attack",
        attack_delivery=attack_delivery,
        to_hit=5,
        damage="1",
        damage_type="bludgeoning",
        reach_ft=5,
    )
    attacker = _actor("attacker", team="party", actions=[action])
    target = _actor("target", team="enemy", hp=1)
    target.position = (5.0, 0.0, 0.0)
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(attacker, target)

    _execute_declared_action_step_or_error(
        rng=_SequenceRng([15, 3]),
        actor=attacker,
        declaration=DeclaredAction(
            action_name="club",
            targets=[TargetRef(actor_id=target.actor_id)],
            zero_hp_intent="knock_out",
        ),
        field_prefix="action",
        expected_cost="action",
        actors={attacker.actor_id: attacker, target.actor_id: target},
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.stable is True
    assert target.dead is False
    assert target.stable_recovery_hours_remaining == 3


def test_declared_knockout_allows_an_all_melee_attack_sequence() -> None:
    first = ActionDefinition(
        name="claw",
        action_type="attack",
        attack_delivery="melee_weapon_attack",
        to_hit=5,
        damage="1",
    )
    second = ActionDefinition(
        name="shocking_grasp",
        action_type="attack",
        attack_delivery="melee_spell_attack",
        to_hit=5,
        damage="1",
    )
    multiattack = ActionDefinition(
        name="multiattack",
        action_type="attack",
        mechanics=[
            {
                "effect_type": "attack_sequence",
                "sequence": [
                    {"action_name": "claw"},
                    {"action_name": "shocking_grasp"},
                ],
            }
        ],
    )
    attacker = _actor(
        "attacker",
        team="party",
        actions=[multiattack, first, second],
    )
    target = _actor("target", team="enemy", hp=2)
    target.position = (5.0, 0.0, 0.0)
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(attacker, target)

    _execute_declared_action_step_or_error(
        rng=_SequenceRng([15, 15, 4]),
        actor=attacker,
        declaration=DeclaredAction(
            action_name="multiattack",
            targets=[TargetRef(actor_id=target.actor_id)],
            zero_hp_intent="knock_out",
        ),
        field_prefix="action",
        expected_cost="action",
        actors={attacker.actor_id: attacker, target.actor_id: target},
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.stable is True
    assert target.dead is False
    assert target.stable_recovery_hours_remaining == 4


def test_declared_knockout_rejects_a_mixed_delivery_attack_sequence() -> None:
    melee = ActionDefinition(
        name="club",
        action_type="attack",
        attack_delivery="melee_weapon_attack",
        to_hit=5,
        damage="1",
    )
    ranged = ActionDefinition(
        name="shot",
        action_type="attack",
        attack_delivery="ranged_weapon_attack",
        to_hit=5,
        damage="1",
    )
    multiattack = ActionDefinition(
        name="mixed_multiattack",
        action_type="attack",
        resource_cost={"multiattack_use": 1},
        mechanics=[
            {
                "effect_type": "attack_sequence",
                "sequence": [
                    {"action_name": "club"},
                    {"action_name": "shot"},
                ],
            }
        ],
    )
    attacker = _actor(
        "attacker",
        team="party",
        actions=[multiattack, melee, ranged],
    )
    attacker.resources = {"multiattack_use": 1}
    attacker.max_resources = {"multiattack_use": 1}
    target = _actor("target", team="enemy", hp=2)
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(attacker, target)

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        _execute_declared_action_step_or_error(
            rng=_SequenceRng([]),
            actor=attacker,
            declaration=DeclaredAction(
                action_name="mixed_multiattack",
                targets=[TargetRef(actor_id=target.actor_id)],
                zero_hp_intent="knock_out",
            ),
            field_prefix="action",
            expected_cost="action",
            actors={attacker.actor_id: attacker, target.actor_id: target},
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=[],
        )

    assert exc_info.value.code == "illegal_knockout_intent"
    assert attacker.resources == {"multiattack_use": 1}


@pytest.mark.parametrize(
    "attack_delivery",
    ["ranged_weapon_attack", "ranged_spell_attack", None],
)
def test_declared_knockout_rejects_non_melee_delivery_before_spending_resources(
    attack_delivery: str | None,
) -> None:
    action = ActionDefinition(
        name="shot",
        action_type="attack",
        attack_delivery=attack_delivery,
        to_hit=5,
        damage="1",
        resource_cost={"ammo": 1},
        range_ft=30,
    )
    attacker = _actor("attacker", team="party", actions=[action])
    attacker.resources = {"ammo": 1}
    attacker.max_resources = {"ammo": 1}
    target = _actor("target", team="enemy", hp=1)
    target.position = (5.0, 0.0, 0.0)
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(attacker, target)

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        _execute_declared_action_step_or_error(
            rng=_SequenceRng([]),
            actor=attacker,
            declaration=DeclaredAction(
                action_name="shot",
                targets=[TargetRef(actor_id=target.actor_id)],
                zero_hp_intent="knock_out",
            ),
            field_prefix="action",
            expected_cost="action",
            actors={attacker.actor_id: attacker, target.actor_id: target},
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=[],
        )

    assert exc_info.value.code == "illegal_knockout_intent"
    assert exc_info.value.field == "action.zero_hp_intent"
    assert attacker.resources == {"ammo": 1}
    assert resources_spent[attacker.actor_id] == {}


def test_declared_action_rejects_unknown_zero_hp_intent() -> None:
    action = ActionDefinition(
        name="club",
        action_type="attack",
        attack_delivery="melee_weapon_attack",
        to_hit=5,
        damage="1",
    )
    attacker = _actor("attacker", team="party", actions=[action])
    target = _actor("target", team="enemy", hp=1)
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(attacker, target)

    with pytest.raises(TurnDeclarationValidationError) as exc_info:
        _execute_declared_action_step_or_error(
            rng=_SequenceRng([]),
            actor=attacker,
            declaration=DeclaredAction(
                action_name="club",
                targets=[TargetRef(actor_id=target.actor_id)],
                zero_hp_intent="maybe",
            ),
            field_prefix="action",
            expected_cost="action",
            actors={attacker.actor_id: attacker, target.actor_id: target},
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            threat_scores=threat_scores,
            resources_spent=resources_spent,
            active_hazards=[],
        )

    assert exc_info.value.code == "invalid_zero_hp_intent"
    assert exc_info.value.field == "action.zero_hp_intent"


def test_multiattack_only_rolls_recovery_when_final_hit_knocks_target_out() -> None:
    action = ActionDefinition(
        name="two_clubs",
        action_type="attack",
        attack_delivery="melee_weapon_attack",
        to_hit=5,
        damage="1",
        attack_count=2,
        reach_ft=5,
    )
    attacker = _actor("attacker", team="party", actions=[action])
    target = _actor("target", team="enemy", hp=2)
    target.position = (5.0, 0.0, 0.0)
    damage_dealt, damage_taken, threat_scores, resources_spent = _trackers(attacker, target)
    rng = _SequenceRng([15, 15, 4])

    _execute_declared_action_step_or_error(
        rng=rng,
        actor=attacker,
        declaration=DeclaredAction(
            action_name="two_clubs",
            targets=[TargetRef(actor_id=target.actor_id)],
            zero_hp_intent="knock_out",
        ),
        field_prefix="action",
        expected_cost="action",
        actors={attacker.actor_id: attacker, target.actor_id: target},
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert target.stable is True
    assert target.stable_recovery_hours_remaining == 4
    assert damage_dealt[attacker.actor_id] == 2
    assert rng.values == []
