from __future__ import annotations

import pytest

from dnd_sim.engine_runtime import (
    _build_attack_action_instances,
    _create_combat_timing_engine,
    _execute_action,
)
from dnd_sim.models import ActionDefinition, ActorRuntimeState
from dnd_sim.rules_2014 import ActionDeclaredEvent


class FixedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randint(self, _a: int, _b: int) -> int:
        if not self.values:
            raise AssertionError("RNG exhausted")
        return self.values.pop(0)


def _actor(actor_id: str, team: str) -> ActorRuntimeState:
    return ActorRuntimeState(
        actor_id=actor_id,
        team=team,
        name=actor_id,
        max_hp=40,
        hp=40,
        temp_hp=0,
        ac=12,
        initiative_mod=0,
        str_mod=3,
        dex_mod=2,
        con_mod=2,
        int_mod=0,
        wis_mod=0,
        cha_mod=0,
        save_mods={"str": 3, "dex": 2, "con": 2, "int": 0, "wis": 0, "cha": 0},
        actions=[],
    )


def _combat_trackers(
    attacker: ActorRuntimeState,
    target: ActorRuntimeState,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    damage_dealt = {attacker.actor_id: 0, target.actor_id: 0}
    damage_taken = {attacker.actor_id: 0, target.actor_id: 0}
    threat_scores = {attacker.actor_id: 0, target.actor_id: 0}
    resources_spent = {attacker.actor_id: {}, target.actor_id: {}}
    return damage_dealt, damage_taken, threat_scores, resources_spent


def test_extra_attack_action_can_replace_one_attack_with_grapple(monkeypatch) -> None:
    monkeypatch.setattr("dnd_sim.rules_2014.run_contested_check", lambda *_args, **_kwargs: True)

    attacker = _actor("attacker", "party")
    target = _actor("target", "enemy")
    grapple = ActionDefinition(name="grapple", action_type="grapple", action_cost="action")
    attack_action = ActionDefinition(
        name="longsword",
        action_type="attack",
        to_hit=10,
        damage="1",
        damage_type="slashing",
        attack_count=2,
        mechanics=[
            {
                "effect_type": "attack_replacement",
                "action_name": "grapple",
                "count": 1,
            }
        ],
    )
    attacker.actions = [attack_action, grapple]

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _combat_trackers(attacker, target)

    _execute_action(
        rng=FixedRng([15]),
        actor=attacker,
        action=attack_action,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
    )

    assert "grappled" in target.conditions
    assert damage_dealt[attacker.actor_id] == 1
    assert damage_taken[target.actor_id] == 1


def test_multiattack_sequence_uses_defined_attack_order() -> None:
    attacker = _actor("hydra", "enemy")
    target = _actor("hero", "party")
    bite = ActionDefinition(
        name="bite",
        action_type="attack",
        to_hit=10,
        damage="1",
        damage_type="piercing",
    )
    tail = ActionDefinition(
        name="tail",
        action_type="attack",
        to_hit=10,
        damage="1",
        damage_type="bludgeoning",
    )
    multiattack = ActionDefinition(
        name="multiattack",
        action_type="utility",
        action_cost="action",
        target_mode="single_enemy",
        mechanics=[
            {
                "effect_type": "attack_sequence",
                "sequence": [{"action_name": "bite"}, {"action_name": "tail"}],
            }
        ],
    )
    attacker.actions = [multiattack, bite, tail]

    actors = {attacker.actor_id: attacker, target.actor_id: target}
    damage_dealt, damage_taken, threat_scores, resources_spent = _combat_trackers(attacker, target)

    timing_engine = _create_combat_timing_engine(include_default_rules=False)
    declared_actions: list[str] = []

    def _capture(event: ActionDeclaredEvent) -> None:
        declared_actions.append(event.action.name)

    timing_engine.subscribe(ActionDeclaredEvent, _capture, name="capture")

    _execute_action(
        rng=FixedRng([15, 15]),
        actor=attacker,
        action=multiattack,
        targets=[target],
        actors=actors,
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        threat_scores=threat_scores,
        resources_spent=resources_spent,
        active_hazards=[],
        timing_engine=timing_engine,
    )

    assert declared_actions == ["bite", "tail"]
    assert damage_dealt[attacker.actor_id] == 2
    assert damage_taken[target.actor_id] == 2


def test_replacement_count_cannot_exceed_available_attacks() -> None:
    attacker = _actor("attacker", "party")
    grapple = ActionDefinition(name="grapple", action_type="grapple", action_cost="action")
    attack_action = ActionDefinition(
        name="spear",
        action_type="attack",
        to_hit=8,
        damage="1",
        attack_count=1,
        mechanics=[
            {
                "effect_type": "attack_replacement",
                "action_name": "grapple",
                "count": 2,
            }
        ],
    )
    attacker.actions = [attack_action, grapple]

    with pytest.raises(ValueError, match="replacements"):
        _build_attack_action_instances(attacker, attack_action)
